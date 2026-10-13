"""Operators for building and clearing deposited biological assemblies.

The domain logic lives in ``core.assembly``; these are the thin Blender-facing
wrappers the panel drives.
"""

import logging

import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from bpy.types import Operator

from ..core import assembly as assembly_core
from ..core import symmetry_builder
from ..utils.scene_manager import ProteinBlenderScene, resolve_active_molecule_id

logger = logging.getLogger(__name__)

#: The scene controls a generated symmetry is built from: (settings key, scene
#: property, default). Named in one place so the dialog that edits them, the
#: build that consumes them and the record the build leaves behind cannot
#: drift apart about what a setting is.
SYMMETRY_SETTINGS = (
    ("kind", "pb_symmetry_kind", "C"),
    ("order", "pb_symmetry_order", 3),
    ("count", "pb_symmetry_count", 10),
    ("rise", "pb_symmetry_rise", 0.0),
    ("twist", "pb_symmetry_twist", 0.0),
    ("axis", "pb_symmetry_axis", (0.0, 0.0, 1.0)),
    # How many strands a filament has and how each stands to the last. The
    # twist between strands is 0 on its control for "evenly round the axis",
    # and None in a settings dict - see symmetry_builder.lattice_settings.
    ("strands", "pb_symmetry_strands", 1),
    ("stagger", "pb_symmetry_stagger", 0.0),
    ("strand_twist", "pb_symmetry_strand_twist", 0.0),
    ("range_limit", "pb_symmetry_range", 0.0),
    ("contact", "pb_symmetry_contact", 0.0),
)


def symmetry_settings(scene) -> dict:
    """Read the builder's controls off the scene into a plain dict."""
    values = {}
    for key, prop, default in SYMMETRY_SETTINGS:
        value = getattr(scene, prop, default)
        # The axis is a FloatVectorProperty, whose bpy_prop_array does not
        # survive being stored or JSON-encoded.
        values[key] = tuple(float(v) for v in value) if key == "axis" else value
    values.update(symmetry_builder.lattice_settings(values))
    return values


def apply_symmetry_settings(scene, values: dict) -> None:
    """Push a settings dict back onto the scene's controls.

    Field by field on purpose: a stored value that no longer fits its property
    - an enum identifier since renamed, a count past a new maximum - should
    leave the rest of the dialog correctly seeded rather than abort the seed.
    """
    # Settings that say nothing about strands describe a filament of one. The
    # controls are one set standing in for whichever assembly was last worked
    # on, so leaving them alone would show an older helix the thirteen strands
    # of the microtubule built after it.
    values = {**values, **symmetry_builder.lattice_settings(values)}
    for key, prop, default in SYMMETRY_SETTINGS:
        if key not in values:
            continue
        value = default if values[key] is None else values[key]
        try:
            setattr(scene, prop, value)
        except (TypeError, ValueError, AttributeError):
            logger.warning("could not seed %s from stored value %r",
                           prop, value)


def built_symmetry_settings(scene, molecule) -> dict:
    """The settings the assembly on screen was built from.

    Its own record, wherever it has one. The scene's controls only stand in
    for a build too old to carry a record at all - they describe whatever was
    set up last, which need not be this assembly.
    """
    settings = symmetry_settings(scene)
    built = assembly_core.built_build_params(molecule)
    if built:
        settings.update(built)
        settings.update(symmetry_builder.lattice_settings(built))
    settings["axis"] = tuple(settings["axis"])
    return settings


def build_generated_symmetry(molecule, settings: dict):
    """Build a generated symmetry from a settings dict. Returns (ok, message).

    The one path both the Symmetry dialog's Apply and its OK go through, so
    what the viewport previews and what the dialog commits cannot be built by
    two different pieces of code.
    """
    from ..core import symmetry_bend

    kind = settings.get("kind", "C") or "C"
    shape = {
        "order": settings.get("order", 3),
        "count": settings.get("count", 10),
        "rise": settings.get("rise", 0.0),
        "twist": settings.get("twist", 0.0),
        **symmetry_builder.lattice_settings(settings),
    }

    # A filament that is being rebuilt at another length takes its path with
    # it, before anything is laid along that path - and gives it back if the
    # build then comes to nothing, or the next attempt would resize it twice.
    previous = None
    if kind.upper() == "H" and symmetry_builder.built_symmetry_kind(molecule) == "H":
        previous = assembly_core.built_build_params(molecule)
    resized = bool(previous) and symmetry_bend.follow_length(
        molecule, previous, settings)

    def failed(message):
        if resized:
            symmetry_bend.follow_length(molecule, settings, previous)
        return False, message

    # Through symmetry_bend, not symmetry_builder: a helical filament with a
    # bend curve is laid along it, and everything else falls straight through
    # to the generator.
    operators = symmetry_bend.build_operators(
        molecule, kind,
        axis=tuple(settings.get("axis", (0.0, 0.0, 1.0))),
        **shape)

    range_limit = settings.get("range_limit", 0.0) or None
    contact = settings.get("contact", 0.0) or None
    if range_limit is not None or contact is not None:
        operators = assembly_core.filter_operators(
            molecule, operators,
            range_limit=range_limit, contact_distance=contact)

    if not operators:
        return failed("The range or contact limit removed every copy")

    targets = None
    source_id = settings.get("source_item_id", molecule.identifier)
    if source_id != molecule.identifier:
        from ..core.outliner_targets import resolve_target
        source_molecule, targets = resolve_target(source_id)
        if source_molecule != molecule or not targets:
            return failed("The symmetry source no longer exists")
    if not assembly_core.apply_operators(
            molecule, operators, f"generated:{kind.upper()}", targets=targets):
        return failed("Could not build that symmetry")

    # Leave the settings with the build, so the dialog can reopen on what was
    # actually built rather than on whatever the scene sliders now say.
    assembly_core.record_build_params(molecule, dict(settings))
    return True, symmetry_builder.describe(kind, **shape)

#: Blender does not keep a reference to the strings an EnumProperty items
#: callback returns, so anything built on the fly there must be held alive on
#: the Python side or the UI shows garbage. Rebuilt on every call.
_ASSEMBLY_ENUM_CACHE = {}


def _molecule(molecule_id):
    return ProteinBlenderScene.get_instance().molecules.get(molecule_id)


def _active_molecule_id(context):
    return resolve_active_molecule_id(context) or ""


def assembly_enum_items(self, context):
    """What the active molecule can be shown as.

    The list names *states*, not just builds, so it leads with the asymmetric
    unit - the structure as deposited, which is what is on screen before
    anything is built and the one-step way back afterwards. Being first makes
    it the enum's default, which is the honest opening value.

    All deposited assemblies follow it. Identity transforms may select only
    some chains, and even equivalent assemblies retain the depositor's names.
    """
    global _ASSEMBLY_ENUM_CACHE

    molecule_id = getattr(self, "molecule_id", "") or _active_molecule_id(context)
    molecule = _molecule(molecule_id)

    items = [(assembly_core.ASYMMETRIC_UNIT_ID,
              assembly_core.ASYMMETRIC_UNIT_LABEL,
              assembly_core.ASYMMETRIC_UNIT_DESCRIPTION)]

    if molecule is not None:
        for info in assembly_core.buildable_assemblies(molecule):
            items.append((
                info.assembly_id,
                info.label,
                info.tooltip,
            ))

    return _ASSEMBLY_ENUM_CACHE.setdefault(tuple(items), items)


def _set_picker(context, assembly_id: str) -> None:
    """Point the panel's picker at the state now on screen.

    Best-effort: a dynamic EnumProperty refuses any identifier its items
    callback is not currently offering, and the picker is only ever a
    convenience - what is *built* is read back off the node itself.
    """
    try:
        context.scene.pb_assembly_id = str(assembly_id)
    except (TypeError, ValueError):
        pass


class MOLECULE_PB_OT_build_assembly(Operator):
    """Build the deposited biological assembly for this protein"""

    bl_idname = "molecule.build_assembly"
    bl_label = "Build Assembly"
    bl_description = (
        "Repeat this protein under the symmetry operators deposited with it, "
        "building the biological assembly - the dimer, ring or capsid it forms")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    assembly_id: StringProperty()

    @classmethod
    def description(cls, context, properties):
        """The tooltip has to follow the picker, because the button does.

        One operator serves both of the picker's states, so a fixed
        ``bl_description`` would promise to build an assembly while hovering a
        button that is about to take one away.
        """
        if getattr(properties, "assembly_id", "") == assembly_core.ASYMMETRIC_UNIT_ID:
            return assembly_core.ASYMMETRIC_UNIT_DESCRIPTION
        return cls.bl_description

    def execute(self, context):
        molecule_id = self.molecule_id or _active_molecule_id(context)
        molecule = _molecule(molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        assembly_id = self.assembly_id
        if not assembly_id:
            assembly_id = getattr(context.scene, "pb_assembly_id", "") or ""
        if not assembly_id:
            assembly_id = assembly_core.ASYMMETRIC_UNIT_ID

        if assembly_id == assembly_core.ASYMMETRIC_UNIT_ID:
            return self._show_asymmetric_unit(context, molecule)

        info = assembly_core.get_assembly_info(molecule, assembly_id)
        if info is None:
            self.report({"ERROR"}, f"No assembly {assembly_id} in this structure")
            return {"CANCELLED"}

        operators = _filtered(context, molecule,
                              assembly_core._operators_for(molecule, assembly_id))
        if not operators:
            self.report({"WARNING"}, "The range or contact limit removed every copy")
            return {"CANCELLED"}

        if not assembly_core.apply_operators(molecule, operators, str(assembly_id)):
            self.report({"ERROR"}, "Could not build the assembly")
            return {"CANCELLED"}

        trimmed = ("" if len(operators) == info.transform_count
                   else f" (trimmed from {info.transform_count})")
        self.report(
            {"INFO"},
            f"Built assembly {assembly_id}: {len(operators)} copies{trimmed}")
        _set_picker(context, assembly_id)
        _refresh(context)
        return {"FINISHED"}

    def _show_asymmetric_unit(self, context, molecule):
        """Take everything off, leaving the structure the file deposited.

        Succeeds either way. Asking for the state you are already in is not an
        error, and reporting one for a picker that opens on this entry would
        make the panel's default choice look broken.
        """
        removed = assembly_core.clear_assembly(molecule)
        self.report(
            {"INFO"},
            "Showing the asymmetric unit as deposited" if removed
            else "Already showing the asymmetric unit")
        _set_picker(context, assembly_core.ASYMMETRIC_UNIT_ID)
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_build_symmetry(Operator):
    """Generate symmetry copies from parameters, not from the file"""

    bl_idname = "molecule.build_symmetry"
    bl_label = "Build Symmetry"
    bl_description = (
        "Generate a symmetric assembly - a ring, a double ring or a filament - "
        "for a structure whose file does not describe one")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    kind: StringProperty(default="")

    def execute(self, context):
        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        settings = symmetry_settings(context.scene)
        if self.kind:
            settings["kind"] = self.kind

        ok, message = build_generated_symmetry(molecule, settings)
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        self.report({"INFO"}, message)
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_toggle_symmetry_axes(Operator):
    """Show or hide the assembly's symmetry axes"""

    bl_idname = "molecule.toggle_symmetry_axes"
    bl_label = "Symmetry Axes"
    bl_description = (
        "Draw the rotation axes of the built symmetry as renderable objects - "
        "the five-fold through a capsid vertex, the two-fold between subunits")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        from ..core import symmetry_axes

        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        if symmetry_axes.symmetry_axis_objects(molecule):
            symmetry_axes.clear_symmetry_axes(molecule)
            self.report({"INFO"}, "Symmetry axes hidden")
            _refresh(context)
            return {"FINISHED"}

        tag = assembly_core.built_assembly_id(molecule)
        if tag is None:
            self.report({"WARNING"}, "Build a symmetry before showing its axes")
            return {"CANCELLED"}

        operators = _operators_of_built(context, molecule, tag)
        if not operators:
            self.report({"WARNING"}, "Could not recover the built operators")
            return {"CANCELLED"}

        created = symmetry_axes.show_symmetry_axes(molecule, operators)
        if not created:
            self.report({"INFO"}, "This symmetry has no axes to draw")
            return {"CANCELLED"}

        folds = ", ".join(sorted({a.label for a in symmetry_axes.axes_of(operators)}))
        self.report({"INFO"}, f"Showing {len(created)} axes ({folds})")
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_realize_copies(Operator):
    """Turn each copy into a protein of its own in the PB Outliner"""

    bl_idname = "molecule.realize_copies"
    bl_label = "Realize Copies"
    bl_description = (
        "Replace the assembly with real copies listed in the PB Outliner, so "
        "each one can be selected, coloured, hidden and moved on its own. An "
        "assembly of the whole protein becomes that many proteins; one made "
        "from a chain or domain becomes copies of it inside the protein")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    force: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        from .assembly_realize import realize_assembly

        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        created = realize_assembly(context, molecule, force=self.force)

        if created is None:
            self.report(
                {"WARNING"},
                f"More than {assembly_core.REALIZE_THRESHOLD} copies would "
                "make a great many proteins, so they are left as instances")
            return {"CANCELLED"}

        if not created:
            self.report({"INFO"}, "There were no copies to realize")
            return {"CANCELLED"}

        if created.proteins:
            made = f"{created.copies} copies as proteins"
        elif created.domains:
            made = f"{created.copies} copies as chain and domain copies"
        elif created.objects:
            made = f"{created.copies} copies as objects"
        else:
            made = "the assembly where it stood"
        self.report({"INFO"}, f"Realized {made}")
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_cutaway(Operator):
    """Take the near side off the assembly to reveal its interior"""

    bl_idname = "molecule.cutaway"
    bl_label = "Cut Away"
    bl_description = (
        "Remove the copies in front of a plane, opening the shell up - the "
        "canonical virus figure. Whole subunits are removed, not sliced")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    normal: FloatVectorProperty(name="Cut Direction", size=3, default=(0.0, -1.0, 0.0))
    offset: FloatProperty(name="Cut Depth", default=0.0)

    def execute(self, context):
        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        tag = assembly_core.built_assembly_id(molecule)
        if tag is None:
            self.report({"WARNING"}, "Build a symmetry before cutting it away")
            return {"CANCELLED"}

        scene = context.scene
        operators = _operators_of_built(context, molecule, tag)
        kept = assembly_core.cutaway_operators(
            molecule, operators,
            normal=tuple(self.normal if self.properties.is_property_set('normal')
                         else getattr(scene, "pb_cutaway_normal", (0.0, -1.0, 0.0))),
            offset=(self.offset if self.properties.is_property_set('offset')
                    else getattr(scene, "pb_cutaway_offset", 0.0)))

        if not kept:
            self.report({"WARNING"}, "That cut removes the whole assembly")
            return {"CANCELLED"}

        if not assembly_core.replace_operators(molecule, kept):
            self.report({"ERROR"}, "Could not apply the cutaway")
            return {"CANCELLED"}

        self.report({"INFO"},
                    f"Cut away {len(operators) - len(kept)} of {len(operators)} copies")
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_clear_assembly(Operator):
    """Drop the assembly copies, leaving the deposited asymmetric unit"""

    bl_idname = "molecule.clear_assembly"
    bl_label = "Clear Assembly"
    bl_description = (
        "Remove the symmetry copies and show only the asymmetric unit as "
        "deposited")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        molecule_id = self.molecule_id or _active_molecule_id(context)
        molecule = _molecule(molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        if not assembly_core.clear_assembly(molecule):
            self.report({"INFO"}, "No assembly was built")
            return {"CANCELLED"}

        refresh_symmetry_axes(context, molecule)
        self.report({"INFO"}, "Assembly cleared")
        _set_picker(context, assembly_core.ASYMMETRIC_UNIT_ID)
        _refresh(context)
        return {"FINISHED"}


def _operators_of_built(context, molecule, tag):
    """Rebuild the operator list behind whatever is currently built.

    The tag and recorded build parameters belong to this assembly. Scene
    defaults are only a fallback for older builds with no saved parameters.

    Goes through ``symmetry_bend`` for the same reason the build does: a bent
    filament that was *built* one way and *measured* another would cut away
    and draw axes for a straight filament nobody can see.
    """
    from ..core import symmetry_bend

    tag = str(tag)
    if tag.startswith("generated:"):
        built = built_symmetry_settings(context.scene, molecule)
        return symmetry_bend.build_operators(
            molecule,
            tag.split(":", 1)[1],
            order=built["order"], count=built["count"],
            rise=built["rise"], twist=built["twist"], axis=built["axis"],
            **symmetry_builder.lattice_settings(built),
        )
    return assembly_core._operators_for(molecule, tag)


def refresh_symmetry_axes(context, molecule) -> None:
    """Bring axes that are being shown back in line with what is built.

    Axes are objects of their own, so a rebuild leaves them describing the
    symmetry before it and a clear leaves them describing nothing - and they
    are switched off from the assembly's own dialog, which a cleared assembly
    no longer has.
    """
    from ..core import symmetry_axes

    if not symmetry_axes.symmetry_axis_objects(molecule):
        return
    tag = assembly_core.built_assembly_id(molecule)
    operators = _operators_of_built(context, molecule, tag) if tag else []
    if operators:
        symmetry_axes.show_symmetry_axes(molecule, operators)
    else:
        symmetry_axes.clear_symmetry_axes(molecule)


def _filtered(context, molecule, operators):
    """Apply the panel's range and contact limits. 0 means "no limit"."""
    scene = context.scene
    range_limit = getattr(scene, "pb_symmetry_range", 0.0) or None
    contact = getattr(scene, "pb_symmetry_contact", 0.0) or None
    if range_limit is None and contact is None:
        return list(operators)
    return assembly_core.filter_operators(
        molecule, operators, range_limit=range_limit, contact_distance=contact)


def _refresh(context):
    from ..utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(context)
    for area in getattr(context.screen, "areas", []):
        area.tag_redraw()


CLASSES = (
    MOLECULE_PB_OT_build_assembly,
    MOLECULE_PB_OT_build_symmetry,
    MOLECULE_PB_OT_toggle_symmetry_axes,
    MOLECULE_PB_OT_realize_copies,
    MOLECULE_PB_OT_cutaway,
    MOLECULE_PB_OT_clear_assembly,
)
