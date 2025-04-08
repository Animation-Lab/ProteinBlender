import bpy
from bpy.props import (BoolProperty, StringProperty, CollectionProperty, 
                      IntProperty, EnumProperty, FloatVectorProperty, PointerProperty)
from bpy.types import PropertyGroup
from ..utils.molecularnodes.style import STYLE_ITEMS
from ..utils.scene_manager import ProteinBlenderScene
from ..core.domain import Domain
from ..utils.molecularnodes.blender import nodes

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
        
        # Use the mapping stored in the molecule wrapper
        if molecule.chain_mapping:
            return [(str(chain_id), 
                    f"Chain {molecule.chain_mapping.get(chain_id, chr(65 + chain_id))}", 
                    molecule.chain_mapping.get(chain_id, chr(65 + chain_id))) 
                   for chain_id in chain_ids]
        else:
            # Fallback to numeric IDs if mapping not available
            return [(str(chain_id), 
                    f"Chain {chr(65 + chain_id)}", 
                    chr(65 + chain_id)) 
                   for chain_id in chain_ids]
    return []

class DomainTransformData(PropertyGroup):
    """Stores transform data for a domain in a pose"""
    domain_id: StringProperty(name="Domain ID", description="ID of the domain")
    location: FloatVectorProperty(name="Location", size=3)
    rotation: FloatVectorProperty(name="Rotation", size=3, subtype='EULER')
    scale: FloatVectorProperty(name="Scale", size=3, default=(1, 1, 1))

class MoleculePose(PropertyGroup):
    """Group of properties representing a saved pose for a molecule"""
    name: StringProperty(name="Pose Name", description="Name of this pose", default="New Pose")
    
    # Add properties for the main protein object transform
    has_protein_transform: BoolProperty(name="Has Protein Transform", default=False)
    protein_location: FloatVectorProperty(name="Protein Location", size=3)
    protein_rotation: FloatVectorProperty(name="Protein Rotation", size=3, subtype='EULER')
    protein_scale: FloatVectorProperty(name="Protein Scale", size=3, default=(1, 1, 1))
    
    # Collection of domain transforms
    domain_transforms: CollectionProperty(type=DomainTransformData)
    
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
        items=get_chain_items,
        update=lambda self, context: self.ensure_valid_domain_range(context, "chain")
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
        default=9999,
        min=1,
        update=lambda self, context: self.ensure_valid_domain_range(context, "end")
    )
    
    domains: CollectionProperty(type=Domain)
    
    poses: CollectionProperty(type=MoleculePose, description="Saved poses for this molecule")
    active_pose_index: IntProperty(name="Active Pose", default=0, min=0)
    
    def get_chain_range(self, context):
        """Get the range for the currently selected chain"""
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        
        if molecule and self.selected_chain_for_domain != "NONE":
            chain_ranges = molecule.chain_residue_ranges
            if self.selected_chain_for_domain in chain_ranges:
                return chain_ranges[self.selected_chain_for_domain]
        return (1, 999999)  # fallback range

    def ensure_valid_domain_range(self, context, changed_prop):
        """Ensure domain range is valid and within chain's range"""
        # Get the valid range for the selected chain
        min_res, max_res = self.get_chain_range(context)
        
        # Ensure start is within valid range
        self.domain_start = max(min(self.domain_start, max_res), min_res)
        
        # For end, only clamp to max_res if it exceeds max_res
        if self.domain_end > max_res:
            self.domain_end = max_res
        if self.domain_end < min_res:
            self.domain_end = min_res
        
        # Ensure start doesn't exceed end and vice versa
        if changed_prop == "start" and self.domain_end < self.domain_start:
            self.domain_end = self.domain_start
        elif changed_prop == "end" and self.domain_start > self.domain_end:
            self.domain_start = self.domain_end

def get_max_residue_for_chain(molecule, chain_id):
    print(f"Getting max residue for chain: {chain_id}")
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
    """Ensure domain range is valid for the selected chain and update selection"""
    
    # Get the current molecule list item
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
    
    if molecule:
        author_chain_id = molecule.get_author_chain_id(int(context.scene.selected_chain_for_domain))
        min_res, max_res = molecule.chain_residue_ranges[author_chain_id]
        
        if changed_prop == "chain":
            # When chain changes, set domain to full range of new chain
            domain_start = min_res
            domain_end = max_res
        else:
            # First ensure start is within valid range
            domain_start = max(min(self.domain_start, max_res), min_res)
            
            # For end, only clamp to max_res if it exceeds max_res
            domain_end = self.domain_end
            if domain_end > max_res:
                domain_end = max_res
            if domain_end < min_res:
                domain_end = min_res
            
            # Then adjust based on which value changed
            if changed_prop == "start":
                if domain_start > domain_end:
                    domain_end = domain_start
            else:  # changed_prop == "end"
                if domain_end < domain_start:
                    domain_start = domain_end
        
        self['domain_start'] = int(domain_start)
        self['domain_end'] = int(domain_end)

    # Add after existing range validation code
    if context.scene.show_domain_preview:
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        if molecule:
            molecule.update_preview_range(
                context.scene.selected_chain_for_domain,
                self.domain_start,
                self.domain_end
            )

def update_domain_preview(self, context):
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
    
    if molecule:
        molecule.set_preview_visibility(self.show_domain_preview)
        if self.show_domain_preview:
            molecule.update_preview_range(
                context.scene.selected_chain_for_domain,
                context.scene.domain_start,
                context.scene.domain_end
            )

def get_max_residue_for_chain(context):
    return 888

def update_new_domain_range(self, context):
    """Update new domain range when chain is changed"""
    # Get the current molecule
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
    
    if molecule:
        author_chain_id = molecule.get_author_chain_id(int(context.scene.new_domain_chain))
        if author_chain_id in molecule.chain_residue_ranges:
            min_res, max_res = molecule.chain_residue_ranges[author_chain_id]
            # Only set start to min_res, but don't change end unless it's the default value
            self.new_domain_start = min_res
            
            # Only set end to max_res if it's the default value or greater than max_res
            if self.new_domain_end == 9999 or self.new_domain_end > max_res:
                self.new_domain_end = max_res

# Update callback function to connect color picker to material nodes
def update_domain_color(self, context):
    domain_id = self["domain_id"]
    parent_molecule_id = self["parent_molecule_id"]
    
    # Get scene manager and find which domain this object belongs to
    scene_manager = ProteinBlenderScene.get_instance()
    print(f"Updating domain color for domain: {domain_id} in molecule: {parent_molecule_id}")
    # Find which molecule and domain this object belongs to
    for molecule_id, molecule in scene_manager.molecules.items():
        print(f"Checking molecule: {molecule_id}")
        if parent_molecule_id.startswith(molecule_id):
            print(f"Updating domain color for domain: {domain_id} in molecule: {molecule_id}")
            molecule.update_domain_color(domain_id, self.domain_color)
            return

def register():
    """Register molecule properties"""
    # Try to unregister first if already registered
    try:
        unregister()
    except Exception:
        pass
        
    # Register Domain first since other classes might depend on it
    bpy.utils.register_class(Domain)
    bpy.utils.register_class(ChainSelectionItem)
    bpy.utils.register_class(DomainTransformData)
    bpy.utils.register_class(MoleculePose)
    bpy.utils.register_class(MoleculeListItem)
    
    # Register temporary properties needed for domain editing
    bpy.types.Scene.temp_domain_start = IntProperty(
        name="Start",
        description="Temporary start residue for domain editing",
        default=1,
        min=1
    )
    
    bpy.types.Scene.temp_domain_end = IntProperty(
        name="End",
        description="Temporary end residue for domain editing",
        default=9999,
        min=1
    )
    
    bpy.types.Scene.temp_domain_id = StringProperty(
        name="Domain ID",
        description="Temporary storage for domain ID in popup menus",
        default=""
    )
    
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
        default=9999,
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
    
    # Properties for creating new domains
    bpy.types.Scene.new_domain_chain = EnumProperty(
        name="Chain",
        description="Select chain for new domain creation",
        items=get_chain_items,
        update=update_new_domain_range
    )
    bpy.types.Scene.new_domain_start = IntProperty(
        name="Start",
        description="Starting residue number for new domain",
        default=1,
        min=1
    )
    bpy.types.Scene.new_domain_end = IntProperty(
        name="End",
        description="Ending residue number for new domain",
        default=9999,
        min=1
    )
    
    # Temporary property for domain color
    bpy.types.Scene.temp_domain_color = FloatVectorProperty(
        name="Temp Domain Color",
        description="Temporary color for domain editing",
        subtype='COLOR',
        size=4,
        min=0.0, max=1.0,
        default=(0.8, 0.1, 0.8, 1.0)  # Default to purple
    )
    
    # Properties for editing existing domains
    bpy.types.Scene.selected_chain_for_domain = EnumProperty(
        name="Chain",
        description="Select chain for domain editing",
        items=get_chain_items,
        update=lambda self, context: ensure_valid_scene_domain_range(self, context, "chain")
    )
    bpy.types.Scene.show_domain_preview = BoolProperty(
        name="Show Domain Selection",
        description="Show preview of domain selection",
        default=False,
        update=lambda self, context: update_domain_preview(self, context)
    )

    bpy.types.Object.domain_color = FloatVectorProperty(
        name="Domain Color",
        subtype='COLOR',
        size=4,  # RGBA
        min=0.0, max=1.0,
        default=(0.8, 0.1, 0.8, 1.0),  # Default purple to match DomainDefinition
        description="Color of the domain",
        update=lambda self, context: update_domain_color(self, context)
    )

def unregister():
    """Unregister molecule properties"""
    
    # Safely unregister classes
    try:
        bpy.utils.unregister_class(MoleculeListItem)
    except Exception:
        pass
    
    try:
        bpy.utils.unregister_class(ChainSelectionItem)
    except Exception:
        pass
    
    try:
        bpy.utils.unregister_class(DomainTransformData)
    except Exception:
        pass
    
    try:
        bpy.utils.unregister_class(MoleculePose)
    except Exception:
        pass
    
    try:
        bpy.utils.unregister_class(Domain)
    except Exception:
        pass
    
    # Safely unregister properties with checks
    if hasattr(bpy.types.Scene, "chain_selections"):
        del bpy.types.Scene.chain_selections
    if hasattr(bpy.types.Scene, "molecule_style"):
        del bpy.types.Scene.molecule_style
    if hasattr(bpy.types.Scene, "edit_molecule_identifier"):
        del bpy.types.Scene.edit_molecule_identifier
    if hasattr(bpy.types.Scene, "show_molecule_edit_panel"):
        del bpy.types.Scene.show_molecule_edit_panel
    if hasattr(bpy.types.Scene, "selected_molecule_id"):
        del bpy.types.Scene.selected_molecule_id
    if hasattr(bpy.types.Scene, "molecule_list_index"):
        del bpy.types.Scene.molecule_list_index
    if hasattr(bpy.types.Scene, "molecule_list_items"):
        del bpy.types.Scene.molecule_list_items
    
    # Unregister new domain creation properties
    if hasattr(bpy.types.Scene, "new_domain_chain"):
        del bpy.types.Scene.new_domain_chain
    if hasattr(bpy.types.Scene, "new_domain_start"):
        del bpy.types.Scene.new_domain_start
    if hasattr(bpy.types.Scene, "new_domain_end"):
        del bpy.types.Scene.new_domain_end
    
    # Unregister temporary domain editing properties
    if hasattr(bpy.types.Scene, "temp_domain_start"):
        del bpy.types.Scene.temp_domain_start
    if hasattr(bpy.types.Scene, "temp_domain_end"):
        del bpy.types.Scene.temp_domain_end
    if hasattr(bpy.types.Scene, "temp_domain_id"):
        del bpy.types.Scene.temp_domain_id
    if hasattr(bpy.types.Object, "domain_color"):
        del bpy.types.Object.domain_color
    