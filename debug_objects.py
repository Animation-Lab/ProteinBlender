import bpy

# Check if there are any objects in the scene
print('=== SCENE OBJECTS ===')
for obj in bpy.data.objects:
    print(f'Object: {obj.name}, Type: {obj.type}, Visible: {not obj.hide_viewport}, Location: {obj.location}')
    if obj.type == 'MESH' and obj.data:
        print(f'  - Vertices: {len(obj.data.vertices)}')
        print(f'  - Has modifiers: {len(obj.modifiers) > 0}')
        if obj.modifiers:
            for mod in obj.modifiers:
                print(f'    - Modifier: {mod.name}, Type: {mod.type}')

print('\n=== SCENE COLLECTIONS ===')
for collection in bpy.data.collections:
    print(f'Collection: {collection.name}, Objects: {len(collection.objects)}')

# Check specifically for domain objects
print('\n=== DOMAIN OBJECTS ===')
for obj in bpy.data.objects:
    if "domain" in obj.name.lower() or obj.get("is_protein_blender_domain"):
        print(f'Domain Object: {obj.name}')
        print(f'  - Type: {obj.type}')
        print(f'  - Visible: {not obj.hide_viewport}')
        print(f'  - Location: {obj.location}')
        print(f'  - Parent: {obj.parent.name if obj.parent else None}')
        if obj.type == 'MESH':
            print(f'  - Vertices: {len(obj.data.vertices)}')
            print(f'  - Faces: {len(obj.data.polygons)}') 