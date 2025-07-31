"""Domain Maker panel with conditional display"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import IntProperty
from ..utils.scene_manager import ProteinBlenderScene


def get_selected_item_range(context):
    """Get the valid range for the currently selected item"""
    scene = context.scene
    for item in scene.outliner_items:
        if item.is_selected and item.item_type in ['CHAIN', 'DOMAIN']:
            if item.item_type == 'CHAIN':
                # Check if we have valid chain ranges
                if item.chain_start > 0 and item.chain_end > 0 and item.chain_end >= item.chain_start:
                    return item.chain_start, item.chain_end
                else:
                    # Fallback to a reasonable default range
                    return 1, 200
            else:  # DOMAIN
                return item.domain_start, item.domain_end
    return 1, 200  # Default if nothing selected




class PROTEINBLENDER_OT_validate_domain_range(Operator):
    """Validate and clamp domain range values"""
    bl_idname = "proteinblender.validate_domain_range"
    bl_label = "Validate Domain Range"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        scene = context.scene
        min_val, max_val = get_selected_item_range(context)
        
        # Clamp values to valid range
        if scene.domain_maker_start < min_val:
            scene.domain_maker_start = min_val
        elif scene.domain_maker_start > max_val:
            scene.domain_maker_start = max_val
            
        if scene.domain_maker_end < min_val:
            scene.domain_maker_end = min_val
        elif scene.domain_maker_end > max_val:
            scene.domain_maker_end = max_val
            
        # Ensure start < end
        if scene.domain_maker_start >= scene.domain_maker_end:
            if scene.domain_maker_end > min_val:
                scene.domain_maker_start = scene.domain_maker_end - 1
            else:
                scene.domain_maker_end = scene.domain_maker_start + 1
                if scene.domain_maker_end > max_val:
                    scene.domain_maker_end = max_val
                    scene.domain_maker_start = max_val - 1
        
        return {'FINISHED'}


class PROTEINBLENDER_PT_domain_maker(Panel):
    """Domain Maker panel - only active when chain or domain selected"""
    bl_label = "Domain Maker"
    bl_idname = "PROTEINBLENDER_PT_domain_maker"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 3  # After visual setup
    
    @classmethod
    def poll(cls, context):
        """Show panel when chains or domains are selected"""
        scene = context.scene
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        # Must have at least one selection
        if len(selected_items) == 0:
            return False
        
        # All selections must be chains or domains
        for item in selected_items:
            if item.item_type not in ['CHAIN', 'DOMAIN']:
                return False
        
        return True
    
    def check_domains_adjacent(self, domains):
        """Check if selected domains are adjacent and from same chain"""
        if len(domains) < 2:
            return False
        
        # Get the actual parent chains, handling group references
        parent_chains = set()
        for domain in domains:
            parent_id = domain.parent_id
            
            # If this is a group reference item, extract the actual parent chain ID
            if "_ref_" in domain.item_id:
                # For group references, the actual parent is embedded in the reference ID
                # Format: group_XXXXX_ref_ACTUAL_PARENT_ID
                parts = domain.item_id.split("_ref_", 1)
                if len(parts) == 2:
                    # The actual parent is after '_ref_'
                    # But we need to find the actual chain parent, not the domain parent
                    # The reference ID points to the actual domain, so we need to parse it
                    actual_domain_id = parts[1]
                    # Domain IDs are like: 3b75_001_9_1_51_Residues_1-51
                    # The chain parent would be: 3b75_001_chain_9
                    id_parts = actual_domain_id.split('_')
                    if len(id_parts) >= 3:
                        # Reconstruct the chain parent ID
                        molecule_id = '_'.join(id_parts[:2])  # e.g., "3b75_001"
                        chain_id = id_parts[2]  # e.g., "9"
                        parent_id = f"{molecule_id}_chain_{chain_id}"
            
            parent_chains.add(parent_id)
        
        if len(parent_chains) != 1:
            print(f"[Domain Maker] Different parent chains: {parent_chains}")
            return False
        
        # Sort domains by start position
        sorted_domains = sorted(domains, key=lambda d: d.domain_start)
        
        # Debug print
        print(f"[Domain Maker] Checking adjacency for {len(sorted_domains)} domains:")
        for d in sorted_domains:
            print(f"  - {d.name}: {d.domain_start}-{d.domain_end} (ID: {d.item_id})")
        
        # Check if they're adjacent (end of one is start-1 of next)
        for i in range(len(sorted_domains) - 1):
            current_end = sorted_domains[i].domain_end
            next_start = sorted_domains[i+1].domain_start
            if current_end + 1 != next_start:
                print(f"[Domain Maker] Not adjacent: {sorted_domains[i].name} ends at {current_end}, {sorted_domains[i+1].name} starts at {next_start}")
                return False
        
        print(f"[Domain Maker] All domains are adjacent!")
        return True
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create a box for the entire panel content
        main_box = layout.box()
        
        # Add panel title inside the box
        main_box.label(text="Domain Maker", icon='MESH_DATA')
        main_box.separator()
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected item - prioritize domains over chains
        selected_item = None
        selected_chain = None
        for item in scene.outliner_items:
            if item.is_selected:
                if item.item_type == 'DOMAIN':
                    selected_item = item
                    break  # Domain takes priority
                elif item.item_type == 'CHAIN' and selected_chain is None:
                    selected_chain = item
        
        # If no domain selected, use the chain
        if selected_item is None:
            selected_item = selected_chain
        
        if not selected_item:
            main_box.label(text="Select a chain or domain", icon='INFO')
            layout.separator()  # Add bottom spacing
            return
        
        # Show what's selected
        box = main_box.box()
        col = box.column(align=True)
        
        if selected_item.item_type == 'CHAIN':
            col.label(text=f"Chain: {selected_item.name}", icon='LINKED')
            
            # Show chain residue range
            if selected_item.chain_start > 0 and selected_item.chain_end > 0 and selected_item.chain_end >= selected_item.chain_start:
                col.label(text=f"Residue range: {selected_item.chain_start}-{selected_item.chain_end}", icon='INFO')
            else:
                # Try to get residue range from molecule if available
                molecule_id = selected_item.parent_id
                molecule = scene_manager.molecules.get(molecule_id)
                if molecule and hasattr(molecule, 'chain_residue_ranges'):
                    # Try to find the range for this chain
                    found_range = False
                    if hasattr(molecule, 'idx_to_label_asym_id_map'):
                        try:
                            chain_id_int = int(selected_item.chain_id)
                            if chain_id_int in molecule.idx_to_label_asym_id_map:
                                label_asym_id = molecule.idx_to_label_asym_id_map[chain_id_int]
                                if label_asym_id in molecule.chain_residue_ranges:
                                    start, end = molecule.chain_residue_ranges[label_asym_id]
                                    col.label(text=f"Residue range: {start}-{end}", icon='INFO')
                                    found_range = True
                        except:
                            pass
                    if not found_range:
                        col.label(text="Residue range: Unable to determine", icon='INFO')
                else:
                    col.label(text="Residue range: Unknown", icon='INFO')
                
        elif selected_item.item_type == 'DOMAIN':
            col.label(text=f"Domain: {selected_item.name}", icon='GROUP_VERTEX')
            col.label(text=f"Residues: {selected_item.domain_start}-{selected_item.domain_end}")
        
        main_box.separator()
        
        # Smart button based on selection
        if selected_item.item_type in ['CHAIN', 'DOMAIN']:
            col = main_box.column(align=True)
            
            # Count selected items and check if they're adjacent
            selected_items = [item for item in scene.outliner_items if item.is_selected]
            
            # Filter domains and remove duplicates (when both actual and reference are selected)
            domains_dict = {}  # Use dict to track unique domains by their actual ID
            for item in selected_items:
                if item.item_type == 'DOMAIN':
                    # Get the actual domain ID
                    if "_ref_" in item.item_id:
                        # This is a reference - extract actual domain ID
                        parts = item.item_id.split("_ref_", 1)
                        if len(parts) == 2:
                            actual_id = parts[1]
                            # Only add if we haven't seen this domain yet
                            if actual_id not in domains_dict:
                                domains_dict[actual_id] = item
                    else:
                        # This is an actual domain
                        if item.item_id not in domains_dict:
                            domains_dict[item.item_id] = item
            
            domains_selected = list(domains_dict.values())
            
            # Determine button type based on selection
            if len(domains_selected) >= 2:
                # Check if domains are adjacent and from same chain
                can_merge = self.check_domains_adjacent(domains_selected)
                
                if can_merge:
                    # Merge button
                    row = col.row()
                    row.scale_y = 1.5
                    op = row.operator("proteinblender.merge_domains", text="Merge Domains", icon='AUTOMERGE_ON')
                    col.separator()
                    info_box = col.box()
                    info_col = info_box.column(align=True)
                    info_col.scale_y = 0.8
                    info_col.label(text=f"Merge {len(domains_selected)} selected domains", icon='INFO')
                else:
                    # Can't merge - not adjacent or different chains
                    row = col.row()
                    row.scale_y = 1.5
                    # Create the operator button but disable it
                    op = row.operator("proteinblender.merge_domains", text="Merge Domains", icon='AUTOMERGE_ON')
                    row.enabled = False
                    col.separator()
                    info_box = col.box()
                    info_col = info_box.column(align=True)
                    info_col.scale_y = 0.8
                    
                    # More detailed error message
                    if len(set(d.parent_id for d in domains_selected)) > 1:
                        info_col.label(text="Domains from different chains", icon='ERROR')
                    else:
                        # Check which domains are not adjacent
                        sorted_domains = sorted(domains_selected, key=lambda d: d.domain_start)
                        non_adjacent = []
                        for i in range(len(sorted_domains) - 1):
                            if sorted_domains[i].domain_end + 1 != sorted_domains[i+1].domain_start:
                                non_adjacent.append(f"{sorted_domains[i].name} and {sorted_domains[i+1].name}")
                        
                        if non_adjacent:
                            info_col.label(text="Domains must be adjacent", icon='ERROR')
                            if len(non_adjacent) == 1:
                                info_col.label(text=f"Gap between: {non_adjacent[0]}")
                        else:
                            info_col.label(text="Cannot merge these domains", icon='ERROR')
            else:
                # Split button for single chain/domain
                if selected_item:
                    item_type = "Chain" if selected_item.item_type == 'CHAIN' else "Domain"
                    row = col.row()
                    row.scale_y = 1.5
                    op = row.operator("proteinblender.split_domain_popup", text=f"Split {item_type}", icon='MESH_PLANE')
                    op.item_id = selected_item.item_id
                    op.item_type = selected_item.item_type
                else:
                    # No valid selection
                    row = col.row()
                    row.scale_y = 1.5
                    row.label(text="No valid selection", icon='ERROR')
                    return
                
                col.separator()
                info_box = col.box()
                info_col = info_box.column(align=True)
                info_col.scale_y = 0.8
                info_col.label(text="Split into multiple domains", icon='INFO')
                if selected_item.item_type == 'CHAIN':
                    info_col.label(text="Auto-generates complementary domains")
            
        # Domain operations
        elif selected_item.item_type == 'DOMAIN':
            col = main_box.column(align=True)
            
            # Rename domain
            row = col.row(align=True)
            row.label(text="Name:", icon='FONT_DATA')
            row.prop(selected_item, "name", text="")
            
            col.separator()
            
            # Adjust domain range
            col.label(text="Adjust Range", icon='ARROW_LEFTRIGHT')
            row = col.row(align=True)
            row.prop(selected_item, "domain_start", text="Start")
            row.prop(selected_item, "domain_end", text="End")
            
            # Update button
            row = col.row()
            row.operator("proteinblender.update_domain_range", text="Update Range", icon='FILE_REFRESH')
            
            col.separator()
            
            # Merge/Delete operations
            row = col.row(align=True)
            row.scale_y = 1.2
            row.operator("proteinblender.merge_domains", text="Merge", icon='AUTOMERGE_ON')
            row.operator("proteinblender.delete_domain", text="Delete", icon='X')
        
        # Add bottom spacing
        layout.separator()


# Register properties
def register_props():
    """Register scene properties for domain maker"""
    
    bpy.types.Scene.domain_maker_start = IntProperty(
        name="Start",
        description="Start residue for new domain",
        min=1,
        max=10000,  # Reasonable max for protein length
        default=1
    )
    
    bpy.types.Scene.domain_maker_end = IntProperty(
        name="End",
        description="End residue for new domain",
        min=1,
        max=10000,  # Reasonable max for protein length
        default=50
    )


def unregister_props():
    """Unregister scene properties"""
    if hasattr(bpy.types.Scene, "domain_maker_start"):
        del bpy.types.Scene.domain_maker_start
    if hasattr(bpy.types.Scene, "domain_maker_end"):
        del bpy.types.Scene.domain_maker_end


# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_validate_domain_range,
    PROTEINBLENDER_PT_domain_maker,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    register_props()


def unregister():
    unregister_props()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)