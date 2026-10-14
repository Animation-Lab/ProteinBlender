"""PropertyGroup for the Membrane Builder panel.

The scene-level properties feed the build dialog. When the active object is
an existing membrane (``pb_is_membrane`` custom property set), the panel
syncs the props from the object so the user is editing the selected membrane
in-place.

The same props also describe a membrane that does not exist yet, while the
Create New Membrane dialog is open. That is a *draft*: see
``begin_new_membrane_draft`` for why it must reach no existing membrane.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


# Max number of simultaneous hole controllers (matches GN tree slot count).
MAX_HOLES = 8


def _sync_to_active_membrane(self, context):
    """When a property changes, write it through to the relevant membrane.

    Nothing is written while the props are a draft for a new membrane (see
    ``begin_new_membrane_draft``). Otherwise, resolution order:
      1. ``context.active_object`` if it is a membrane root or one of its
         children (lattice / hole), via ``_get_membrane_root``.
      2. If the active object isn't related to any membrane, fall back to
         the single membrane in the scene — there's no ambiguity, so
         changing the panel sliders should still drive it.
      3. If there are multiple membranes and none is the active context,
         we genuinely can't tell which one to edit. Stay silent so the
         value still updates the scene panel for the next Build click.

    Tester report (Janet, Windows): "Changing the number for lipid
    density doesn't seem to work after you build a membrane". Root
    cause: the user had clicked elsewhere after Build, the active
    object was no longer the membrane, and the prop change went
    nowhere. The single-membrane fallback (case 2 above) makes the
    common case Just Work.
    """
    if getattr(MembraneBuilderProperties, "_syncing_from_object", False):
        # Re-entrancy guard: this same prop change can be triggered by
        # the object→props sync path, and we don't want to loop.
        return
    if MembraneBuilderProperties._draft_restore is not None:
        return
    from .membrane_operators import _get_membrane_root, apply_props_to_membrane

    # During file load / early-init the Context may not yet expose
    # active_object or scene — fall back to None / no sync rather than
    # raising AttributeError to stderr.
    active_obj = getattr(context, "active_object", None)
    scene = getattr(context, "scene", None)

    target = _get_membrane_root(active_obj) if active_obj is not None else None
    if target is None and scene is not None:
        candidates = [o for o in scene.objects
                      if o.get("pb_is_membrane", False)]
        if len(candidates) == 1:
            target = candidates[0]
    if target is None:
        return

    try:
        apply_props_to_membrane(target, self)
    except Exception:
        pass


class MembraneBuilderProperties(PropertyGroup):
    """Scene-level properties for the Membrane Builder UI."""

    _syncing_from_object = False  # class flag (see msgbus callback below)
    # The fields as they stood when Create New Membrane opened, or None when
    # no draft is open (see begin_new_membrane_draft).
    _draft_restore = None

    # ------------------------------------------------------------------
    # Size
    # ------------------------------------------------------------------
    width: FloatProperty(
        name="Width",
        description="Membrane width in nanometers (X axis)",
        default=20.0,
        min=2.0,
        max=200.0,
        soft_max=80.0,
        unit="NONE",
        update=_sync_to_active_membrane,
    )

    height: FloatProperty(
        name="Height",
        description="Membrane height in nanometers (Y axis)",
        default=20.0,
        min=2.0,
        max=200.0,
        soft_max=80.0,
        unit="NONE",
        update=_sync_to_active_membrane,
    )

    # ------------------------------------------------------------------
    # Shape
    # ------------------------------------------------------------------
    shape: EnumProperty(
        name="Shape",
        description=(
            "Sheet = a flat patch. Sphere = a closed vesicle (lipids on both "
            "the outer and inner surfaces). Hemisphere = an open-top bowl, "
            "so you can look down inside the cell"
        ),
        items=(
            ("FLAT", "Sheet", "A flat membrane patch (default)"),
            ("SPHERE", "Sphere", "A closed spherical vesicle"),
            ("HEMISPHERE", "Hemisphere", "Open-top bowl — useful for "
             "cell-cutaway visualisations"),
        ),
        default="FLAT",
        update=_sync_to_active_membrane,
    )

    radius: FloatProperty(
        name="Radius",
        description="Membrane radius in nanometers (used in Sphere / Hemisphere mode)",
        default=15.0,
        min=2.0,
        max=200.0,
        soft_max=80.0,
        unit="NONE",
        update=_sync_to_active_membrane,
    )

    # ------------------------------------------------------------------
    # Lipid look
    # ------------------------------------------------------------------
    density: FloatProperty(
        name="Lipid Density",
        description=(
            "Lipids per nm² in each leaflet. A real fluid bilayer packs "
            "~1.5 lipids/nm² (each lipid occupies ~0.65 nm²) — the default. "
            "Lower values look sparse/artificial; raise it for a tighter, "
            "more crowded membrane"
        ),
        default=1.5,
        min=0.05,
        max=5.0,
        soft_max=3.0,
        update=_sync_to_active_membrane,
    )

    bilayer_thickness: FloatProperty(
        name="Bilayer Thickness",
        description=(
            "Visible thickness of the rendered bilayer, in nm — measured "
            "from the top of the upper leaflet's head groups to the "
            "bottom of the lower leaflet's head groups. Internally the "
            "leaflets are inset by the per-style lipid mesh extent so the "
            "slider value equals what you measure with a ruler. Above about "
            "4.8 nm the leaflets are pushed further apart than the lipid "
            "meshes are long, which opens a visible void down the midplane"
        ),
        # 4.8, not the 5.0 of a real fluid PC bilayer. The SURFACE lipid mesh
        # runs ~0.80 nm above its origin and only 1.25-1.65 nm below, so two
        # leaflets can span about 4.8 nm before their tails stop meeting.
        # Measured across the slider range: 4.8 leaves a 0.08 nm midplane gap
        # (tails touching, reads as a solid hydrophobic core), while 5.0 opens
        # it to 0.28 nm and shows as a seam down the middle of the membrane.
        # 4.8 also reproduces the 1.6 nm half-offset this builder used before
        # the slider was redefined from origin-to-origin to outer-to-outer.
        default=4.8,
        min=2.0,
        max=15.0,
        soft_max=8.0,
        update=_sync_to_active_membrane,
    )

    # Render style — picks which collection feeds the GN modifier's
    # Lipid Collection input. Items are pulled into a static tuple at
    # class-build time (callback-style EnumProperty doesn't support a
    # ``default=`` argument).
    from . import lipid_assets as _la
    render_style: EnumProperty(
        name="Render Style",
        description=(
            "How each lipid is drawn. Stylized = head sphere + two bent "
            "tail tubes following the PDB pose; Ball and Stick = real "
            "PDB atoms + bonds"
        ),
        items=_la.RENDER_STYLE_ITEMS,
        default=_la.DEFAULT_STYLE,
        update=_sync_to_active_membrane,
    )
    del _la

    random_rotation: BoolProperty(
        name="Randomize Lipid Rotation",
        description=(
            "Randomly rotate each lipid around its long axis so the top view "
            "looks bumpy and natural rather than uniform"
        ),
        default=True,
        update=_sync_to_active_membrane,
    )

    # ------------------------------------------------------------------
    # Bobbing animation (pseudo-random per lipid)
    # ------------------------------------------------------------------
    animate_bob: BoolProperty(
        name="Animate Bobbing",
        description=(
            "Each lipid jostles like a crowd in a mosh pit — bobbing, "
            "swaying sideways, leaning and twisting on six independent "
            "axes. Phase, speed and amplitude are randomised per lipid, so "
            "no two move alike. Fully deterministic (seeded by lipid index, "
            "not random state) — the animation plays back identically "
            "every time."
        ),
        default=False,
        update=_sync_to_active_membrane,
    )

    bob_amplitude: FloatProperty(
        name="Motion Amount",
        description=(
            "Master amount of jostling, in nm. Scales every motion axis at "
            "once (vertical bob, lateral sway, lean and twist). Each lipid "
            "gets its own randomised fraction of this."
        ),
        default=0.3,
        min=0.0,
        max=3.0,
        soft_max=1.5,
        update=_sync_to_active_membrane,
    )

    bob_speed: FloatProperty(
        name="Motion Speed",
        description=(
            "Master tempo of the jostling, in cycles per second. Each lipid "
            "and each motion axis gets a randomised fraction of this, so the "
            "crowd never moves in lockstep."
        ),
        default=0.6,
        min=0.05,
        max=5.0,
        update=_sync_to_active_membrane,
    )

    # ------------------------------------------------------------------
    # Deformation (lattice resolution)
    # ------------------------------------------------------------------
    lattice_resolution: IntProperty(
        name="Deform Resolution",
        description=(
            "Lattice grid resolution for surface deformation. More = finer "
            "control but slower. Applied at creation time."
        ),
        default=5,
        min=2,
        max=12,
    )

    # ------------------------------------------------------------------
    # Colors
    # ------------------------------------------------------------------
    # Head/tail must write through on change like every other membrane
    # property. Without the callback the pick lived only in these scene props:
    # no live preview, and the object->props sync that fires whenever the
    # active object changes (in-dialog Add Hole / Edit Deformation / Select
    # Hole all change it) replaced the pick with the membrane's stale stored
    # colour, which OK then re-applied. Tester report (Janet): "changing the
    # lipid colors can be buggy ... especially the head domains".
    color_head: FloatVectorProperty(
        name="Head Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.92, 0.30, 0.55, 1.0),
        update=_sync_to_active_membrane,
    )

    color_tail: FloatVectorProperty(
        name="Tail Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.98, 0.82, 0.30, 1.0),
        update=_sync_to_active_membrane,
    )

    # Single colour for the SURFACE render style — head and tail share it,
    # which is the whole point of that style. Default off-white matches
    # the reference render the user picked the style from.
    color_surface: FloatVectorProperty(
        name="Lipid Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.92, 0.92, 0.92, 1.0),
        update=_sync_to_active_membrane,
    )

    # ------------------------------------------------------------------
    # Name
    # ------------------------------------------------------------------
    name_prefix: StringProperty(
        name="Name",
        description="Base name for the new membrane object",
        default="Membrane",
    )

    # Collapsible sections in the panel
    show_lipid_section: BoolProperty(name="Show Lipid Section", default=True)
    show_animation_section: BoolProperty(name="Show Animation Section", default=False)
    show_colors_section: BoolProperty(name="Show Colors Section", default=False)
    show_holes_section: BoolProperty(name="Show Holes Section", default=True)


CLASSES = (MembraneBuilderProperties,)


# ---------------------------------------------------------------------------
# Auto-sync: when a membrane becomes the active object, copy its stored
# settings into the scene's membrane_builder_props so the panel acts as an
# editor for the selected membrane.
# ---------------------------------------------------------------------------

_PROP_KEYS = (
    "shape",
    "width",
    "height",
    "radius",
    "density",
    "bilayer_thickness",
    "random_rotation",
    "animate_bob",
    "bob_amplitude",
    "bob_speed",
    "color_head",
    "color_tail",
    "color_surface",
    "render_style",
)

_msgbus_owner = object()


def sync_props_from_object(props, obj) -> bool:
    """Copy pb_membrane_* custom props from *obj* into *props*.

    Returns True if any value was actually changed.
    """
    if not obj or not obj.get("pb_is_membrane", False):
        return False

    changed = False
    # Block the props' update callbacks from writing back to the object during
    # this sync — we're copying object→props, not the other way around.
    MembraneBuilderProperties._syncing_from_object = True
    try:
        for key in _PROP_KEYS:
            val = obj.get(f"pb_mem_{key}")
            if val is None:
                continue
            try:
                cur = getattr(props, key)
                is_seq = hasattr(cur, "__iter__") and not isinstance(cur, str)
                if is_seq:
                    cur_list = list(cur)
                    new_list = list(val)
                    if cur_list != new_list:
                        setattr(props, key, new_list)
                        changed = True
                else:
                    if cur != val:
                        setattr(props, key, val)
                        changed = True
            except Exception:
                pass
    finally:
        MembraneBuilderProperties._syncing_from_object = False
    return changed


def _on_active_object_changed(*_args):
    try:
        ctx = bpy.context
        scene = getattr(ctx, "scene", None)
        if scene is None or not hasattr(scene, "membrane_builder_props"):
            return
        obj = getattr(ctx, "active_object", None)
        if obj is None:
            return
        # Allow sync if the active obj is the membrane itself, OR a child
        # object (hole, lattice) — resolve to its membrane.
        target = obj
        if not obj.get("pb_is_membrane", False):
            owner = obj.get("pb_membrane_owner")
            if owner:
                target = bpy.data.objects.get(owner)
        if target is None:
            return
        sync_props_from_object(scene.membrane_builder_props, target)
    except Exception:
        pass


def register_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.LayerObjects, "active"),
            owner=_msgbus_owner,
            args=(),
            notify=_on_active_object_changed,
        )
    except Exception:
        pass


def unregister_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Drafting a new membrane
# ---------------------------------------------------------------------------

def begin_new_membrane_draft(props) -> None:
    """Start describing a membrane that has not been built yet.

    Create New Membrane and Edit Membrane draw the same props, and in Edit a
    change is written through to the membrane at once. In Create there is no
    membrane for it to land on, but the write-through looked for one anyway and
    found the active membrane - which, straight after a build, is the one just
    built. Tester report (alpha 1.2.3): asked for one sheet and one hemisphere,
    got two sheets, because choosing Sheet for the second reshaped the first
    before OK was pressed.

    While a draft is open the props reach no membrane. It ends with
    ``finish_new_membrane_draft`` (OK) or ``discard_new_membrane_draft``
    (cancel).
    """
    MembraneBuilderProperties._draft_restore = {
        key: _plain(getattr(props, key)) for key in _PROP_KEYS
    }


def finish_new_membrane_draft() -> None:
    """The draft is being built, so the props describe a real membrane again."""
    MembraneBuilderProperties._draft_restore = None


def discard_new_membrane_draft(props) -> None:
    """Drop the draft and put the props back as they were before it.

    Putting them back matters as much as stopping the write-through. The
    props outlive the dialog - Adjust Last Operation draws the same form - and
    a change there applies every one of them to the active membrane. Left
    holding the abandoned draft, the next field touched would deliver the
    cancelled shape to a membrane the user never asked to change.
    """
    restore = MembraneBuilderProperties._draft_restore
    if restore is None:
        return
    try:
        # Still a draft while the values go back, so none of them write through.
        for key, value in restore.items():
            if _plain(getattr(props, key)) != value:
                setattr(props, key, value)
    finally:
        MembraneBuilderProperties._draft_restore = None


def _plain(value):
    """A prop value detached from Blender: vectors come back as live arrays."""
    if hasattr(value, "__iter__") and not isinstance(value, str):
        return tuple(value)
    return value


@persistent
def _load_post_handler(_dummy):
    register_msgbus()
    # No dialog survives a file load, so neither does a draft.
    finish_new_membrane_draft()
    # Upgrade any membranes built with an older GN tree so they pick up new
    # motion features. get_or_build rebuilds + re-applies when it sees a
    # stale version tag; skip the work entirely if there are no membranes.
    try:
        if any(o.get("pb_is_membrane", False) for o in bpy.data.objects):
            from .membrane_geometry import get_or_build_membrane_gn_tree
            get_or_build_membrane_gn_tree()
    except Exception:
        pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.membrane_builder_props = bpy.props.PointerProperty(
        type=MembraneBuilderProperties
    )
    register_msgbus()
    if _load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_handler)


def unregister():
    unregister_msgbus()
    if _load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_handler)
    if hasattr(bpy.types.Scene, "membrane_builder_props"):
        del bpy.types.Scene.membrane_builder_props
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
