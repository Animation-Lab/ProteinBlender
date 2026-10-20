"""The Cytoskeleton builder: a named filament, of a length, with a path to bend.

The Assembly dialog can build any filament from a structure and its helical
numbers, which is the right tool for someone who has both. This is for someone
who wants an actin filament: it brings the subunit (``core.filament_presets``),
knows the numbers, and asks only for how long.

What it makes is an ordinary generated assembly - the same instanced copies,
built by the same :func:`build_generated_symmetry` - so there is nothing here
to edit it with. Its row in the PB Outliner opens the Assembly dialog on it
like any other, with the length, the strands and the bend all there to change.
It starts straight, drawn as a surface, with a path whose control nodes bend
it into whatever shape is wanted.
"""

import logging

import bpy
from bpy.props import EnumProperty, FloatProperty
from bpy.types import Operator

from ..core import filament_presets, symmetry_bend, symmetry_builder
from ..utils.scene_manager import (
    ProteinBlenderScene,
    build_outliner_hierarchy,
    delete_molecule_cascade,
)
from .assembly_operators import SYMMETRY_SETTINGS, build_generated_symmetry

logger = logging.getLogger(__name__)

ANGSTROM_PER_NM = 10.0

_PRESET_ITEMS = tuple((preset.id, preset.label, preset.description)
                      for preset in filament_presets.PRESETS)


def subunits_for(preset, length: float) -> int:
    """Subunits along each strand for ``length`` Angstrom of this filament."""
    return min(preset.count_for_length(length), symmetry_builder.MAX_COUNT)


#: How a new filament is drawn. A filament is read by its outline - the
#: grooves of actin, the protofilaments of a tube - which a surface shows and
#: a cartoon of hundreds of subunits buries.
FILAMENT_STYLE = "surface"


def show_as(molecule, style: str) -> None:
    """Draw every part of a molecule in ``style``, as Visual Set-up would."""
    from ..core import visual_style

    objects = [molecule.object] if molecule.object is not None else []
    objects.extend(domain.object for domain in molecule.domains.values()
                   if domain.object is not None)
    for obj in objects:
        visual_style.apply_style_to_object(obj, style)
    # The model as well as the node trees: a domain made on it later, and a
    # save and load, take the style from here.
    molecule.style = style
    for domain in molecule.domains.values():
        domain.style = style


def build_filament(context, preset, length: float):
    """Import a preset's subunit and build ``length`` Angstrom of its filament.

    Returns ``(molecule, message)``; the molecule is ``None`` if nothing was
    built, and then nothing is left behind either.
    """
    manager = ProteinBlenderScene.get_instance()
    # Its name in the outliner, so "Microtubule" rather than a file's stem.
    identifier = manager.free_identifier(preset.label)
    if not manager.import_molecule_from_file(
            filament_presets.structure_path(preset), identifier):
        return None, f"Could not load the {preset.label.lower()} subunit"
    molecule = manager.molecules.get(identifier)
    show_as(molecule, FILAMENT_STYLE)

    # Every setting the Assembly dialog has, so that it can reopen on this
    # filament as it would on one it built itself.
    settings = {key: default for key, _prop, default in SYMMETRY_SETTINGS}
    settings.update(preset.settings(subunits_for(preset, length)))
    lattice = symmetry_builder.lattice_settings(settings)
    settings.update(lattice)
    settings["source_item_id"] = molecule.identifier

    # The path goes down first: the build lays the filament along whatever
    # path it finds. It starts straight, down the filament's own axis.
    if symmetry_bend.add_bend(
            molecule, count=settings["count"], rise=settings["rise"],
            axis=settings["axis"], strands=lattice["strands"],
            stagger=lattice["stagger"]) is None:
        logger.warning("%s was built without a bend path", identifier)

    ok, message = build_generated_symmetry(molecule, settings)
    if not ok:
        delete_molecule_cascade(context, identifier)
        return None, message
    return molecule, message


class MOLECULE_PB_OT_build_filament(Operator):
    """Build an actin filament or a microtubule of a chosen length"""

    bl_idname = "molecule.build_filament"
    bl_label = "Create New Cytoskeleton"
    bl_description = (
        "Build an actin filament or a microtubule: choose how long, and it "
        "comes straight, with a path whose control nodes bend it")
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        name="Cytoskeleton",
        description="Which cytoskeletal filament to build",
        items=_PRESET_ITEMS,
    )
    length: FloatProperty(
        name="Length",
        description="How long to make the filament, in nanometres",
        default=100.0, min=1.0, soft_max=2000.0, max=20000.0, precision=1,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def check(self, context):
        # The summary line follows the filament and the length.
        return True

    def draw(self, context):
        layout = self.layout
        preset = filament_presets.get(self.preset)

        # Label beside field on every row, so the two line up as one form.
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "preset")
        layout.prop(self, "length", text="Length (nm)")
        if preset is not None:
            summary = layout.row()
            summary.enabled = False
            summary.alignment = 'RIGHT'
            summary.label(text=self._summary(preset))

        layout.separator(factor=0.5)

        note = layout.column(align=True)
        note.enabled = False
        note.label(text="Drag its control nodes to bend it", icon='INFO')
        note.label(text="Edit it from its assembly row in the PB Outliner",
                   icon='BLANK1')

    def _summary(self, preset) -> str:
        count = subunits_for(preset, self.length * ANGSTROM_PER_NM)
        built = preset.length(count) / ANGSTROM_PER_NM
        if preset.strands > 1:
            return (f"{preset.strands} strands of {count} - "
                    f"{preset.subunit_total(count)} copies, {built:g} nm")
        return f"{count} subunits, {built:g} nm"

    def execute(self, context):
        preset = filament_presets.get(self.preset)
        if preset is None:
            self.report({"ERROR"}, f"There is no filament called {self.preset}")
            return {"CANCELLED"}

        molecule, message = build_filament(
            context, preset, self.length * ANGSTROM_PER_NM)
        if molecule is None:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        build_outliner_hierarchy(context)
        for area in getattr(context.screen, "areas", []):
            area.tag_redraw()
        self.report({"INFO"}, f"Built {preset.label.lower()}: {message}")
        return {"FINISHED"}


CLASSES = (
    MOLECULE_PB_OT_build_filament,
)
