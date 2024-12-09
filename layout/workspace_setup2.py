# protein_workspace/layout/workspace_setup.py
import bpy

def create_custom_workspace(name="Protein Blender"):
    # Check if workspace already exists
    if name in bpy.data.workspaces:
        return None

    original_workspace_names = [ws.name for ws in bpy.data.workspaces]
    original_workspace_names.append(name)
    original_workspace_name = bpy.context.workspace.name

    # Duplicate the current workspace
    bpy.ops.workspace.duplicate()

    new_workspace = bpy.context.workspace
    new_workspace.name = name

    window = None
    for window_obj in bpy.context.window_manager.windows:
        window = window_obj

    ctx = bpy.context
    screen = ctx.screen  # <-- set once.

    p_areas = {area for area in ctx.screen.areas if area.ui_type != 'VIEW_3D'}
    for area in p_areas:
        override = {}
        override['screen'] = screen
        override['window'] = ctx.window_manager.windows[0]
        override['area'] = area

        with bpy.context.temp_override(**override):
            if bpy.ops.screen.area_close.poll():
                bpy.ops.screen.area_close()

    # Restore original workspace names
    for i, workspace in enumerate(bpy.data.workspaces):
        if workspace.name not in original_workspace_names:
            workspace.name = original_workspace_name

    # Move workspace to the back with proper context
    override = bpy.context.copy()
    override["window"] = window
    with bpy.context.temp_override(**override):
        bpy.ops.workspace.reorder_to_back()

    return new_workspace
