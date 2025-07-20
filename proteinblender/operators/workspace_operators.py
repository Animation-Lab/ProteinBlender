import bpy
from bpy.types import Operator


class PROTEIN_PB_OT_create_workspace(Operator):
    """Create and activate the ProteinBlender workspace"""
    bl_idname = "pb.create_workspace"
    bl_label = "Create ProteinBlender Workspace"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        workspace_name = "ProteinBlender"
        
        # Check if workspace already exists
        if workspace_name in bpy.data.workspaces:
            # Just activate it
            context.window.workspace = bpy.data.workspaces[workspace_name]
            self.report({'INFO'}, f"Activated existing {workspace_name} workspace")
            return {'FINISHED'}
        
        # Create new workspace by duplicating current one
        # First, store current workspace
        current_workspace = context.window.workspace
        
        # Use the duplicate operator to create a new workspace
        bpy.ops.workspace.duplicate()
        
        # The new workspace is now active, rename it
        new_workspace = context.window.workspace
        new_workspace.name = workspace_name
        
        # Get the screen for configuration
        new_screen = context.window.screen
        
        # Configure the screen layout
        self.setup_workspace_layout(context, new_screen)
        
        self.report({'INFO'}, f"Created {workspace_name} workspace")
        return {'FINISHED'}
    
    def setup_workspace_layout(self, context, screen):
        """Configure the workspace layout with 3D Viewport, Properties panel, and timeline"""
        
        # Clear all areas first (except the first one)
        areas_to_remove = []
        for area in screen.areas[1:]:
            areas_to_remove.append(area)
        
        # Keep the first area and configure it
        if screen.areas:
            main_area = screen.areas[0]
            
            # Join all other areas into the main area to start fresh
            for area in areas_to_remove:
                override = context.copy()
                override['area'] = main_area
                override['screen'] = screen
                
                # Find a region to use for the operation
                for region in main_area.regions:
                    if region.type == 'WINDOW':
                        override['region'] = region
                        break
                
                try:
                    # Set cursor position inside the area to join
                    override['cursor'] = (area.x + 10, area.y + 10)
                    bpy.ops.screen.area_join(override)
                except:
                    pass
        
        # Now we should have one large area - set it as 3D viewport
        if screen.areas:
            main_area = screen.areas[0]
            main_area.type = 'VIEW_3D'
            
            # Configure the 3D viewport
            for space in main_area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'SOLID'
                    space.shading.show_cavity = True
                    # Hide all default panels
                    space.show_region_ui = False
                    space.show_region_tool_header = True
                    space.show_region_header = True
            
            # Now split the area to create our layout
            # First, split vertically to create right panel area (30% for panels)
            override = context.copy()
            override['area'] = main_area
            override['screen'] = screen
            
            # Find window region
            for region in main_area.regions:
                if region.type == 'WINDOW':
                    override['region'] = region
                    break
            
            # Split vertically - 70% for 3D view, 30% for properties
            bpy.ops.screen.area_split(override, direction='VERTICAL', factor=0.7)
            
            # Find the new area (should be on the right)
            properties_area = None
            for area in screen.areas:
                if area != main_area and area.x > main_area.x:
                    properties_area = area
                    break
            
            if properties_area:
                # Set the right area to Properties editor
                properties_area.type = 'PROPERTIES'
                
                # Configure properties to show Scene properties where our panels are
                for space in properties_area.spaces:
                    if space.type == 'PROPERTIES':
                        space.context = 'SCENE'  # This is where our panels will show
            
            # Now split the 3D viewport horizontally for timeline (80% for 3D, 20% for timeline)
            override['area'] = main_area
            bpy.ops.screen.area_split(override, direction='HORIZONTAL', factor=0.8)
            
            # Find the timeline area (should be at bottom)
            timeline_area = None
            for area in screen.areas:
                if area != main_area and area != properties_area and area.y < main_area.y:
                    timeline_area = area
                    break
            
            if timeline_area:
                timeline_area.type = 'DOPESHEET_EDITOR'
                # Set to timeline mode
                for space in timeline_area.spaces:
                    if space.type == 'DOPESHEET_EDITOR':
                        space.mode = 'TIMELINE'


def ensure_workspace_exists(context):
    """Ensure the ProteinBlender workspace exists and is active"""
    workspace_name = "ProteinBlender"
    
    if workspace_name not in bpy.data.workspaces:
        # Create workspace using operator
        bpy.ops.pb.create_workspace()
    else:
        # Just activate it
        context.window.workspace = bpy.data.workspaces[workspace_name]


# List of classes to register
CLASSES = [
    PROTEIN_PB_OT_create_workspace,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)