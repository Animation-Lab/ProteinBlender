import bpy

# Test script to check modifier inputs
obj = bpy.context.active_object
if obj:
    print(f"Active object: {obj.name}")
    
    # Find geometry nodes modifier
    for mod in obj.modifiers:
        if mod.type == 'NODES':
            print(f"\nModifier: {mod.name}")
            
            # Check if modifier has direct input properties
            # In newer Blender versions, node group inputs are exposed as modifier properties
            print("Modifier attributes:")
            for attr in dir(mod):
                if not attr.startswith('_') and not attr.startswith('bl_'):
                    try:
                        value = getattr(mod, attr)
                        if isinstance(value, (int, float, str, bool)):
                            print(f"  {attr}: {value}")
                    except:
                        pass
            
            # Check for Input_ attributes (common pattern for geometry nodes inputs)
            print("\nChecking for Input_ attributes:")
            for attr in dir(mod):
                if attr.startswith('Input_'):
                    try:
                        value = getattr(mod, attr)
                        print(f"  {attr}: {value}")
                    except:
                        pass
            
            # Also check the node group's interface
            if mod.node_group:
                print(f"\nNode group interface ({mod.node_group.name}):")
                if hasattr(mod.node_group, 'inputs'):
                    for i, input_socket in enumerate(mod.node_group.inputs):
                        print(f"  Input {i}: {input_socket.name} ({input_socket.type})")
                        # Try to access via modifier
                        try:
                            # Geometry nodes inputs are exposed as modifier["Input_X"]
                            input_value = mod[f"Input_{i}"]
                            print(f"    Current value: {input_value}")
                        except:
                            # Try with socket name
                            try:
                                input_value = mod[input_socket.name]
                                print(f"    Current value: {input_value}")
                            except:
                                print(f"    Could not access value")
else:
    print("No active object")