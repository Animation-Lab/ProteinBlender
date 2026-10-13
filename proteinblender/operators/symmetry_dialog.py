"""The Symmetry Builder dialog.

The Create New Assembly button opens this; everything that *shapes* a
generated symmetry lives inside it. Three ways out, and they mean different
things:

* **Apply** builds the symmetry and leaves the dialog open, so the settings
  can be judged against the viewport rather than against the numbers. It is an
  ordinary operator button drawn in the dialog body - Blender keeps a props
  dialog open across those, which is what makes a preview possible at all.
* **OK** builds and closes, and refreshes the PB Outliner so the result takes
  its place there as a row of its own.
* **Cancel** puts back whatever was on screen before the dialog opened -
  nothing, a deposited assembly, or an earlier generated symmetry - because a
  preview the user rejected should not be what they are left with.

Two modes, like the membrane builder's dialog and for the same reason:
opened empty it configures a new build, and opened from the outliner's edit
pencil it reopens on what that protein was actually built with.

Opened on an existing assembly it is also the one place that assembly is
worked on: below the build settings sit its axes, cutaway, realization and,
for a filament, its bend. Those act on the assembly as it stands, so they are
only live while the settings above still describe it - see
:func:`dialog_signature`.
"""

from __future__ import annotations

import json
import logging

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from ..core import assembly as assembly_core
from ..core import bend_rig, symmetry_axes, symmetry_bend, symmetry_builder
from ..utils.scene_manager import ProteinBlenderScene, resolve_active_molecule_id
from .assembly_operators import (
    apply_symmetry_settings,
    build_generated_symmetry,
    built_symmetry_settings,
    refresh_symmetry_axes,
    symmetry_settings,
)

logger = logging.getLogger(__name__)

#: Blender does not keep the strings an EnumProperty items callback returns
#: alive, so they must be held on the Python side or the picker draws garbage.
_TARGET_ENUM_CACHE = {}

#: What Cancel has to put back, as {molecule id: pre-preview state}.
#:
#: Module state rather than operator properties, for two reasons this codebase
#: has already been bitten by: a modal ``invoke_props_dialog`` operator is
#: absent from ``wm.operators`` until it finishes, so Apply cannot reach the
#: running dialog through the operator history; and Blender rebuilds the
#: instance behind a props dialog, so the one that ran ``invoke`` is not
#: necessarily the one whose ``cancel`` runs. Anything that must survive from
#: opening to dismissal cannot live on the instance.
#:
#: Keyed by molecule because the picker can be moved mid-dialog: preview A,
#: switch to B, preview B, and both need putting back.
_PREVIEWS: dict = {}


def remember_preview_target(molecule) -> None:
    """Record what to put back for this molecule, before a preview builds.

    First preview of a molecule wins: later ones would record the previous
    *preview* as the thing to restore, which is how Cancel ends up putting
    back a state the user never had.
    """
    if molecule.identifier not in _PREVIEWS:
        _PREVIEWS[molecule.identifier] = snapshot_state(molecule)


def pending_previews() -> list:
    """Which molecules have a preview outstanding that Cancel would undo."""
    return list(_PREVIEWS)


def discard_previews(keep: str = "") -> list:
    """Put back every previewed molecule, optionally sparing one.

    ``keep`` is the molecule being committed by OK: its preview *is* the
    result, so it stays. Everything else the dialog touched on the way there
    was only ever a preview and goes back to what it was.
    """
    restored = []
    for molecule_id, state in list(_PREVIEWS.items()):
        if molecule_id == keep:
            continue
        molecule = _molecule(molecule_id)
        if molecule is not None:
            restore_state(molecule, state)
            restored.append(molecule_id)
    _PREVIEWS.clear()
    return restored


def _molecules():
    return ProteinBlenderScene.get_instance().molecules


def _molecule(molecule_id):
    from ..core.outliner_targets import resolve_target as resolve_row
    return resolve_row(molecule_id)[0]


def target_enum_items(self, context):
    """Every loaded molecule, as the dialog's "which protein" picker.

    One at a time: the generator works in a molecule's own coordinate frame,
    so the same operator set applied to two proteins rings each about its own
    origin rather than building one assembly out of both.
    """
    global _TARGET_ENUM_CACHE

    items = []
    from ..core.outliner_targets import target_rows
    for row in target_rows(context.scene):
        molecule = _molecule(row.item_id)
        name = row.name if row.item_type == 'PROTEIN' else f"{getattr(molecule, 'name', molecule.identifier)} / {row.name}"
        items.append((row.item_id, name, f"Build symmetry for {name}"))

    if not items:
        items = [("", "No protein loaded", "Import a structure first")]

    return _TARGET_ENUM_CACHE.setdefault(tuple(items), items)


def resolve_target(context, requested: str = "") -> str:
    """Which protein the dialog should open on, or "" if there is none.

    Create New Assembly is always enabled, like the other two builders, so it
    gets clicked when nothing in particular is selected - the state a user is
    in after deleting a protein, after an undo, or simply on a scene they have
    not clicked into yet. Refusing then is wrong twice over: the dialog has a
    picker, and there is something to pick.

    So an explicit request wins, then whatever the UI considers active, and
    failing both, the first molecule loaded - which is exactly what the picker
    would have opened on anyway. "" is reserved for the one case the dialog
    genuinely cannot proceed from: no proteins at all.
    """
    if requested and _molecule(requested) is not None:
        return requested

    active = resolve_active_molecule_id(context) or ""
    if _molecule(active) is not None:
        return active

    return next(iter(_molecules()), "")


def snapshot_state(molecule) -> dict:
    """What is on screen now, in enough detail to put it back.

    Three states worth restoring and they restore differently: nothing built,
    a deposited assembly (rebuild it by id), or a generated symmetry (rebuild
    it from the settings recorded with it).
    """
    return {
        "assembly_id": assembly_core.built_assembly_id(molecule),
        "params": assembly_core.built_build_params(molecule),
    }


def restore_state(molecule, state: dict) -> None:
    """Put back what :func:`snapshot_state` recorded."""
    assembly_id = state.get("assembly_id")
    params = state.get("params")
    if not assembly_id:
        assembly_core.clear_assembly(molecule)
    elif params and str(assembly_id).startswith("generated:"):
        ok, message = build_generated_symmetry(molecule, params)
        if not ok:
            logger.warning("could not restore the previous symmetry: %s",
                           message)
    else:
        assembly_core.build_assembly(molecule, str(assembly_id))
    refresh_symmetry_axes(bpy.context, molecule)


_BIOLOGICAL_ENUM_CACHE = {}


def biological_enum_items(self, context):
    molecule = _molecule(getattr(self, 'target_id', ''))
    infos = assembly_core.buildable_assemblies(molecule) if molecule else []
    values = [(info.assembly_id, info.label, info.tooltip, i)
              for i, info in enumerate(infos)] or [("", "No deposited assembly", "", 0)]
    return _BIOLOGICAL_ENUM_CACHE.setdefault(tuple(values), values)


def _assembly_choice_changed(self, context):
    self.assembly_id = self.assembly_choice


def _sync_assembly_choice(self, context):
    if self.source != 'BIOLOGICAL':
        return
    choices = [item[0] for item in biological_enum_items(self, context)]
    chosen = self.assembly_id if self.assembly_id in choices else choices[0]
    self.assembly_id = chosen
    if chosen:
        self.assembly_choice = chosen



def _get_bend_nodes(dialog) -> int:
    """How many control nodes the edited filament's path has now."""
    molecule = _molecule(dialog.molecule_id_to_update)
    nodes = (len(symmetry_bend.get_bend_nodes(molecule))
             if molecule is not None else 0)
    return nodes or bend_rig.RES_DEFAULT


def _set_bend_nodes(dialog, value) -> None:
    """Give the edited filament's path this many control nodes, at once.

    The field is the control: a number that had to be confirmed with a button
    beside it read as a setting that did nothing. Run as the operator, with
    an undo step of its own, so one change of the field is one Ctrl+Z.
    """
    molecule = _molecule(dialog.molecule_id_to_update)
    if molecule is None or not symmetry_bend.has_bend(molecule):
        return
    value = min(max(int(value), bend_rig.RES_MIN), bend_rig.RES_MAX)
    if value == len(symmetry_bend.get_bend_nodes(molecule)):
        return
    bpy.ops.molecule.set_filament_bend_nodes(
        'EXEC_DEFAULT', True, molecule_id=molecule.identifier, n_points=value)


def dialog_signature(dialog, scene) -> str:
    """Everything OK would build from, as one comparable string.

    Taken when the dialog opens on an existing assembly and compared from then
    on, which answers "has the user asked for anything different?" without the
    dialog having to know what each control means.
    """
    described = {"target": dialog.target_id, "source": dialog.source}
    if dialog.source == 'BIOLOGICAL':
        described["assembly"] = dialog.assembly_id
    else:
        described["settings"] = symmetry_settings(scene)
    return json.dumps(described, sort_keys=True)


def build_dialog_symmetry(molecule, context, target_id, source, assembly_id):
    """Build what the dialog describes. Returns (ok, message)."""
    ok, message = _build_dialog_symmetry(
        molecule, context, target_id, source, assembly_id)
    if ok:
        refresh_symmetry_axes(context, molecule)
    return ok, message


def _build_dialog_symmetry(molecule, context, target_id, source, assembly_id):
    if source == 'BIOLOGICAL':
        if target_id != molecule.identifier:
            return False, "Choose the whole protein to build its biological assembly"
        if not assembly_id:
            choices = assembly_core.buildable_assemblies(molecule)
            assembly_id = choices[0].assembly_id if choices else ""
        if not assembly_id or not assembly_core.build_assembly(molecule, assembly_id):
            return False, "No biological assembly available for this structure"
        return True, f"Built biological assembly {assembly_id}"
    settings = symmetry_settings(context.scene)
    settings['source_item_id'] = target_id or molecule.identifier
    return build_generated_symmetry(molecule, settings)


class MOLECULE_PB_OT_symmetry_dialog(Operator):
    """Build generated symmetry or deposited biological transformations"""

    bl_idname = "molecule.symmetry_dialog"
    bl_label = "Create New Assembly"
    bl_description = (
        "Repeat a protein, chain or domain using generated symmetry, or build "
        "the protein's deposited biological assembly (BMT). Apply previews; OK keeps it")
    bl_options = {"REGISTER", "UNDO"}

    source: EnumProperty(
        name="Source",
        items=[('BIOLOGICAL', 'PDB-defined Assembly',
                'Use the biological assemblies deposited with the structure'),
               ('GENERATED', 'Generated Symmetry', 'Create a ring or filament')],
        # Scripted calls historically build generated symmetry. The actual
        # Create window selects the deposited source in invoke below.
        default='GENERATED',
    )
    # The public id is a string: Blender 5.1 validates enum keyword arguments
    # before applying target_id, against a different protein's choices. Keep
    # the dynamic picker separate and synchronize it on UI changes instead.
    assembly_id: StringProperty(name="Assembly ID", options={'HIDDEN', 'SKIP_SAVE'})
    assembly_choice: EnumProperty(
        name="Assembly", items=biological_enum_items,
        update=_assembly_choice_changed, options={'SKIP_SAVE'})

    target_id: EnumProperty(
        name="Protein, Chain or Domain",
        description="Which protein, chain or domain to repeat",
        items=target_enum_items,
        options={'SKIP_SAVE'},
    )

    #: Set by the PB Outliner's edit pencil to reopen the dialog on an existing
    #: build. Empty means "configure a new one".
    molecule_id_to_update: StringProperty(
        name="Symmetry to edit",
        description=("If set, open on this protein's existing assembly "
                     "instead of on the scene's current settings"),
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    #: :func:`dialog_signature` as the dialog opened on an existing assembly.
    #: Empty for a new build and for a scripted call, which always build.
    opened_on: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    #: Which of the assembly's sections are unfolded. On the dialog rather
    #: than left to Blender, which remembers a section's state between dialogs
    #: in 5.1 and 5.2 and not in 5.0.
    show_cutaway: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    show_bend: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    #: The edited filament's control node count. Read from its path and
    #: written straight to it, so nothing is stored here to fall out of step
    #: with a shape that brought more nodes of its own.
    bend_nodes: IntProperty(
        name="Nodes",
        description=("How many control nodes shape the filament's path. The "
                     "bend already made is kept and resampled onto them"),
        min=bend_rig.RES_MIN, max=bend_rig.RES_MAX,
        get=_get_bend_nodes, set=_set_bend_nodes,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        """One operator, two buttons: Create New Assembly and a row's pencil."""
        if getattr(properties, "molecule_id_to_update", ""):
            return ("Edit this assembly: change how it is built, show its "
                    "axes, cut it away, realize its copies or bend a filament")
        return cls.bl_description

    # -- opening -----------------------------------------------------------

    def invoke(self, context, event):
        """Always opens. There is no scene too empty for this dialog.

        It carries its own Download / Import Local File controls, so an empty
        scene is something it *fixes* rather than something it refuses: the
        form is where you get hold of a protein as well as where you shape the
        symmetry built from it. Refusing here shut the one screen that could
        have helped.
        """
        molecule_id = resolve_target(context, self.molecule_id_to_update)
        molecule = _molecule(molecule_id)

        if molecule is None and not self.properties.is_property_set('source'):
            self.source = 'BIOLOGICAL'

        if molecule is not None:
            params = assembly_core.built_build_params(molecule) or {}
            if self.molecule_id_to_update:
                molecule_id = params.get('source_item_id', molecule_id)
                built_id = assembly_core.built_assembly_id(molecule)
                self.source = 'BIOLOGICAL' if built_id and not params else 'GENERATED'
            elif not self.properties.is_property_set('source'):
                self.source = 'BIOLOGICAL' if assembly_core.available_assemblies(molecule) else 'GENERATED'
        if molecule_id:
            try:
                self.target_id = molecule_id
            except TypeError:
                # The picker refuses an identifier its items callback is not
                # currently offering; it then opens on its first entry.
                logger.warning("could not point the picker at %s", molecule_id)

        # Reopening on a build shows what that build was made with, not what
        # the scene sliders happen to say - they are one set of controls
        # standing in for whichever protein was last active.
        if molecule is not None:
            stored = assembly_core.built_build_params(molecule)
            if stored:
                apply_symmetry_settings(context.scene, stored)

        if self.source == 'BIOLOGICAL' and molecule is not None:
            built_id = assembly_core.built_assembly_id(molecule)
            if self.molecule_id_to_update and built_id in {
                    item[0] for item in biological_enum_items(self, context)}:
                self.assembly_id = built_id

        _sync_assembly_choice(self, context)

        # Anything left over from a dialog that was torn down without its
        # cancel() running would otherwise be restored on top of this one.
        _PREVIEWS.clear()

        self.opened_on = ""
        if (self.molecule_id_to_update and molecule is not None
                and assembly_core.built_assembly_id(molecule) is not None):
            self.opened_on = dialog_signature(self, context.scene)
            # A bend added from here starts with as many nodes as this
            # filament's last one had.
            nodes = len(symmetry_bend.get_bend_nodes(molecule))
            if nodes and context.scene.pb_bend_nodes != nodes:
                context.scene.pb_bend_nodes = nodes
            # A filament that is already bent opens on its bend.
            self.show_bend = symmetry_bend.has_bend(molecule)
        return context.window_manager.invoke_props_dialog(
            self, width=380,
            title="Edit Assembly" if self.molecule_id_to_update else "Create New Assembly")

    def check(self, context):
        # Blender calls check() before the enum update callback for a menu
        # selection. Accept the picker value first or syncing the old public
        # id here immediately resets the user's selection.
        if self.source == 'BIOLOGICAL':
            self.assembly_id = self.assembly_choice
        _sync_assembly_choice(self, context)
        return True

    # -- body --------------------------------------------------------------

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        self._draw_protein_block(layout, scene)
        layout.separator(factor=0.5)
        self._draw_build(layout, scene)
        self._draw_tools(layout, scene)

    def _draw_build(self, layout, scene):
        layout.prop(self, 'source', text="")
        if self.source == 'BIOLOGICAL':
            molecule = _molecule(self.target_id)
            if molecule is None:
                message = "Import a protein to use its deposited assembly"
            elif self.target_id != molecule.identifier:
                message = "Choose the whole protein in Build from"
            elif not assembly_core.available_assemblies(molecule):
                message = "No assembly deposited for this protein"
            else:
                message = ""
            if message:
                layout.label(text=message, icon='INFO')
                return
            layout.prop(self, 'assembly_choice')
            info = assembly_core.get_assembly_info(molecule, self.assembly_id)
            if info:
                layout.label(text=f'{info.transform_count} transformation applications')
            self._draw_apply(layout)
            return

        kind = getattr(scene, "pb_symmetry_kind", "C")

        col = layout.column(align=True)
        col.prop(scene, "pb_symmetry_kind", text="")
        if kind in {"C", "D"}:
            col.prop(scene, "pb_symmetry_order")
        else:
            strands = getattr(scene, "pb_symmetry_strands", 1)
            col.prop(scene, "pb_symmetry_count",
                     text="Subunits per Strand" if strands > 1 else "Subunits")
            # The same number as Subunits, for whoever arrives knowing how
            # long the filament should be rather than how many it holds.
            col.prop(scene, "pb_symmetry_length", text="Length (nm)")
            col.prop(scene, "pb_symmetry_rise")
            col.prop(scene, "pb_symmetry_twist")
            col.prop(scene, "pb_symmetry_strands")
            if strands > 1:
                col.prop(scene, "pb_symmetry_stagger")
                col.prop(scene, "pb_symmetry_strand_twist")

        axis_row = col.row(align=True)
        axis_row.label(text="Axis")
        axis_row.prop(scene, "pb_symmetry_axis", text="")

        summary = layout.row()
        summary.enabled = False
        summary.label(text=symmetry_builder.describe(
            kind,
            order=getattr(scene, "pb_symmetry_order", 3),
            count=getattr(scene, "pb_symmetry_count", 10),
            rise=getattr(scene, "pb_symmetry_rise", 0.0),
            twist=getattr(scene, "pb_symmetry_twist", 0.0),
            strands=getattr(scene, "pb_symmetry_strands", 1)))

        layout.separator(factor=0.5)
        trim = layout.box()
        trim.label(text="Trim Copies")
        trim_col = trim.column(align=True)
        trim_col.prop(scene, "pb_symmetry_range")
        trim_col.prop(scene, "pb_symmetry_contact")
        note = trim.row()
        note.enabled = False
        note.label(text="0 keeps every copy", icon='INFO')

        self._draw_apply(layout)

    def _draw_apply(self, layout):
        layout.separator(factor=0.5)
        apply_row = layout.row(align=True)
        apply_row.scale_y = 1.2
        apply_row.enabled = bool(self.target_id)
        apply_op = apply_row.operator("molecule.symmetry_preview",
                                      text="Apply", icon='CHECKMARK')
        apply_op.molecule_id = self.target_id
        apply_op.source = self.source
        apply_op.assembly_id = self.assembly_id
        hint = layout.row()
        hint.enabled = False
        hint.label(text="Apply previews it - OK keeps it", icon='INFO')

    # -- working on the assembly the dialog was opened on --------------------

    def _edited_molecule(self):
        """The built assembly this dialog was opened on, if it is still there.

        It stops being there the moment Realize Copies turns it into objects.
        """
        if not self.opened_on:
            return None
        molecule = _molecule(self.molecule_id_to_update)
        if molecule is None or assembly_core.built_assembly_id(molecule) is None:
            return None
        return molecule

    def _shows_what_it_opened_on(self, scene) -> bool:
        return (bool(self.opened_on) and not _PREVIEWS
                and dialog_signature(self, scene) == self.opened_on)

    def _draw_tools(self, layout, scene):
        molecule = self._edited_molecule()
        if molecule is None:
            return

        # These act on the assembly as it is built. Once a setting above has
        # been changed or previewed, that is no longer what OK will leave
        # behind, and a cut or a realization made now would be thrown away or
        # doubled up by it.
        current = self._shows_what_it_opened_on(scene)

        layout.separator(factor=0.5)
        tools = layout.column()
        tools.enabled = current

        actions = tools.row(align=True)
        showing = bool(symmetry_axes.symmetry_axis_objects(molecule))
        axes_op = actions.operator(
            "molecule.toggle_symmetry_axes",
            text="Hide Symmetry Axes" if showing else "Show Symmetry Axes",
            icon='EMPTY_AXIS')
        axes_op.molecule_id = molecule.identifier
        real_op = actions.operator("molecule.realize_copies",
                                   text="Realize Copies", icon='OUTLINER_OB_MESH')
        real_op.molecule_id = molecule.identifier

        # Folded away until asked for, so that opening the dialog to change a
        # count does not mean reading past a cutaway and a bend to reach OK.
        header, cut = tools.panel_prop(self, "show_cutaway")
        header.label(text="Cutaway")
        if cut is not None:
            direction = cut.row(align=True)
            direction.label(text="Direction")
            direction.prop(scene, "pb_cutaway_normal", text="")
            depth = cut.row(align=True)
            depth.prop(scene, "pb_cutaway_offset")
            cut_op = depth.operator("molecule.cutaway", text="Cut Away",
                                    icon='MOD_BOOLEAN')
            cut_op.molecule_id = molecule.identifier
            cut_op.normal = scene.pb_cutaway_normal
            cut_op.offset = scene.pb_cutaway_offset

        # Only a filament: a ring or a double ring has no path to follow.
        if symmetry_builder.built_symmetry_kind(molecule) == 'H':
            header, bend = tools.panel_prop(self, "show_bend")
            header.label(text="Bend")
            if bend is not None:
                self._draw_bend(bend, scene, molecule)

        if not current:
            hint = layout.row()
            hint.enabled = False
            hint.label(text="OK the new settings first to use these",
                       icon='INFO')

    def _draw_bend(self, box, scene, molecule):
        if not symmetry_bend.has_bend(molecule):
            add_op = box.operator("molecule.add_filament_bend",
                                  text="Add Bend", icon='CURVE_BEZCURVE')
            add_op.molecule_id = molecule.identifier
            add_op.n_points = scene.pb_bend_nodes
            note = box.row()
            note.enabled = False
            note.label(text="Subunits stay rigid as the path bends",
                       icon='INFO')
            return

        # Changing the count recreates the nodes, which would orphan every
        # key set on the old ones - so a keyframed path keeps the count it has.
        keyed = bend_rig.has_keyframes(symmetry_bend.SPEC,
                                       symmetry_bend.owner_object(molecule))
        count = box.row(align=True)
        count.enabled = not keyed
        count.prop(self, "bend_nodes")
        if keyed:
            locked = box.row()
            locked.enabled = False
            locked.label(text="Keyframed - clear its keys to change the nodes",
                         icon='INFO')

        presets = box.row(align=True)
        for identifier, label, _description in bend_rig.PRESETS:
            preset_op = presets.operator("molecule.filament_bend_preset",
                                         text=label)
            preset_op.molecule_id = molecule.identifier
            preset_op.preset = identifier

        actions = box.row(align=True)
        edit_op = actions.operator("molecule.edit_filament_bend",
                                   text="Edit Bend", icon='EMPTY_DATA')
        edit_op.molecule_id = molecule.identifier
        remove_op = actions.operator("molecule.remove_filament_bend",
                                     text="Remove", icon='X')
        remove_op.molecule_id = molecule.identifier

        # Say whether the rig is doing anything, not merely that it exists -
        # a freshly added bend is straight until a node is dragged. Measured
        # against the settings the filament was *built* from, which the
        # scene sliders stop agreeing with as soon as one is moved.
        built = built_symmetry_settings(scene, molecule)
        departure = symmetry_bend.bend_departure(
            molecule,
            count=built["count"], rise=built["rise"], twist=built["twist"],
            axis=built["axis"], **symmetry_builder.lattice_settings(built))

        # The nodes cannot be reached through an open dialog.
        status = box.row()
        status.enabled = False
        if departure < 1.0:
            status.label(text="Press OK, then drag a node to bend",
                         icon='INFO')
        else:
            status.label(text=f"Tip is {departure:.0f} A off straight - "
                              "OK to drag the nodes",
                         icon='CHECKMARK')

    def _draw_protein_block(self, layout, scene):
        """Getting hold of a protein, and choosing which one to repeat.

        The same Method / id / Download / Import Local File controls the
        Protein Import panel offers, because the dialog has to stand on its
        own: it opens on an empty scene, and this is what makes that useful
        rather than a dead end. Operator buttons inside a props dialog do not
        dismiss it, so a download lands and the picker below simply gains an
        entry.
        """
        box = layout.box()
        box.label(text="Protein", icon='FILE_FOLDER')

        props = getattr(scene, "protein_props", None)
        if props is not None:
            source = box.row(align=True)
            source.prop(props, "import_method", text="Method")
            method = getattr(props, "import_method", "PDB")
            if method in {'PDB', 'MMCIF'}:
                source.prop(props, "pdb_id", text="PDB ID")
            elif method == 'ALPHAFOLD':
                source.prop(props, "uniprot_id", text="UniProt ID")

            buttons = box.row(align=True)
            buttons.operator("molecule.import_protein", text="Download")
            # Opens Blender's file browser, which cannot be nested inside a
            # popup: this one closes the dialog behind it. The import still
            # lands, and reopening finds the protein waiting in the picker.
            buttons.operator("molecule.import_local", text="Import Local File")

        box.separator(factor=0.5)
        if _molecules():
            picker = box.row(align=True)
            # Labelled, unlike the kind dropdown below it: "Cyclic (Cn)" says
            # what it is on its own, where a bare "ubq" does not.
            picker.label(text="Build from")
            picker.prop(self, "target_id", text="")
        else:
            # No picker at all rather than one holding the placeholder item.
            # An enum whose only entry has an empty identifier draws as a
            # blank dropdown, which reads as broken rather than as empty.
            note = box.row()
            note.enabled = False
            note.label(text="Import one above to build a symmetry from it",
                       icon='INFO')

    # -- leaving -----------------------------------------------------------

    def execute(self, context):
        if self._shows_what_it_opened_on(context.scene):
            # Opened on an assembly and asked for nothing different, so there
            # is nothing to build - and building anyway would undo whatever
            # was done to it from here: a cutaway made whole again, realized
            # copies given a second assembly on top of them. Cancelled rather
            # than finished so that closing leaves no undo step of its own.
            _rebuild_outliner(context)
            _refresh(context)
            return {"CANCELLED"}

        # The picker's choice wins; resolve_target only fills in when it is
        # empty, which is the no-protein case.
        molecule = _molecule(resolve_target(context, self.target_id))
        if molecule is None:
            molecule = self._import_typed_structure(context)
            if molecule is None:
                return {"CANCELLED"}

        target_id = self.target_id or molecule.identifier
        ok, message = build_dialog_symmetry(
            molecule, context, target_id, self.source, self.assembly_id)
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        # A preview on some *other* protein - the picker was moved after an
        # Apply - was still only a preview, and goes back to what it was. The
        # one being committed keeps its build.
        discard_previews(keep=molecule.identifier)

        # The outliner derives its symmetry row from what is actually built,
        # so this is a refresh rather than a write - which is what keeps the
        # row correct through undo, save/load and a build made any other way.
        _rebuild_outliner(context)
        self.report({"INFO"}, message)
        _refresh(context)
        return {"FINISHED"}

    def _import_typed_structure(self, context):
        """Import the id typed into the dialog's own Protein block, as Download would.

        OK on an empty scene with an id in that field means "this one": the
        field is part of the form, and a Download click first is a step the
        form never asked for. Reported as "Import a protein first" when the
        field is empty too, so people were typing 1atn, pressing OK and
        being told to do what they had just done.

        Returns the molecule to build from, or None after reporting why not.
        """
        from .operator_import_protein import import_request
        request = import_request(getattr(context.scene, "protein_props", None))
        identifier = (request[0] if request else "").strip()
        if not identifier:
            self.report({"ERROR"},
                        "Import a protein first - a symmetry repeats one")
            return None
        _, method, fmt = request
        if not ProteinBlenderScene.get_instance().create_molecule_from_id(
                request[0], import_method=method, remote_format=fmt):
            self.report({"ERROR"},
                        f"Could not import {identifier} - check the ID, or try Download")
            return None
        molecule = _molecule(resolve_target(context))
        if molecule is None:
            self.report({"ERROR"},
                        f"Imported {identifier}, but could not find it to build from")
            return None
        try:
            self.target_id = molecule.identifier
        except TypeError:
            logger.warning("could not point the picker at %s", molecule.identifier)
        return molecule

    def cancel(self, context):
        """Take every preview back down.

        Reads module state, not ``self``: the instance running cancel is not
        reliably the one that ran invoke.
        """
        if not _PREVIEWS:
            return
        discard_previews()
        _rebuild_outliner(context)
        _refresh(context)


class MOLECULE_PB_OT_symmetry_preview(Operator):
    """Build the symmetry now, without closing the dialog"""

    bl_idname = "molecule.symmetry_preview"
    bl_label = "Apply"
    bl_description = (
        "Build the symmetry with these settings so it can be judged in the "
        "viewport. The dialog stays open; Cancel puts back what was there "
        "before")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={'SKIP_SAVE'})
    source: EnumProperty(items=[('GENERATED', 'Generated', ''), ('BIOLOGICAL', 'Biological', '')])
    assembly_id: StringProperty()

    def execute(self, context):
        molecule = _molecule(resolve_target(context, self.molecule_id))
        if molecule is None:
            self.report({"ERROR"},
                        "Import a protein first - a symmetry repeats one")
            return {"CANCELLED"}

        # Before building, not after: the point of the record is what was
        # there *instead* of this preview.
        remember_preview_target(molecule)

        ok, message = build_dialog_symmetry(
            molecule, context, self.molecule_id or molecule.identifier,
            self.source, self.assembly_id)
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        self.report({"INFO"}, message)
        _refresh(context)
        return {"FINISHED"}


def _rebuild_outliner(context) -> None:
    from ..utils.scene_manager import build_outliner_hierarchy

    try:
        build_outliner_hierarchy(context)
    except Exception:
        logger.exception("could not rebuild the outliner")


def _refresh(context) -> None:
    for area in getattr(context.screen, "areas", []):
        area.tag_redraw()


CLASSES = (
    MOLECULE_PB_OT_symmetry_dialog,
    MOLECULE_PB_OT_symmetry_preview,
)
