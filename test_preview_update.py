import bpy

# Test script to directly update geometry nodes
obj = bpy.context.active_object
if obj:
    print(f"Active object: {obj.name}")
    
    # Find geometry nodes modifier
    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group:
            print(f"Found modifier: {mod.name}")
            print(f"Node group: {mod.node_group.name}")
            
            # List all nodes
            for node in mod.node_group.nodes:
                print(f"  Node: {node.name} ({node.bl_idname})")
                if node.bl_idname == 'GeometryNodeGroup' and hasattr(node, 'node_tree') and node.node_tree:
                    print(f"    -> Node tree: {node.node_tree.name}")
                    
                    # Check if this is Select Res ID Range
                    if "Select Res ID Range" in node.node_tree.name:
                        print(f"    -> Found Select Res ID Range!")
                        print(f"    -> Current Min: {node.inputs['Min'].default_value}")
                        print(f"    -> Current Max: {node.inputs['Max'].default_value}")
                        
                        # Try to update
                        node.inputs['Min'].default_value = 50
                        node.inputs['Max'].default_value = 100
                        print(f"    -> Updated to Min=50, Max=100")
else:
    print("No active object")