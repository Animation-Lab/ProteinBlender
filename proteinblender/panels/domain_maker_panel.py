"""Domain Maker panel for managing protein domains.

This module implements the Domain Maker panel with:
- Context-sensitive chain detection
- Dynamic label showing selected chain
- Split Chain button (enabled only for single chain selection)
- Domain rules enforcement
"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import IntProperty, StringProperty
from ..utils.scene_manager import ProteinBlenderScene


def get_selected_outliner_items(context):
    """Get all selected items from the outliner."""
    outliner_state = context.scene.protein_outliner_state
    selected_items = []
    
    for item in outliner_state.items:
        if item.is_selected:
            # Skip items that are in groups (unless they ARE groups)
            if item.type != 'GROUP' and is_item_in_group(item, context):
                continue
            selected_items.append(item)
    
    return selected_items


def is_item_in_group(item, context):
    """Check if an item is part of a group."""
    scene = context.scene
    if not hasattr(scene, 'pb_groups'):
        return False
    
    for group in scene.pb_groups:
        for member in group.members:
            if member.identifier == item.identifier:
                return True
    
    return False


def get_chain_info(item):
    """Extract chain information from an outliner item."""
    if item.type == 'CHAIN':
        # Extract chain ID from identifier (format: "protein_id_chain_X")
        parts = item.identifier.split('_chain_')
        if len(parts) == 2:
            return {
                'chain_id': parts[1],
                'protein_id': parts[0],
                'name': item.name
            }
    return None


def get_domains_for_chain(context, chain_id, protein_id):
    """Get all domains that belong to a specific chain."""
    outliner_state = context.scene.protein_outliner_state
    domains = []
    
    # Look for domains that belong to this chain
    for item in outliner_state.items:
        if item.type == 'DOMAIN':
            # Check if this domain belongs to the chain
            # Domain identifiers might include chain info
            if chain_id in item.identifier and protein_id in item.identifier:
                domains.append(item)
    
    return domains


class VIEW3D_PT_pb_domain_maker(Panel):
    """Domain Maker panel for chain and domain management."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "Domain Maker"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        
        # Get selected items
        selected_items = get_selected_outliner_items(context)
        
        # Filter for chain selections only
        selected_chains = [item for item in selected_items if item.type == 'CHAIN']
        
        if len(selected_chains) == 1:
            # Single chain selected - show chain name and enable button
            chain = selected_chains[0]
            chain_info = get_chain_info(chain)
            
            if chain_info:
                # Show chain name
                layout.label(text=chain_info['name'])
                
                # Split Chain button (enabled)
                op = layout.operator("pb.split_chain", text="Split Chain")
                op.chain_id = chain_info['chain_id']
                op.protein_id = chain_info['protein_id']
                op.chain_name = chain_info['name']
                
                # Show current domains if any
                domains = get_domains_for_chain(context, chain_info['chain_id'], chain_info['protein_id'])
                if domains:
                    layout.separator()
                    layout.label(text=f"Current domains: {len(domains)}")
            else:
                # Fallback if chain info extraction fails
                layout.label(text=chain.name)
                layout.operator("pb.split_chain", text="Split Chain")
        
        elif len(selected_chains) > 1:
            # Multiple chains selected
            layout.label(text=f"{len(selected_chains)} chains selected")
            
            # Split Chain button (disabled)
            row = layout.row()
            row.enabled = False
            row.operator("pb.split_chain", text="Split Chain")
            
            layout.label(text="Select a single chain", icon='INFO')
        
        else:
            # No chains selected
            layout.label(text="Select a single chain")
            
            # Split Chain button (disabled)
            row = layout.row()
            row.enabled = False
            row.operator("pb.split_chain", text="Split Chain")


class PB_OT_split_chain(Operator):
    """Split a protein chain into domains."""
    bl_idname = "pb.split_chain"
    bl_label = "Split Chain"
    bl_description = "Split the selected chain into domains"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Properties to pass chain information
    chain_id: StringProperty()
    protein_id: StringProperty()
    chain_name: StringProperty()
    
    def execute(self, context):
        """Execute the split chain operation."""
        # This is a placeholder - actual implementation would:
        # 1. Analyze the chain structure
        # 2. Identify potential domain boundaries
        # 3. Create domain objects
        # 4. Update the outliner
        
        self.report({'INFO'}, f"Split chain functionality for {self.chain_name} not yet implemented")
        
        # In the actual implementation, we would:
        # - Use molecular analysis to identify domains
        # - Create new domain entries in the outliner
        # - Ensure domains span the entire chain with no gaps
        # - Update the scene with new domain objects
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        """Invoke the operator - could show a dialog for domain split options."""
        # For now, just execute directly
        return self.execute(context)


class PB_OT_auto_split_chains(Operator):
    """Automatically split all chains in a protein into individual domains."""
    bl_idname = "pb.auto_split_chains"
    bl_label = "Auto Split Chains"
    bl_description = "Automatically split all chains into individual domains"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        """Split all chains in all proteins into domains."""
        scene_manager = ProteinBlenderScene.get_instance()
        outliner_state = context.scene.protein_outliner_state
        
        chains_processed = 0
        domains_created = 0
        
        # Process all proteins
        for item in outliner_state.items:
            if item.type == 'PROTEIN':
                protein_id = item.identifier
                molecule = scene_manager.molecules.get(protein_id)
                
                if not molecule:
                    continue
                
                # Find all chains for this protein
                chain_items = []
                for i, sub_item in enumerate(outliner_state.items):
                    if (sub_item.type == 'CHAIN' and 
                        protein_id in sub_item.identifier):
                        chain_items.append((i, sub_item))
                
                # Create a domain for each chain
                for chain_idx, chain_item in chain_items:
                    chain_info = get_chain_info(chain_item)
                    if not chain_info:
                        continue
                    
                    # Check if domain already exists
                    domain_exists = False
                    for check_item in outliner_state.items:
                        if (check_item.type == 'DOMAIN' and 
                            chain_info['chain_id'] in check_item.identifier and
                            protein_id in check_item.identifier):
                            domain_exists = True
                            break
                    
                    if not domain_exists:
                        # Create domain entry in outliner
                        domain_item = outliner_state.items.add()
                        domain_item.name = f"Domain {chain_info['chain_id']}"
                        domain_item.identifier = f"{protein_id}_domain_{chain_info['chain_id']}"
                        domain_item.type = 'DOMAIN'
                        domain_item.depth = 2  # Domains are at depth 2
                        domain_item.is_selected = False
                        domain_item.is_visible = True
                        
                        # Move to correct position (after the chain)
                        outliner_state.items.move(len(outliner_state.items) - 1, chain_idx + 1)
                        
                        domains_created += 1
                    
                    chains_processed += 1
        
        self.report({'INFO'}, f"Processed {chains_processed} chains, created {domains_created} domains")
        return {'FINISHED'}


# Classes to register
CLASSES = [
    VIEW3D_PT_pb_domain_maker,
    PB_OT_split_chain,
    PB_OT_auto_split_chains,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)