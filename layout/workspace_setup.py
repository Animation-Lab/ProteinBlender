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
    screen = ctx.screen  # store once
    
    # Gather all areas that are not the 3D viewport
    p_areas = {area for area in screen.areas if area.type != 'VIEW_3D'}

    for area in p_areas:
        override = {}
        override['screen'] = screen
        override['window'] = ctx.window_manager.windows[0]
        override['area'] = area

        # Use temp_override context manager
        with bpy.context.temp_override(**override):
            if bpy.ops.screen.area_close.poll():
                bpy.ops.screen.area_close()

    # Restore original workspace names
    for workspace in bpy.data.workspaces:
        if workspace.name not in original_workspace_names:
            workspace.name = original_workspace_name

    # Move workspace to the back with proper context
    override = bpy.context.copy()
    override["window"] = window
    with bpy.context.temp_override(**override):
        bpy.ops.workspace.reorder_to_back()

    return new_workspace
