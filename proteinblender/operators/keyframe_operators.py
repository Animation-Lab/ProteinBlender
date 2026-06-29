"""Keyframe operators for animation functionality"""

import bpy
import json
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, IntProperty, CollectionProperty, StringProperty
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.chain_utils import get_puppet_member_objects as _resolve_puppet_member_objects
from ..utils.animation import (
    keyframe_transforms,
    delete_transform_keyframes,
    keyframe_color_properties,
    remove_color_keyframes,
    has_color_keyframe,
    get_fcurves_from_action,
    ensure_quaternion_mode,
)
from ..utils.brownian import (
    get_brownian_metadata,
    save_brownian_metadata,
    find_previous_keyframe,
)


# ============================================================================
# Keyframe Metadata Storage Functions
# ============================================================================

def get_keyframe_metadata(controller_obj, frame):
    """Retrieve stored keyframe settings for a specific frame.

    Args:
        controller_obj: The puppet controller Empty object
        frame: The frame number to retrieve metadata for

    Returns:
        Dictionary with keyframe settings, or None if not found
    """
    if not controller_obj or 'pb_keyframe_metadata' not in controller_obj:
        return None

    try:
        metadata_str = controller_obj['pb_keyframe_metadata']
        metadata = json.loads(metadata_str)
        return metadata.get(str(frame), None)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Warning: Failed to load keyframe metadata: {e}")
        return None


def save_keyframe_metadata(controller_obj, frame, settings):
    """Save keyframe settings to controller object as custom property.

    Args:
        controller_obj: The puppet controller Empty object
        frame: The frame number to save metadata for
        settings: PuppetKeyframeSettings object with checkbox states
    """
    if not controller_obj:
        return

    # Get existing metadata or create new dictionary
    if 'pb_keyframe_metadata' in controller_obj:
        try:
            metadata_str = controller_obj['pb_keyframe_metadata']
            metadata = json.loads(metadata_str)
        except (json.JSONDecodeError, KeyError, TypeError):
            metadata = {}
    else:
        metadata = {}

    # Store settings for this frame
    metadata[str(frame)] = {
        'use_puppet': settings.use_puppet,
        'location': settings.keyframe_location,
        'rotation': settings.keyframe_rotation,
        'scale': settings.keyframe_scale,
        'pose': settings.keyframe_pose,
        'color': settings.keyframe_color,
    }

    # Save back to object as custom property (automatically saved in .blend file)
    controller_obj['pb_keyframe_metadata'] = json.dumps(metadata)


def check_existing_keyframes(controller_obj, domain_objects, frame):
    """Check which properties actually have keyframes at the specified frame.

    This queries Blender's F-Curves to detect what's actually keyframed,
    which can be used to validate stored metadata.

    Args:
        controller_obj: The puppet controller Empty object
        domain_objects: List of domain objects belonging to this puppet
        frame: The frame number to check

    Returns:
        Dictionary with boolean values for each property type
    """
    keyframe_state = {
        'location': False,
        'rotation': False,
        'scale': False,
        'pose': False,
        'color': False
    }

    # Check controller object F-Curves
    if controller_obj and controller_obj.animation_data and controller_obj.animation_data.action:
        action = controller_obj.animation_data.action
        fcurves = get_fcurves_from_action(action, controller_obj.animation_data)
        for fcurve in fcurves:
            # Check if any keyframe exists at this frame
            for kf in fcurve.keyframe_points:
                if abs(kf.co.x - frame) < 0.01:  # Frame match (with float tolerance)
                    if 'location' in fcurve.data_path:
                        keyframe_state['location'] = True
                    elif 'rotation' in fcurve.data_path:
                        keyframe_state['rotation'] = True
                    elif 'scale' in fcurve.data_path:
                        keyframe_state['scale'] = True
                    break

    # Check domain objects for pose keyframes (local transforms)
    for domain_obj in domain_objects:
        if domain_obj.animation_data and domain_obj.animation_data.action:
            action = domain_obj.animation_data.action
            fcurves = get_fcurves_from_action(action, domain_obj.animation_data)
            for fcurve in fcurves:
                for kf in fcurve.keyframe_points:
                    if abs(kf.co.x - frame) < 0.01:
                        # Any keyframe on domain objects indicates pose keyframing
                        keyframe_state['pose'] = True
                        break
                if keyframe_state['pose']:
                    break
        if keyframe_state['pose']:
            break

    # Check for color keyframes in geometry nodes
    for domain_obj in domain_objects:
        if has_color_keyframe(domain_obj, frame):
            keyframe_state['color'] = True
            break

    return keyframe_state




def validate_keyframe_metadata(controller_obj, domain_objects, frame, stored_settings):
    """Validate stored metadata against actual F-Curves.

    Args:
        controller_obj: The puppet controller Empty object
        domain_objects: List of domain objects
        frame: Frame number to validate
        stored_settings: Dictionary of stored settings

    Returns:
        List of discrepancy messages (empty if everything matches)
    """
    if not stored_settings:
        return []

    actual_state = check_existing_keyframes(controller_obj, domain_objects, frame)
    discrepancies = []

    # Check each property
    for key in ['location', 'rotation', 'scale', 'pose', 'color']:
        stored_value = stored_settings.get(key, False)
        actual_value = actual_state.get(key, False)

        if stored_value and not actual_value:
            discrepancies.append(f"{key.capitalize()} metadata indicates keyframe, but none found in timeline")
        elif not stored_value and actual_value:
            discrepancies.append(f"{key.capitalize()} keyframe found in timeline, but metadata says unchecked")

    return discrepancies


# ============================================================================
# Keyframe target discovery (single source of truth)
# ============================================================================

def get_keyframe_targets(context):
    """Return ``[(label, object, kind, item_id)]`` for everything ProteinBlender
    can keyframe: puppet controllers (kind ``'PUPPET'``), DNA/RNA molecule
    objects (kind ``'MOLECULE'``, keyframed directly) and membrane roots
    (kind ``'MEMBRANE'`` — root transform + holes + lattice deformation).

    Shared by the Create dialog, the keyframe list and keyframe deletion so all
    three agree on what is animatable.
    """
    scene = context.scene
    sm = ProteinBlenderScene.get_instance()
    targets, seen = [], set()
    for item in scene.outliner_items:
        if (item.item_type == 'PUPPET' and item.item_id != "puppets_separator"
                and item.controller_object_name):
            obj = bpy.data.objects.get(item.controller_object_name)
            if obj and obj.name not in seen:
                seen.add(obj.name)
                targets.append((item.name, obj, 'PUPPET', item.item_id))
    for item in scene.outliner_items:
        if item.item_type == 'DNA_RNA':
            mol = sm.molecules.get(item.item_id)
            obj = (mol.object if mol else None) or bpy.data.objects.get(item.object_name)
            if obj and obj.name not in seen:
                seen.add(obj.name)
                targets.append((item.name, obj, 'MOLECULE', item.item_id))
    for item in scene.outliner_items:
        if item.item_type == 'MEMBRANE':
            obj = bpy.data.objects.get(item.object_name)
            if obj and obj.name not in seen and obj.get("pb_is_membrane", False):
                seen.add(obj.name)
                targets.append((item.name, obj, 'MEMBRANE', item.item_id))
    return targets


def get_membrane_holes(mem_obj):
    """Hole-controller empties belonging to a membrane (or [] if none). Each
    hole's transform IS what shapes the hole — its world position is the hole
    centre, its scale the radius — so all of them must be keyframed for a
    membrane animation to capture hole movement."""
    if mem_obj is None:
        return []
    return [c for c in mem_obj.children if c.get("pb_is_membrane_hole", False)]


def get_membrane_lattice(mem_obj):
    """Lattice deformer child of a membrane, or None if it has none. The
    surface deformation lives in the lattice DATA's ``points[i].co_deform``,
    NOT in the lattice OBJECT's transform — keyframes for deformation must
    target the data block, not the object."""
    if mem_obj is None:
        return None
    for c in mem_obj.children:
        if c.type == "LATTICE":
            return c
    return None


def get_dna_bend_nodes(dna_obj):
    """Bend control-node empties for a DNA/RNA object, or [] if it has no bend
    rig. These empties drive the bend curve, so they must be keyframed for a
    bend to animate — the molecule's own transform does NOT capture the shape."""
    if dna_obj is None:
        return []
    try:
        from ..dna_builder.bender import get_bend_nodes
        return get_bend_nodes(dna_obj)
    except Exception:
        return []


def get_dna_bend_objects(dna_obj):
    """The bend curve plus its control-node empties — every object whose
    transform shapes a DNA/RNA bend (empty list if there's no bend rig). All
    must be keyframed with FULL transforms: a hook responds to a node's
    rotation and scale, not only its location, so location-only keys would drop
    any twist the user dialed in."""
    if dna_obj is None:
        return []
    objs = []
    try:
        from ..dna_builder.bender import get_bend_curve
        curve = get_bend_curve(dna_obj)
        if curve is not None:
            objs.append(curve)
    except Exception:
        pass
    objs.extend(get_dna_bend_nodes(dna_obj))
    return objs


def get_keyframe_animated_objects(obj, kind):
    """Every object whose transform F-curves make up one keyframe target's
    animation. The target object itself, plus — for a DNA/RNA molecule (kind
    'MOLECULE') — its bend curve and control nodes, and for a membrane (kind
    'MEMBRANE') — its hole controllers. A single keyframe in the Animate panel
    captures the full target (bend / holes) automatically, no extra step.

    The membrane LATTICE is intentionally NOT in this list: its deformation
    keys live on ``lattice.data.animation_data``, not on the object — see
    :func:`get_keyframe_frames` and the create/delete operators, which handle
    that separate data-block path explicitly.
    """
    objs = [obj]
    if kind == 'MOLECULE':
        objs.extend(get_dna_bend_objects(obj))
    elif kind == 'MEMBRANE':
        objs.extend(get_membrane_holes(obj))
    return objs


def _iter_lattice_data_fcurves(mem_obj):
    """F-curves on a membrane's lattice DATA block (``points[i].co_deform``
    channels), or an empty iterator if the membrane has no lattice / no keys.
    Surface-deformation keys never appear on the lattice object itself, so
    every place that scans for membrane keyframes must also visit this."""
    lat = get_membrane_lattice(mem_obj)
    if lat is None or lat.data is None:
        return
    ad = lat.data.animation_data
    if not ad or not ad.action:
        return
    for fc in get_fcurves_from_action(ad.action, ad):
        yield fc


def _target_owned_object_names(context, obj, kind, item_id):
    """Every Blender object a user could plausibly click in the viewport to
    *mean* this keyframe target — the target itself plus the children whose
    transforms the target's animation captures. Used by
    ``get_filtered_keyframe_targets`` to decide whether the current selection
    matches a given target."""
    names = {obj.name}
    if kind == 'PUPPET':
        # Use the local wrapper (context, item_id), NOT the raw chain_utils
        # function — that one has signature (scene, scene_manager, puppet_item)
        # and a wrong-arity call breaks the panel as soon as a puppet exists.
        for o in get_puppet_member_objects(context, item_id):
            if o is not None:
                names.add(o.name)
    elif kind == 'MOLECULE':
        for o in get_dna_bend_objects(obj):
            if o is not None:
                names.add(o.name)
    elif kind == 'MEMBRANE':
        for o in get_membrane_holes(obj):
            if o is not None:
                names.add(o.name)
        lat = get_membrane_lattice(obj)
        if lat is not None:
            names.add(lat.name)
    return names


def get_filtered_keyframe_targets(context):
    """Return ``(targets, n_selected)`` — the subset of keyframe targets that
    the user's current selection implies, plus how many selected objects we
    matched against. If nothing relevant is selected, return ALL targets
    with ``n_selected = 0`` so the panel keeps showing every keyframe.

    A target is included if any of its owned objects (target itself + its
    members / holes / bend nodes / lattice) is in the selection — so a user
    can click a puppet member chain, or a single membrane hole, to scope
    the keyframe view to that target."""
    all_targets = get_keyframe_targets(context)
    selected_names = {o.name for o in context.selected_objects}
    if not selected_names:
        return all_targets, 0

    filtered = []
    matched_sel_names = set()
    for tgt in all_targets:
        label, obj, kind, item_id = tgt
        owned = _target_owned_object_names(context, obj, kind, item_id)
        hits = owned & selected_names
        if hits:
            filtered.append(tgt)
            matched_sel_names |= hits

    # If the selection didn't intersect ANY keyframe target, fall back to all
    # — selecting an unrelated light/camera shouldn't blank the panel.
    if not filtered:
        return all_targets, 0
    return filtered, len(matched_sel_names)


def get_keyframe_frames(context, targets=None):
    """Sorted unique integer frames with a keyframe on any keyframe target
    (puppet controllers, DNA/RNA molecules + bend nodes, membrane roots +
    holes + lattice-point deformation).

    Pass ``targets`` to restrict the scan to a specific subset — e.g. the
    selection-filtered list returned by
    :func:`get_filtered_keyframe_targets`."""
    if targets is None:
        targets = get_keyframe_targets(context)
    frames = set()
    for _label, obj, kind, _item_id in targets:
        for o in get_keyframe_animated_objects(obj, kind):
            ad = o.animation_data
            if ad and ad.action:
                for fc in get_fcurves_from_action(ad.action, ad):
                    for kp in fc.keyframe_points:
                        frames.add(int(round(kp.co[0])))
        if kind == 'MEMBRANE':
            for fc in _iter_lattice_data_fcurves(obj):
                for kp in fc.keyframe_points:
                    frames.add(int(round(kp.co[0])))
    return sorted(frames)


def keyframe_lattice_deformation(mem_obj, frame):
    """Keyframe every lattice point's ``co_deform`` for a membrane at *frame*.
    Returns the number of points keyed (0 if the membrane has no lattice).

    The lattice itself is a single data block animated point-by-point — one
    F-curve per point per axis — so even a small 5x5x5 lattice produces 375
    F-curves. That's by design: every deformation handle needs its own
    interpolation timeline."""
    lat = get_membrane_lattice(mem_obj)
    if lat is None or lat.data is None:
        return 0
    n = 0
    for i in range(len(lat.data.points)):
        try:
            lat.data.keyframe_insert(
                data_path=f"points[{i}].co_deform", frame=frame)
            n += 1
        except Exception:
            pass
    return n


def delete_lattice_deformation_keyframes(mem_obj, frame):
    """Remove every lattice-point ``co_deform`` key for *mem_obj* at *frame*.
    Inverse of :func:`keyframe_lattice_deformation`; called from the unified
    Delete Keyframe operator so membrane deletion mirrors object transforms."""
    lat = get_membrane_lattice(mem_obj)
    if lat is None or lat.data is None:
        return
    ad = lat.data.animation_data
    if not ad or not ad.action:
        return
    for fc in list(get_fcurves_from_action(ad.action, ad)):
        # Walk a copy of keyframe_points so we can mutate while iterating.
        for kp in list(fc.keyframe_points):
            if abs(kp.co.x - frame) < 0.01:
                try:
                    fc.keyframe_points.remove(kp)
                except Exception:
                    pass


def get_puppet_member_objects(context, puppet_id):
    """Every Blender object belonging to a puppet, resolved by item_id.

    Thin wrapper over the shared resolver in chain_utils (the single source of
    truth, also used by selection sync) that looks the puppet row up by id."""
    scene = context.scene
    puppet_item = next(
        (it for it in scene.outliner_items
         if it.item_id == puppet_id and it.item_type == 'PUPPET'), None)
    if not puppet_item:
        return []
    return _resolve_puppet_member_objects(
        scene, ProteinBlenderScene.get_instance(), puppet_item)


def delete_keyframe_metadata(controller_obj, frame):
    """Remove a single frame's entry from an object's pb_keyframe_metadata."""
    if not controller_obj or 'pb_keyframe_metadata' not in controller_obj:
        return
    try:
        meta = json.loads(controller_obj['pb_keyframe_metadata'])
    except (ValueError, TypeError):
        return
    if str(frame) in meta:
        del meta[str(frame)]
        controller_obj['pb_keyframe_metadata'] = json.dumps(meta)


# ============================================================================
# Property Groups and Operators
# ============================================================================

class PuppetKeyframeSettings(PropertyGroup):
    """Property group for puppet keyframe settings"""
    puppet_id: StringProperty(name="Puppet ID")
    puppet_name: StringProperty(name="Puppet Name")
    controller_object_name: StringProperty(name="Controller Object")
    # 'PUPPET'   – controller Empty + domain poses;
    # 'MOLECULE' – a DNA/RNA molecule object, keyframed directly (no controller
    #              or poses; its bend rig is captured automatically);
    # 'MEMBRANE' – a lipid bilayer root: root transform + hole controllers
    #              + lattice point deformation (each through its own path).
    item_kind: StringProperty(name="Item Kind", default='PUPPET')
    
    # Main checkbox to enable/disable this item (puppet OR DNA/RNA strand)
    use_puppet: BoolProperty(
        name="Include",
        description="Include this item in keyframing",
        default=False
    )

    # Transform checkboxes - all default to True. For a puppet these affect the
    # controller Empty; for a DNA/RNA strand they keyframe the molecule object
    # directly (and its bend curve + control nodes if a bend rig is attached).
    keyframe_location: BoolProperty(
        name="Location",
        description="Keyframe location (puppet controller, or DNA/RNA object + bend rig)",
        default=True
    )
    keyframe_rotation: BoolProperty(
        name="Rotation",
        description="Keyframe rotation (puppet controller, or DNA/RNA object + bend rig)",
        default=True
    )
    keyframe_scale: BoolProperty(
        name="Scale",
        description="Keyframe scale (puppet controller, or DNA/RNA object + bend rig)",
        default=True
    )
    keyframe_color: BoolProperty(
        name="Color",
        description="Keyframe domain colors",
        default=True
    )
    keyframe_pose: BoolProperty(
        name="Pose",
        description="Keyframe domain poses (relative positions within puppet)",
        default=True
    )

    # Brownian motion settings
    brownian_enabled: BoolProperty(
        name="Brownian Motion",
        description="Enable Brownian motion for this keyframe segment",
        default=False
    )


class PROTEINBLENDER_OT_create_keyframe(Operator):
    """Create keyframes for puppet animations"""
    bl_idname = "proteinblender.create_keyframe"
    bl_label = "Create Keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    frame_number: IntProperty(
        name="Frame",
        description="Frame number for keyframe",
        default=1,
        min=1
    )
    
    puppet_items: CollectionProperty(
        type=PuppetKeyframeSettings,
        name="Puppet Items",
        description="Collection of puppets to keyframe"
    )
    


    def get_puppet_objects(self, context, puppet_id):
        """Every Blender object belonging to a puppet (see
        :func:`get_puppet_member_objects`)."""
        return get_puppet_member_objects(context, puppet_id)
    
    def invoke(self, context, event):
        scene = context.scene

        # Clear previous items
        self.puppet_items.clear()

        # Set frame to current frame
        self.frame_number = scene.frame_current

        # Add all puppets from the outliner
        if hasattr(scene, 'outliner_items'):
            for item in scene.outliner_items:
                # Only include actual puppets (not separator)
                if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
                    # Only include puppets with a controller object
                    if item.controller_object_name:
                        puppet_item = self.puppet_items.add()
                        puppet_item.puppet_id = item.item_id
                        puppet_item.puppet_name = item.name
                        puppet_item.controller_object_name = item.controller_object_name

                        # Try to load existing keyframe metadata for this frame
                        controller_obj = bpy.data.objects.get(item.controller_object_name)
                        existing_settings = get_keyframe_metadata(controller_obj, self.frame_number)

                        if existing_settings:
                            # Restore previous settings from metadata
                            puppet_item.use_puppet = existing_settings.get('use_puppet', False)
                            puppet_item.keyframe_location = existing_settings.get('location', True)
                            puppet_item.keyframe_rotation = existing_settings.get('rotation', True)
                            puppet_item.keyframe_scale = existing_settings.get('scale', True)
                            puppet_item.keyframe_color = existing_settings.get('color', True)
                            puppet_item.keyframe_pose = existing_settings.get('pose', True)

                            # Validate metadata against actual F-Curves
                            domain_objects = self.get_puppet_objects(context, item.item_id)
                            discrepancies = validate_keyframe_metadata(
                                controller_obj, domain_objects, self.frame_number, existing_settings
                            )

                            if discrepancies:
                                print(f"⚠ Keyframe metadata validation warnings for '{item.name}' at frame {self.frame_number}:")
                                for msg in discrepancies:
                                    print(f"  - {msg}")
                        else:
                            # No metadata found - use defaults
                            puppet_item.use_puppet = False  # Unchecked by default
                            puppet_item.keyframe_location = True
                            puppet_item.keyframe_rotation = True
                            puppet_item.keyframe_scale = True
                            puppet_item.keyframe_color = True
                            puppet_item.keyframe_pose = True

                        # Load Brownian motion settings
                        brownian_metadata = get_brownian_metadata(controller_obj)
                        frame_key = str(self.frame_number)
                        if frame_key in brownian_metadata:
                            puppet_item.brownian_enabled = brownian_metadata[frame_key].get('enabled', False)
                        else:
                            puppet_item.brownian_enabled = False

        # Add DNA/RNA molecules as directly-keyframable items. Unlike puppets
        # (controller Empty + domain poses), a nucleic-acid molecule is
        # keyframed on its own object's transform — no controller, no poses.
        sm = ProteinBlenderScene.get_instance()
        for item in scene.outliner_items:
            if item.item_type != 'DNA_RNA':
                continue
            mol = sm.molecules.get(item.item_id)
            obj = (mol.object if mol else None) or bpy.data.objects.get(item.object_name)
            if not obj:
                continue
            mol_item = self.puppet_items.add()
            mol_item.item_kind = 'MOLECULE'
            mol_item.puppet_id = item.item_id
            mol_item.puppet_name = item.name
            mol_item.controller_object_name = obj.name
            existing = get_keyframe_metadata(obj, self.frame_number)
            mol_item.use_puppet = existing.get('use_puppet', False) if existing else False
            mol_item.keyframe_location = existing.get('location', True) if existing else True
            mol_item.keyframe_rotation = existing.get('rotation', True) if existing else True
            mol_item.keyframe_scale = existing.get('scale', True) if existing else True
            mol_item.keyframe_pose = False    # nucleic acids have no domain poses
            mol_item.keyframe_color = False   # per-base colour handled elsewhere
            mol_item.brownian_enabled = False

        # Add membrane roots. Each membrane is one row; ticking it captures the
        # root transform PLUS every hole controller (as full transforms) and
        # every lattice-point co_deform — see execute(). The user gets one
        # checkbox for the whole bilayer rather than one per sub-piece.
        for item in scene.outliner_items:
            if item.item_type != 'MEMBRANE':
                continue
            obj = bpy.data.objects.get(item.object_name)
            if not obj or not obj.get("pb_is_membrane", False):
                continue
            mem_item = self.puppet_items.add()
            mem_item.item_kind = 'MEMBRANE'
            mem_item.puppet_id = item.item_id
            mem_item.puppet_name = item.name
            mem_item.controller_object_name = obj.name
            existing = get_keyframe_metadata(obj, self.frame_number)
            mem_item.use_puppet = existing.get('use_puppet', False) if existing else False
            mem_item.keyframe_location = existing.get('location', True) if existing else True
            mem_item.keyframe_rotation = existing.get('rotation', True) if existing else True
            mem_item.keyframe_scale = existing.get('scale', True) if existing else True
            mem_item.keyframe_pose = False
            mem_item.keyframe_color = False
            mem_item.brownian_enabled = False

        # Show popup dialog
        return context.window_manager.invoke_props_dialog(self, width=500)
    
    def draw(self, context):
        layout = self.layout
        
        # Frame number input
        row = layout.row()
        row.label(text="Frame:")
        row.prop(self, "frame_number", text="")
        
        layout.separator()
        
        # Puppet rows
        box = layout.box()
        
        if not self.puppet_items:
            box.label(text="Nothing to keyframe", icon='INFO')
            box.label(text="Create a puppet (Puppet Maker) or a DNA/RNA strand (DNA Builder) first")
        else:
            # Create a subtle header with icons
            header_row = box.row(align=False)
            header_row.scale_y = 0.8
            header_row.label(text="")  # Empty space for checkbox column

            # Header label — covers both puppets and DNA/RNA strands shown below
            header_row.label(text="Item")

            # Spacer to push transform icons to the right
            header_row.separator(factor=2.0)

            # Transform type icons - Pose first (leftmost)
            header_row.label(text="", icon='ARMATURE_DATA')  # Pose icon
            header_row.label(text="", icon='CON_LOCLIKE')  # Location icon
            header_row.label(text="", icon='CON_ROTLIKE')  # Rotation icon
            header_row.label(text="", icon='CON_SIZELIKE')  # Scale icon
            header_row.label(text="", icon='COLOR')  # Color icon
            header_row.label(text="", icon='MOD_NOISE')  # Brownian icon
            header_row.label(text="", icon='BLANK1')  # Space for settings button

            box.separator(factor=0.5)

            for item in self.puppet_items:
                row = box.row(align=False)
                row.scale_y = 1.2  # Make rows slightly taller for better readability

                # Checkbox for selecting the item
                row.prop(item, "use_puppet", text="")

                # Name with kind-specific icon
                is_puppet = item.item_kind == 'PUPPET'
                is_membrane = item.item_kind == 'MEMBRANE'
                if is_puppet:
                    item_icon = 'GROUP'
                elif is_membrane:
                    item_icon = 'MOD_FLUIDSIM'
                else:
                    item_icon = 'RNA'
                name_col = row.column()
                name_col.alignment = 'LEFT'
                name_row = name_col.row(align=True)
                name_row.label(text=item.puppet_name, icon=item_icon)

                # Add spacer to push transform checkboxes to the right
                row.separator(factor=2.0)

                # Transform checkboxes - enabled only when the row is selected.
                # Pose is puppet-only (DNA/membrane have no domain poses; the
                # membrane's per-hole / lattice keys are captured automatically
                # alongside the root and don't get a separate column).
                pose_row = row.row()
                pose_row.enabled = item.use_puppet and is_puppet
                pose_row.prop(item, "keyframe_pose", text="")

                loc_row = row.row()
                loc_row.enabled = item.use_puppet
                loc_row.prop(item, "keyframe_location", text="")

                rot_row = row.row()
                rot_row.enabled = item.use_puppet
                rot_row.prop(item, "keyframe_rotation", text="")

                scale_row = row.row()
                scale_row.enabled = item.use_puppet
                scale_row.prop(item, "keyframe_scale", text="")

                # Colour and Brownian are puppet-only (per-domain features).
                color_row = row.row()
                color_row.enabled = item.use_puppet and is_puppet
                color_row.prop(item, "keyframe_color", text="")

                # Brownian motion checkbox
                brownian_row = row.row()
                brownian_row.enabled = item.use_puppet and is_puppet
                brownian_row.prop(item, "brownian_enabled", text="")

                # Settings button (gear icon)
                settings_row = row.row()
                settings_row.enabled = item.use_puppet and is_puppet
                settings_op = settings_row.operator(
                    "proteinblender.brownian_settings",
                    text="",
                    icon='PREFERENCES'
                )
                settings_op.puppet_id = item.puppet_id
                settings_op.puppet_name = item.puppet_name
                settings_op.controller_object_name = item.controller_object_name
                settings_op.frame_number = self.frame_number

        layout.separator()

        # Select all/none buttons
        row = layout.row(align=True)
        row.operator("proteinblender.keyframe_select_all_puppets", text="Select All")
        row.operator("proteinblender.keyframe_select_none_puppets", text="Select None")

        # Add sync button for rebuilding metadata from timeline
        layout.separator()
        row = layout.row()
        row.operator("proteinblender.sync_keyframe_metadata", text="Sync from Timeline", icon='FILE_REFRESH')
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get selected items (puppets and/or DNA/RNA molecules)
        selected_puppets = [item for item in self.puppet_items if item.use_puppet]

        if not selected_puppets:
            self.report({'WARNING'}, "Nothing selected to keyframe")
            return {'CANCELLED'}
        
        # Store current frame
        original_frame = scene.frame_current
        
        # Only change frame if necessary
        if original_frame != self.frame_number:
            scene.frame_set(self.frame_number)
        
        keyframed_puppets = []
        total_keyframed = 0
        
        for puppet_item in selected_puppets:
            puppet_name = puppet_item.puppet_name
            puppet_id = puppet_item.puppet_id
            
            print(f"\nProcessing puppet: {puppet_name}")
            
            # Get the Empty controller object
            controller_obj = None
            if puppet_item.controller_object_name:
                controller_obj = bpy.data.objects.get(puppet_item.controller_object_name)
                if not controller_obj:
                    print(f"  Warning: Controller object '{puppet_item.controller_object_name}' not found")
            
            # Domain objects only apply to real puppets; a MOLECULE item (DNA/RNA)
            # is keyframed on its own object transform, with no domains or poses.
            domain_objects = (self.get_puppet_objects(context, puppet_id)
                              if puppet_item.item_kind == 'PUPPET' else [])
            
            if not domain_objects and not controller_obj:
                print(f"  Warning: No objects found for puppet '{puppet_name}'")
                continue
            
            # Apply any active poses for the puppet's domains
            # This preserves domain arrangements
            for item in scene.molecule_list_items:
                if hasattr(item, 'active_pose_index') and hasattr(item, 'poses'):
                    if item.active_pose_index >= 0 and item.active_pose_index < len(item.poses):
                        active_pose = item.poses[item.active_pose_index]
                        
                        # Apply pose transforms to matching domains
                        for transform in active_pose.domain_transforms:
                            for domain_obj in domain_objects:
                                if domain_obj.name == transform.domain_id or \
                                   domain_obj.name.endswith(f"_{transform.domain_id}"):
                                    print(f"  Applying pose transform to {domain_obj.name}")
                                    domain_obj.location = transform.location
                                    # Use quaternion mode for proper keyframe interpolation
                                    ensure_quaternion_mode(domain_obj)
                                    domain_obj.rotation_quaternion = transform.rotation.to_quaternion()
                                    domain_obj.scale = transform.scale
            
            # Keyframe the Empty controller based on checkboxes
            # Only process if puppet is selected
            if controller_obj and puppet_item.use_puppet:
                keyframed_properties = []

                # Location
                if puppet_item.keyframe_location:
                    keyframe_transforms(controller_obj, self.frame_number, location=True, rotation=False, scale=False)
                    keyframed_properties.append("location")
                    print(f"  ✓ Keyframed controller location at frame {self.frame_number}")
                else:
                    delete_transform_keyframes(controller_obj, self.frame_number, location=True, rotation=False, scale=False)
                    print(f"  ✗ Removed controller location keyframe at frame {self.frame_number}")

                # Rotation
                if puppet_item.keyframe_rotation:
                    keyframe_transforms(controller_obj, self.frame_number, location=False, rotation=True, scale=False)
                    keyframed_properties.append("rotation")
                    print(f"  ✓ Keyframed controller rotation at frame {self.frame_number}")
                else:
                    delete_transform_keyframes(controller_obj, self.frame_number, location=False, rotation=True, scale=False)
                    print(f"  ✗ Removed controller rotation keyframe at frame {self.frame_number}")

                # Scale
                if puppet_item.keyframe_scale:
                    keyframe_transforms(controller_obj, self.frame_number, location=False, rotation=False, scale=True)
                    keyframed_properties.append("scale")
                    print(f"  ✓ Keyframed controller scale at frame {self.frame_number}")
                else:
                    delete_transform_keyframes(controller_obj, self.frame_number, location=False, rotation=False, scale=True)
                    print(f"  ✗ Removed controller scale keyframe at frame {self.frame_number}")

                if keyframed_properties:
                    print(f"  Controller: Keyframed {', '.join(keyframed_properties)}")
                    total_keyframed += 1

            # Membrane: capture every hole controller + every lattice point's
            # ``co_deform``. Hole transforms shape the carving (position +
            # scale), and lattice deformation lives on the lattice DATA, not
            # the lattice object — see :func:`keyframe_lattice_deformation`.
            # All of this is grouped under the single membrane row so one tick
            # captures the whole bilayer.
            if (puppet_item.item_kind == 'MEMBRANE' and puppet_item.use_puppet
                    and controller_obj):
                holes = get_membrane_holes(controller_obj)
                for hole in holes:
                    keyframe_transforms(hole, self.frame_number)
                n_lattice = keyframe_lattice_deformation(
                    controller_obj, self.frame_number)
                if holes:
                    print(f"  ✓ Keyframed {len(holes)} membrane hole(s)"
                          f" at frame {self.frame_number}")
                    total_keyframed += 1
                if n_lattice:
                    print(f"  ✓ Keyframed {n_lattice} lattice point(s)"
                          f" at frame {self.frame_number}")
                    total_keyframed += 1

            # DNA/RNA: also capture the bend rig automatically. The bend is
            # driven by separate control-node empties, not the molecule's own
            # transform, so without this the strand's SHAPE would not animate
            # between keyframes — only its position would. Captured in the same
            # "Create Keyframe" action, so the user never leaves the panel.
            if (puppet_item.item_kind == 'MOLECULE' and puppet_item.use_puppet
                    and controller_obj):
                bend_objs = get_dna_bend_objects(controller_obj)
                for bend_obj in bend_objs:
                    # Full transform (location + rotation + scale) so a twisted
                    # bend — a rotated/scaled control node — is captured too, not
                    # just node positions.
                    keyframe_transforms(bend_obj, self.frame_number)
                if bend_objs:
                    print(f"  ✓ Keyframed {len(bend_objs)} DNA bend object(s) at frame {self.frame_number}")
                    total_keyframed += 1

            # Keyframe domain relative transforms (local space) based on pose checkbox
            for domain_obj in domain_objects:
                if puppet_item.keyframe_pose:
                    # Keyframe local transforms when pose checkbox is checked
                    keyframe_transforms(domain_obj, self.frame_number)
                    print(f"  ✓ Keyframed domain '{domain_obj.name}' pose (local transforms)")
                else:
                    # Remove existing keyframes if pose checkbox is unchecked
                    delete_transform_keyframes(domain_obj, self.frame_number)
                    print(f"  ✗ Removed domain '{domain_obj.name}' pose keyframes")
                
                # Keyframe color if requested
                if puppet_item.keyframe_color:
                    # Keyframe the actual geometry node color inputs
                    if not keyframe_color_properties(domain_obj, self.frame_number):
                        # Try to apply color if it failed (meaning node probably didn't exist)
                        try:
                            from ..panels.visual_setup_panel import get_object_color, apply_color_to_object
                            color = get_object_color(domain_obj)
                            if color:
                                apply_color_to_object(domain_obj, color)
                                keyframe_color_properties(domain_obj, self.frame_number)
                        except ImportError:
                            pass
                else:
                    # Remove color keyframes if checkbox is unchecked
                    remove_color_keyframes(domain_obj, self.frame_number)
                
                total_keyframed += 1
            
            keyframed_puppets.append(puppet_name)

        # Save keyframe metadata for all processed puppets
        for puppet_item in self.puppet_items:
            controller_obj = bpy.data.objects.get(puppet_item.controller_object_name)
            if controller_obj:
                save_keyframe_metadata(controller_obj, self.frame_number, puppet_item)
                print(f"💾 Saved keyframe metadata for '{puppet_item.puppet_name}' at frame {self.frame_number}")

                # Handle Brownian motion settings
                # The system bakes JITTER keyframes at even intervals
                if puppet_item.brownian_enabled:
                    # Ensure quaternion mode before Brownian motion
                    ensure_quaternion_mode(controller_obj)

                    # Find previous keyframe for start frame
                    prev_frame = find_previous_keyframe(controller_obj, self.frame_number)
                    if prev_frame is not None:
                        # Get existing Brownian settings or use defaults
                        brownian_metadata = get_brownian_metadata(controller_obj)
                        frame_key = str(self.frame_number)

                        if frame_key in brownian_metadata:
                            # Preserve existing settings, just ensure enabled and update start_frame
                            settings = brownian_metadata[frame_key].copy()
                            settings['enabled'] = True
                            settings['start_frame'] = prev_frame
                        else:
                            # Create default settings (user should open settings popup to customize)
                            settings = {
                                'enabled': True,
                                'jitter_interval': 3,
                                'jitter_max_distance': 1.0,
                                'jitter_max_rotation': 30.0,
                                'use_random_seed': True,
                                'seed': None,
                                'start_frame': prev_frame,
                                'puppet_id': puppet_item.puppet_id,
                                'use_physical_params': False,
                                'molecular_weight': 50.0,
                                'temperature': 300.0,
                                'viscosity_factor': 1.0,
                            }
                        # save_brownian_metadata bakes JITTER keyframes at even intervals
                        save_brownian_metadata(controller_obj, self.frame_number, settings)
                        print(f"  Brownian motion enabled for frames {prev_frame}-{self.frame_number}")
                        print(f"     (JITTER keyframes baked)")
                    else:
                        print(f"  Cannot enable Brownian motion: no previous keyframe found")
                else:
                    # Disable Brownian motion for this frame
                    # This removes the baked JITTER keyframes for the segment
                    brownian_metadata = get_brownian_metadata(controller_obj)
                    frame_key = str(self.frame_number)
                    if frame_key in brownian_metadata:
                        # Create disabled settings to remove baked keyframes
                        settings = brownian_metadata[frame_key].copy()
                        settings['enabled'] = False
                        # save_brownian_metadata handles clearing JITTER keyframes when disabled
                        save_brownian_metadata(controller_obj, self.frame_number, settings)
                        print(f"  Brownian motion disabled for frame {self.frame_number}")

        # Restore original frame
        if original_frame != self.frame_number:
            scene.frame_set(original_frame)

        if keyframed_puppets:
            puppet_names = ", ".join(keyframed_puppets)
            self.report({'INFO'}, f"Keyframed {total_keyframed} objects from puppets: {puppet_names} at frame {self.frame_number}")
        else:
            self.report({'WARNING'}, "No objects were keyframed")

        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_all_puppets(Operator):
    """Select all puppets for keyframing"""
    bl_idname = "proteinblender.keyframe_select_all_puppets"
    bl_label = "Select All"
    
    def execute(self, context):
        # Get the active operator
        wm = context.window_manager
        if hasattr(wm, 'operators') and len(wm.operators) > 0:
            for op in reversed(wm.operators):
                if hasattr(op, 'bl_idname') and op.bl_idname == 'proteinblender.create_keyframe':
                    if hasattr(op, 'puppet_items'):
                        for item in op.puppet_items:
                            item.use_puppet = True
                            # Keep default transform settings
                        # Force a redraw
                        context.area.tag_redraw()
                    break
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_none_puppets(Operator):
    """Deselect all puppets"""
    bl_idname = "proteinblender.keyframe_select_none_puppets"
    bl_label = "Select None"
    
    def execute(self, context):
        # Get the active operator
        wm = context.window_manager
        if hasattr(wm, 'operators') and len(wm.operators) > 0:
            for op in reversed(wm.operators):
                if hasattr(op, 'bl_idname') and op.bl_idname == 'proteinblender.create_keyframe':
                    if hasattr(op, 'puppet_items'):
                        for item in op.puppet_items:
                            item.use_puppet = False
                        # Force a redraw
                        context.area.tag_redraw()
                    break
        return {'FINISHED'}


# Keep old operators for backwards compatibility but deprecated
class PROTEINBLENDER_OT_keyframe_select_all(Operator):
    """Deprecated - use keyframe_select_all_poses"""
    bl_idname = "proteinblender.keyframe_select_all"
    bl_label = "Select All (Deprecated)"
    
    def execute(self, context):
        return bpy.ops.proteinblender.keyframe_select_all_poses()


class PROTEINBLENDER_OT_keyframe_select_none(Operator):
    """Deprecated - use keyframe_select_none_poses"""
    bl_idname = "proteinblender.keyframe_select_none"
    bl_label = "Select None (Deprecated)"

    def execute(self, context):
        return bpy.ops.proteinblender.keyframe_select_none_poses()


class PROTEINBLENDER_OT_sync_keyframe_metadata(Operator):
    """Sync keyframe metadata from timeline for current frame"""
    bl_idname = "proteinblender.sync_keyframe_metadata"
    bl_label = "Sync Keyframe Metadata from Timeline"
    bl_description = "Rebuild keyframe metadata by reading actual keyframes from the timeline at current frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        current_frame = scene.frame_current
        synced_count = 0

        # Process all puppets
        if hasattr(scene, 'outliner_items'):
            for item in scene.outliner_items:
                if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
                    if item.controller_object_name:
                        controller_obj = bpy.data.objects.get(item.controller_object_name)
                        if not controller_obj:
                            continue

                        # Get puppet's domain objects
                        from ..operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe
                        temp_op = PROTEINBLENDER_OT_create_keyframe()
                        domain_objects = temp_op.get_puppet_objects(context, item.item_id)

                        # Check what's actually keyframed
                        actual_state = check_existing_keyframes(controller_obj, domain_objects, current_frame)

                        # Create a temporary settings object to save
                        class TempSettings:
                            def __init__(self):
                                self.use_puppet = any(actual_state.values())  # True if any property is keyframed
                                self.keyframe_location = actual_state.get('location', False)
                                self.keyframe_rotation = actual_state.get('rotation', False)
                                self.keyframe_scale = actual_state.get('scale', False)
                                self.keyframe_pose = actual_state.get('pose', False)
                                self.keyframe_color = actual_state.get('color', False)

                        temp_settings = TempSettings()

                        # Only save metadata if at least one property is keyframed
                        if temp_settings.use_puppet:
                            save_keyframe_metadata(controller_obj, current_frame, temp_settings)
                            synced_count += 1
                            print(f"🔄 Synced metadata for '{item.name}' at frame {current_frame}")

        if synced_count > 0:
            self.report({'INFO'}, f"Synced keyframe metadata for {synced_count} puppet(s) at frame {current_frame}")
        else:
            self.report({'INFO'}, f"No keyframes found at frame {current_frame}")

        return {'FINISHED'}


def register():
    """Register keyframe operators and properties"""
    # PoseKeyframeSettings is now registered with the main CLASSES in __init__.py
    pass


def unregister():
    """Unregister keyframe operators and properties"""
    # PoseKeyframeSettings is now unregistered with the main CLASSES in __init__.py
    pass