import bpy

def create_custom_workspace(name="Protein Blender"):
    # Check if workspace already exists
    if name in bpy.data.workspaces:
        return None
        
    # Store current workspace names and active workspace name
    original_workspace_names = [ws.name for ws in bpy.data.workspaces]
    original_workspace_names.append(name)
    original_workspace_name = bpy.context.workspace.name
    
    # Duplicate the current workspace
    bpy.ops.workspace.duplicate()
    
    # Get the newly created workspace (it will be the active one)
    new_workspace = bpy.context.workspace
    new_workspace.name = name
    
    window = None
    for window_obj in bpy.context.window_manager.windows:
        window = window_obj
        
    # Clear existing areas by setting them all to EMPTY first
    for screen in new_workspace.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                continue
            
            override = bpy.context.copy()
            override["window"] = window
            override["screen"] = screen
            override["area"] = area
            
            try:
                with bpy.context.temp_override(**override):
                    bpy.ops.screen.area_close()
            except Exception as e:
                pass
                    
    for i, workspace in enumerate(bpy.data.workspaces):
        if workspace.name not in original_workspace_names:
            workspace.name = original_workspace_name
            
    # Move workspace to back with proper context
    override = bpy.context.copy()
    override["window"] = window
    with bpy.context.temp_override(**override):
        bpy.ops.workspace.reorder_to_back()
    
    return new_workspace