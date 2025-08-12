"""Debug script to understand why get_group_objects is failing"""

import bpy

def debug_groups_and_domains():
    """Debug the current state of groups and domains"""
    
    print("\n" + "="*60)
    print("Debugging Groups and Domains")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Check scene manager
    try:
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        print("\n1. Scene Manager Status:")
        print(f"   - Molecules: {list(scene_manager.molecules.keys())}")
        
        for mol_id, molecule in scene_manager.molecules.items():
            print(f"\n   Molecule '{mol_id}':")
            print(f"   - Object: {molecule.object.name if molecule.object else 'None'}")
            print(f"   - Domains: {list(molecule.domains.keys())}")
            
            for domain_id, domain in molecule.domains.items():
                print(f"     Domain '{domain_id}':")
                print(f"       - Object: {domain.object.name if domain.object else 'None'}")
                print(f"       - Has object: {domain.object is not None}")
    except Exception as e:
        print(f"✗ Could not access scene manager: {e}")
    
    # Check outliner items
    print("\n2. Outliner Items:")
    if hasattr(scene, 'outliner_items'):
        for item in scene.outliner_items:
            if item.item_type == 'GROUP':
                print(f"\n   Group: '{item.name}' (ID: {item.item_id})")
                print(f"   - Members: {item.group_memberships}")
                
                if item.group_memberships:
                    member_ids = item.group_memberships.split(',')
                    print(f"   - Member count: {len(member_ids)}")
                    
                    for member_id in member_ids:
                        print(f"     - Member ID: '{member_id}'")
                        
                        # Try to parse it
                        if '_' in member_id:
                            parts = member_id.split('_', 1)
                            mol_id = parts[0]
                            domain_id = parts[1]
                            print(f"       Parsed as: mol='{mol_id}', domain='{domain_id}'")
                        
                        # Check if we can find this in outliner
                        for outliner_item in scene.outliner_items:
                            if outliner_item.item_id == member_id:
                                print(f"       Found in outliner: type={outliner_item.item_type}, name={outliner_item.name}")
                                if outliner_item.object_name:
                                    print(f"       Object name: '{outliner_item.object_name}'")
                                    if outliner_item.object_name in bpy.data.objects:
                                        print(f"       ✓ Object exists in scene")
                                    else:
                                        print(f"       ✗ Object NOT in scene")
                                break
            elif item.item_type in ['CHAIN', 'DOMAIN']:
                # Show non-group items that might be members
                if item.group_memberships:
                    print(f"   {item.item_type}: '{item.name}' (ID: {item.item_id})")
                    print(f"   - In groups: {item.group_memberships}")
                    print(f"   - Object name: {item.object_name if item.object_name else 'None'}")
    else:
        print("✗ No outliner_items found")
    
    # Check pose library
    print("\n3. Pose Library:")
    if hasattr(scene, 'pose_library'):
        print(f"   - Poses: {len(scene.pose_library)}")
        for idx, pose in enumerate(scene.pose_library):
            print(f"\n   Pose {idx}: '{pose.name}'")
            print(f"   - Group IDs: {pose.group_ids}")
            print(f"   - Group names: {pose.group_names}")
            print(f"   - Transforms: {len(pose.transforms)}")
            
            for t_idx, transform in enumerate(pose.transforms[:3]):  # Show first 3
                print(f"     Transform {t_idx}:")
                print(f"       - Object: '{transform.object_name}'")
                print(f"       - Group ID: {transform.group_id}")
                print(f"       - Location: {list(transform.location)}")
    else:
        print("✗ No pose_library found")
    
    print("\n" + "="*60)

# Run the debug
if __name__ == "__main__":
    debug_groups_and_domains()