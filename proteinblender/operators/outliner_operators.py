"""Outliner operators for ProteinBlender.

This module contains operators for the Protein Outliner functionality.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty


class PROTEIN_PB_OT_rename_outliner_item(Operator):
    """Rename an item in the Protein Outliner"""
    bl_idname = "protein_pb.rename_outliner_item"
    bl_label = "Rename Item"
    bl_description = "Rename the selected protein/chain/domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Properties for the dialog
    new_name: StringProperty(
        name="Name",
        description="New name for the item",
        default="",
        maxlen=64
    )
    
    item_index: IntProperty(
        name="Item Index",
        description="Index of the item in the outliner",
        default=-1
    )
    
    def execute(self, context):
        """Execute the rename operation"""
        scene = context.scene
        outliner_state = scene.protein_outliner_state
        
        # Validate item index
        if self.item_index < 0 or self.item_index >= len(outliner_state.items):
            self.report({'ERROR'}, "Invalid item index")
            return {'CANCELLED'}
        
        item = outliner_state.items[self.item_index]
        
        # Validate new name
        if not self.new_name.strip():
            self.report({'ERROR'}, "Name cannot be empty")
            return {'CANCELLED'}
        
        # Update the item name
        old_name = item.name
        item.name = self.new_name.strip()
        
        # TODO: Here you could add logic to also rename the underlying Blender objects
        # For now, we just update the outliner display name
        
        self.report({'INFO'}, f"Renamed '{old_name}' to '{item.name}'")
        
        # Trigger UI refresh
        context.area.tag_redraw()
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        """Show the rename dialog"""
        scene = context.scene
        outliner_state = scene.protein_outliner_state
        
        # Validate item index
        if self.item_index < 0 or self.item_index >= len(outliner_state.items):
            self.report({'ERROR'}, "Invalid item index")
            return {'CANCELLED'}
        
        item = outliner_state.items[self.item_index]
        
        # Set the current name as default
        self.new_name = item.name
        
        # Show the dialog
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def draw(self, context):
        """Draw the dialog UI"""
        layout = self.layout
        layout.prop(self, "new_name")


class PROTEIN_PB_OT_manage_domains(Operator):
    """Manage domains for a protein item"""
    bl_idname = "protein_pb.manage_domains"
    bl_label = "Manage Protein Domains"
    bl_description = "Manage domains for the selected protein/chain"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_index: IntProperty(
        name="Item Index",
        description="Index of the item in the outliner",
        default=-1
    )
    
    def execute(self, context):
        """Execute the manage domains operation"""
        # For now, just close the dialog
        self.report({'INFO'}, "Manage Domains dialog opened")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        """Show the manage domains dialog"""
        scene = context.scene
        outliner_state = scene.protein_outliner_state
        
        # Validate item index
        if self.item_index < 0 or self.item_index >= len(outliner_state.items):
            self.report({'ERROR'}, "Invalid item index")
            return {'CANCELLED'}
        
        item = outliner_state.items[self.item_index]
        
        # Show the dialog
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        """Draw the dialog UI"""
        layout = self.layout
        
        # Header
        layout.label(text="Manage Protein Domains", icon='DNA')
        layout.separator()
        
        # Placeholder content
        box = layout.box()
        box.label(text="Domain management functionality coming soon...")
        
        layout.separator() 