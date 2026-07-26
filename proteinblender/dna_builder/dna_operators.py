"""Operators for the DNA/RNA Builder.

Heavy imports (biotite, scipy) are deferred to execute() time
so that panel/operator classes can register before dependencies are loaded.
"""

import random
import bpy
from bpy.types import Operator
from bpy.props import StringProperty


# MN's encoded value for residue name "DT" (thymine). Used by uniform-
# rungs mode to overwrite every nucleotide's res_name so MN's Cartoon
# style draws the same pyrimidine block for every base.
_DT_CODE = 33

# Styles that draw individual atoms. For these the ladder backbone keeps
# a natural 3D extent ("realistic atoms") so the nucleotide reads as a
# real molecule. Cartoon and surface don't draw atoms, so the backbone
# stays collapsed flat. This is implied by the style — there is no
# separate UI toggle.
_REALISTIC_ATOM_STYLES = {"ball_and_stick", "spheres", "sticks"}


def _snapshot_real_res_name(obj):
    """Copy the mesh's ``res_name`` attribute into ``pb_real_res_name``.

    ``apply_base_colors`` (and ``update_dna_colors``) read this attribute
    in preference to ``res_name`` when assigning per-base colours, which
    lets uniform-rungs mode overwrite ``res_name`` for cartoon's shape
    selection without losing the original base identity needed for
    colour assignment.
    """
    import numpy as np

    mesh = getattr(obj, "data", None)
    if mesh is None:
        return
    rn_attr = mesh.attributes.get("res_name")
    if rn_attr is None:
        return
    n = len(mesh.vertices)
    values = np.zeros(n, dtype=np.int32)
    rn_attr.data.foreach_get("value", values)
    existing = mesh.attributes.get("pb_real_res_name")
    if existing is not None:
        try:
            mesh.attributes.remove(existing)
        except Exception:
            pass
    new_attr = mesh.attributes.new("pb_real_res_name", "INT", "POINT")
    new_attr.data.foreach_set("value", values)


def _override_res_name_uniform(obj, value):
    """Set the mesh's ``res_name`` attribute to ``value`` for every atom.

    Used by uniform-rungs mode so MN's Cartoon style sees one residue
    type everywhere and draws a single block shape, while the real
    residue identities are preserved in ``pb_real_res_name``.
    """
    import numpy as np

    mesh = getattr(obj, "data", None)
    if mesh is None:
        return
    rn_attr = mesh.attributes.get("res_name")
    if rn_attr is None:
        return
    n = len(mesh.vertices)
    rn_attr.data.foreach_set("value", np.full(n, int(value), dtype=np.int32))
    mesh.update()


# ---------------------------------------------------------------------------
# Shared dialog form
# ---------------------------------------------------------------------------

def _validate_seq_preview(seq, nt):
    """Lightweight validation for dialog preview labels — keeps only the
    valid characters for the chosen nucleic-acid type."""
    valid = set("ATGC") if nt == "DNA" else set("AUGC")
    return "".join(c for c in seq.upper() if c in valid)


def _helix_info_preview(length, nt, winding_mode="HELIX"):
    """Lightweight helix-length / turns preview for dialog labels."""
    rise = 2.6 if nt == "RNA" else 3.38
    twist = 32.7 if nt == "RNA" else 36.0
    wound_transitions = 0 if winding_mode == "LADDER" else max(0, length - 1)
    return {
        "helix_length_angstrom": length * rise,
        "turns": wound_transitions * twist / 360.0,
    }


def _draw_dna_form(layout, props, *, dna_obj=None):
    """Shared dialog body for Create-DNA / Edit-DNA.

    Both ``PROTEINBLENDER_OT_build_dna`` (in create mode) and the same
    operator (in edit mode, when ``molecule_id_to_update`` is set) call
    this from their ``draw`` method. Binds directly to
    ``scene.dna_builder_props`` (passed in as ``props``) so the
    randomise / swap-to-complement sub-operators can keep mutating the
    same scene props they always have. If ``dna_obj`` is passed (edit
    mode), the "Apply to Selected" button at the bottom of the colour
    section is shown.
    """
    # Type toggle
    row = layout.row(align=True)
    row.prop(props, "nucleic_type", expand=True)

    layout.separator(factor=0.3)

    # Input mode toggle
    row = layout.row(align=True)
    row.prop(props, "input_mode", expand=True)

    if props.input_mode == "RANDOM":
        row = layout.row(align=True)
        row.prop(props, "sequence_length", text="Length")
        row.operator(
            "proteinblender.randomize_sequence", text="", icon="FILE_REFRESH"
        )

    # Sequence text area
    layout.prop(props, "sequence", text="")

    # Validation feedback
    nt = props.nucleic_type
    seq = _validate_seq_preview(props.sequence, nt)
    valid_chars = "A T G C" if nt == "DNA" else "A U G C"
    status = "✓ valid" if len(seq) >= 2 else "✗ too short"
    layout.label(
        text=f"{valid_chars} only · {len(seq)} / 500 · {status}"
    )

    layout.separator(factor=0.3)

    # Double / single stranded
    layout.prop(props, "double_stranded")

    # Single-strand: offer swap-to-complement helper
    if not props.double_stranded:
        row = layout.row()
        row.operator(
            "proteinblender.swap_to_complement",
            text="⇄ Swap to Complement",
            icon="ARROW_LEFTRIGHT",
        )

    # Style + name
    layout.prop(props, "style")
    layout.prop(props, "name_prefix", text="Name")

    # ---- Collapsible winding section ---------------------------------
    wind_box = layout.box()
    wind_header = wind_box.row()
    wind_header.prop(
        props, "show_winding",
        text="Winding",
        icon="TRIA_DOWN" if props.show_winding else "TRIA_RIGHT",
        emboss=False,
    )
    if props.show_winding:
        wind_box.prop(props, "winding_mode", expand=True)
        if props.winding_mode == "LADDER":
            wind_box.label(
                text="Stylised flat ladder. Backbone is not atomically valid here.",
                icon="INFO",
            )
        elif nt == "DNA":
            # Canonical helix form only applies to a wound DNA helix; RNA is
            # always A-form, and LADDER ignores form.
            wind_box.prop(props, "helix_form", expand=True)

    # ---- Collapsible colour section ----------------------------------
    color_box = layout.box()
    color_header = color_box.row()
    color_header.prop(
        props, "show_colors",
        text="Base Colors",
        icon="TRIA_DOWN" if props.show_colors else "TRIA_RIGHT",
        emboss=False,
    )
    if props.show_colors:
        col = color_box.column(align=True)
        col.prop(props, "color_a")
        if nt == "DNA":
            col.prop(props, "color_t")
        else:
            col.prop(props, "color_u")
        col.prop(props, "color_g")
        col.prop(props, "color_c")
        col.separator(factor=0.3)
        col.prop(props, "color_backbone")
        # Edit-mode: live "Apply to Selected" button to update colours
        # without rebuilding the strand.
        if dna_obj is not None:
            col.separator(factor=0.3)
            col.operator(
                "proteinblender.update_dna_colors",
                text="Apply to Selected",
                icon="CHECKMARK",
            )

    # ---- Collapsible shape (bend) section — edit mode only -----------
    # Bending only makes sense on an existing strand, so create mode
    # never shows this. The buttons fire the same `dna_*_bend` operators
    # the Builders panel used to host — once the user clicks one, the
    # operator runs against the active object (which the parent
    # operator's invoke() set to the target DNA, so resolution works).
    # After Edit Bend the empties are placed but invisible behind the
    # modal dialog; close the dialog to grab them in the viewport.
    if dna_obj is not None:
        _draw_shape_section(layout, props, dna_obj)

    # ---- Helix info readout ------------------------------------------
    if len(seq) >= 2:
        info = _helix_info_preview(len(seq), nt, winding_mode=props.winding_mode)
        info_box = layout.box()
        r = info_box.row()
        r.label(text="Helix length")
        r.label(text=f"{info['helix_length_angstrom']:.1f} Å")
        r = info_box.row()
        r.label(text="Turns")
        r.label(text=f"{info['turns']:.2f}")


def _draw_shape_section(layout, props, dna_obj):
    """Bending controls — only rendered in edit mode (dna_obj is not None).

    Same control surface the Builders panel used to host: Add / Edit /
    Remove bend, node-count +/-, hide-curve toggle. Add/Remove/resolution
    are locked while the strand is keyframed (would orphan F-curves).
    """
    from .bender import (
        BEND_CURVE_PROP,
        RES_DEFAULT, RES_MIN, RES_MAX,
        get_bend_curve,
        get_bend_nodes,
        dna_has_keyframes,
    )

    shape_box = layout.box()
    shape_header = shape_box.row()
    shape_header.prop(
        props, "show_shape",
        text="Shape",
        icon="TRIA_DOWN" if props.show_shape else "TRIA_RIGHT",
        emboss=False,
    )
    if not props.show_shape:
        return

    has_bend = bool(dna_obj.get(BEND_CURVE_PROP))
    is_keyframed = dna_has_keyframes(dna_obj)
    lock_msg = "Locked: remove this DNA's keyframes (Animate panel) to change the bend rig."

    if not has_bend:
        row = shape_box.row()
        row.scale_y = 1.2
        row.enabled = not is_keyframed
        row.operator(
            "proteinblender.dna_add_bend",
            text="✚ Add Bend Control",
            icon="OUTLINER_OB_CURVE",
        )
        if is_keyframed:
            shape_box.label(text=lock_msg, icon="LOCKED")
        else:
            shape_box.label(
                text="Adds a Bezier curve along the helix axis.",
                icon="INFO",
            )
        return

    # ---- Bend exists ---------------------------------------------------
    nodes = get_bend_nodes(dna_obj)
    n_nodes = len(nodes)
    has_nodes = n_nodes > 0

    # Edit / Remove row. Edit Bend just re-selects existing nodes, so it
    # stays enabled even when keyframed. Remove Bend rebuilds the strand's
    # origin and would orphan F-curves, so it's locked.
    row = shape_box.row(align=True)
    row.scale_y = 1.2
    edit_op = row.operator(
        "proteinblender.dna_edit_bend",
        text="Edit Bend" if has_nodes else "Place Control Nodes",
        icon="EMPTY_AXIS",
    )
    edit_op.n_points = n_nodes if n_nodes >= RES_MIN else RES_DEFAULT
    remove_sub = row.row(align=True)
    remove_sub.enabled = not is_keyframed
    remove_sub.operator(
        "proteinblender.dna_remove_bend",
        text="",
        icon="X",
    )

    # Node count +/-
    if has_nodes:
        shape_box.separator(factor=0.3)
        res_row = shape_box.row(align=True)
        res_row.enabled = not is_keyframed
        res_row.label(text="Nodes:")
        minus = res_row.operator(
            "proteinblender.dna_set_bend_resolution",
            text="", icon="REMOVE",
        )
        minus.n_points = max(RES_MIN, n_nodes - 1)
        res_row.label(text=str(n_nodes))
        plus = res_row.operator(
            "proteinblender.dna_set_bend_resolution",
            text="", icon="ADD",
        )
        plus.n_points = min(RES_MAX, n_nodes + 1)

        if is_keyframed:
            shape_box.label(text=lock_msg, icon="LOCKED")
        else:
            shape_box.label(
                text="Close this dialog to grab nodes in the viewport.",
                icon="INFO",
            )

    # Hide bend curve (viewport-only, never affects renders). Uses a toggle
    # operator that flips the curve's EYE visibility (hide_set), not its
    # depsgraph "disable in viewport" flag — hiding it must never disturb the
    # Curve modifier / hook rig or the strand jumps (tester report, Janet).
    curve_obj = get_bend_curve(dna_obj)
    if curve_obj is not None:
        shape_box.separator(factor=0.3)
        is_hidden = curve_obj.hide_get()
        vis_row = shape_box.row(align=True)
        vis_row.operator(
            "proteinblender.dna_toggle_bend_curve",
            text="Show Bend Curve" if is_hidden else "Hide Bend Curve",
            icon="HIDE_ON" if is_hidden else "HIDE_OFF",
        )
        shape_box.label(
            text="Bend curve is a guide only — never appears in renders.",
            icon="INFO",
        )


# ---------------------------------------------------------------------------
# Build / update path
# ---------------------------------------------------------------------------

def _build_dna_from_props(operator, context, identifier):
    """Shared build path: read scene props, build the AtomArray, create the
    Blender object via MN pipeline, apply colours and finalize.

    Returns (wrapper, info_dict) on success or (None, None) on failure
    (the operator's `report` will already have been called).
    """
    from ..utils.scene_manager import ProteinBlenderScene
    from .sequence_builder import (
        build_nucleic_acid,
        validate_sequence,
        calculate_helix_info,
        make_wound_mask,
    )
    from .dna_colors import apply_base_colors, colors_from_props, store_colors_on_object

    props = context.scene.dna_builder_props
    nucleic_type = props.nucleic_type
    seq = validate_sequence(props.sequence, nucleic_type)
    if len(seq) < 2:
        operator.report({"ERROR"}, "Sequence must be at least 2 valid nucleotides.")
        return None, None
    if len(seq) > 500:
        operator.report(
            {"WARNING"}, f"Long sequence ({len(seq)} nt) may be slow to build."
        )

    scene_mgr = ProteinBlenderScene.get_instance()

    n = len(seq)
    primary_mask = make_wound_mask(n, props.winding_mode)
    schematic = props.winding_mode == "LADDER" and bool(props.ladder_uniform)
    realistic = (
        props.winding_mode == "LADDER"
        and props.style in _REALISTIC_ATOM_STYLES
    )

    try:
        array = build_nucleic_acid(
            sequence=seq,
            nucleic_type=nucleic_type,
            double_stranded=props.double_stranded,
            form=props.helix_form,
            wound_mask=primary_mask,
            schematic=schematic,
            realistic_atoms=realistic,
        )
    except Exception as e:
        operator.report({"ERROR"}, f"Build failed: {e}")
        return None, None

    try:
        wrapper = scene_mgr.molecule_manager.create_from_array(
            array=array, identifier=identifier, style=props.style,
        )
    except Exception as e:
        operator.report({"ERROR"}, f"Object creation failed: {e}")
        return None, None

    obj = wrapper.molecule.object
    obj["pb_is_nucleic_acid"] = True
    obj["pb_nucleic_type"] = nucleic_type
    obj["pb_sequence"] = seq
    obj["pb_double_stranded"] = props.double_stranded
    obj["pb_style"] = props.style
    obj["pb_winding_mode"] = props.winding_mode
    obj["pb_helix_form"] = props.helix_form
    obj["pb_ladder_uniform"] = bool(props.ladder_uniform)
    obj["pb_ladder_realistic"] = bool(realistic)

    context.evaluated_depsgraph_get()
    _snapshot_real_res_name(obj)
    if schematic:
        # MN's Cartoon style switches base shape based on the res_name
        # attribute. Force every atom to look like DT so the cartoon
        # draws the same pyrimidine block for every rung. The original
        # residue type lives on in pb_real_res_name, which
        # apply_base_colors prefers for the colour lookup so per-base
        # colours stay correct.
        _override_res_name_uniform(obj, _DT_CODE)
    colors = colors_from_props(props)
    store_colors_on_object(obj, colors)
    apply_base_colors(obj, colors)

    scene_mgr._finalize_dna_molecule(wrapper)

    return wrapper, calculate_helix_info(len(seq), nucleic_type, primary_mask)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class PROTEINBLENDER_OT_build_dna(Operator):
    """Open the DNA / RNA builder dialog.

    Two modes, controlled by the ``molecule_id_to_update`` operator
    property:

    * **Create (empty)** — opens the dialog seeded from the current
      ``scene.dna_builder_props`` (which the msgbus sync keeps
      reasonable). Clicking OK creates a new molecule registered in
      the PB Outliner.

    * **Update (``molecule_id_to_update`` set)** — the PB Outliner's
      edit pencil invokes us with this set to a molecule's identifier.
      ``invoke`` syncs ``scene.dna_builder_props`` from the target
      molecule's ``pb_*`` custom properties so the dialog opens pre-
      populated. ``execute`` deletes the old molecule and rebuilds
      with the *same* identifier so the outliner slot stays put, and
      the molecule's transform + bend rig are preserved.

    Identical dialog body for both modes (see ``_draw_dna_form``) — the
    user sees the same controls whether they're creating fresh or
    editing an existing strand.
    """

    bl_idname = "proteinblender.build_dna"
    bl_label = "Build DNA/RNA"
    bl_options = {"REGISTER", "UNDO"}

    molecule_id_to_update: StringProperty(
        name="Molecule to update",
        description=(
            "If set, edit this DNA molecule's identifier instead of "
            "creating a new one (the existing molecule is deleted and "
            "rebuilt with the same identifier so the outliner slot "
            "stays put)"
        ),
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        # Edit mode: seed scene.dna_builder_props from the target's
        # pb_* custom props so the dialog opens with the molecule's
        # current settings. The msgbus auto-sync already does this
        # when the user clicks the strand in the viewport — but the
        # edit-pencil in the outliner doesn't change the active
        # object, so we have to seed explicitly here. Also make the
        # target DNA the active object so the in-dialog bend operators
        # (dna_add_bend / dna_edit_bend / etc.) resolve to the right
        # strand — they look at context.active_object.
        if self.molecule_id_to_update:
            from ..utils.scene_manager import ProteinBlenderScene
            from .dna_props import sync_props_from_object
            sm = ProteinBlenderScene.get_instance()
            wrapper = sm.molecules.get(self.molecule_id_to_update)
            if wrapper and wrapper.molecule and wrapper.molecule.object:
                dna_obj = wrapper.molecule.object
                sync_props_from_object(
                    context.scene.dna_builder_props,
                    dna_obj,
                )
                try:
                    if context.mode != "OBJECT":
                        bpy.ops.object.mode_set(mode="OBJECT")
                    bpy.ops.object.select_all(action="DESELECT")
                    dna_obj.select_set(True)
                    context.view_layer.objects.active = dna_obj
                except Exception:
                    pass
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        _draw_dna_form(
            self.layout,
            context.scene.dna_builder_props,
            dna_obj=self._target_object(context),
        )

    def _target_object(self, context):
        """The DNA object the dialog is editing, or None for Create mode."""
        if not self.molecule_id_to_update:
            return None
        from ..utils.scene_manager import ProteinBlenderScene
        sm = ProteinBlenderScene.get_instance()
        wrapper = sm.molecules.get(self.molecule_id_to_update)
        return wrapper.molecule.object if (wrapper and wrapper.molecule) else None

    def execute(self, context):
        from ..utils.scene_manager import ProteinBlenderScene
        from ..utils.blender_utils import ensure_object_mode

        # The build path appends MN style node groups and calls select_all,
        # neither of which polls in an edit mode - and the membrane builder's
        # Edit Deformation leaves the user in one. See ensure_object_mode.
        ensure_object_mode()

        scene_mgr = ProteinBlenderScene.get_instance()
        props = context.scene.dna_builder_props

        if self.molecule_id_to_update:
            # Update path — preserve identifier, transform, and bend rig
            # across the rebuild. Logic merged from the former
            # PROTEINBLENDER_OT_update_dna operator (now removed).
            return self._update_existing(context, scene_mgr,
                                         self.molecule_id_to_update)

        # Create path — pick a fresh identifier and build
        identifier = self._next_id(props, scene_mgr)
        wrapper, info = _build_dna_from_props(self, context, identifier)
        if wrapper is None:
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Created {identifier}: {info['base_pairs']} nt, "
            f"{info['helix_length_angstrom']:.1f} Å, "
            f"{info['turns']:.1f} turns",
        )
        return {"FINISHED"}

    def _update_existing(self, context, scene_mgr, identifier):
        """Rebuild the existing DNA at the given identifier. Preserves
        the molecule's transform and bend rig the same way the former
        update_dna operator did."""
        from . import bender as _bender
        from mathutils import Vector

        wrapper = scene_mgr.molecules.get(identifier)
        if wrapper is None or wrapper.molecule is None:
            self.report({"ERROR"}, f"Molecule '{identifier}' not found.")
            return {"CANCELLED"}

        old_obj = wrapper.molecule.object
        if old_obj is None or not old_obj.get("pb_is_nucleic_acid", False):
            self.report({"ERROR"}, f"'{identifier}' is not a DNA/RNA molecule.")
            return {"CANCELLED"}

        # Make sure we're in OBJECT mode + the DNA is active (origin_set
        # and select_all in the rebuild path require it).
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action="DESELECT")
            old_obj.select_set(True)
            context.view_layer.objects.active = old_obj
        except Exception:
            pass

        # Save the world-space bounding-box centre (not obj.location —
        # obj.location includes the pivot-shift offset added by
        # shift_origin_to_bottom, which would accumulate on each rebuild).
        bbox = [old_obj.matrix_world @ Vector(c) for c in old_obj.bound_box]
        old_visual_center = sum(bbox, Vector()) / 8

        old_rot_mode = old_obj.rotation_mode
        old_rot_euler = old_obj.rotation_euler.copy()
        old_rot_quat = old_obj.rotation_quaternion.copy()
        bend_curve_name = old_obj.get(_bender.BEND_CURVE_PROP)
        bend_curve_obj = bpy.data.objects.get(bend_curve_name) if bend_curve_name else None

        # Take custody of the strand's and the control nodes' animation before
        # anything is deleted: this rebuild destroys both objects, and with
        # them every F-curve the user keyed. Re-bound after the bend rig is
        # reattached below.
        anim_stash = _bender.capture_bend_animation(old_obj)

        # Bake any user-driven bend into the curve's bezier data before
        # we destroy the hook empties — hooks only deform at eval time.
        if bend_curve_obj is not None:
            try:
                _bender.bake_evaluated_curve_shape(bend_curve_obj)
            except Exception as e:
                self.report({"WARNING"}, f"Could not bake bend shape: {e}")

        # Delete the old molecule (object + collection + registry).
        # The bend curve survives because it's a separate object.
        scene_mgr.delete_molecule(identifier)

        # Purge the cached MN_<id> node tree so create_starting_node_tree
        # doesn't early-return and silently ignore a style change.
        ng_name = f"MN_{identifier}"
        old_tree = bpy.data.node_groups.get(ng_name)
        if old_tree is not None:
            try:
                bpy.data.node_groups.remove(old_tree, do_unlink=True)
            except Exception:
                pass

        # Build new with the SAME identifier so the outliner slot is preserved.
        wrapper, info = _build_dna_from_props(self, context, identifier)
        if wrapper is None:
            return {"CANCELLED"}
        new_obj = wrapper.molecule.object

        # Restore rotation (not location yet — reattach_after_rebuild
        # below modifies location via shift_origin_to_bottom).
        if new_obj is not None:
            new_obj.rotation_mode = old_rot_mode
            new_obj.rotation_euler = old_rot_euler
            new_obj.rotation_quaternion = old_rot_quat

        # Re-establish the bend if there was one.
        if bend_curve_obj is not None and new_obj is not None:
            try:
                _bender.reattach_after_rebuild(new_obj, bend_curve_obj)
            except Exception as e:
                self.report({"WARNING"}, f"Could not reattach bend: {e}")

        # Put the animation back on the rebuilt strand and its fresh control
        # nodes - must run after reattach_after_rebuild, which is what creates
        # the nodes the F-curves bind to.
        if new_obj is not None:
            try:
                _bender.restore_bend_animation(new_obj, anim_stash)
            except Exception as e:
                self.report({"WARNING"}, f"Could not restore animation: {e}")

        # Restore visual position: align the new bbox centre with the
        # saved centre so the strand stays where the user put it.
        if new_obj is not None:
            context.view_layer.update()
            bbox = [new_obj.matrix_world @ Vector(c) for c in new_obj.bound_box]
            new_visual_center = sum(bbox, Vector()) / 8
            new_obj.location += old_visual_center - new_visual_center

        # Re-select the new object
        if new_obj:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                new_obj.select_set(True)
                context.view_layer.objects.active = new_obj
            except Exception:
                pass

        self.report(
            {"INFO"},
            f"Updated {identifier}: {info['helix_length_angstrom']:.1f} Å, "
            f"{info['turns']:.1f} turns",
        )
        return {"FINISHED"}

    @staticmethod
    def _next_id(props, scene_mgr):
        prefix = props.name_prefix or ("DNA" if props.nucleic_type == "DNA" else "RNA")
        counter = 1
        while True:
            name = f"{prefix}_{counter:03d}"
            if name not in scene_mgr.molecules:
                return name
            counter += 1


class PROTEINBLENDER_OT_randomize_sequence(Operator):
    """Generate a random nucleotide sequence of the specified length"""

    bl_idname = "proteinblender.randomize_sequence"
    bl_label = "Generate Random Sequence"

    def execute(self, context):
        props = context.scene.dna_builder_props
        chars = "ATGC" if props.nucleic_type == "DNA" else "AUGC"
        props.sequence = "".join(random.choice(chars) for _ in range(props.sequence_length))
        return {"FINISHED"}


class PROTEINBLENDER_OT_swap_to_complement(Operator):
    """Replace the sequence with its reverse complement (the antisense strand
    read 5'->3'). Click twice to return to the original — useful for hopping
    between the two single strands when building them separately."""

    bl_idname = "proteinblender.swap_to_complement"
    bl_label = "Swap to Complement"

    def execute(self, context):
        from .sequence_builder import COMPLEMENTS, validate_sequence

        props = context.scene.dna_builder_props
        nt = props.nucleic_type
        seq = validate_sequence(props.sequence, nt)
        if len(seq) < 1:
            self.report({"WARNING"}, "Nothing to swap — sequence is empty.")
            return {"CANCELLED"}
        comp_map = COMPLEMENTS[nt]
        props.sequence = "".join(comp_map[b] for b in reversed(seq))
        return {"FINISHED"}


class PROTEINBLENDER_OT_update_dna_colors(Operator):
    """Update per-base colours on the selected DNA/RNA molecule"""

    bl_idname = "proteinblender.update_dna_colors"
    bl_label = "Update DNA Colors"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("pb_is_nucleic_acid", False)

    def execute(self, context):
        from .dna_colors import apply_base_colors, colors_from_props, store_colors_on_object

        obj = context.active_object
        props = context.scene.dna_builder_props
        colors = colors_from_props(props)
        store_colors_on_object(obj, colors)
        apply_base_colors(obj, colors)
        self.report({"INFO"}, "Colours updated.")
        return {"FINISHED"}


class PROTEINBLENDER_OT_update_dna_style(Operator):
    """Change the visualisation style of the selected DNA/RNA molecule"""

    bl_idname = "proteinblender.update_dna_style"
    bl_label = "Update DNA Style"

    new_style: StringProperty()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("pb_is_nucleic_acid", False)

    def execute(self, context):
        from ..utils.molecularnodes.blender.nodes import change_style_node
        from .dna_colors import apply_base_colors, colors_from_object

        obj = context.active_object
        if not self.new_style:
            self.new_style = context.scene.dna_builder_props.style

        change_style_node(obj, self.new_style)
        obj["pb_style"] = self.new_style

        # Re-apply base colours (style change may reset Color attribute)
        colors = colors_from_object(obj)
        apply_base_colors(obj, colors)

        self.report({"INFO"}, f"Style changed to {self.new_style}.")
        return {"FINISHED"}


CLASSES = (
    PROTEINBLENDER_OT_build_dna,
    PROTEINBLENDER_OT_randomize_sequence,
    PROTEINBLENDER_OT_swap_to_complement,
    PROTEINBLENDER_OT_update_dna_colors,
    PROTEINBLENDER_OT_update_dna_style,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
