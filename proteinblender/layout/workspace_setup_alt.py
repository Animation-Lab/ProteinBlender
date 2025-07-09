import bpy

class ProteinWorkspaceManagerAlt:
    def __init__(self, name="ProteinBlenderAlt"):
        self.name = name
        self.workspace = None
        self.screen = None
        self.window = None
        self.main_area = None
        self.left_area = None
        self.right_area = None
        self.bottom_area = None

    def create_custom_workspace(self):
        # Check if workspace already exists
        if self.name in bpy.data.workspaces:
            self.workspace = bpy.data.workspaces[self.name]
            return self.workspace

        original_workspace_names = [ws.name for ws in bpy.data.workspaces]
        original_workspace_names.append(self.name)
        original_workspace_name = bpy.context.workspace.name

        # Duplicate the current workspace
        bpy.ops.workspace.duplicate()
        self.workspace = bpy.context.workspace
        self.workspace.name = self.name

        # Store references to window and screen
        ctx = bpy.context
        self.window = ctx.window_manager.windows[0]
        self.screen = ctx.screen

        # Remove all areas except the 3D View
        p_areas = {area for area in self.screen.areas if area.type != 'VIEW_3D'}
        for area in p_areas:
            override = {
                'screen': self.screen,
                'window': self.window,
                'area': area
            }
            with bpy.context.temp_override(**override):
                if bpy.ops.screen.area_close.poll():
                    bpy.ops.screen.area_close()

        # Restore original workspace names if needed
        for workspace in bpy.data.workspaces:
            if workspace.name not in original_workspace_names:
                workspace.name = original_workspace_name

        # Move workspace to the back with proper context
        override = bpy.context.copy()
        override["window"] = self.window
        with bpy.context.temp_override(**override):
            bpy.ops.workspace.reorder_to_back()

        # Identify the main 3D view area
        self.main_area = next((area for area in self.screen.areas if area.type == 'VIEW_3D'), None)

        # Remove default objects before returning
        self._remove_default_objects()
        return self.workspace

    def add_panels_to_workspace(self):
        # Ensure we have a main area before proceeding
        if not self.main_area:
            return

        # Add the left area for mockup panel
        self.left_area = self._split_area(self.main_area, 'VERTICAL', 0.3, 'PROPERTIES')

        # Add the right area for protein importer
        self.right_area = self._split_area(self.main_area, 'VERTICAL', 0.75, 'PROPERTIES')

        # Add the bottom area for timeline (below 3D viewport)
        # Use factor 0.25 to create timeline in bottom 25% of the viewport
        self.bottom_area = self._split_area(self.main_area, 'HORIZONTAL', 0.25, 'DOPESHEET_EDITOR')

    def _split_area(self, area, direction, factor, new_type):
        # Helper function to split an area and set the new area type
        areas_before = set(self.screen.areas)
        original_area = area
        override = {
            'window': self.window,
            'screen': self.screen,
            'area': area
        }
        with bpy.context.temp_override(**override):
            bpy.ops.screen.area_split(direction=direction, factor=factor)
        areas_after = set(self.screen.areas)
        new_area = (areas_after - areas_before).pop()

        # For horizontal splits (timeline), ensure the new area is at the bottom
        if direction == 'HORIZONTAL' and new_type == 'DOPESHEET_EDITOR':
            # Check which area is lower (has smaller y coordinate) - that should be the timeline
            if new_area.y < original_area.y:
                # New area is below original, use new area for timeline
                target_area = new_area
            else:
                # New area is above original, use original area for timeline
                target_area = original_area
                
        else:
            target_area = new_area

        # Set the target area's type
        override['area'] = target_area
        with bpy.context.temp_override(**override):
            target_area.type = new_type

        return target_area

    def set_properties_context(self):
        # Set left area to collection context to show mockup panel
        if self.left_area:
            override = {
                'window': self.window,
                'screen': self.screen,
                'area': self.left_area,
            }
            with bpy.context.temp_override(**override):
                self.left_area.type = 'PROPERTIES'
                self.left_area.spaces[0].context = 'COLLECTION'

        # Set right area to scene context to show protein importer
        if self.right_area:
            override = {
                'window': self.window,
                'screen': self.screen,
                'area': self.right_area,
            }
            with bpy.context.temp_override(**override):
                self.right_area.type = 'PROPERTIES'
                self.right_area.spaces[0].context = 'SCENE'

        # Set bottom area to timeline
        if self.bottom_area:
            override = {
                'window': self.window,
                'screen': self.screen,
                'area': self.bottom_area,
            }
            with bpy.context.temp_override(**override):
                self.bottom_area.type = 'DOPESHEET_EDITOR'
                # Set the dopesheet mode to timeline
                if hasattr(self.bottom_area.spaces[0], 'mode'):
                    self.bottom_area.spaces[0].mode = 'TIMELINE'

    def _remove_default_objects(self):
        # Only proceed if there are exactly 3 objects
        if len(bpy.data.objects) != 3:
            return

        # Check if we have the default objects
        has_light = any(obj.name.startswith('Light') for obj in bpy.data.objects)
        has_camera = any(obj.name.startswith('Camera') for obj in bpy.data.objects)
        cube = next((obj for obj in bpy.data.objects if obj.name.startswith('Cube')), None)

        # Check if we have all three default objects
        if not (has_light and has_camera and cube):
            return

        # Check cube position and scale
        is_default_position = (
            abs(cube.location.x) < 0.001 and 
            abs(cube.location.y) < 0.001 and 
            abs(cube.location.z) < 0.001
        )
        is_default_scale = (
            abs(cube.scale.x - 1.0) < 0.001 and 
            abs(cube.scale.y - 1.0) < 0.001 and 
            abs(cube.scale.z - 1.0) < 0.001
        )

        # Only remove the cube if it's in default position and scale
        if is_default_position and is_default_scale:
            bpy.data.objects.remove(cube, do_unlink=True)


# Operator to create the ProteinBlenderAlt workspace
class WORKSPACE_OT_create_proteinblender_alt(bpy.types.Operator):
    bl_idname = "workspace.create_proteinblender_alt"
    bl_label = "Create ProteinBlenderAlt Workspace"
    bl_description = "Create the ProteinBlenderAlt workspace with mockup UI layout"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            manager = ProteinWorkspaceManagerAlt("ProteinBlenderAlt")
            manager.create_custom_workspace()
            manager.add_panels_to_workspace()
            manager.set_properties_context()
            
            # Switch to the new workspace
            context.window.workspace = manager.workspace
            
            self.report({'INFO'}, f"Created workspace: {manager.name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create workspace: {str(e)}")
            return {'CANCELLED'}


# Register the operator
CLASSES = [
    WORKSPACE_OT_create_proteinblender_alt,
] 