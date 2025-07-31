"""Check object collections"""

import bpy

print("\n=== CHECKING COLLECTIONS ===")

# List all collections
print("\nCollections:")
for col in bpy.data.collections:
    print(f"  {col.name}: {len(col.objects)} objects")

# Check view layer collections
view_layer = bpy.context.view_layer
print(f"\nView Layer: {view_layer.name}")
print("Layer Collections:")

def print_layer_collection(lc, indent=0):
    prefix = "  " * indent
    print(f"{prefix}{lc.name} - Visible: {lc.visible_get()}, Exclude: {lc.exclude}, Hide: {lc.hide_viewport}")
    for child in lc.children:
        print_layer_collection(child, indent + 1)

print_layer_collection(view_layer.layer_collection)

# Check objects and their collections
print("\n\nObjects and their collections:")
scene = bpy.context.scene
for item in scene.outliner_items:
    if item.object_name and item.item_type in ['PROTEIN', 'DOMAIN']:
        obj = bpy.data.objects.get(item.object_name)
        if obj:
            collections = [col.name for col in obj.users_collection]
            print(f"{item.name} -> {obj.name} in collections: {collections}")
            
            # Check if selectable
            can_select = True
            for col in obj.users_collection:
                # Find layer collection
                def find_layer_collection(lc, name):
                    if lc.collection.name == name:
                        return lc
                    for child in lc.children:
                        result = find_layer_collection(child, name)
                        if result:
                            return result
                    return None
                
                lc = find_layer_collection(view_layer.layer_collection, col.name)
                if lc:
                    if lc.exclude or lc.hide_viewport or not lc.visible_get():
                        can_select = False
                        print(f"  -> Collection {col.name} prevents selection (exclude={lc.exclude}, hide={lc.hide_viewport})")
            
            if can_select:
                print(f"  -> Should be selectable")
        break  # Just check first few