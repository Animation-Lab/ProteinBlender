import bpy

class ProteinWorkspaceManager:
    def __init__(self, name="Protein Blender"):
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

        return self.workspace

    def add_panels_to_workspace(self):
        # Ensure we have a main area before proceeding
        if not self.main_area:
            return

        # Add the left area
        self.left_area = self._split_area(self.main_area, 'VERTICAL', 0.25, 'EMPTY')

        # Add the right area
        self.right_area = self._split_area(self.main_area, 'VERTICAL', 0.66, 'OUTLINER')

        # Add the bottom area
        self.bottom_area = self._split_area(self.main_area, 'HORIZONTAL', 0.25, 'DOPESHEET_EDITOR')

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


# Example usage (Run in Blender's Python console or as part of your addon registration process):
# manager = ProteinWorkspaceManager("Protein Blender")
# manager.create_custom_workspace()
# manager.add_panels_to_workspace()
#
# After this, you have `manager.workspace`, `manager.screen`, `manager.main_area`,
# `manager.left_area`, `manager.right_area`, and `manager.bottom_area` all stored.
