import bpy
from bpy.props import (BoolProperty, StringProperty, CollectionProperty, 
                      IntProperty, EnumProperty)
from bpy.types import PropertyGroup
from ..utils.molecularnodes.style import STYLE_ITEMS

class MoleculeListItem(PropertyGroup):
    """Group of properties representing a molecule in the UI list."""
    identifier: StringProperty(
        name="Identifier",
        description="PDB ID or filename of the molecule",
        default=""
    )
    style: EnumProperty(
        name="Style",
        description="Visualization style for the molecule",
        items=STYLE_ITEMS,
        default="cartoon"
    )

def register():
    # Register the PropertyGroup class first
    bpy.utils.register_class(MoleculeListItem)
    
    # Then register the properties
    bpy.types.Scene.molecule_list_items = CollectionProperty(type=MoleculeListItem)
    bpy.types.Scene.molecule_list_index = IntProperty()
    bpy.types.Scene.selected_molecule_id = StringProperty()
    bpy.types.Scene.show_molecule_edit_panel = BoolProperty(default=False)
    bpy.types.Scene.edit_molecule_identifier = StringProperty(
        name="Identifier",
        description="New identifier for the molecule",
        default=""
    )
    bpy.types.Scene.molecule_style = EnumProperty(
        name="Style",
        description="Visualization style for the molecule",
        items=STYLE_ITEMS,
        default="cartoon"
    )

def unregister():
    # Remove properties
    del bpy.types.Scene.show_molecule_edit_panel
    del bpy.types.Scene.selected_molecule_id
    del bpy.types.Scene.molecule_list_index
    del bpy.types.Scene.molecule_list_items
    del bpy.types.Scene.edit_molecule_identifier
    del bpy.types.Scene.molecule_style
    
    # Unregister the PropertyGroup class last
    bpy.utils.unregister_class(MoleculeListItem) 