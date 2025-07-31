# ProteinBlender Selection System Redesign

## Current Issues
1. Race conditions between timer-based sync and direct updates
2. Inconsistent state management for groups and references
3. Complex recursive selection logic
4. Multiple sources of truth for selection state

## New Design Principles

### 1. Single Source of Truth
- The outliner items (`scene.outliner_items`) will be the single source of truth for selection state
- Blender viewport selection will be updated FROM the outliner, not the other way around
- Remove timer-based synchronization completely

### 2. Clear Selection Rules
- **Proteins**: Selecting a protein selects all its children (chains and domains)
- **Chains**: Selecting a chain selects all its domains (if any)
- **Domains**: Simple selection toggle
- **Groups**: Groups don't have selection state - only display member state
- **References**: References always mirror the original item's state

### 3. Event-Driven Updates
- Selection changes trigger immediate viewport sync
- No polling or timers
- Use Blender's depsgraph update handlers for external selection changes

### 4. State Management
- Selection state stored only on original items
- References computed dynamically
- Groups compute their checkbox state from members

## Implementation Plan

### Phase 1: Remove Current System
1. Remove timer-based selection sync
2. Remove global state flags
3. Simplify selection operators

### Phase 2: Implement New Selection Logic
1. Create centralized selection manager
2. Implement clear selection rules
3. Add proper viewport synchronization

### Phase 3: Fix Group Handling
1. Groups never store selection state
2. Group checkbox reflects member state
3. Clicking group toggles all members

### Phase 4: Testing
1. Create unit tests for selection logic
2. Test all edge cases
3. Verify undo/redo behavior