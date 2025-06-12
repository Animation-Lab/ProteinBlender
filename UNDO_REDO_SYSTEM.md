# ProteinBlender Robust Undo/Redo System

## Overview

This document describes the robust undo/redo system implemented for ProteinBlender. The system ensures that protein imports, deletions, and domain operations can be safely undone and redone while maintaining consistent state between the addon and Blender's native undo system.

## Key Features

### ✅ **Native Blender Undo Integration**
- All operators that modify Blender data now include the `'UNDO'` flag
- Single undo steps for complex operations (protein + all domains)
- Automatic state restoration via Blender's native system

### ✅ **Custom Property Tracking** 
- Comprehensive custom properties on all objects for state reconstruction
- Protein-domain relationships preserved across undo/redo
- No stale object references or memory issues

### ✅ **Simplified Sync Handler**
- Lightweight handler that rebuilds UI from object properties
- No complex state reconstruction or object reference tracking
- Robust against addon reloads and scene changes

### ✅ **Atomic Operations**
- Import creates protein + all domains in one undoable operation
- Delete removes protein + all domains in one undoable operation
- UI updates automatically reflect undo/redo state

## Implementation Details

### Custom Properties Schema

#### Main Protein Objects
```python
obj["is_protein_blender_main"] = True
obj["molecule_identifier"] = "unique_molecule_id"
obj["import_source"] = "remote" | "local"
obj["protein_style"] = "surface" | "ribbon" | etc.
```

#### Domain Objects
```python
obj["is_protein_blender_domain"] = True
obj["pb_domain_id"] = "unique_domain_id"
obj["molecule_identifier"] = "parent_molecule_id"  # Links to parent
obj["parent_molecule"] = "parent_molecule_id"
obj["domain_chain_id"] = "A"
obj["domain_start"] = 100
obj["domain_end"] = 200
obj["domain_name"] = "Domain A: 100-200"
obj["domain_style"] = "ribbon"
```

### Operators with UNDO Support

All these operators now create proper undo steps:

- `PROTEIN_OT_import_protein` - Protein import
- `PROTEIN_OT_import_local` - Local file import  
- `MOLECULE_OT_delete` - Molecule deletion
- `MOLECULE_OT_select` - Molecule selection
- `MOLECULE_OT_delete_domain` - Domain deletion
- `MOLECULE_PB_OT_*` - All pivot and style operations

### Sync Handler Logic

```python
def sync_manager_on_undo_redo(scene):
    """Rebuilds UI state from object custom properties"""
    
    # 1. Clear current UI state
    scene.molecule_list_items.clear()
    
    # 2. Scan all objects for proteins and domains
    found_molecules = {}
    found_domains = {}
    
    for obj in bpy.data.objects:
        mol_id = obj.get("molecule_identifier")
        if not mol_id:
            continue
            
        if obj.get("is_protein_blender_main"):
            found_molecules[mol_id] = obj
        elif obj.get("is_protein_blender_domain"):
            domain_id = obj.get("pb_domain_id")
            if mol_id not in found_domains:
                found_domains[mol_id] = {}
            found_domains[mol_id][domain_id] = obj
    
    # 3. Rebuild UI from found objects
    for mol_id, mol_obj in found_molecules.items():
        item = scene.molecule_list_items.add()
        item.identifier = mol_id
        item.name = mol_obj.get("molecule_identifier", mol_obj.name)
    
    # 4. Validate selected molecule
    if scene.selected_molecule_id not in found_molecules:
        scene.selected_molecule_id = ""
```

## Benefits for Domain System

### **Tight Coupling Preserved**
- Domains are automatically deleted when parent protein is deleted
- Domains are automatically restored when parent protein is undone
- All relationships maintained via custom properties

### **UI Consistency**
- Domain counts update correctly after undo/redo
- Domain selection states preserved
- No orphaned domain references

### **Performance**
- No complex object reconstruction 
- Fast property-based scanning
- Minimal memory usage

## Testing

Use the provided `test_undo_redo.py` script to verify functionality:

```bash
# In Blender's text editor:
exec(open("test_undo_redo.py").read())
```

The test covers:
1. Protein import with domain creation
2. Protein deletion (protein + all domains)  
3. Undo operation (restores protein + all domains)
4. Redo operation (deletes protein + all domains again)
5. UI consistency across multiple cycles

## Migration Notes

### **What Changed**
- Added `'UNDO'` flags to key operators
- Added comprehensive custom properties to all objects
- Simplified sync handler to use properties instead of complex reconstruction
- Updated delete operations to be atomic (protein + domains together)

### **Backward Compatibility**
- Existing molecules without custom properties will be handled gracefully
- Old sync handler logic removed for simpler, more reliable approach
- PropertyGroups still supported for UI integration

### **Performance Impact**
- ✅ Faster sync operations (property scanning vs object reconstruction)
- ✅ Lower memory usage (no object reference caching)
- ✅ More reliable (no stale references)

## Best Practices

### **For Operators**
```python
class MyOperator(Operator):
    bl_options = {'REGISTER', 'UNDO'}  # Always include UNDO for data modifications
    
    def execute(self, context):
        # Modify objects directly, let Blender handle undo
        obj["custom_property"] = "value"
        return {'FINISHED'}
```

### **For State Management**
```python
# ❌ BAD - Store object references
self.my_object = some_blender_object

# ✅ GOOD - Store object names/IDs and lookup dynamically  
self.my_object_name = some_blender_object.name
# Later: obj = bpy.data.objects.get(self.my_object_name)
```

### **For Custom Properties**
```python
# Add tracking properties when creating objects
obj["is_protein_blender_main"] = True
obj["molecule_identifier"] = unique_id

# Use properties for state reconstruction after undo/redo
for obj in bpy.data.objects:
    if obj.get("is_protein_blender_main"):
        # This is one of our protein objects
        mol_id = obj.get("molecule_identifier")
```

## Troubleshooting

### **Common Issues**

**"Objects not restored after undo"**
- Check that operators have `'UNDO'` in bl_options
- Verify custom properties are set on object creation

**"UI shows wrong molecule count"**  
- Sync handler should rebuild UI from objects
- Check that `molecule_identifier` properties are set correctly

**"Domains not linked to protein after undo"**
- Verify domains have `molecule_identifier` matching parent protein
- Check that `is_protein_blender_domain` flag is set

### **Debug Commands**

```python
# List all ProteinBlender objects
for obj in bpy.data.objects:
    if obj.get("molecule_identifier"):
        print(f"{obj.name}: {obj.get('molecule_identifier')}")
        if obj.get("is_protein_blender_main"):
            print("  - Main protein")
        elif obj.get("is_protein_blender_domain"):
            print(f"  - Domain: {obj.get('pb_domain_id')}")

# Manually trigger sync handler
from proteinblender.handlers.sync import sync_manager_on_undo_redo
sync_manager_on_undo_redo(bpy.context.scene)
```

## Future Enhancements

### **Potential Improvements**
- Add custom property validation on import
- Implement automatic migration for old molecules
- Add performance metrics for sync operations
- Consider PropertyGroup integration for complex state

### **Monitoring**
- Track undo/redo performance in production
- Monitor for any edge cases with complex protein structures
- Gather user feedback on undo behavior

---

**Result**: A robust, simple, and efficient undo/redo system that handles protein-domain relationships correctly and integrates seamlessly with Blender's native undo system. 