"""Molecule properties module for ProteinBlender.

This module defines all the property groups and registration functions
for molecule-related data in the ProteinBlender addon.
"""

import bpy
from bpy.props import (BoolProperty, StringProperty, CollectionProperty, 
                      IntProperty, EnumProperty, FloatVectorProperty, FloatProperty, PointerProperty)
from bpy.types import PropertyGroup

from ..utils.molecularnodes.style import STYLE_ITEMS
from ..utils.scene_manager import ProteinBlenderScene
from ..core.domain import Domain

# Constants
DEFAULT_DOMAIN_COLOR = (0.8, 0.1, 0.8, 1.0)  # Purple
DEFAULT_DOMAIN_END = 9999
FALLBACK_RESIDUE_RANGE = (1, 999999)

# Delayed import for ProteinBlenderScene to avoid circular dependencies at startup
# This module (molecule_props.py) is imported by many others, including scene_manager.py
_scene_manager_module = None

def get_protein_blender_scene():
    global _scene_manager_module
    if _scene_manager_module is None:
        from ..utils import scene_manager as sm # Adjusted import path
        _scene_manager_module = sm
    return _scene_manager_module.ProteinBlenderScene.get_instance()

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
    
class MoleculeKeyframe(PropertyGroup):
    """Group of properties representing a saved keyframe for a molecule"""
    name: StringProperty(name="Keyframe Name", description="Name of this keyframe", default="")
    frame: IntProperty(name="Frame Number", description="Frame number of the keyframe", default=0)
    # Brownian motion toggle
    use_brownian_motion: BoolProperty(
        name="Use Brownian Motion", 
        description="Use Brownian motion for animation to this keyframe from the previous keyframe",
        default=True,
        update=lambda self, context: self.recompute_brownian_motion(context)
    )
    # Brownian motion parameters
    intensity: FloatProperty(name="Intensity", description="Max random offset magnitude", default=0.1, min=0.0)
    frequency: FloatProperty(name="Frequency", description="Frequency of motion", default=1.0, min=0.0)
    seed: IntProperty(name="Seed", description="Random seed for reproducibility", default=0, min=0)
    resolution: IntProperty(name="Resolution", description="Frame step for Brownian bake", default=1, min=1)
    
    def recompute_brownian_motion(self, context):
        """Recompute the animation path when brownian motion setting changes"""
        # Find the molecule and keyframe index
        scene = context.scene
        scene_manager = get_protein_blender_scene()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            return
            
        # Find this keyframe in the molecule's keyframe list
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                current_idx = -1
                for idx, kf in enumerate(item.keyframes):
                    if kf == self:  # Found the current keyframe
                        current_idx = idx
                        break
                
                if current_idx <= 0:  # First keyframe doesn't have a previous segment
                    return
                    
                # Get the previous keyframe
                prev_kf = item.keyframes[current_idx - 1]
                
                # Clear existing intermediate keyframes between prev and current
                self._clear_intermediate_keyframes(molecule, prev_kf.frame, self.frame)
                
                if self.use_brownian_motion:
                    # Re-bake brownian motion
                    from ..operators.domain_operators import bake_brownian
                    bake_brownian(
                        None, context, molecule,
                        prev_kf.frame, self.frame,
                        self.intensity, self.frequency,
                        self.seed, self.resolution
                    )
                else:
                    # Just use linear interpolation (Blender's default)
                    # Set keyframes at both ends to ensure smooth interpolation
                    # Collect all objects to keyframe: protein + all domain objects
                    objects_to_keyframe = []
                    if molecule.object:
                        objects_to_keyframe.append(molecule.object)
                    
                    # Add all domain objects
                    for domain_id, domain in molecule.domains.items():
                        if domain.object:
                            objects_to_keyframe.append(domain.object)
                    
                    # Keyframe all objects at both frames
                    for obj in objects_to_keyframe:
                        context.scene.frame_set(prev_kf.frame)
                        obj.keyframe_insert(data_path="location", frame=prev_kf.frame)
                        obj.keyframe_insert(data_path="rotation_euler", frame=prev_kf.frame)
                        obj.keyframe_insert(data_path="scale", frame=prev_kf.frame)
                        
                        context.scene.frame_set(self.frame)
                        obj.keyframe_insert(data_path="location", frame=self.frame)
                        obj.keyframe_insert(data_path="rotation_euler", frame=self.frame)
                        obj.keyframe_insert(data_path="scale", frame=self.frame)
                break
    
    def _clear_intermediate_keyframes(self, molecule, start_frame, end_frame):
        """Clear intermediate keyframes between two frames"""
        # Collect all objects to clear keyframes from: protein + all domain objects
        objects_to_clear = []
        if molecule.object:
            objects_to_clear.append(molecule.object)
        
        # Add all domain objects
        for domain_id, domain in molecule.domains.items():
            if domain.object:
                objects_to_clear.append(domain.object)
        
        # Clear keyframes for all objects
        for obj in objects_to_clear:
            if not obj.animation_data or not obj.animation_data.action:
                continue
                
            # Remove keyframes in the range (exclusive of endpoints)
            for fcurve in obj.animation_data.action.fcurves:
                keyframes_to_remove = []
                for kf in fcurve.keyframe_points:
                    if start_frame < kf.co.x < end_frame:
                        keyframes_to_remove.append(kf)
                
                for kf in keyframes_to_remove:
                    fcurve.keyframe_points.remove(kf)

class MoleculeListItem(PropertyGroup):
    """Group of properties representing a molecule in the UI list."""
    identifier: StringProperty(
        name="Identifier",
        description="PDB ID or filename of the molecule",
        default=""
    )
    object_ptr: PointerProperty(
        name="Object",
        description="Pointer to the Blender object for this molecule",
        type=bpy.types.Object,
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
        default=DEFAULT_DOMAIN_END,
        min=1,
        update=lambda self, context: self.ensure_valid_domain_range(context, "end")
    )
    
    domains: CollectionProperty(type=Domain)
    
    poses: CollectionProperty(type=MoleculePose, description="Saved poses for this molecule")
    active_pose_index: IntProperty(name="Active Pose", default=0, min=0)
    keyframes: CollectionProperty(type=MoleculeKeyframe, description="Saved keyframes for this molecule")
    active_keyframe_index: IntProperty(name="Active Keyframe", default=0, min=0)
    
    def get_chain_range(self, context):
        """Get the range for the currently selected chain"""
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        
        if molecule and self.selected_chain_for_domain != "NONE":
            chain_ranges = molecule.chain_residue_ranges
            if self.selected_chain_for_domain in chain_ranges:
                return chain_ranges[self.selected_chain_for_domain]
        return FALLBACK_RESIDUE_RANGE

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
            if self.new_domain_end == DEFAULT_DOMAIN_END or self.new_domain_end > max_res:
                self.new_domain_end = max_res


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
    bpy.utils.register_class(MoleculeKeyframe)
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
        default=DEFAULT_DOMAIN_END,
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
        default=DEFAULT_DOMAIN_END,
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
        default="surface",
        update=update_molecule_style
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
        default=DEFAULT_DOMAIN_END,
        min=1
    )
    
    # Temporary property for domain color
    bpy.types.Scene.temp_domain_color = FloatVectorProperty(
        name="Temp Domain Color",
        description="Temporary color for domain editing",
        subtype='COLOR',
        size=4,
        min=0.0, max=1.0,
        default=DEFAULT_DOMAIN_COLOR
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
        default=DEFAULT_DOMAIN_COLOR,
        description="Color of the domain",
        update=lambda self, context: update_domain_color(self, context)
    )

    # Property to store the active domain being considered for splitting
    bpy.types.Scene.active_splitting_domain_id = StringProperty(
        name="Active Splitting Domain ID",
        description="Internally tracks the domain whose split UI is active",
        default="" # Add a default value
    )

    # Properties for domain splitting UI
    bpy.types.Scene.split_domain_new_start = IntProperty(
        name="New Start",
        description="New starting residue for the split domain",
        default=1,
        min=1, # Broad min, will be effectively constrained by update logic and initial setting
        update=update_split_start
    )
    bpy.types.Scene.split_domain_new_end = IntProperty(
        name="New End",
        description="New ending residue for the split domain",
        default=1,
        min=1, # Broad min, will be effectively constrained by update logic and initial setting
        update=update_split_end
    )

def unregister():
    """Unregister molecule properties."""
    # Safely unregister classes
    classes_to_unregister = [
        MoleculeListItem,
        MoleculeKeyframe,
        ChainSelectionItem,
        DomainTransformData,
        MoleculePose,
        Domain
    ]
    
    for cls in classes_to_unregister:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    
    # Safely unregister properties with checks
    scene_properties = [
        "chain_selections",
        "molecule_style",
        "edit_molecule_identifier",
        "show_molecule_edit_panel",
        "selected_molecule_id",
        "molecule_list_index",
        "molecule_list_items",
        "new_domain_chain",
        "new_domain_start",
        "new_domain_end",
        "temp_domain_start",
        "temp_domain_end",
        "temp_domain_id",
        "temp_domain_color",
        "selected_chain_for_domain",
        "domain_start",
        "domain_end",
        "selected_chain",
        "show_domain_preview",
        "split_domain_new_start",
        "split_domain_new_end",
        "active_splitting_domain_id"
    ]
    
    for prop in scene_properties:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    
    # Unregister object properties
    if hasattr(bpy.types.Object, "domain_color"):
        del bpy.types.Object.domain_color
# --- Update Callbacks for Split Domain Properties ---
def update_split_start(self, context):
    scene = context.scene
    if not scene.selected_molecule_id or not hasattr(scene, 'active_splitting_domain_id') or not scene.active_splitting_domain_id:
        return

    scene_manager = get_protein_blender_scene()
    molecule = scene_manager.molecules.get(scene.selected_molecule_id)
    if not molecule or scene.active_splitting_domain_id not in molecule.domains:
        return
    
    active_domain = molecule.domains[scene.active_splitting_domain_id]
    
    # Clamp start value
    new_start_val = scene.split_domain_new_start # Read once
    clamped_start = max(active_domain.start, new_start_val)
    clamped_start = min(clamped_start, scene.split_domain_new_end - 1) # Must be at least 1 less than end
    clamped_start = min(clamped_start, active_domain.end -1) # Cannot exceed domain end -1

    if scene.split_domain_new_start != clamped_start:
        scene.split_domain_new_start = clamped_start

def update_split_end(self, context):
    scene = context.scene
    if not scene.selected_molecule_id or not hasattr(scene, 'active_splitting_domain_id') or not scene.active_splitting_domain_id:
        return

    scene_manager = get_protein_blender_scene()
    molecule = scene_manager.molecules.get(scene.selected_molecule_id)
    if not molecule or scene.active_splitting_domain_id not in molecule.domains:
        return
    
    active_domain = molecule.domains[scene.active_splitting_domain_id]

    # Clamp end value
    new_end_val = scene.split_domain_new_end # Read once
    clamped_end = min(active_domain.end, new_end_val)
    clamped_end = max(clamped_end, scene.split_domain_new_start + 1) # Must be at least 1 greater than start
    clamped_end = max(clamped_end, active_domain.start + 1) # Cannot be less than domain start + 1
    
    if scene.split_domain_new_end != clamped_end:
        scene.split_domain_new_end = clamped_end

# Callback for domain_color property update
def update_domain_color(self, context):
    domain_id = self["domain_id"]
    parent_molecule_id = self["parent_molecule_id"]
    
    # Get scene manager and find which domain this object belongs to
    scene_manager = ProteinBlenderScene.get_instance()
    print(f"Updating domain color for domain: {domain_id} in molecule: {parent_molecule_id}")
    # Find which molecule and domain this object belongs to
    for molecule_id, molecule in scene_manager.molecules.items():
        if parent_molecule_id.startswith(molecule_id):
            molecule.update_domain_color(domain_id, self.domain_color)
            return

def update_molecule_style(self, context):
    from ..utils.scene_manager import ProteinBlenderScene
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
    style = context.scene.molecule_style
    if molecule and molecule.object:
        from ..utils.molecularnodes.blender.nodes import change_style_node
        change_style_node(molecule.object, style)
        for domain in getattr(molecule, 'domains', {}).values():
            if hasattr(domain, 'object') and domain.object:
                try:
                    domain.object.domain_style = style
                except Exception:
                    pass