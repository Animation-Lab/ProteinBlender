import bpy

# Test script to find domain objects and their naming patterns
print("=== Domain Objects Test ===")

# List all mesh objects
print("\nAll mesh objects:")
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        print(f"  - {obj.name}")
        # Check if it has a parent
        if obj.parent:
            print(f"    Parent: {obj.parent.name}")
        # Check for geometry nodes modifier
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group:
                print(f"    Has geometry nodes: {mod.node_group.name}")
                # Look for residue selection nodes
                for node in mod.node_group.nodes:
                    if node.bl_idname == 'GeometryNodeGroup' and hasattr(node, 'node_tree') and node.node_tree:
                        if "Select Res ID Range" in node.node_tree.name:
                            print(f"      -> Has residue selection node: {node.name}")

# Look for objects with "Chain" in name
print("\n\nObjects with 'Chain' in name:")
for obj in bpy.data.objects:
    if obj.type == 'MESH' and "Chain" in obj.name:
        print(f"  - {obj.name}")
        if obj.parent:
            print(f"    Parent: {obj.parent.name}")

# Look for objects with specific patterns
print("\n\nTesting various naming patterns:")
test_patterns = ["Chain_", "chain_", "Domain", "domain", "Residues"]
for pattern in test_patterns:
    matches = [obj.name for obj in bpy.data.objects if obj.type == 'MESH' and pattern in obj.name]
    if matches:
        print(f"  Pattern '{pattern}': {matches}")