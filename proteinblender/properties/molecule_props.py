import bpy
from bpy.props import (BoolProperty, StringProperty, CollectionProperty, 
                      IntProperty, EnumProperty)
from bpy.types import PropertyGroup
from ..utils.molecularnodes.style import STYLE_ITEMS
from ..utils.scene_manager import ProteinBlenderScene
from ..core.domain import Domain

class ChainSelectionItem(PropertyGroup):
    """Represents a selectable chain"""
    chain_id: StringProperty(
        name="Chain ID",
        description="ID of the protein chain",
        default=""
    )
    is_selected: BoolProperty(
        name="Selected",
        description="Whether this chain is currently selected",
        default=False
    )

def get_chain_mapping_from_str(mapping_str):
    """Convert stored string mapping back to dictionary"""
    if not mapping_str:
        return {}
    mapping = {}
    for pair in mapping_str.split(","):
        if ":" in pair:
            k, v = pair.split(":")
            mapping[int(k)] = v
    return mapping

def get_chain_items(self, context):
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
    
    if molecule and molecule.object and "chain_id" in molecule.object.data.attributes:
        chain_attr = molecule.object.data.attributes["chain_id"]
        chain_ids = sorted({value.value for value in chain_attr.data})
        
        # Try to get mapping from custom property
        mapping_str = molecule.object.data.get("chain_mapping_str", "")
        mapping = get_chain_mapping_from_str(mapping_str)
        
        if mapping:
            return [(str(chain_id), 
                    f"Chain {mapping[chain_id]}", 
                    mapping[chain_id]) 
                   for chain_id in chain_ids]
        else:
            # Fallback to numeric IDs if mapping not available
            return [(str(chain_id), 
                    f"Chain {chr(65 + chain_id)}", 
                    chr(65 + chain_id)) 
                   for chain_id in chain_ids]
    return []

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
    selected_chain_for_domain: EnumProperty(
        name="Chain",
        description="Select chain for domain creation",
        items=get_chain_items
    )
    
    domain_start: IntProperty(
        name="Start",
        description="Starting residue number for domain",
        default=1,
        min=1,
        update=lambda self, context: self.ensure_valid_domain_range(context, "start")
    )
    
    domain_end: IntProperty(
        name="End",
        description="Ending residue number for domain",
        default=1,
        min=1,
        update=lambda self, context: self.ensure_valid_domain_range(context, "end")
    )
    
    domains: CollectionProperty(type=Domain)
    
    def ensure_valid_domain_range(self, context, changed_prop):
        if changed_prop == "start" and self.domain_end < self.domain_start:
            self.domain_end = self.domain_start
        elif changed_prop == "end" and self.domain_start > self.domain_end:
            self.domain_start = self.domain_end

def get_max_residue_for_chain(molecule, chain_id):
    """Get the maximum residue number for a given chain"""
    if not (molecule and molecule.object and 
            "residue_id" in molecule.object.data.attributes and 
            "chain_id" in molecule.object.data.attributes):
        return 1
        
    res_attr = molecule.object.data.attributes["residue_id"]
    chain_attr = molecule.object.data.attributes["chain_id"]
    
    # Get all residue IDs for the selected chain
    chain_id_int = int(chain_id)
    residue_ids = [res.value for i, res in enumerate(res_attr.data) 
                   if chain_attr.data[i].value == chain_id_int]
    
    return max(residue_ids) if residue_ids else 1

def ensure_valid_scene_domain_range(self, context, changed_prop):
    if changed_prop == "start" and self.domain_end < self.domain_start:
        self.domain_end = self.domain_start
    elif changed_prop == "end" and self.domain_start > self.domain_end:
        self.domain_start = self.domain_end

def register():
    # Register Domain first since other classes might depend on it
    bpy.utils.register_class(ChainSelectionItem)
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
    bpy.types.Scene.domain_start = IntProperty(
        name="Start",
        description="Starting residue number for domain",
        default=1,
        min=1,
        update=lambda self, context: ensure_valid_scene_domain_range(self, context, "start")
    )
    bpy.types.Scene.domain_end = IntProperty(
        name="End",
        description="Ending residue number for domain",
        default=1,
        min=1,
        update=lambda self, context: ensure_valid_scene_domain_range(self, context, "end")
    )
    bpy.types.Scene.selected_chain = StringProperty(
        name="Selected Chain",
        description="Currently selected chain for domain creation",
        default=""
    )
    bpy.types.Scene.molecule_style = EnumProperty(
        name="Style",
        description="Visualization style for the molecule",
        items=STYLE_ITEMS,
        default="surface"
    )
    bpy.types.Scene.chain_selections = CollectionProperty(type=ChainSelectionItem)
    bpy.types.Scene.selected_chain_for_domain = EnumProperty(
        name="Chain",
        description="Select chain for domain creation",
        items=get_chain_items
    )

def unregister():
    del bpy.types.Scene.chain_selections
    del bpy.types.Scene.molecule_style
    del bpy.types.Scene.edit_molecule_identifier
    del bpy.types.Scene.show_molecule_edit_panel
    del bpy.types.Scene.selected_molecule_id
    del bpy.types.Scene.molecule_list_index
    del bpy.types.Scene.molecule_list_items
    
    bpy.utils.unregister_class(MoleculeListItem)
    bpy.utils.unregister_class(ChainSelectionItem) 