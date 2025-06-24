# Chain Mapping Issue Analysis

## Overview
ProteinBlender creates default domains on import (one per chain) and allows users to add domains manually via the UI. Each domain must mask out atoms belonging to a specific chain using Blender geometry-nodes.

Two mapping systems are in play:
1. **label_asym_id**: e.g. 'A', 'B', 'D' — the string labels used by MolecularNodes and UI.
2. **chain_id_int**: integer indices (0,1,2,…) assigned by Biotite via `np.unique()`, which are alphabetical (`['A','B','D'] → [0,1,2]`).

### Previous Issue (DECEMBER 2024)
Both 1ATN and 3B75 failed to create domains after import. No domains were created for either protein, indicating a fundamental issue in the domain creation system.

### NEW Issue Discovered (DECEMBER 2024)
**Sequential Import Failure**: First protein import works correctly, but subsequent protein imports fail to create domains due to MolecularNodes session conflicts.

### NEWEST Issue Discovered (DECEMBER 2024)  
**Domain Masking Infrastructure Conflict**: Domains are created correctly, but domain hiding/masking system fails on second import due to node name conflicts in shared node groups.

## Root Cause Analysis (UPDATED - DECEMBER 2024)

### Issue 1: Chain ID Mapping (RESOLVED)
**Problem**: The domain creation system was using the wrong mapping dictionary.
**Status**: ✅ **FIXED** - Using correct `idx_to_label_asym_id_map` instead of empty `auth_chain_id_map`.

### Issue 2: MolecularNodes Session Conflict (RESOLVED)  
**Problem**: Sequential imports fail due to MolecularNodes session re-registration.
**Status**: ✅ **FIXED** - Removed dangerous re-registration code in `create_molecule_from_id`.

### Issue 3: Domain Masking Infrastructure Conflict (NEW - DECEMBER 2024)
**CRITICAL FINDING**: Domain masking/hiding system fails due to shared node infrastructure conflicts.

#### The Problem
1. **First Import**: Domain masking works correctly - hiding domains actually hides them ✅
2. **Second Import**: Domain masking breaks - hiding domains leaves visible chunks ✗  
3. **Root Cause**: Domain infrastructure nodes use shared names causing conflicts:
   ```python
   # PROBLEMATIC - Same names for different proteins
   self.domain_join_node.name = "Domain_Boolean_Join"
   final_not.name = "Domain_Final_Not" 
   chain_select_name = f"Domain_Chain_Select_{domain_id}"
   ```

#### Evidence
- First protein: Domain hiding works perfectly
- Second protein: Domain hiding fails (chunks remain visible)
- **Key Detail**: Deleting and re-importing still works (confirms it's not session state)
- Issue is with **node infrastructure conflicts**, not domain creation

#### Technical Details
Each `MoleculeWrapper` creates domain masking infrastructure in the parent molecule's node group:
- `Domain_Boolean_Join` - combines domain selections
- `Domain_Final_Not` - inverts selection for masking
- `Domain_Chain_Select_*` - selects specific chains
- `Domain_Res_Select_*` - selects residue ranges

When second protein imports, it creates nodes with **same names**, causing conflicts and broken masking.

## IMPLEMENTED FIXES (December 2024)

### 1. Fixed Chain ID Mapping in Domain Creation ✅ COMPLETE
**File**: `proteinblender/core/molecule_wrapper.py`
**Method**: `_create_domain_with_params()`

**Issue**: Using wrong mapping dictionary (`auth_chain_id_map` vs `idx_to_label_asym_id_map`)

**Fix**: Corrected chain mapping logic to use proper integer → label_asym_id resolution.

### 2. Fixed MolecularNodes Session Conflict ✅ COMPLETE  
**File**: `proteinblender/utils/scene_manager.py`
**Method**: `create_molecule_from_id()`

**Issue**: Re-registering MolecularNodes addon on each import causing session conflicts.

**Fix**: Removed problematic re-registration code:
```python
# REMOVED: Dangerous re-registration that corrupts state
# if not hasattr(bpy.context.scene, "MNSession"):
#     from ..utils.molecularnodes.addon import register as register_mn
#     register_mn()

# REPLACED WITH: Proper error handling
if not hasattr(bpy.context.scene, "MNSession"):
    error_msg = "MNSession not found - ProteinBlender addon may not be properly initialized"
    print(f"ERROR: {error_msg}")
    return False
```

### 3. Improved MNSession Initialization ✅ COMPLETE
**File**: `proteinblender/addon.py`
**Method**: `register()`

**Enhancement**: Made MNSession initialization more robust:
```python
if not hasattr(bpy.types.Scene, "MNSession"):
    print("ProteinBlender: Initializing MNSession...")
    bpy.types.Scene.MNSession = session.MNSession()
else:
    print("ProteinBlender: MNSession already exists, keeping existing instance")
    # Verify existing session is functional with error recovery
```

### 4. Fixed Domain Masking Infrastructure Conflicts ✅ COMPLETE
**File**: `proteinblender/core/molecule_wrapper.py`
**Methods**: `_setup_protein_domain_infrastructure()`, `_create_domain_mask_nodes()`

**Issue**: Domain masking nodes used shared names causing conflicts between proteins.

**Fix**: Made all domain infrastructure node names protein-specific:
```python
# OLD: Shared names (caused conflicts)
self.domain_join_node.name = "Domain_Boolean_Join"
final_not.name = "Domain_Final_Not"
chain_select_name = f"Domain_Chain_Select_{domain_id}"

# NEW: Protein-specific names (isolated)
join_node_name = f"Domain_Boolean_Join_{self.identifier}"
final_not_name = f"Domain_Final_Not_{self.identifier}"
chain_select_name = f"Domain_Chain_Select_{self.identifier}_{domain_id}"
```

**Enhancement**: Added infrastructure reuse detection to prevent duplicate creation:
```python
# Check if infrastructure already exists for this protein
existing_join = None
existing_not = None
for node in parent_node_group.nodes:
    if node.name == join_node_name:
        existing_join = node
    elif node.name == final_not_name:
        existing_not = node

if existing_join and existing_not:
    # Reuse existing infrastructure
    self.domain_join_node = existing_join
    self.final_not = existing_not
    return
```

## Expected Results After Fix
- **First Import**: Should work correctly (already did)
- **Second Import**: Should now work correctly with proper domain masking (was failing before)
- **Domain Hiding**: Should work correctly for both proteins
- **Sequential Testing**: Multiple proteins can be imported with proper domain masking in same session
- **Node Isolation**: Each protein has its own domain infrastructure in the node group

### Implementation Status: ✅ COMPLETE

**Key Lessons**: 
1. Never re-register addon components during runtime operations
2. MolecularNodes session state must be preserved between imports  
3. Domain infrastructure must be isolated per protein to prevent conflicts
4. Node names in shared spaces must be unique to avoid conflicts
5. Always test sequential operations, not just individual operations
