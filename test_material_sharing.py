"""
Test script to diagnose why changing alpha on one domain affects all domains.
This will help identify if materials are being shared incorrectly.
"""

import bpy

print("\n" + "="*80)
print("MATERIAL SHARING DIAGNOSTIC TEST")
print("="*80 + "\n")

def check_domain_materials():
    """Check how materials are configured for domain objects"""

    # Find all domain objects
    domain_objects = []
    for obj in bpy.data.objects:
        if 'domain' in obj.name.lower() or 'chain' in obj.name.lower():
            # Check if it has a geometry nodes modifier
            has_geo_nodes = False
            for modifier in obj.modifiers:
                if modifier.type == 'NODES':
                    has_geo_nodes = True
                    break
            if has_geo_nodes:
                domain_objects.append(obj)

    if not domain_objects:
        print("No domain objects found with geometry nodes")
        return

    print(f"Found {len(domain_objects)} domain objects with geometry nodes:\n")

    # Check each domain's material setup
    materials_used = {}

    for obj in domain_objects:
        print(f"Object: {obj.name}")

        # Find geometry nodes modifier
        for modifier in obj.modifiers:
            if modifier.type == 'NODES':
                if not modifier.node_group:
                    print("  - No node group")
                    continue

                node_tree = modifier.node_group

                # Find Style node
                style_node = None
                for node in node_tree.nodes:
                    if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                        style_node = node
                        break

                if style_node:
                    print(f"  - Found Style node: {style_node.node_tree.name}")

                    # Check Material input
                    material_input = style_node.inputs.get("Material")
                    if material_input:
                        mat = material_input.default_value
                        if mat:
                            print(f"  - Material: {mat.name}")

                            # Track which objects use which materials
                            if mat.name not in materials_used:
                                materials_used[mat.name] = []
                            materials_used[mat.name].append(obj.name)

                            # Check alpha value
                            if mat.use_nodes and mat.node_tree:
                                for mat_node in mat.node_tree.nodes:
                                    if mat_node.type == 'BSDF_PRINCIPLED':
                                        alpha = mat_node.inputs['Alpha'].default_value
                                        print(f"  - Alpha value: {alpha:.3f}")

                                        # Check if alpha is keyframed
                                        if mat_node.inputs['Alpha'].is_animatable:
                                            anim_data = mat.node_tree.animation_data
                                            if anim_data and anim_data.action:
                                                fcurves = anim_data.action.fcurves
                                                alpha_fcurve = None
                                                for fc in fcurves:
                                                    if 'Alpha' in fc.data_path:
                                                        alpha_fcurve = fc
                                                        break
                                                if alpha_fcurve:
                                                    print(f"  - Alpha is KEYFRAMED ({len(alpha_fcurve.keyframe_points)} keyframes)")
                                        break
                        else:
                            print("  - No material assigned")
                    else:
                        print("  - Style node has no Material input")
                else:
                    print("  - No Style node found")
        print()

    # Report material sharing
    print("\n" + "-"*40)
    print("MATERIAL SHARING ANALYSIS:")
    print("-"*40)

    shared_materials = []
    for mat_name, objects in materials_used.items():
        if len(objects) > 1:
            shared_materials.append((mat_name, objects))

    if shared_materials:
        print("\n⚠️  WARNING: Materials are being SHARED between domains!")
        print("This explains why changing alpha on one domain affects all domains.\n")

        for mat_name, objects in shared_materials:
            print(f"Material '{mat_name}' is shared by {len(objects)} objects:")
            for obj_name in objects:
                print(f"  - {obj_name}")
            print()
    else:
        print("\n✓ Each domain has its own unique material")
        print("Alpha changes should be independent")

    # List all transparent materials
    print("\n" + "-"*40)
    print("ALL TRANSPARENT MATERIALS IN SCENE:")
    print("-"*40)

    transparent_mats = []
    for mat in bpy.data.materials:
        if 'MN_Transparent' in mat.name or 'Alpha' in mat.name:
            transparent_mats.append(mat)

    if transparent_mats:
        for mat in transparent_mats:
            users = mat.users
            print(f"- {mat.name} (users: {users})")
    else:
        print("No transparent materials found")

    return shared_materials

# Run the diagnostic
print("Checking domain material configuration...\n")
shared = check_domain_materials()

if shared:
    print("\n" + "="*80)
    print("DIAGNOSIS: MATERIAL SHARING BUG CONFIRMED")
    print("="*80)
    print("\nThe issue is that domains are sharing the same material instance.")
    print("When you change the alpha value in one material, all domains using")
    print("that material are affected.")
    print("\nSOLUTION: Each domain needs its own unique material instance")
    print("The get_or_create_transparent_material() function should be creating")
    print("unique materials per object, but it seems this isn't working correctly.")
    print("\nPossible causes:")
    print("1. The obj.name might not be unique enough")
    print("2. Materials might be getting reused from a previous state")
    print("3. The material creation logic might have a bug")