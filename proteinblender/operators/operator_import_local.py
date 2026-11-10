"""Local file import operator for ProteinBlender.

This module opens protein structure files from the local filesystem by every
route Blender offers: the Import Local File button, File > Import, and
dragging files onto the Blender window.
"""

import os
import logging
from typing import List, Set
import bpy
from bpy.types import FileHandler, Operator, OperatorFileListElement
from bpy.props import CollectionProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from ..core import conformation_library
from ..utils.scene_manager import ProteinBlenderScene
from .conformation_library import MODEL_INTERPRETATIONS

logger = logging.getLogger(__name__)

# What the structure reader accepts (``molecularnodes...parse``). RCSB serves
# biological assemblies as ``1abc.pdb1``, ``1abc.pdb2``, ... A handler matches
# exact suffixes, so the numbered family is spelled out up to .pdb30. Blender
# keeps only about 255 characters of ``bl_file_extensions`` (a longer list is
# silently cut: .pdb99 stopped matching), so the whole list must stay under that.
_FORMATS = ('.pdb', '.ent', '.cif', '.mmcif', '.bcif', '.pdbx')
_ASSEMBLIES = tuple(f'.pdb{number}' for number in range(1, 31))
_STRUCTURE = (*_FORMATS, *_ASSEMBLIES)

# The file browser lists these (a glob, so it also covers .pdb10 and up and
# compressed files). A file handler matches only the final extension, so
# ``.pdb.gz`` cannot be claimed without claiming every .gz; compressed files
# are opened from the browser (button or File > Import), not by dropping.
BROWSER_FILTER = "*.pdb;*.pdb[0-9]*;*.ent;*.cif;*.mmcif;*.bcif;*.pdbx;*.gz"
DROP_EXTENSIONS = _STRUCTURE


def identifier_from_filename(filename: str) -> str:
    """``1abc.pdb`` -> ``1abc``, ``1ABC.pdb1.gz`` -> ``1ABC``, ``a.b.cif`` -> ``a.b``."""
    name = os.path.basename(filename)
    stem = name[:-3] if name.lower().endswith('.gz') else name
    for extension in _STRUCTURE:
        if stem.lower().endswith(extension):
            stem = stem[:-len(extension)]
            break
    else:
        stem = os.path.splitext(stem)[0]
    return stem or name


class MOLECULE_OT_import_local(Operator, ImportHelper):
    """Import one or more protein structure files from the local filesystem."""
    bl_idname = "molecule.import_local"
    # Also the file browser's confirm button, which cut a longer label short.
    bl_label = "Import Structure"
    bl_description = "Import a protein structure file (PDB, CIF, etc.) from your local filesystem"
    bl_options = {'REGISTER', 'UNDO'}
    # Not remembered between imports: a choice made for one file (say Assembly
    # copies for an MD snapshot) must not silently apply to the next one.
    model_interpretation: EnumProperty(
        name='Multiple models', items=MODEL_INTERPRETATIONS, options={'SKIP_SAVE'})

    # File browser properties
    filename_ext = ".pdb"
    filter_glob: StringProperty(
        default=BROWSER_FILTER,
        options={'HIDDEN'},
        description="File types to filter in the file browser"
    )
    # Set by the file browser when several files are selected, and by Blender
    # when files are dropped on the window. Skipped on save so a previous
    # import's files are never replayed.
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    files: CollectionProperty(type=OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    identifier_override: StringProperty(
        options={'HIDDEN'},
        description="Optional stable identifier for scripted public imports",
    )

    def draw(self, context):
        # The file browser's side panel is narrow: split beside its value,
        # "Multiple models" was cut to "Multiple mod...". A heading over the
        # choices, each a full-width button, keeps every word readable.
        layout = self.layout
        layout.use_property_split = False
        column = layout.column(align=True)
        column.label(text="Multiple models in the file")
        column.prop(self, "model_interpretation", expand=True)

    def invoke(self, context, event):
        # Dropped files arrive already chosen. Only ask when there are none.
        if self.files:
            return self.execute(context)
        return super().invoke(context, event)

    def _make_morphset(self, context, identifier) -> None:
        """Group a states import into a Morphset, as Create Morphset would.

        Only for an explicit "States for Morphsets": that choice says the
        models are a morph to animate. A file Detect from file reads as states
        (an NMR ensemble) is left alone, as the same structure fetched by PDB
        ID is, so its chains can still be split before they are grouped.
        """
        from ..core import model_morphsets
        molecule = ProteinBlenderScene.get_instance().molecules.get(identifier)
        if molecule is None or len(molecule.object.pb_conformations.states) < 2:
            return
        ids = [uid for uid, domain in molecule.domains.items()
               if not model_morphsets.member_issue(context, molecule, domain)]
        try:
            model_morphsets.create(
                context, f'{getattr(molecule, "name", identifier)} conformations',
                identifier, ids)
        except ValueError as exc:
            # The protein imported; only the grouping failed. Say why.
            self.report({'WARNING'}, f"{identifier}: imported, but no Morphset was made: {exc}")

    def _paths(self) -> List[str]:
        if self.files:
            return [os.path.join(self.directory, item.name) for item in self.files]
        return [self.filepath]

    def execute(self, context) -> Set[str]:
        """Import every selected file; one unreadable file does not stop the rest.

        Every unreadable file is reported as an error, so a script (where Blender
        raises on any error report) sees RuntimeError even when other files were
        imported; check the scene for what landed.

        Returns:
            'FINISHED' if at least one file was imported, otherwise 'CANCELLED'.
        """
        paths = self._paths()
        if self.identifier_override and len(paths) > 1:
            self.report({'ERROR'}, "identifier_override names one protein, but several files were given")
            return {'CANCELLED'}
        manager = ProteinBlenderScene.get_instance()
        imported: List[str] = []
        problems: List[str] = []

        for filepath in paths:
            filename = os.path.basename(filepath)
            if not os.path.exists(filepath):
                problems.append(f"File not found: {filepath}")
                continue

            if self.identifier_override and len(paths) == 1:
                identifier = self.identifier_override
                if identifier in manager.molecules:
                    problems.append(f"A protein named '{identifier}' is already loaded")
                    continue
            else:
                # Importing the same file again must add a second protein,
                # never replace the first one's wrapper.
                identifier = manager.free_identifier(identifier_from_filename(filename))

            interpretation = self.model_interpretation
            if (interpretation == 'AUTO'
                    and conformation_library.models_say_nothing(filepath)):
                # A morph or trajectory saved from ChimeraX: several models
                # and no word on what they are. Read it as the states it
                # nearly always is, Morphset and all, rather than refuse it.
                interpretation = 'CONFORMATIONS'
            try:
                success = manager.import_molecule_from_file(
                    filepath, identifier, interpretation)
            except Exception as e:
                logger.error(f"Error importing file {filepath}: {e}")
                problems.append(f"{filename}: {e}")
                continue
            if not success:
                problems.append(f"Failed to import {filepath}")
                continue
            imported.append(identifier)
            if interpretation == 'CONFORMATIONS':
                self._make_morphset(context, identifier)

        if imported:
            self.report({'INFO'}, f"Successfully imported {', '.join(imported)}")
        for problem in problems:
            self.report({'ERROR'}, problem)
        return {'FINISHED'} if imported else {'CANCELLED'}


class MOLECULE_FH_import_structure(FileHandler):
    """Lets structure files be dragged onto Blender, as with any other importer."""
    bl_idname = "MOLECULE_FH_import_structure"
    bl_label = "Protein structure files"
    bl_import_operator = MOLECULE_OT_import_local.bl_idname
    bl_file_extensions = ";".join(DROP_EXTENSIONS)

    @classmethod
    def poll_drop(cls, context):
        # Anywhere in the window except a file browser, where a drop navigates.
        return context.area is None or context.area.type != 'FILE_BROWSER'


def menu_func_import(self, context):
    self.layout.operator(
        MOLECULE_OT_import_local.bl_idname, text="Protein Structure (.pdb, .cif, .mmcif)")


def register_menu() -> None:
    """Add the entry to File > Import (once, however often this is called)."""
    unregister_menu()
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister_menu() -> None:
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    except ValueError:
        pass
