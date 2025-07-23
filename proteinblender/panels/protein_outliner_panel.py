import bpy
from bpy.types import Panel, UIList, Operator
from bpy.props import StringProperty
from ..utils.scene_manager import build_outliner_hierarchy, update_outliner_visibility


class PROTEINBLENDER_UL_outliner(UIList):
    """Custom UIList for hierarchical protein display"""
    
    def filter_items(self, context, data, propname):
        """Filter items based on parent expansion state"""
        items = getattr(data, propname)
        
        # Initialize with all items visible
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items)))
        
        # Hide items whose parents are collapsed
        for idx, item in enumerate(items):
            if not self._should_show_item_by_parent(items, idx):
                flt_flags[idx] = 0
        
        return flt_flags, flt_neworder
    
    def _should_show_item_by_parent(self, items, item_idx):
        """Check if item should be shown based on parent expansion state"""
        item = items[item_idx]
        
        # Separator is always shown
        if item.item_id == "groups_separator":
            return True
        
        # Top-level items are always shown
        if item.indent_level == 0:
            return True
        
        # Check if parent is expanded
        if item.parent_id:
            # Find parent item
            for parent_idx, parent_item in enumerate(items):
                if parent_item.item_id == item.parent_id:
                    # If parent is not expanded, hide this item
                    if not parent_item.is_expanded:
                        return False
                    # Recursively check parent's visibility
                    return self._should_show_item_by_parent(items, parent_idx)
        
        return True
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        # Check if this is the separator
        if item.item_id == "groups_separator":
            layout.label(text=item.name)
            return
        
        # Visual hierarchy through indentation
        row = layout.row(align=True)
        
        # Indentation based on hierarchy level
        for i in range(item.indent_level):
            row.separator(factor=2.0)
        
        # Check if this is a reference item
        is_reference = item.item_id.startswith("group_") and "_ref_" in item.item_id
        
        # Expand/collapse for proteins and groups only (not references)
        if item.item_type in ['PROTEIN', 'GROUP'] and not is_reference:
            if item.is_expanded:
                icon = 'TRIA_DOWN'
            else:
                icon = 'TRIA_RIGHT'
            op = row.operator("proteinblender.toggle_expand", text="", icon=icon, emboss=False)
            op.item_id = item.item_id
        else:
            row.label(text="", icon='BLANK1')  # Spacing
            
        # Item label with appropriate icon
        row.label(text=item.name, icon=item.icon)
        
        # Add some space before the controls
        row.separator()
        
        # For groups, add edit and delete buttons
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            # Edit button
            op = row.operator("proteinblender.edit_group", text="", icon='GREASEPENCIL')
            op.action = 'EDIT'
            op.group_id = item.item_id
            
            # Delete button
            op = row.operator("proteinblender.edit_group", text="", icon='X')
            op.action = 'DELETE'
            op.group_id = item.item_id
        else:
            # Selection toggle (unlabeled checkbox in mockup)
            if item.is_selected:
                selection_icon = 'CHECKBOX_HLT'
            else:
                selection_icon = 'CHECKBOX_DEHLT'
            
            op = row.operator("proteinblender.outliner_select", text="", icon=selection_icon, emboss=False)
            op.item_id = item.item_id
            
            # Visibility toggle
            if item.is_visible:
                visibility_icon = 'HIDE_OFF'
            else:
                visibility_icon = 'HIDE_ON'
            op = row.operator("proteinblender.toggle_visibility", text="", icon=visibility_icon)
            op.item_id = item.item_id
    


class PROTEINBLENDER_OT_toggle_expand(Operator):
    """Toggle expand/collapse state of outliner item"""
    bl_idname = "proteinblender.toggle_expand"
    bl_label = "Toggle Expand"
    bl_options = {'REGISTER', 'UNDO'}

    
    item_id: StringProperty()
    
    def execute(self, context):
        # Don't allow interaction with separator
        if self.item_id == "groups_separator":
            return {'CANCELLED'}
            
        scene = context.scene
        for item in scene.outliner_items:
            if item.item_id == self.item_id:
                item.is_expanded = not item.is_expanded
                break
        
        # Redraw UI
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
                
        return {'FINISHED'}


class PROTEINBLENDER_OT_outliner_select(Operator):
    """Handle outliner selection with hierarchy rules"""
    bl_idname = "proteinblender.outliner_select"
    bl_label = "Select Item"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        
        # Don't allow interaction with separator
        if self.item_id == "groups_separator":
            return {'CANCELLED'}
        
        # Find the clicked item
        clicked_item = None
        actual_item_id = self.item_id
        
        # Check if this is a reference item
        if "_ref_" in self.item_id:
            # Extract the original item ID from the reference
            for item in scene.outliner_items:
                if item.item_id == self.item_id and item.group_memberships:
                    actual_item_id = item.group_memberships  # Original ID stored here
                    break
        
        # Find the actual item to select
        for item in scene.outliner_items:
            if item.item_id == actual_item_id:
                clicked_item = item
                break
        
        if not clicked_item:
            return {'CANCELLED'}
        
        # Remove this block - it's redundant and interferes with proper toggling
        
        # Toggle selection state
        new_selection_state = not clicked_item.is_selected
        clicked_item.is_selected = new_selection_state
        
        # Update all references to this item (both ways)
        # If this is a reference, update the original too
        if "_ref_" in self.item_id:
            # Update the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == actual_item_id:
                    orig_item.is_selected = new_selection_state
                    break
        
        # Update all references to this item
        for ref_item in scene.outliner_items:
            if "_ref_" in ref_item.item_id and ref_item.group_memberships == actual_item_id:
                ref_item.is_selected = new_selection_state
        
        # Handle hierarchical selection
        if clicked_item.item_type == 'PROTEIN':
            # Select/deselect all children (chains and domains)
            self.select_children(scene, clicked_item.item_id, new_selection_state)
        elif clicked_item.item_type == 'GROUP':
            # Select/deselect all references in the group
            for ref_item in scene.outliner_items:
                if ref_item.parent_id == clicked_item.item_id and "_ref_" in ref_item.item_id:
                    ref_item.is_selected = new_selection_state
                    # Also update the original item that this reference points to
                    if ref_item.group_memberships:
                        for orig_item in scene.outliner_items:
                            if orig_item.item_id == ref_item.group_memberships:
                                orig_item.is_selected = new_selection_state
                                # If it's a protein, also select its children
                                if orig_item.item_type == 'PROTEIN':
                                    self.select_children(scene, orig_item.item_id, new_selection_state)
                                break
        # Note: We don't automatically select/deselect children for chains anymore
        # This allows independent chain selection without affecting parent
        
        # Sync to Blender selection
        from ..handlers.selection_sync import sync_outliner_to_blender_selection
        sync_outliner_to_blender_selection(context, actual_item_id)
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}
    
    def select_children(self, scene, parent_id, select_state):
        """Recursively select/deselect all children of an item"""
        # Find the parent item to check if it's a group
        parent_item = None
        for item in scene.outliner_items:
            if item.item_id == parent_id:
                parent_item = item
                break
        
        if parent_item and parent_item.item_type == 'GROUP':
            # For groups, select members by their membership
            member_ids = parent_item.group_memberships.split(',') if parent_item.group_memberships else []
            for member_id in member_ids:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        item.is_selected = select_state
                        # Update all references to this item
                        for ref_item in scene.outliner_items:
                            if "_ref_" in ref_item.item_id and ref_item.group_memberships == member_id:
                                ref_item.is_selected = select_state
                        # If it's a protein, also select its children
                        if item.item_type == 'PROTEIN':
                            self.select_children(scene, item.item_id, select_state)
                        break
        else:
            # For non-groups, use parent-child relationship
            for item in scene.outliner_items:
                if item.parent_id == parent_id:
                    item.is_selected = select_state
                    # Update all references to this item
                    for ref_item in scene.outliner_items:
                        if "_ref_" in ref_item.item_id and ref_item.group_memberships == item.item_id:
                            ref_item.is_selected = select_state
                    # Recursively select children
                    self.select_children(scene, item.item_id, select_state)


class PROTEINBLENDER_OT_toggle_visibility(Operator):
    """Toggle visibility of outliner item"""
    bl_idname = "proteinblender.toggle_visibility"
    bl_label = "Toggle Visibility"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        
        # Don't allow interaction with separator
        if self.item_id == "groups_separator":
            return {'CANCELLED'}
        
        # Check if this is a reference item
        actual_item_id = self.item_id
        if "_ref_" in self.item_id:
            # Extract the original item ID from the reference
            for ref_item in scene.outliner_items:
                if ref_item.item_id == self.item_id and ref_item.group_memberships:
                    actual_item_id = ref_item.group_memberships
                    break
        
        # Find the actual item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == actual_item_id:
                item = outliner_item
                break
        
        if not item:
            return {'CANCELLED'}
        
        # For reference items, update the reference visibility to match the actual item
        if "_ref_" in self.item_id:
            for ref_item in scene.outliner_items:
                if ref_item.item_id == self.item_id:
                    ref_item.is_visible = item.is_visible
                    break
        
        # Toggle visibility
        new_visibility = not item.is_visible
        item.is_visible = new_visibility
        update_outliner_visibility(actual_item_id, new_visibility)
        
        # Update all references to this item (both ways)
        # If this is a reference, update the original too
        if "_ref_" in self.item_id:
            # Update the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == actual_item_id:
                    orig_item.is_visible = new_visibility
                    break
        
        # Update all references to this item
        for ref_item in scene.outliner_items:
            if "_ref_" in ref_item.item_id and ref_item.group_memberships == actual_item_id:
                ref_item.is_visible = new_visibility
        
        # If this is a protein or group, update all children visibility too
        if item.item_type in ['PROTEIN', 'GROUP']:
            # For groups, also update all reference items
            if item.item_type == 'GROUP':
                for ref_item in scene.outliner_items:
                    if ref_item.parent_id == item.item_id and "_ref_" in ref_item.item_id:
                        ref_item.is_visible = new_visibility
            self.update_children_visibility(scene, actual_item_id, new_visibility)
        # Note: Chains don't automatically update children visibility
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}
    
    def update_children_visibility(self, scene, parent_id, visibility):
        """Recursively update visibility of all children"""
        # Find the parent item to check if it's a group
        parent_item = None
        for item in scene.outliner_items:
            if item.item_id == parent_id:
                parent_item = item
                break
        
        if parent_item and parent_item.item_type == 'GROUP':
            # For groups, update members by their membership
            member_ids = parent_item.group_memberships.split(',') if parent_item.group_memberships else []
            for member_id in member_ids:
                update_outliner_visibility(member_id, visibility)
                # If it's a protein, also update its children
                for item in scene.outliner_items:
                    if item.item_id == member_id and item.item_type == 'PROTEIN':
                        self.update_children_visibility(scene, member_id, visibility)
                        break
        else:
            # For non-groups, use parent-child relationship
            for item in scene.outliner_items:
                if item.parent_id == parent_id:
                    update_outliner_visibility(item.item_id, visibility)
                    # Recursively update children
                    self.update_children_visibility(scene, item.item_id, visibility)


class PROTEINBLENDER_PT_outliner(Panel):
    """Protein outliner panel"""
    bl_label = "Protein Outliner"
    bl_idname = "PROTEINBLENDER_PT_outliner"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 1  # Display order (after importer)
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create a box for the entire panel content
        box = layout.box()
        
        # Add panel title inside the box
        box.label(text="Protein Outliner", icon='OUTLINER')
        box.separator()
        
        # Check if outliner items exist
        if len(scene.outliner_items) == 0:
            box.label(text="No proteins loaded", icon='INFO')
            return
        
        # UIList inside the box
        box.template_list(
            "PROTEINBLENDER_UL_outliner", "",
            scene, "outliner_items",
            scene, "outliner_index",
            rows=10,
            maxrows=20
        )
        
        # Add bottom spacing
        layout.separator()


# Operator and panel classes to register
CLASSES = [
    PROTEINBLENDER_UL_outliner,
    PROTEINBLENDER_OT_toggle_expand,
    PROTEINBLENDER_OT_outliner_select,
    PROTEINBLENDER_OT_toggle_visibility,
    PROTEINBLENDER_PT_outliner,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)