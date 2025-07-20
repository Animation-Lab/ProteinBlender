# Chain Selection and Visibility Fix

## Problem Description

The Protein Outliner had issues with 2-way selection and visibility for chain items:

1. **Selection Checkbox**: When clicking the selection checkbox for a chain, it would select/deselect the domains in the viewport, but changes in the viewport wouldn't update the chain checkbox state.

2. **Visibility Checkbox**: The show/hide checkbox for chains was completely non-functional - clicking it had no effect.

## Root Cause

The issues were caused by missing functionality in several key areas:

1. **Missing Chain Visibility Update Function**: The `update_visibility` function in `outliner_properties.py` only handled `PROTEIN` and `DOMAIN` types, but not `CHAIN` type.

2. **Missing Chain Visibility Sync**: The `sync_selection_from_viewport` function in `outliner_handler.py` only synced selection state for chains, but not visibility state.

3. **Missing Visibility Message Bus Subscription**: The message bus subscriptions only monitored selection changes, not visibility changes.

4. **Checkbox Interaction Issues**: The `row.prop()` approach for checkboxes wasn't working properly with the BoolProperty update functions.

## Solution

### 1. Enhanced Chain Visibility Update Function

**File**: `proteinblender/properties/outliner_properties.py`

Added chain handling to the `update_visibility` function:

```python
elif self.type == 'CHAIN':
    # Handle chain visibility - show/hide all domains in the chain
    chain_label = getattr(self, 'chain_label', '')
    
    # Check for hidden domain first
    if hasattr(self, 'hidden_domain_id'):
        hidden_domain_id = getattr(self, 'hidden_domain_id')
        for mol in scene_manager.molecules.values():
            if hasattr(mol, 'domains') and hidden_domain_id in mol.domains:
                domain = mol.domains[hidden_domain_id]
                if domain and domain.object:
                    if domain.object.hide_get() == self.is_visible:
                        domain.object.hide_set(not self.is_visible)
                break
    else:
        # Show/hide all visible domains in this chain
        for mol in scene_manager.molecules.values():
            if hasattr(mol, 'domains'):
                for domain_id, domain in mol.domains.items():
                    if (domain and domain.object and 
                        hasattr(domain, 'chain_id') and domain.chain_id == chain_label):
                        if domain.object.hide_get() == self.is_visible:
                            domain.object.hide_set(not self.is_visible)
```

### 2. Enhanced Chain Visibility Sync

**File**: `proteinblender/handlers/outliner_handler.py`

Added chain visibility sync to `sync_selection_from_viewport`:

```python
# Second pass: update chain selections based on their domains
for item in outliner_state.items:
    if item.type == 'CHAIN':
        chain_selected = _calculate_chain_selection_state(item, scene_manager)
        if item.is_selected != chain_selected:
            item.is_selected = chain_selected
            changes_made = True
        
        # Update chain visibility based on its domains
        chain_visible = _calculate_chain_visibility_state(item, scene_manager)
        if item.is_visible != chain_visible:
            item.is_visible = chain_visible
            changes_made = True
```

### 3. Added Chain Visibility Calculation Function

**File**: `proteinblender/handlers/outliner_handler.py`

Created `_calculate_chain_visibility_state` function:

```python
def _calculate_chain_visibility_state(chain_item, scene_manager):
    """Calculate whether a chain should be considered visible based on its domains."""
    chain_label = getattr(chain_item, 'chain_label', '')
    
    # Check for hidden domain first (single domain spanning entire chain)
    if hasattr(chain_item, 'hidden_domain_id'):
        hidden_domain_id = getattr(chain_item, 'hidden_domain_id')
        for mol in scene_manager.molecules.values():
            if hasattr(mol, 'domains') and hidden_domain_id in mol.domains:
                domain = mol.domains[hidden_domain_id]
                if domain and domain.object:
                    return not domain.object.hide_get()
                break
        return True
    
    # Check visible domains in this chain
    domain_count = 0
    visible_domains = 0
    
    for mol in scene_manager.molecules.values():
        if hasattr(mol, 'domains'):
            for domain_id, domain in mol.domains.items():
                if (domain and domain.object and 
                    hasattr(domain, 'chain_id') and domain.chain_id == chain_label):
                    domain_count += 1
                    if not domain.object.hide_get():
                        visible_domains += 1
    
    # Chain is visible if all its domains are visible (and there are domains)
    return domain_count > 0 and visible_domains == domain_count
```

### 4. Added Visibility Message Bus Subscription

**File**: `proteinblender/handlers/outliner_handler.py`

Added subscription to object visibility changes:

```python
# Subscribe to object visibility changes
bpy.msgbus.subscribe_rna(
    key=(bpy.types.Object, "hide_viewport"),
    owner=outliner_sync_handler,
    args=(),  # Required args parameter
    notify=msgbus_selection_callback,
)
```

### 5. Operator-Based Checkbox Implementation

**Files**: `proteinblender/operators/outliner_operators.py`, `proteinblender/panels/outliner_panel.py`

Replaced `row.prop()` checkboxes with operator buttons for better interaction:

```python
# Selection toggle (right side) - use operator button
selection_icon = 'CHECKBOX_HLT' if item.is_selected else 'CHECKBOX_DEHLT'
selection_op = row.operator("protein_pb.toggle_outliner_selection", text="", icon=selection_icon, emboss=False)
selection_op.item_index = i

# Visibility toggle (right side) - use operator button
visibility_icon = 'HIDE_OFF' if item.is_visible else 'HIDE_ON'
visibility_op = row.operator("protein_pb.toggle_outliner_visibility", text="", icon=visibility_icon, emboss=False)
visibility_op.item_index = i
```

The operators properly trigger the BoolProperty update functions:

```python
class PROTEIN_PB_OT_toggle_outliner_selection(Operator):
    """Toggle selection state of an outliner item"""
    bl_idname = "protein_pb.toggle_outliner_selection"
    
    item_index: IntProperty(default=-1)
    
    def execute(self, context):
        scene = context.scene
        outliner_state = scene.protein_outliner_state
        
        if self.item_index >= 0 and self.item_index < len(outliner_state.items):
            item = outliner_state.items[self.item_index]
            item.is_selected = not item.is_selected  # This triggers update_selection()
        
        return {'FINISHED'}
```

## Behavior After Fix

### Selection Checkbox (2-way)
- **Outliner → Viewport**: Clicking the chain selection checkbox selects/deselects all domains in that chain
- **Viewport → Outliner**: Selecting/deselecting domains in the viewport updates the chain checkbox state
  - Chain is selected if ALL its domains are selected
  - Chain is deselected if ANY of its domains are deselected

### Visibility Checkbox (2-way)
- **Outliner → Viewport**: Clicking the chain visibility checkbox shows/hides all domains in that chain
- **Viewport → Outliner**: Hiding/showing domains in the viewport updates the chain visibility state
  - Chain is visible if ALL its domains are visible
  - Chain is hidden if ANY of its domains are hidden

## Testing

Test scripts have been created to verify the functionality:
- `tmp_tests/test_chain_selection_visibility.py` - Tests the property update functions
- `tmp_tests/test_outliner_operators.py` - Tests the operator-based checkbox interaction

## Compatibility

These changes maintain full backward compatibility and don't affect existing functionality for proteins and domains. 