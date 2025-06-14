# ProteinBlender Undo/Redo Implementation Todo

## Problem Statement

When a protein is deleted and then the user presses undo, the protein appears back in Blender but ProteinBlender's internal state (`ProteinBlenderScene.molecules`) becomes corrupted because:

1. The molecule object references become stale after undo
2. Domain objects lose their parent-child relationships  
3. The UI shows incorrect state
4. Subsequent operations fail because of invalid object references

## Simple Solution

Store complete protein+domain state before destructive operations, then restore missing objects after undo.

## Implementation Steps

### Step 1: Create Simple State Storage
**File:** `proteinblender/core/molecule_state.py`

Create a simple class to capture and restore molecule state:

```python
class MoleculeState:
    def __init__(self, molecule_wrapper):
        # Store all the data needed to recreate the molecule
        self.identifier = molecule_wrapper.identifier
        self.molecule_data = self._capture_molecule_data(molecule_wrapper)
        self.domains_data = self._capture_domains_data(molecule_wrapper)
    
    def _capture_molecule_data(self, molecule):
        # Store basic molecule info
        # Store object name, transforms, materials, etc.
        
    def _capture_domains_data(self, molecule):
        # Store all domain info including:
        # - Domain definitions (chain_id, start, end, name)
        # - Object names and transforms  
        # - Node group configurations
        # - Parent-child relationships
        
    def restore_to_scene(self, scene_manager):
        # Recreate the molecule and all domains
        # Set up all relationships and node networks
```

### Step 2: Add State Capture to Scene Manager
**File:** `proteinblender/utils/scene_manager.py`

Add simple state tracking:

```python
class ProteinBlenderScene:
    def __init__(self):
        # ... existing code ...
        self._saved_states = {}  # molecule_id -> MoleculeState
    
    def _capture_molecule_state(self, molecule_id):
        """Store complete state before destructive operations"""
        if molecule_id in self.molecules:
            self._saved_states[molecule_id] = MoleculeState(self.molecules[molecule_id])
    
    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule - capture state first"""
        # Capture state before deletion
        self._capture_molecule_state(identifier)
        
        # ... existing delete logic ...
```

### Step 3: Implement Working Undo Handler
**File:** `proteinblender/utils/scene_manager.py`

Replace the commented-out undo handler with working logic:

```python
def sync_molecule_list_after_undo(*args):
    """Restore missing molecules after undo operations"""
    print("Syncing molecule list after undo/redo")
    
    scene_manager = ProteinBlenderScene.get_instance()
    scene = bpy.context.scene
    
    # Find molecules that should exist but are missing/invalid
    molecules_to_restore = []
    
    for molecule_id, saved_state in scene_manager._saved_states.items():
        current_molecule = scene_manager.molecules.get(molecule_id)
        
        # Check if molecule exists and is valid
        needs_restore = (
            current_molecule is None or 
            not _is_object_valid(current_molecule.object) or
            _has_invalid_domains(current_molecule)
        )
        
        if needs_restore:
            molecules_to_restore.append((molecule_id, saved_state))
    
    # Restore missing molecules
    for molecule_id, saved_state in molecules_to_restore:
        print(f"Restoring molecule: {molecule_id}")
        saved_state.restore_to_scene(scene_manager)
    
    # Update UI
    _refresh_molecule_ui(scene_manager, scene)
```

### Step 4: Add Helper Functions
**File:** `proteinblender/utils/scene_manager.py`

Add validation and utility functions:

```python
def _is_object_valid(obj):
    """Check if Blender object reference is still valid"""
    try:
        return obj and obj.name in bpy.data.objects
    except:
        return False

def _has_invalid_domains(molecule):
    """Check if any domains have invalid object references"""
    for domain in molecule.domains.values():
        if not _is_object_valid(domain.object):
            return True
    return False

def _refresh_molecule_ui(scene_manager, scene):
    """Refresh the UI to match current state"""
    # Clear and rebuild molecule list
    scene.molecule_list_items.clear()
    
    for identifier, molecule in scene_manager.molecules.items():
        if _is_object_valid(molecule.object):
            item = scene.molecule_list_items.add()
            item.identifier = identifier
    
    # Update active molecule
    if scene_manager.active_molecule not in scene_manager.molecules:
        scene_manager.active_molecule = next(iter(scene_manager.molecules), None)
    
    # Force UI refresh
    scene_manager._refresh_ui()
```

### Step 5: Test the Implementation
**File:** `test_simple_undo_redo.py`

Create a focused test:

```python
def test_simple_undo_redo():
    """Test basic protein delete/undo cycle"""
    
    # 1. Import a protein
    scene_manager = ProteinBlenderScene.get_instance()
    success = scene_manager.create_molecule_from_id("1CRN", "PDB", "pdb")
    assert success
    
    molecule_id = list(scene_manager.molecules.keys())[0]
    molecule = scene_manager.molecules[molecule_id]
    
    # 2. Verify domains exist
    assert len(molecule.domains) > 0
    
    # 3. Delete the molecule
    success = scene_manager.delete_molecule(molecule_id)
    assert success
    assert molecule_id not in scene_manager.molecules
    
    # 4. Undo deletion
    bpy.ops.ed.undo()
    
    # 5. Verify everything is restored
    assert molecule_id in scene_manager.molecules
    restored_molecule = scene_manager.molecules[molecule_id]
    assert _is_object_valid(restored_molecule.object)
    assert len(restored_molecule.domains) > 0
    
    # 6. Verify domains are restored
    for domain in restored_molecule.domains.values():
        assert _is_object_valid(domain.object)
```

### Step 6: Register the Handler
**File:** `proteinblender/addon.py`

Ensure the undo handler is registered:

```python
def register():
    # ... existing registration ...
    
    # Register undo handler
    from .utils.scene_manager import sync_molecule_list_after_undo
    if sync_molecule_list_after_undo not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(sync_molecule_list_after_undo)

def unregister():
    # ... existing unregistration ...
    
    # Unregister undo handler
    from .utils.scene_manager import sync_molecule_list_after_undo
    if sync_molecule_list_after_undo in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(sync_molecule_list_after_undo)
```

## Key Design Principles

1. **Simple State Capture**: Only capture state when needed (before destructive operations)
2. **Lazy Restoration**: Only restore what's actually missing/invalid
3. **Minimal Data**: Store only what's needed to recreate objects
4. **Robust Validation**: Use safe checks for object validity
5. **Clear Separation**: Keep state management separate from UI logic

## Success Criteria

- ✅ Protein delete → undo → protein restored with all domains
- ✅ All domain objects have valid parent-child relationships  
- ✅ UI reflects correct state after undo/redo
- ✅ Multiple undo/redo cycles work correctly
- ✅ No crashes or stale object references

This approach is **simple but sufficient** - it solves the core problem without unnecessary complexity. 