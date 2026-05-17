"""PropertyGroup for the Membrane Builder panel.

The scene-level properties feed the build dialog. When the active object is
an existing membrane (``pb_is_membrane`` custom property set), the panel
syncs the props from the object so the user is editing the selected membrane
in-place.
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
    """When a property changes, write it through to the active membrane object.

    Only fires when there is a selected membrane — otherwise the value just
    sits on the scene props for the next Build click.
    """
    obj = context.active_object
    if obj is None or not obj.get("pb_is_membrane", False):
        return
    # Avoid recursive sync — guard via a class-level flag set in the
    # object→props sync path.
    if getattr(MembraneBuilderProperties, "_syncing_from_object", False):
        return
    from .membrane_operators import apply_props_to_membrane
    try:
        apply_props_to_membrane(obj, self)
    except Exception:
        pass


class MembraneBuilderProperties(PropertyGroup):
    """Scene-level properties for the Membrane Builder UI."""

    _syncing_from_object = False  # class flag (see msgbus callback below)

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
        description="Distance between the two leaflets' head groups, in nm",
        default=4.0,
        min=1.0,
        max=15.0,
        soft_max=8.0,
        update=_sync_to_active_membrane,
    )

    lipid_scale: FloatProperty(
        name="Lipid Size",
        description="Overall scale of each lipid (head + tails)",
        default=1.0,
        min=0.3,
        max=3.0,
        update=_sync_to_active_membrane,
    )

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
    color_head: FloatVectorProperty(
        name="Head Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.92, 0.30, 0.55, 1.0),
    )

    color_tail: FloatVectorProperty(
        name="Tail Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.98, 0.82, 0.30, 1.0),
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
    show_deform_section: BoolProperty(name="Show Deform Section", default=False)
    show_holes_section: BoolProperty(name="Show Holes Section", default=True)


CLASSES = (MembraneBuilderProperties,)


# ---------------------------------------------------------------------------
# Auto-sync: when a membrane becomes the active object, copy its stored
# settings into the scene's membrane_builder_props so the panel acts as an
# editor for the selected membrane.
# ---------------------------------------------------------------------------

_PROP_KEYS = (
    "width",
    "height",
    "density",
    "bilayer_thickness",
    "lipid_scale",
    "random_rotation",
    "animate_bob",
    "bob_amplitude",
    "bob_speed",
    "color_head",
    "color_tail",
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


@persistent
def _load_post_handler(_dummy):
    register_msgbus()
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
