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
    
    add_panels_to_workspace(screen, new_workspace)
    return new_workspace

def add_panels_to_workspace(screen, workspace):
    ctx = bpy.context
    window = ctx.window_manager.windows[0]
    main_area = next((area for area in screen.areas if area.type == 'VIEW_3D'), None)

    if not main_area:
        return

    # Split the main area vertically for the left area
    areas_before = set(screen.areas)
    override = {
        'window': window,
        'screen': screen,
        'area': main_area
    }
    with bpy.context.temp_override(**override):
        bpy.ops.screen.area_split(direction='VERTICAL', factor=0.25)
    areas_after = set(screen.areas)
    left_area = (areas_after - areas_before).pop()
    override = {
        'window': window,
        'screen': screen,
        'area': left_area
    }
    with bpy.context.temp_override(**override):
        left_area.type = 'EMPTY'

    # Split the main area vertically for the right area
    areas_before = set(screen.areas)
    override = {
        'window': window,
        'screen': screen,
        'area': main_area
    }
    with bpy.context.temp_override(**override):
        bpy.ops.screen.area_split(direction='VERTICAL', factor=0.66)
    areas_after = set(screen.areas)
    right_area = (areas_after - areas_before).pop()
    override = {
        'window': window,
        'screen': screen,
        'area': right_area
    }
    with bpy.context.temp_override(**override):
        right_area.type = 'OUTLINER'


    areas_before = set(screen.areas)
    override = {
        'window': window,
        'screen': screen,
        'area': main_area
    }
    with bpy.context.temp_override(**override):
        bpy.ops.screen.area_split(direction='HORIZONTAL', factor=0.25)
    areas_after = set(screen.areas)
    bottom_area = (areas_after - areas_before).pop()
    override = {
        'window': window,
        'screen': screen,
        'area': bottom_area
    }
    with bpy.context.temp_override(**override):
        bottom_area.type = 'DOPESHEET_EDITOR'
