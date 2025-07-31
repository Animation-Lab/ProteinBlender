# ProteinBlender Selection System Analysis

## Overview
The selection system in ProteinBlender involves complex interactions between:
1. The protein outliner UI (custom UI list)
2. Blender's viewport selection 
3. Group selection logic
4. Reference items in groups

## Key Components

### 1. Selection State Storage

#### ProteinOutlinerItem Properties (`protein_props.py`)
- `is_selected`: BoolProperty on each outliner item
- `group_memberships`: StringProperty storing comma-separated group IDs
- No update callback on `is_selected` property itself

#### Global State (`selection_sync.py`)
- `_last_selection`: Set of selected object names
- `_selection_update_in_progress`: Boolean flag to prevent recursive updates
- Timer-based polling every 0.1 seconds to detect viewport selection changes

### 2. Selection Flow

#### From Outliner to Viewport
1. User clicks checkbox in outliner → `PROTEINBLENDER_OT_outliner_select.execute()`
2. Updates `is_selected` property on clicked item
3. Applies selection rules based on item type:
   - PROTEIN: Selects protein and all children
   - CHAIN: Selects all domains in chain
   - DOMAIN: Simple toggle
   - GROUP: Toggles all members (no cascading)
4. Updates references to match original items
5. Calls `sync_outliner_to_blender_selection()` to update viewport
6. Sets `_selection_update_in_progress = True` to prevent feedback loop

#### From Viewport to Outliner
1. Timer checks for selection changes every 0.1 seconds
2. If selection changed, calls `on_blender_selection_change()`
3. Sets `_selection_update_in_progress = True`
4. Calls `update_outliner_from_blender_selection()`
5. Updates `is_selected` on all outliner items based on viewport selection
6. Special handling for chains (selected if any domain is selected)
7. Updates reference items to match originals

### 3. Group Selection Logic

#### Group Creation (`PROTEINBLENDER_OT_create_group`)
- Creates new group item with unique ID
- Adds group ID to `group_memberships` of selected items
- Deselects grouped items after creation
- Rebuilds outliner hierarchy

#### Group Selection (`PROTEINBLENDER_OT_outliner_select`)
- Groups don't have their own selection state
- Selecting a group toggles ALL members
- Checks if all members are selected to determine checkbox state
- No cascading - only direct members are affected

#### Reference Items
- Created during `build_outliner_hierarchy()` for expanded groups
- Have format: `{group_id}_ref_{original_id}`
- Store original item ID in `group_memberships` field
- Selection state synced with original item

### 4. Potential Issues Identified

#### Race Conditions
1. **Timer vs Direct Updates**: Timer runs every 0.1s but direct updates happen immediately
2. **Multiple Sync Paths**: Both outliner and viewport changes trigger syncs
3. **Recursive Group Selection**: Groups can call `sync_outliner_to_blender_selection()` recursively for each member

#### State Synchronization Issues
1. **Reference Update Logic**: References updated in multiple places:
   - In `update_outliner_from_blender_selection()` (lines 131-138)
   - In `PROTEINBLENDER_OT_outliner_select._update_references()` (lines 349-353)
   - Could lead to inconsistent state

2. **Group Member State**: When selecting a group:
   - Direct members updated in operator (lines 269-272)
   - But `sync_outliner_to_blender_selection()` called recursively (line 291)
   - Could cause multiple updates to same items

3. **Chain Selection Logic**: Complex logic to determine if chain is selected:
   - Checks all domains in chain
   - Uses regex to extract chain info from domain names
   - Could fail if domain naming is inconsistent

#### State Corruption Scenarios
1. **During Group Operations**:
   - Creating/deleting groups triggers full hierarchy rebuild
   - Selection states preserved but references recreated
   - Timing issues if selection changes during rebuild

2. **Reference Item Selection**:
   - Clicking reference redirects to original item
   - But updates happen in multiple steps
   - State could be inconsistent mid-update

3. **Undo/Redo Operations**:
   - Object references can become stale
   - Selection sync handler tries to update invalid objects
   - Could leave outliner in inconsistent state

### 5. Key Functions

#### Selection Sync Functions
- `check_selection_changes()`: Timer function, polls viewport selection
- `on_blender_selection_change()`: Called when viewport selection changes
- `update_outliner_from_blender_selection()`: Updates outliner based on viewport
- `sync_outliner_to_blender_selection()`: Updates viewport based on outliner

#### Outliner Operations
- `PROTEINBLENDER_OT_outliner_select`: Main selection operator
- `build_outliner_hierarchy()`: Rebuilds entire outliner structure
- `_are_all_group_members_selected()`: Checks group selection state

### 6. Recommendations

1. **Consolidate Update Paths**: Have single source of truth for selection state
2. **Batch Updates**: Group multiple selection changes before syncing
3. **Simplify Reference Logic**: Store reference state separately from original
4. **Add Debug Logging**: Track selection state changes for debugging
5. **Validate State**: Add checks to ensure consistency after operations
6. **Consider Event-Based Updates**: Replace timer with proper event handlers if possible