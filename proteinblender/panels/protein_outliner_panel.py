import bpy
from bpy.types import Panel, UIList, Operator
from bpy.props import StringProperty
from ..utils.scene_manager import build_outliner_hierarchy, update_outliner_visibility


class PROTEINBLENDER_UL_outliner(UIList):
    """Custom UIList for hierarchical protein display"""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        # Visual hierarchy through indentation
        row = layout.row(align=True)
        
        # Only show items that should be visible based on parent expansion
        if not self.should_show_item(context, item):
            return
        
        # Indentation based on hierarchy level
        for i in range(item.indent_level):
            row.separator(factor=2.0)
        
        # Expand/collapse for proteins and groups only
        if item.item_type in ['PROTEIN', 'GROUP']:
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
    
    def should_show_item(self, context, item):
        """Check if item should be displayed based on parent expansion state"""
        if item.indent_level == 0:
            return True  # Always show top-level items
        
        # Check if parent is expanded
        parent_id = item.parent_id
        if parent_id:
            for parent_item in context.scene.outliner_items:
                if parent_item.item_id == parent_id:
                    # If parent is not expanded, don't show this item
                    if not parent_item.is_expanded:
                        return False
                    # Check parent's parent recursively
                    return self.should_show_item(context, parent_item)
        
        return True


class PROTEINBLENDER_OT_toggle_expand(Operator):
    """Toggle expand/collapse state of outliner item"""
    bl_idname = "proteinblender.toggle_expand"
    bl_label = "Toggle Expand"
    bl_options = {'REGISTER', 'UNDO'}

    
    item_id: StringProperty()
    
    def execute(self, context):
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
        
        # Find the clicked item
        clicked_item = None
        for item in scene.outliner_items:
            if item.item_id == self.item_id:
                clicked_item = item
                break
        
        if not clicked_item:
            return {'CANCELLED'}
        
        # Toggle selection state
        clicked_item.is_selected = not clicked_item.is_selected
        
        # Handle hierarchical selection
        if clicked_item.item_type == 'PROTEIN':
            # Select/deselect all children (chains and domains)
            self.select_children(scene, clicked_item.item_id, clicked_item.is_selected)
        elif clicked_item.item_type == 'CHAIN':
            # Select/deselect all domains under this chain
            self.select_children(scene, clicked_item.item_id, clicked_item.is_selected)
        
        # Sync to Blender selection
        from ..handlers.selection_sync import sync_outliner_to_blender_selection
        sync_outliner_to_blender_selection(context, self.item_id)
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}
    
    def select_children(self, scene, parent_id, select_state):
        """Recursively select/deselect all children of an item"""
        for item in scene.outliner_items:
            if item.parent_id == parent_id:
                item.is_selected = select_state
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
        
        # Find the item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == self.item_id:
                item = outliner_item
                break
        
        if not item:
            return {'CANCELLED'}
        
        # Toggle visibility
        new_visibility = not item.is_visible
        update_outliner_visibility(self.item_id, new_visibility)
        
        # If this is a parent item, update children visibility too
        if item.item_type in ['PROTEIN', 'CHAIN']:
            self.update_children_visibility(scene, self.item_id, new_visibility)
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}
    
    def update_children_visibility(self, scene, parent_id, visibility):
        """Recursively update visibility of all children"""
        for item in scene.outliner_items:
            if item.parent_id == parent_id:
                update_outliner_visibility(item.item_id, visibility)
                # Recursively update children
                self.update_children_visibility(scene, item.item_id, visibility)


class PROTEINBLENDER_OT_refresh_outliner(Operator):
    """Refresh the protein outliner"""
    bl_idname = "proteinblender.refresh_outliner"
    bl_label = "Refresh Outliner"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        build_outliner_hierarchy(context)
        return {'FINISHED'}


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
        
        # Always show refresh button for debugging
        box.operator("proteinblender.refresh_outliner", text="Refresh", icon='FILE_REFRESH')
        
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
    PROTEINBLENDER_OT_refresh_outliner,
    PROTEINBLENDER_PT_outliner,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)