import bpy

class ProteinWorkspaceManager:
    def __init__(self, name="Protein Blender"):
        self.name = name
        self.workspace = None
        self.screen = None
        self.window = None
        self.main_area = None
        self.panel_area = None  # Right-side panel area (was right_area)
        self.timeline_area = None  # Bottom timeline (was bottom_area)

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

        # Split vertically: viewport (70%) | panel area (30%)
        self.panel_area = self._split_area(self.main_area, 'VERTICAL', 0.7, 'PROPERTIES')

        # Split the viewport horizontally: timeline (20%) at top | viewport (80%) at bottom
        self.timeline_area = self._split_area(self.main_area, 'HORIZONTAL', 0.2, 'DOPESHEET_EDITOR')

    def _split_area(self, area, direction, factor, new_type):
        # Helper function to split an area and set the new area type
        areas_before = set(self.screen.areas)
        override = {
            'window': self.window,
            'screen': self.screen,
            'area': area
        }
        with bpy.context.temp_override(**override):
            bpy.ops.screen.area_split(direction=direction, factor=factor)
        areas_after = set(self.screen.areas)
        new_area = (areas_after - areas_before).pop()

        # Set the new area's type
        override['area'] = new_area
        with bpy.context.temp_override(**override):
            new_area.type = new_type

        return new_area

    def set_properties_context(self):
        # Set panel area to scene context (all panels in one area)
        if self.panel_area:
            override = {
                'window': self.window,
                'screen': self.screen,
                'area': self.panel_area,
            }
            with bpy.context.temp_override(**override):
                self.panel_area.type = 'PROPERTIES'
                self.panel_area.spaces[0].context = 'SCENE'

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

# Example usage (Run in Blender's Python console or as part of your addon registration process):
# manager = ProteinWorkspaceManager("Protein Blender")
# manager.create_custom_workspace()
# manager.add_panels_to_workspace()
# manager.set_properties_context()
#
# After this, you have `manager.workspace`, `manager.screen`, `manager.main_area`,
# `manager.panel_area`, and `manager.timeline_area` all stored.
