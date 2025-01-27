import bpy
from bpy.props import BoolProperty, StringProperty, CollectionProperty, IntProperty
from bpy.types import PropertyGroup

class MoleculeListItem(PropertyGroup):
    """Group of properties representing a molecule in the UI list."""
    identifier: StringProperty(
        name="Identifier",
        description="PDB ID or filename of the molecule",
        default=""
    )

def register():
    # Register the PropertyGroup class first
    bpy.utils.register_class(MoleculeListItem)
    
    # Then register the properties
    bpy.types.Scene.molecule_list_items = CollectionProperty(type=MoleculeListItem)
    bpy.types.Scene.molecule_list_index = IntProperty()
    bpy.types.Scene.selected_molecule_id = StringProperty()
    bpy.types.Scene.show_molecule_edit_panel = BoolProperty(default=False)

def unregister():
    # Remove properties
    del bpy.types.Scene.show_molecule_edit_panel
    del bpy.types.Scene.selected_molecule_id
    del bpy.types.Scene.molecule_list_index
    del bpy.types.Scene.molecule_list_items
    
    # Unregister the PropertyGroup class last
    bpy.utils.unregister_class(MoleculeListItem) 