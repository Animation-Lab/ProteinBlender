"""
Debug script to test if the outliner operators are properly registered and accessible.
"""

import bpy

def test_operator_registration():
    """Test if the operators are registered and accessible."""
    
    print("=== Operator Registration Debug ===")
    
    # List of operators to test
    operators_to_test = [
        "protein_pb.toggle_outliner_selection",
        "protein_pb.toggle_outliner_visibility", 
        "protein_pb.toggle_outliner_expand",
        "protein_pb.manage_domains",
        "protein_pb.rename_outliner_item"
    ]
    
    print("\n1. Checking operator registration:")
    for op_name in operators_to_test:
        try:
            # Try to access the operator
            category, name = op_name.split('.')
            if hasattr(bpy.ops, category):
                category_ops = getattr(bpy.ops, category)
                if hasattr(category_ops, name):
                    print(f"  ✅ {op_name} is registered")
                else:
                    print(f"  ❌ {op_name} - name not found in category")
            else:
                print(f"  ❌ {op_name} - category not found")
        except Exception as e:
            print(f"  ❌ {op_name} - Error: {e}")
    
    print("\n2. Listing all protein_pb operators:")
    try:
        if hasattr(bpy.ops, 'protein_pb'):
            pb_ops = dir(bpy.ops.protein_pb)
            print(f"  Found {len(pb_ops)} protein_pb operators:")
            for op in pb_ops:
                if not op.startswith('_'):
                    print(f"    - protein_pb.{op}")
        else:
            print("  ❌ protein_pb category not found")
    except Exception as e:
        print(f"  ❌ Error listing operators: {e}")
    
    print("\n3. Testing operator calls:")
    for op_name in operators_to_test:
        try:
            # Try to poll the operator
            category, name = op_name.split('.')
            if hasattr(bpy.ops, category) and hasattr(getattr(bpy.ops, category), name):
                operator = getattr(getattr(bpy.ops, category), name)
                # Test if operator can be polled
                poll_result = operator.poll()
                print(f"  ✅ {op_name} - Poll result: {poll_result}")
            else:
                print(f"  ❌ {op_name} - Not accessible")
        except Exception as e:
            print(f"  ❌ {op_name} - Poll error: {e}")
    
    print("\n4. Checking outliner state:")
    try:
        scene = bpy.context.scene
        if hasattr(scene, 'protein_outliner_state'):
            outliner_state = scene.protein_outliner_state
            print(f"  ✅ Outliner state found with {len(outliner_state.items)} items")
            
            # List item types
            types = {}
            for item in outliner_state.items:
                item_type = item.type
                if item_type not in types:
                    types[item_type] = 0
                types[item_type] += 1
            
            for item_type, count in types.items():
                print(f"    - {item_type}: {count} items")
        else:
            print("  ❌ No protein_outliner_state found on scene")
    except Exception as e:
        print(f"  ❌ Error checking outliner state: {e}")

if __name__ == "__main__":
    test_operator_registration() 