"""Blender-side half of the live lane. Imported as ``R`` inside live Blender.

Everything in this module executes *in the running Blender process*, reached
over the BlenderMCP socket by ``mcp_client.BlenderMCP``. It never runs in the
test runner's Python.

The split is deliberate. Pixels are large and JSON is small, so images are
measured where they are produced and only compact numbers cross the wire. Whole
captures are kept in a process-local registry (``capture`` / ``compare``) so a
test can relate two images without either one being transferred.

What this adds over the headless lane:

  * It observes the **viewport**, not a Cycles render. `--background` has no
    screen, so the existing suite cannot see the shading path a user looks at.
  * It measures **color**. Every existing pixel check reduces a render to an
    alpha mask and discards RGB, so a domain drawn in the wrong color, or every
    domain drawn identically, is currently invisible to the suite.
  * It runs against the **deployed** add-on in a normal Blender profile, which
    is the configuration CLAUDE.md requires a change to be proven in.

Color measurements force ``view_transform = 'Standard'`` for the duration of a
capture and restore the scene's own setting afterwards. Without that, Blender's
default filmic-style transform remaps every channel and "is this domain red"
stops being answerable in a stable way.
"""

from __future__ import annotations

import base64
import os
import tempfile

import bpy
import numpy as np

# label -> {"alpha": bool ndarray, "rgb": float ndarray, "shape": (h, w)}
_CAPTURES: dict[str, dict] = {}

ALPHA_THRESHOLD = 0.01


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def env() -> dict:
    """Describe the live session. Used by the harness to decide what can run."""
    scene = bpy.context.scene
    return {
        "blender": bpy.app.version_string,
        "background": bool(bpy.app.background),
        "numpy": np.__version__,
        "addon_loaded": hasattr(scene, "molecule_list_items"),
        "areas": sorted({a.type for a in bpy.context.screen.areas}),
        "has_view3d": find_view3d() is not None,
        "engine": scene.render.engine,
        "workspaces": [w.name for w in bpy.data.workspaces],
        "tempdir": tempfile.gettempdir(),
    }


def find_view3d():
    """(window, area, region) of a usable 3D viewport, or None.

    Searched across every open window, because the ProteinBlender workspace may
    put the 3D view somewhere other than the active screen.
    """
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return window, area, region
    return None


def view3d_override():
    """A ``temp_override`` bound to a real 3D viewport.

    Operators reaching us over the socket arrive on a timer callback, which
    inherits no editor area. Anything view-dependent (framing, OpenGL render,
    append of MolecularNodes node groups) needs a genuine VIEW_3D context, the
    same one a user-triggered action would have.
    """
    found = find_view3d()
    if found is None:
        raise RuntimeError("live Blender has no 3D viewport area")
    window, area, region = found
    return bpy.context.temp_override(
        window=window, screen=window.screen, area=area, region=region)


# ---------------------------------------------------------------------------
# Scene control
# ---------------------------------------------------------------------------

def reset():
    """Scrub add-on state between live tests.

    Delegates to the suite's own ``helpers.reset_scene`` so the live lane and
    the headless lane start from an identical scene, then restores the render
    settings and the add-on's settings that a previous test may have changed.

    Resetting the property groups is not housekeeping, it is a correctness
    requirement unique to this lane. Every other lane runs in a throwaway
    Blender, but this one drives the *developer's own session*: a test that
    sets ``membrane_builder_props.color_head`` and walks away leaves that colour
    in the panel, and the next membrane the user builds by hand comes out
    wrong. That happened - a colour test left head and tail at (0.05, 0.05,
    0.95) and (0.15, 0.15, 0.15), and the resulting blue-and-grey membrane was
    reported as a product bug.
    """
    import helpers as H

    H.reset_scene()
    scene = bpy.context.scene
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "AgX"
    except (TypeError, AttributeError):
        pass
    restored = reset_addon_settings()
    _CAPTURES.clear()
    return {"objects": len(bpy.data.objects), "settings_restored": restored}


def reset_addon_settings():
    """Return every ProteinBlender settings block to its registered defaults.

    Discovered from the RNA rather than hard-coded, so a property group added
    later is covered without anyone remembering to update a list.
    """
    scene = bpy.context.scene
    restored = []

    for prop in scene.bl_rna.properties:
        if prop.type != "POINTER" or prop.identifier == "rna_type":
            continue
        fixed = getattr(prop, "fixed_type", None)
        if fixed is None or not fixed.identifier.startswith(
                ("Protein", "Membrane", "DNA", "PB", "Molecule", "Brownian")):
            continue
        group = getattr(scene, prop.identifier, None)
        if group is None:
            continue
        for field in group.bl_rna.properties:
            if field.identifier == "rna_type" or field.is_readonly:
                continue
            try:
                group.property_unset(field.identifier)
            except (TypeError, AttributeError):
                pass
        restored.append(prop.identifier)

    # Scene-level singles the add-on registers directly (colour pickers, style
    # dropdowns, split bounds) rather than inside a group.
    for name in ("molecule_style", "visual_setup_color", "visual_setup_style",
                 "temp_domain_color", "temp_domain_start", "temp_domain_end",
                 "domain_start", "domain_end", "split_domain_new_start",
                 "split_domain_new_end", "active_splitting_domain_id",
                 "show_domain_preview", "selected_molecule_id"):
        try:
            scene.property_unset(name)
            restored.append(name)
        except (TypeError, AttributeError):
            pass

    return restored


def set_shading(kind: str = "SOLID", color_type: str = "MATERIAL"):
    """Set the viewport shading mode. ``kind`` in WIREFRAME/SOLID/MATERIAL/RENDERED."""
    found = find_view3d()
    if found is None:
        raise RuntimeError("no 3D viewport")
    _, area, _ = found
    shading = area.spaces.active.shading
    shading.type = kind
    if kind == "SOLID":
        shading.color_type = color_type
    return {"type": shading.type}


def frame_all(objects: list[str] | None = None, zoom: float = 0.55):
    """Point the viewport at the scene, or at named objects, so captures compare.

    Framing is what makes two captures of the same subject overlay. Without it,
    an unrelated view rotation reads as a geometry regression.

    ``zoom`` scales the resulting view distance. The captures are square while
    the viewport is wide, so Blender's own framing leaves the subject occupying
    a small part of a square render. Pulling in fills the frame, which matters
    because coverage and color are both averaged over covered pixels and get
    noisy when the subject is only a few hundred pixels.
    """
    found = find_view3d()
    if found is None:
        raise RuntimeError("no 3D viewport")
    with view3d_override():
        if objects:
            bpy.ops.object.select_all(action="DESELECT")
            for name in objects:
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    obj.select_set(True)
                    bpy.context.view_layer.objects.active = obj
            bpy.ops.view3d.view_selected()
        else:
            bpy.ops.view3d.view_all()
    region_3d = found[1].spaces.active.region_3d
    region_3d.view_distance *= zoom
    return {"view_distance": round(float(region_3d.view_distance), 5)}


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _render_viewport(resolution: int, transparent: bool, standard_color: bool):
    """OpenGL-render the 3D viewport to an RGBA float array of shape (h, w, 4).

    ``bpy.ops.render.opengl`` renders from the scene camera unless it is given a
    VIEW_3D context, in which case it uses that viewport's own view matrix. We
    always give it one, so the capture is the view the user has on screen.

    Overlays and gizmos are switched off for the duration. They are drawn into
    an OpenGL render, and the floor grid alone covers roughly a third of the
    frame, so leaving them on would make "is any geometry on screen" always
    true and every coverage assertion meaningless. The viewport's own settings
    are restored afterwards, so the user's session looks unchanged.
    """
    scene = bpy.context.scene
    prev = {
        "x": scene.render.resolution_x,
        "y": scene.render.resolution_y,
        "pct": scene.render.resolution_percentage,
        "transparent": scene.render.film_transparent,
        "path": scene.render.filepath,
        "fmt": scene.render.image_settings.file_format,
        "mode": scene.render.image_settings.color_mode,
    }
    try:
        view_transform = scene.view_settings.view_transform
    except AttributeError:
        view_transform = None

    out = os.path.join(tempfile.gettempdir(), "pb_live_viewport.png")
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = transparent
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = out
    if standard_color and view_transform is not None:
        try:
            scene.view_settings.view_transform = "Standard"
        except TypeError:
            pass

    found = find_view3d()
    if found is None:
        raise RuntimeError("no 3D viewport to render")
    space = found[1].spaces.active
    overlay_state = (space.overlay.show_overlays, space.show_gizmo)
    space.overlay.show_overlays = False
    space.show_gizmo = False

    try:
        with view3d_override():
            bpy.ops.render.opengl(write_still=True)
        image = bpy.data.images.load(out)
        try:
            width, height = image.size
            pixels = np.array(image.pixels[:], dtype=np.float32)
            return pixels.reshape(height, width, 4)
        finally:
            bpy.data.images.remove(image)
    finally:
        space.overlay.show_overlays, space.show_gizmo = overlay_state
        scene.render.resolution_x = prev["x"]
        scene.render.resolution_y = prev["y"]
        scene.render.resolution_percentage = prev["pct"]
        scene.render.film_transparent = prev["transparent"]
        scene.render.filepath = prev["path"]
        scene.render.image_settings.file_format = prev["fmt"]
        scene.render.image_settings.color_mode = prev["mode"]
        if standard_color and view_transform is not None:
            try:
                scene.view_settings.view_transform = view_transform
            except TypeError:
                pass
        try:
            os.remove(out)
        except OSError:
            pass


def _measure(rgba: np.ndarray, want_png_path: str | None = None) -> dict:
    height, width = rgba.shape[:2]
    alpha = rgba[:, :, 3] > ALPHA_THRESHOLD
    covered = int(alpha.sum())
    total = int(height * width)
    metrics = {
        "resolution": [int(width), int(height)],
        "pixels": total,
        "covered": covered,
        "coverage": round(covered / total, 6) if total else 0.0,
    }
    if covered:
        ys, xs = np.nonzero(alpha)
        metrics["bbox"] = [int(xs.min()), int(ys.min()),
                           int(xs.max()), int(ys.max())]
        metrics["centroid"] = [round(float(xs.mean()) / width, 4),
                               round(float(ys.mean()) / height, 4)]
        rgb = rgba[:, :, :3][alpha]
        metrics["mean_rgb"] = [round(float(c), 4) for c in rgb.mean(axis=0)]
        metrics["max_rgb"] = [round(float(c), 4) for c in rgb.max(axis=0)]
        # Quantised distinct colors: how many visually different colors are on
        # screen. One color across a multi-domain molecule means recoloring or
        # per-domain materials silently did nothing.
        quantised = np.unique((np.clip(rgb, 0, 1) * 16).astype(np.uint8), axis=0)
        metrics["distinct_colors"] = int(len(quantised))
        metrics["dominant_channel"] = int(np.argmax(rgb.mean(axis=0)))
    else:
        metrics["bbox"] = None
        metrics["centroid"] = None
        metrics["mean_rgb"] = None
        metrics["max_rgb"] = None
        metrics["distinct_colors"] = 0
        metrics["dominant_channel"] = None
    return metrics


def viewport_metrics(resolution: int = 480, transparent: bool = True,
                     want_png: bool = False, standard_color: bool = True,
                     label: str | None = None) -> dict:
    """Render the viewport and return measurements of what is on screen.

    Keys: ``resolution``, ``pixels``, ``covered``, ``coverage``, ``bbox``,
    ``centroid`` (normalised 0-1), ``mean_rgb``, ``max_rgb``,
    ``distinct_colors``, ``dominant_channel``. ``png_b64`` when ``want_png``.

    Pass ``label`` to also retain the full capture for later ``compare``.
    """
    rgba = _render_viewport(resolution, transparent, standard_color)
    metrics = _measure(rgba)
    if label:
        _CAPTURES[label] = {
            "alpha": rgba[:, :, 3] > ALPHA_THRESHOLD,
            "rgb": rgba[:, :, :3].copy(),
        }
    if want_png:
        metrics["png_b64"] = _encode_png(rgba)
    return metrics


def capture(label: str, resolution: int = 480, **kwargs) -> dict:
    """Render, retain the full image under ``label``, and return its metrics."""
    return viewport_metrics(resolution=resolution, label=label, **kwargs)


def compare(left: str, right: str) -> dict:
    """Relate two retained captures without transferring either.

    Returns ``xor`` (pixels covered by exactly one), ``iou`` of the two masks,
    ``rgb_delta`` (mean absolute color difference over the union), and
    ``identical``. This supports metamorphic assertions in the style the suite
    already uses: two styles must differ, a pivot change must not.
    """
    for name in (left, right):
        if name not in _CAPTURES:
            raise KeyError(f"no capture named {name!r}; captured: "
                           f"{sorted(_CAPTURES)}")
    a, b = _CAPTURES[left], _CAPTURES[right]
    if a["alpha"].shape != b["alpha"].shape:
        raise ValueError("captures have different resolutions")
    union = np.logical_or(a["alpha"], b["alpha"])
    inter = np.logical_and(a["alpha"], b["alpha"])
    xor = int(np.logical_xor(a["alpha"], b["alpha"]).sum())
    union_n = int(union.sum())
    delta = 0.0
    if union_n:
        delta = float(np.abs(a["rgb"][union] - b["rgb"][union]).mean())
    return {
        "xor": xor,
        "union": union_n,
        "intersection": int(inter.sum()),
        "iou": round(float(inter.sum() / union_n), 6) if union_n else 0.0,
        "rgb_delta": round(delta, 6),
        "identical": xor == 0 and delta < 1e-6,
    }


def _encode_png(rgba: np.ndarray) -> str:
    """Encode an RGBA float array as base64 PNG, via Blender's image writer."""
    height, width = rgba.shape[:2]
    image = bpy.data.images.new("pb_live_tmp", width=width, height=height,
                                alpha=True)
    path = os.path.join(tempfile.gettempdir(), "pb_live_encode.png")
    try:
        image.pixels = rgba.reshape(-1).tolist()
        image.file_format = "PNG"
        image.filepath_raw = path
        image.save()
        with open(path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    finally:
        bpy.data.images.remove(image)
        try:
            os.remove(path)
        except OSError:
            pass


def screenshot_b64(max_size: int = 1000) -> str:
    """Base64 PNG of the literal Blender window, UI chrome included.

    Distinct from ``viewport_metrics``: this is what the user's screen looks
    like, panels and all, which is what makes it useful as a saved artifact for
    reviewing panel layout. Geometry assertions should use the viewport render.
    """
    found = find_view3d()
    if found is None:
        raise RuntimeError("no 3D viewport to screenshot")
    _, area, _ = found
    path = os.path.join(tempfile.gettempdir(), "pb_live_screenshot.png")
    with bpy.context.temp_override(area=area):
        bpy.ops.screen.screenshot_area(filepath=path)
    image = bpy.data.images.load(path)
    try:
        width, height = image.size
        if max(width, height) > max_size:
            scale = max_size / max(width, height)
            image.scale(int(width * scale), int(height * scale))
            image.file_format = "PNG"
            image.save()
        with open(path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    finally:
        bpy.data.images.remove(image)
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Scene inspection
# ---------------------------------------------------------------------------

def object_summary(name: str) -> dict:
    """Geometry facts about one object, evaluated through its modifier stack."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise KeyError(f"no object named {name!r}")
    import helpers as H

    positions = H.eval_positions(obj)
    summary = {
        "name": obj.name,
        "type": obj.type,
        "visible": bool(obj.visible_get()),
        "location": [round(float(v), 5) for v in obj.location],
        "modifiers": [m.type for m in obj.modifiers],
        "materials": [m.name for m in obj.data.materials] if getattr(
            obj.data, "materials", None) else [],
        "eval_verts": int(len(positions)),
    }
    if len(positions):
        summary["bbox_min"] = [round(float(v), 4) for v in positions.min(axis=0)]
        summary["bbox_max"] = [round(float(v), 4) for v in positions.max(axis=0)]
        summary["centroid"] = [round(float(v), 4) for v in positions.mean(axis=0)]
    return summary


def scene_snapshot() -> dict:
    """A compact description of add-on state, for assertions and for triage."""
    import helpers as H

    scene = bpy.context.scene
    manager = H.sm()
    return {
        "objects": sorted(o.name for o in bpy.data.objects),
        "molecules": sorted(manager.molecules.keys()),
        "molecule_rows": [it.identifier for it in scene.molecule_list_items],
        "outliner": [
            {"type": it.item_type, "name": it.name, "id": it.item_id}
            for it in scene.outliner_items
        ],
        "selected_molecule_id": getattr(scene, "selected_molecule_id", ""),
        "frame": scene.frame_current,
    }


def ui_state() -> dict:
    """Which ProteinBlender panels are registered and accept the live context.

    Headless Blender cannot draw a panel, so this is the lane where a panel that
    registers but refuses to appear can actually be caught.
    """
    panels = []
    for cls in bpy.types.Panel.__subclasses__():
        idname = getattr(cls, "bl_idname", "") or cls.__name__
        # The import panel is PROTEIN_PB_PT_*, not PROTEINBLENDER_PT_*. Matching
        # only the obvious prefix silently dropped it and left the panel count
        # one short of the nine the add-on actually ships.
        if not idname.startswith(("PROTEINBLENDER_PT", "PROTEIN_PB_PT",
                                  "PB2_PT", "MOLECULE_PT")):
            continue
        try:
            polled = bool(cls.poll(bpy.context)) if hasattr(cls, "poll") else True
        except Exception as exc:
            polled = f"error: {exc}"
        panels.append({
            "idname": idname,
            "label": getattr(cls, "bl_label", ""),
            "space": getattr(cls, "bl_space_type", ""),
            "context": getattr(cls, "bl_context", ""),
            "registered": bool(getattr(cls, "is_registered", False)),
            "poll": polled,
        })
    return {"panels": sorted(panels, key=lambda p: p["idname"])}
