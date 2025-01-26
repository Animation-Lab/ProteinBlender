# protein_workspace/panels/__init__.py
from .panel_import_protein import register_panel_import_protein, unregister_panel_import_protein
from .molecule_list_panel import register_molecule_list_panel, unregister_molecule_list_panel
from .molecule_edit_panel import register_molecule_edit_panel, unregister_molecule_edit_panel
from ..properties.molecule_props import register_properties, unregister_properties
from ..utils.molecularnodes.addon import register as register_mn, unregister as unregister_mn

def register():
    # Register Molecular Nodes first
    register_mn()
    
    # Then register our properties and panels
    register_properties()
    register_panel_import_protein()
    register_molecule_list_panel()
    register_molecule_edit_panel()

def unregister():
    unregister_molecule_edit_panel()
    unregister_molecule_list_panel()
    unregister_panel_import_protein()
    unregister_properties()
    unregister_mn()