"""Domain management operators with auto-split functionality"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty
from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy
from ..core.domain import Domain


class PROTEINBLENDER_OT_split_domain(Operator):
    """Split domain with auto-generation of complementary domains"""
    bl_idname = "proteinblender.split_domain"
    bl_label = "Split Domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Properties for the split operation
    chain_id: StringProperty(
        name="Chain ID",
        description="ID of the chain to split"
    )
    
    molecule_id: StringProperty(
        name="Molecule ID",
        description="ID of the molecule"
    )
    
    split_start: IntProperty(
        name="Start",
        description="Start residue of new domain",
        min=1,
        default=1
    )
    
    split_end: IntProperty(
        name="End",
        description="End residue of new domain",
        min=1,
        default=50
    )
    
    def invoke(self, context, event):
        """Show dialog to get split parameters"""
        # Get selected chain from outliner
        scene = context.scene
        selected_item = None
        
        # Find selected chain or domain
        for item in scene.outliner_items:
            if item.is_selected and item.item_type in ['CHAIN', 'DOMAIN']:
                selected_item = item
                break
        
        if not selected_item:
            self.report({'WARNING'}, "Please select a chain or domain to split")
            return {'CANCELLED'}
        
        # Get parent molecule
        if selected_item.item_type == 'CHAIN':
            self.chain_id = selected_item.chain_id
            self.molecule_id = selected_item.parent_id
        else:  # DOMAIN
            # Find parent chain
            for chain_item in scene.outliner_items:
                if chain_item.item_id == selected_item.parent_id:
                    self.chain_id = chain_item.chain_id
                    self.molecule_id = chain_item.parent_id
                    break
        
        # Set default values based on chain
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if molecule:
            # Get chain residue range
            # For now, use a default range
            self.split_start = 1
            self.split_end = 50
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        """Draw the dialog"""
        layout = self.layout
        
        col = layout.column()
        col.label(text=f"Split Chain {self.chain_id}")
        
        row = col.row(align=True)
        row.prop(self, "split_start", text="Start")
        row.prop(self, "split_end", text="End")
        
        col.label(text="Auto-generates complementary domains", icon='INFO')
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}
        
        # Validate range
        if not self.validate_split_range(molecule):
            return {'CANCELLED'}
        
        # Auto-generate domains to cover full chain
        domains = self.auto_generate_domains(molecule)
        
        # Create the domains
        for i, (start, end) in enumerate(domains):
            domain_name = f"Domain {self.chain_id}{chr(65 + i)}"  # A, B, C...
            
            # Create domain using existing domain creation logic
            domain = Domain(
                name=domain_name,
                object=None,  # Will be created
                start=start,
                end=end
            )
            
            # Add to molecule
            domain_id = f"domain_{self.chain_id}_{chr(65 + i).lower()}"
            molecule.domains[domain_id] = domain
            
            # TODO: Create actual domain object using MolecularNodes
            self.report({'INFO'}, f"Created {domain_name} (residues {start}-{end})")
        
        # Rebuild outliner to show new domains
        build_outliner_hierarchy(context)
        
        return {'FINISHED'}
    
    def validate_split_range(self, molecule):
        """Validate that the split range is valid"""
        if self.split_start >= self.split_end:
            self.report({'ERROR'}, "Start must be less than end")
            return False
        
        # TODO: Validate against actual chain residue range
        # For now, just check basic sanity
        if self.split_start < 1:
            self.report({'ERROR'}, "Start residue must be at least 1")
            return False
        
        return True
    
    def auto_generate_domains(self, molecule):
        """Generate domain ranges to cover the full chain"""
        # For this example, assume chain goes from 1 to 200
        # TODO: Get actual chain residue range from molecule data
        chain_start = 1
        chain_end = 200
        
        domains = []
        
        # If split doesn't start at chain start, create preceding domain
        if self.split_start > chain_start:
            domains.append((chain_start, self.split_start - 1))
        
        # Add the requested domain
        domains.append((self.split_start, self.split_end))
        
        # If split doesn't end at chain end, create following domain
        if self.split_end < chain_end:
            domains.append((self.split_end + 1, chain_end))
        
        return domains


class PROTEINBLENDER_OT_merge_domains(Operator):
    """Merge selected domains"""
    bl_idname = "proteinblender.merge_domains"
    bl_label = "Merge Domains"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # Find selected domains
        selected_domains = []
        for item in scene.outliner_items:
            if item.is_selected and item.item_type == 'DOMAIN':
                selected_domains.append(item)
        
        if len(selected_domains) < 2:
            self.report({'WARNING'}, "Select at least 2 domains to merge")
            return {'CANCELLED'}
        
        # Check that all domains belong to the same chain
        parent_chains = {item.parent_id for item in selected_domains}
        if len(parent_chains) > 1:
            self.report({'WARNING'}, "Can only merge domains from the same chain")
            return {'CANCELLED'}
        
        # TODO: Implement actual domain merging logic
        self.report({'INFO'}, f"Would merge {len(selected_domains)} domains")
        
        return {'FINISHED'}


class PROTEINBLENDER_OT_rename_domain(Operator):
    """Rename selected domain"""
    bl_idname = "proteinblender.rename_domain"
    bl_label = "Rename Domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    new_name: StringProperty(
        name="New Name",
        description="New name for the domain"
    )
    
    domain_id: StringProperty()
    
    def invoke(self, context, event):
        scene = context.scene
        
        # Find selected domain
        for item in scene.outliner_items:
            if item.is_selected and item.item_type == 'DOMAIN':
                self.domain_id = item.item_id
                self.new_name = item.name
                break
        
        if not self.domain_id:
            self.report({'WARNING'}, "Please select a domain to rename")
            return {'CANCELLED'}
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")
    
    def execute(self, context):
        scene = context.scene
        
        # Update domain name in outliner
        for item in scene.outliner_items:
            if item.item_id == self.domain_id:
                item.name = self.new_name
                break
        
        # TODO: Update actual domain object name
        
        # Redraw UI
        context.area.tag_redraw()
        return {'FINISHED'}


# Operator classes to register
CLASSES = [
    PROTEINBLENDER_OT_split_domain,
    PROTEINBLENDER_OT_merge_domains,
    PROTEINBLENDER_OT_rename_domain,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)