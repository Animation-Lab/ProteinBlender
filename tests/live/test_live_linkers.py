"""Flexible linkers, observed in a live Blender.

Linkers are the subsystem with the widest gap between what is tested and what a
user sees. The headless suite drives every one of their operators and asserts on
the definition row, the curve object's existence and its control points - but a
linker is a *curve*, and a curve is not geometry until a bevel, a taper or a
geometry-nodes tree turns it into something with surface area. Nothing anywhere
in the suite has ever rendered one. A linker whose control points are perfect
but whose curve carries no bevel, whose object sits in no visible collection, or
whose material never binds, passes every existing test and draws nothing.

So the assertions here start from pixels:

  * the linker renders at all, proven by hiding it and watching those pixels
    leave - which is what distinguishes "the linker is on screen" from "the
    protein behind it is on screen";
  * TUBE and BEADS render differently, so the style property reaches geometry
    rather than only the definition;
  * the linker's colour survives into a MATERIAL-shaded viewport, the class of
    check this lane exists for and the one that already caught
    ``update_domain_color`` doing nothing.

The three behaviours are compared on raw control points instead, because that
is a claim about the *path* rather than about the shading, and the control
points are data the geometry module wrote rather than a value derived by
re-calling it.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Blender-side setup
# ---------------------------------------------------------------------------

_SETUP_LINKER = '''
mid = H.import_local("4hhb.pdb", "4hhb")
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
scene = bpy.context.scene
chain_ids = [it.item_id for it in scene.outliner_items
             if it.item_type == "CHAIN" and it.parent_id == mid][:2]
if len(chain_ids) < 2:
    raise RuntimeError("a linker needs two chains inside one puppet")
wanted = set(chain_ids)
for it in scene.outliner_items:
    it.is_selected = it.item_id in wanted
with R.view3d_override():
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=puppet_name)

# create_puppet rebuilds outliner_items, so every row read before it is now
# dangling and returns defaults instead of raising. Re-resolve by id.
puppet = next(p for p in scene.outliner_items
              if p.item_type == "PUPPET"
              and p.item_id != "puppets_separator"
              and p.name == puppet_name)
by_id = {it.item_id: it for it in scene.outliner_items}
chains = []
for cid in chain_ids:
    row = by_id[cid]
    start = row.chain_start or 1
    end = row.chain_end or start
    chains.append({"item_id": row.item_id, "chain_id": row.chain_id,
                   "residue": max(start, (start + end) // 2)})

kwargs = dict(
    puppet_selector=puppet.item_id,
    endpoint_a_item="A_" + chains[0]["item_id"],
    endpoint_a_residue=chains[0]["residue"],
    endpoint_b_item="B_" + chains[1]["item_id"],
    endpoint_b_residue=chains[1]["residue"],
    linker_name=linker_name,
    length_residues=length_residues,
    style=style,
    behavior=behavior,
    rendering_mode="QUICK",
)
n_before = len(scene.pb2_linkers)
with R.view3d_override():
    bpy.ops.pb2.add_linker('EXEC_DEFAULT', **kwargs)
if len(scene.pb2_linkers) != n_before + 1:
    raise RuntimeError("add_linker did not add a definition")
linker = scene.pb2_linkers[-1]
return {
    "molecule_id": mid,
    "puppet_id": puppet.item_id,
    "chains": chains,
    "uid": linker.uid,
    "name": linker.name,
    "curve": linker.curve_object_name,
    "endpoint_a_item_id": linker.endpoint_a_item_id,
    "endpoint_b_item_id": linker.endpoint_b_item_id,
    "length_residues": linker.length_residues,
    "is_valid": linker.is_valid,
    "curve_type": (bpy.data.objects[linker.curve_object_name].type
                   if bpy.data.objects.get(linker.curve_object_name) else None),
}
'''


def setup_linker(blender, *, puppet_name="Live_Link_Puppet",
                 linker_name="Live_Linker", length_residues=30,
                 style="TUBE", behavior="GRAVITY") -> dict:
    """Import 4hhb, puppet two chains, and link them. Returns plain data.

    Nothing here returns a live row. ``pb2_linkers`` and ``outliner_items`` are
    both rebuilt by later operators, and a held row reads back defaults rather
    than raising, so callers re-resolve by ``uid`` or ``item_id``.
    """
    return blender.call(_SETUP_LINKER, puppet_name=puppet_name,
                        linker_name=linker_name,
                        length_residues=length_residues,
                        style=style, behavior=behavior)


_CURVE_POINTS = '''
scene = bpy.context.scene
linker = next((l for l in scene.pb2_linkers if l.uid == uid), None)
if linker is None:
    return None
obj = bpy.data.objects.get(linker.curve_object_name)
if obj is None or not obj.data or not obj.data.splines:
    return None
spline = obj.data.splines[0]
points = [[round(float(c), 5) for c in bp.co] for bp in spline.bezier_points]
return {"curve": obj.name, "points": points,
        "n_points": len(points),
        "bevel_depth": round(float(obj.data.bevel_depth), 6),
        "materials": [m.name for m in obj.data.materials if m],
        "modifiers": [m.type for m in obj.modifiers],
        "hide_viewport": bool(obj.hide_viewport),
        "visible": bool(obj.visible_get())}
'''


def curve_points(blender, uid: str):
    """Raw control points of a linker's curve, re-resolved by uid."""
    return blender.call(_CURVE_POINTS, uid=uid)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_add_linker_creates_a_definition_and_a_curve_object(blender):
    """The definition must be wired to both endpoints and backed by a curve."""
    setup = setup_linker(blender, linker_name="Live_L1")

    assert setup["is_valid"] is True
    assert setup["endpoint_a_item_id"] == setup["chains"][0]["item_id"]
    assert setup["endpoint_b_item_id"] == setup["chains"][1]["item_id"]
    assert setup["curve"], "the linker recorded no curve object name"
    assert setup["curve_type"] == "CURVE"

    geometry = curve_points(blender, setup["uid"])
    assert geometry is not None, "the linker's curve has no spline data"
    assert geometry["n_points"] >= 2, (
        f"a linker needs at least two control points, got {geometry['n_points']}")


@pytest.mark.live
def test_add_linker_refuses_both_endpoints_on_one_chain(blender):
    """A linker from a chain to itself is meaningless and must be refused.

    The count assertion is the load-bearing half: an operator that reports the
    error only after adding its definition would still satisfy a test that
    merely expected an exception.
    """
    setup = setup_linker(blender, linker_name="Live_L_Valid")

    result = blender.call('''
        scene = bpy.context.scene
        n_before = len(scene.pb2_linkers)
        rejected = False
        try:
            with R.view3d_override():
                res = bpy.ops.pb2.add_linker(
                    'EXEC_DEFAULT',
                    puppet_selector=puppet_id,
                    endpoint_a_item="A_" + item_id,
                    endpoint_a_residue=residue,
                    endpoint_b_item="B_" + item_id,
                    endpoint_b_residue=residue,
                    linker_name="Live_SelfLink")
            rejected = (res == {'CANCELLED'})
        except RuntimeError:
            rejected = True
        return {"rejected": rejected, "before": n_before,
                "after": len(scene.pb2_linkers)}
    ''', puppet_id=setup["puppet_id"],
        item_id=setup["chains"][0]["item_id"],
        residue=setup["chains"][0]["residue"])

    assert result["rejected"], "a self-linking linker was accepted"
    assert result["after"] == result["before"], (
        "the rejected linker still left a definition behind")


@pytest.mark.live
def test_update_linker_rebuilds_geometry_and_select_targets_the_curve(blender):
    """Changing length must move the control points, and select must find it.

    Ground truth is the control-point set read straight off the curve data
    before and after, not anything the geometry module recomputes on request.
    More length means more slack means a different path; a definition that
    stores the new length without rebuilding leaves the points untouched.
    """
    setup = setup_linker(blender, linker_name="Live_L_Update",
                         length_residues=30)
    before = curve_points(blender, setup["uid"])
    assert before is not None

    result = blender.call('''
        scene = bpy.context.scene
        linker = next(l for l in scene.pb2_linkers if l.uid == uid)
        linker.length_residues = min(100, linker.length_residues + 40)
        with R.view3d_override():
            updated = sorted(bpy.ops.pb2.update_linker(
                'EXEC_DEFAULT', linker_uid=uid))
            bulk = sorted(bpy.ops.pb2.update_all_linkers('EXEC_DEFAULT'))
            selected = sorted(bpy.ops.pb2.select_linker_object(
                'EXEC_DEFAULT', linker_uid=uid))
        linker = next(l for l in scene.pb2_linkers if l.uid == uid)
        obj = bpy.data.objects.get(linker.curve_object_name)
        return {"updated": updated, "bulk": bulk, "selected": selected,
                "active": (bpy.context.view_layer.objects.active.name
                           if bpy.context.view_layer.objects.active else None),
                "is_selected": bool(obj.select_get()) if obj else False,
                "curve": linker.curve_object_name}
    ''', uid=setup["uid"])

    assert result["updated"] == ["FINISHED"]
    assert result["bulk"] == ["FINISHED"]
    assert result["selected"] == ["FINISHED"]

    after = curve_points(blender, setup["uid"])
    assert after is not None, "the curve did not survive the rebuild"
    assert after["points"] != before["points"], (
        "adding 40 residues of slack left every control point where it was; "
        "the length change never reached the geometry")

    assert result["active"] == result["curve"], (
        "select_linker_object did not make the linker's curve the active object")
    assert result["is_selected"], "the linker's curve was not selected"


@pytest.mark.live
def test_the_three_behaviors_produce_different_paths(blender):
    """GRAVITY, ZERO_G and RANDOM_COIL must each shape the slack differently.

    Behaviour is the property with the least observable footprint anywhere else:
    it changes no counts, no names and no validity flag, only the shape of the
    path between two fixed endpoints. Compared pairwise on raw control points,
    so two behaviours that silently fall through to the same code path cannot
    pass.
    """
    setup = setup_linker(blender, linker_name="Live_L_Behavior",
                         length_residues=60, behavior="GRAVITY")
    uid = setup["uid"]

    paths = {"GRAVITY": curve_points(blender, uid)["points"]}
    for behavior in ("ZERO_G", "RANDOM_COIL"):
        blender.call('''
            scene = bpy.context.scene
            with R.view3d_override():
                bpy.ops.pb2.edit_linker(
                    'EXEC_DEFAULT',
                    linker_uid=uid,
                    puppet_selector=puppet_id,
                    endpoint_a_item="A_" + item_a,
                    endpoint_a_residue=residue_a,
                    endpoint_b_item="B_" + item_b,
                    endpoint_b_residue=residue_b,
                    linker_name="Live_L_Behavior",
                    length_residues=60,
                    style="TUBE",
                    rendering_mode="QUICK",
                    behavior=behavior)
            return None
        ''', uid=uid, puppet_id=setup["puppet_id"],
            item_a=setup["chains"][0]["item_id"],
            residue_a=setup["chains"][0]["residue"],
            item_b=setup["chains"][1]["item_id"],
            residue_b=setup["chains"][1]["residue"],
            behavior=behavior)
        points = curve_points(blender, uid)
        assert points is not None, f"the curve vanished after switching to {behavior}"
        paths[behavior] = points["points"]

    names = sorted(paths)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            assert paths[a] != paths[b], (
                f"{a} and {b} produced an identical path; the behaviour "
                "setting is not reaching the curve geometry")


@pytest.mark.live
def test_toggle_linker_visibility_round_trips(blender):
    """Hiding and re-showing must move both the flag and the object together.

    They can drift apart: the definition's ``is_visible`` drives the panel's
    eye icon while ``hide_viewport`` drives what is drawn, and a toggle that
    updates only one leaves the icon lying about the viewport.
    """
    setup = setup_linker(blender, linker_name="Live_L_Toggle")

    result = blender.call('''
        scene = bpy.context.scene

        def state():
            linker = next(l for l in scene.pb2_linkers if l.uid == uid)
            obj = bpy.data.objects.get(linker.curve_object_name)
            return {"flag": bool(linker.is_visible),
                    "hidden": bool(obj.hide_viewport) if obj else None}

        before = state()
        with R.view3d_override():
            bpy.ops.pb2.toggle_linker_visibility('EXEC_DEFAULT', linker_uid=uid)
        toggled = state()
        with R.view3d_override():
            bpy.ops.pb2.toggle_linker_visibility('EXEC_DEFAULT', linker_uid=uid)
        restored = state()
        return {"before": before, "toggled": toggled, "restored": restored}
    ''', uid=setup["uid"])

    assert result["toggled"]["flag"] != result["before"]["flag"], (
        "is_visible did not flip")
    assert result["toggled"]["hidden"] != result["before"]["hidden"], (
        "the curve's hide_viewport did not follow is_visible, so the panel's "
        "eye icon and the viewport now disagree")
    assert result["restored"] == result["before"], (
        "toggling twice did not return to the original state")


@pytest.mark.live
def test_remove_linker_deletes_the_definition_and_its_curve(blender):
    """Removal must take the curve object with it, not orphan it in the scene."""
    setup = setup_linker(blender, linker_name="Live_L_Remove")

    result = blender.call('''
        scene = bpy.context.scene
        with R.view3d_override():
            bpy.ops.pb2.remove_linker('EXEC_DEFAULT', linker_uid=uid)
        return {"count": len(scene.pb2_linkers),
                "uid_present": any(l.uid == uid for l in scene.pb2_linkers),
                "curve_present": bpy.data.objects.get(curve_name) is not None}
    ''', uid=setup["uid"], curve_name=setup["curve"])

    assert result["count"] == 0
    assert not result["uid_present"]
    assert not result["curve_present"], (
        "the definition is gone but its curve object is still in the scene")


# ---------------------------------------------------------------------------
# Cascade cleanup
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_deleting_the_puppet_removes_its_linkers(blender):
    """A linker lives inside one puppet, so it cannot outlive it."""
    setup = setup_linker(blender, linker_name="Live_L_Cascade_Puppet")

    result = blender.call('''
        scene = bpy.context.scene
        with R.view3d_override():
            bpy.ops.proteinblender.delete_puppet(
                'EXEC_DEFAULT', puppet_id=puppet_id)
        return {"linkers": len(scene.pb2_linkers),
                "curve_present": bpy.data.objects.get(curve_name) is not None}
    ''', puppet_id=setup["puppet_id"], curve_name=setup["curve"])

    assert result["linkers"] == 0, "deleting the puppet left its linkers behind"
    assert not result["curve_present"], (
        "the linker definition was pruned but its curve object survives, so a "
        "dangling curve is still drawn with nothing driving it")


@pytest.mark.live
def test_deleting_an_endpoint_chain_prunes_the_linker(blender):
    """A linker anchored to a deleted chain has no endpoint left to follow."""
    setup = setup_linker(blender, linker_name="Live_L_Cascade_Chain")

    result = blender.call('''
        scene = bpy.context.scene
        with R.view3d_override():
            bpy.ops.molecule.delete_chain(
                'EXEC_DEFAULT', chain_id=chain_id, molecule_id=mid)
        return {"linkers": len(scene.pb2_linkers),
                "curve_present": bpy.data.objects.get(curve_name) is not None}
    ''', chain_id=setup["chains"][0]["chain_id"], mid=setup["molecule_id"],
        curve_name=setup["curve"])

    assert result["linkers"] == 0, (
        "deleting an endpoint chain left a linker pointing at nothing")
    assert not result["curve_present"], "the orphaned curve object survives"


@pytest.mark.live
def test_deleting_the_protein_removes_its_linkers(blender):
    """Deleting the whole molecule cascades through puppet and linker alike."""
    setup = setup_linker(blender, linker_name="Live_L_Cascade_Protein")

    result = blender.call('''
        scene = bpy.context.scene
        with R.view3d_override():
            bpy.ops.molecule.delete('EXEC_DEFAULT', molecule_id=mid)
        return {"linkers": len(scene.pb2_linkers),
                "curve_present": bpy.data.objects.get(curve_name) is not None}
    ''', mid=setup["molecule_id"], curve_name=setup["curve"])

    assert result["linkers"] == 0, (
        "deleting the protein left linkers referencing it")
    assert not result["curve_present"], "the orphaned curve object survives"


# ---------------------------------------------------------------------------
# What the user sees - the assertions no other lane makes about linkers
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_a_linker_actually_renders(blender, shot):
    """A linker must put pixels on the screen, and they must be its own.

    "Something is on screen" is not enough: the protein it connects is on screen
    too, and framing tightly on the curve still catches the chains behind it. So
    the linker is measured by *subtraction* - capture with it visible, hide it
    through the public visibility toggle, capture again. Coverage has to fall,
    and the two images have to differ. Both hold only if the linker was
    contributing pixels of its own.

    This is the check nothing else in the suite performs. The headless tests
    assert the curve object exists and that its control points are where the
    maths says; a curve with no bevel and no radius satisfies all of that and
    draws a mathematically perfect nothing.
    """
    setup = setup_linker(blender, linker_name="Live_L_Render",
                         length_residues=60)

    geometry = curve_points(blender, setup["uid"])
    assert geometry is not None
    assert geometry["visible"], "the linker's curve object is not visible"

    # Frame on the linker so it occupies a useful share of the frame; the
    # protein remains behind it, which is exactly why the hide/show subtraction
    # below is necessary.
    blender.call("return R.frame_all(objects=[name])", name=setup["curve"])
    visible = blender.call('return R.capture("linker-visible")')
    shot("linker-visible", frame=False)

    blender.call('''
        with R.view3d_override():
            bpy.ops.pb2.toggle_linker_visibility('EXEC_DEFAULT', linker_uid=uid)
        return None
    ''', uid=setup["uid"])
    hidden = blender.call('return R.capture("linker-hidden")')
    shot("linker-hidden", frame=False)

    difference = blender.call('return R.compare("linker-visible", "linker-hidden")')

    assert visible["covered"] > 0, "nothing at all rendered"
    assert difference["xor"] > 0, (
        "hiding the linker changed nothing on screen. Either the linker was "
        "never drawn - a curve with no bevel or radius renders as nothing even "
        "though its control points are correct - or the visibility toggle does "
        "not affect the render")
    assert visible["covered"] > hidden["covered"], (
        f"hiding the linker did not reduce coverage ({visible['covered']} -> "
        f"{hidden['covered']}); the pixels that disappeared were not the "
        "linker's")


@pytest.mark.live
@pytest.mark.visual
def test_tube_and_beads_render_differently(blender, shot):
    """The style property must change geometry, not just the definition.

    TUBE and BEADS are two different shapes for the same path. The headless
    tests can see the enum value change and can see the control points, which
    are identical between the two styles - the path does not move, only what is
    swept along it. That makes this difference invisible to every existing
    assertion and visible only to a renderer.

    The view is framed once, before the style change, and not re-framed:
    re-framing on a slightly different bounding box would move the subject and
    produce a difference even if the two styles drew identically.
    """
    setup = setup_linker(blender, linker_name="Live_L_Style",
                         length_residues=60, style="TUBE")

    blender.call("return R.frame_all(objects=[name])", name=setup["curve"])
    tube = blender.call('return R.capture("tube")')
    shot("style-tube", frame=False)
    assert tube["covered"] > 0, "the TUBE linker rendered nothing"

    blender.call('''
        with R.view3d_override():
            bpy.ops.pb2.edit_linker(
                'EXEC_DEFAULT',
                linker_uid=uid,
                puppet_selector=puppet_id,
                endpoint_a_item="A_" + item_a,
                endpoint_a_residue=residue_a,
                endpoint_b_item="B_" + item_b,
                endpoint_b_residue=residue_b,
                linker_name="Live_L_Style",
                length_residues=60,
                style="BEADS",
                rendering_mode="QUICK",
                behavior="GRAVITY")
        return None
    ''', uid=setup["uid"], puppet_id=setup["puppet_id"],
        item_a=setup["chains"][0]["item_id"],
        residue_a=setup["chains"][0]["residue"],
        item_b=setup["chains"][1]["item_id"],
        residue_b=setup["chains"][1]["residue"])

    beads = blender.call('return R.capture("beads")')
    shot("style-beads", frame=False)

    difference = blender.call('return R.compare("tube", "beads")')

    assert beads["covered"] > 0, (
        "switching to BEADS rendered nothing; the bead geometry never reached "
        "the viewport")
    assert not difference["identical"], (
        "a TUBE linker and a BEADS linker render identically. The style is "
        "stored on the definition but never applied to the geometry")


@pytest.mark.live
@pytest.mark.visual
def test_linker_color_reaches_the_render(blender):
    """A linker's colour must be visible, not merely recorded.

    This is the failure mode this lane was built for and the one already caught
    in ``molecule.update_domain_color``: the property updates, the panel shows
    the new swatch, and the render never changes. Every pixel check in the
    headless suite reduces its render to an alpha mask and discards RGB, so
    colour is invisible there by construction.

    The molecule is hidden so the linker is the only thing on screen - otherwise
    the protein's own colour dominates the frame-wide mean and a linker a few
    pixels wide cannot move it. That leaves an unambiguous control: recolour red
    to blue and the dominant channel must follow. Measurements are taken first
    and the viewport shading restored before asserting, so a failure does not
    leave the session in MATERIAL shading for the next test.
    """
    setup = setup_linker(blender, linker_name="Live_L_Color",
                         length_residues=60)
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")

    measured = blender.call('''
        scene = bpy.context.scene
        linker = next(l for l in scene.pb2_linkers if l.uid == uid)
        curve_name = linker.curve_object_name

        def current_curve():
            # edit_linker rebuilds the linker in place and may hand back a
            # different object, so never cache the curve across a call.
            live = next(l for l in scene.pb2_linkers if l.uid == uid)
            return live.curve_object_name

        # Isolate the linker: with the protein on screen its colour dominates
        # the mean over covered pixels and the linker cannot be measured.
        # Re-applied after every rebuild, since a freshly created curve object
        # starts visible and anything else new would pollute the measurement.
        hidden = []

        def isolate(keep_name):
            for obj in bpy.data.objects:
                if obj.name == keep_name:
                    obj.hide_viewport = False
                elif not obj.hide_viewport:
                    obj.hide_viewport = True
                    hidden.append(obj.name)

        def recolor(rgba):
            with R.view3d_override():
                bpy.ops.pb2.edit_linker(
                    'EXEC_DEFAULT',
                    linker_uid=uid,
                    puppet_selector=puppet_id,
                    endpoint_a_item="A_" + item_a,
                    endpoint_a_residue=residue_a,
                    endpoint_b_item="B_" + item_b,
                    endpoint_b_residue=residue_b,
                    linker_name="Live_L_Color",
                    length_residues=60,
                    style="TUBE",
                    rendering_mode="QUICK",
                    behavior="GRAVITY",
                    color=rgba)
            return None

        try:
            R.frame_all(objects=[curve_name])
            isolate(curve_name)
            recolor((1.0, 0.0, 0.0, 1.0))
            isolate(current_curve())
            red = R.capture("linker-red")
            recolor((0.0, 0.0, 1.0, 1.0))
            isolate(current_curve())
            blue = R.capture("linker-blue")
            final = bpy.data.objects.get(current_curve())
            materials = ([m.name for m in final.data.materials if m]
                         if final is not None else [])
        finally:
            for name in hidden:
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    obj.hide_viewport = False
        return {"red": red, "blue": blue, "materials": materials}
    ''', uid=setup["uid"], puppet_id=setup["puppet_id"],
        item_a=setup["chains"][0]["item_id"],
        residue_a=setup["chains"][0]["residue"],
        item_b=setup["chains"][1]["item_id"],
        residue_b=setup["chains"][1]["residue"])

    difference = blender.call('return R.compare("linker-red", "linker-blue")')
    blender.call("return R.set_shading(kind='SOLID', color_type='MATERIAL')")

    red, blue = measured["red"], measured["blue"]
    assert red["covered"] > 0, (
        "the linker rendered nothing with the protein hidden, so its colour "
        "cannot be measured")
    assert blue["covered"] > 0, "the linker vanished when it was recoloured"

    assert difference["rgb_delta"] > 0, (
        "recolouring the linker from red to blue left the render "
        "byte-identical; the colour is stored on the definition but never "
        "reaches the material that is drawn")
    assert red["dominant_channel"] == 0, (
        f"a red linker rendered with dominant channel {red['dominant_channel']} "
        f"(mean RGB {red['mean_rgb']})")
    assert blue["dominant_channel"] == 2, (
        f"a blue linker rendered with dominant channel "
        f"{blue['dominant_channel']} (mean RGB {blue['mean_rgb']})")
