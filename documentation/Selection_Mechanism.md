# ProteinBlender Selection Mechanism

## Overview

The ProteinBlender selection system provides bidirectional synchronization between Blender's 3D viewport selection and the custom protein outliner UI. The system uses Blender's message bus (msgbus) for event-driven updates rather than polling, ensuring responsive and efficient selection synchronization.

## Architecture

### Core Components

1. **Selection Synchronization Handler** (`handlers/selection_sync.py`)
   - Manages bidirectional sync between viewport and outliner
   - Uses msgbus subscriptions for real-time updates
   - Implements depth counters to prevent recursion

2. **Outliner Panel** (`panels/protein_outliner_panel.py`)
   - Custom UI list displaying protein hierarchy
   - Checkbox-based selection interface
   - Handles user interaction with outliner items

3. **Property Definitions** (`properties/protein_props.py`)
   - `ProteinOutlinerItem`: Stores selection state and item metadata
   - `is_selected`: BoolProperty for checkbox state
   - No update callbacks on properties (handled by operators)

## Selection State Management

### Data Structure
```python
class ProteinOutlinerItem(PropertyGroup):
    is_selected: BoolProperty(default=False)  # Checkbox state
    object_name: StringProperty()              # Associated Blender object
    item_type: EnumProperty()                  # PROTEIN, CHAIN, DOMAIN, PUPPET
    item_id: StringProperty()                  # Unique identifier
    parent_id: StringProperty()                # Parent item reference
```

### State Storage
- **Primary State**: Stored in `scene.outliner_items` collection
- **Viewport State**: Native Blender object selection
- **Synchronization**: Bidirectional sync maintains consistency

## Selection Flow

### 1. Viewport to Outliner (3D View → Checkboxes)

#### Trigger Mechanisms:
- **Message Bus Events**: Object selection changes trigger msgbus callbacks
- **Depsgraph Updates**: New objects or selection changes detected
- **Deferred Processing**: Uses timers to avoid callback context issues

#### Process Flow:
```
1. User selects object in viewport
   ↓
2. msgbus.subscribe_rna() detects selection change
   ↓
3. on_selection_changed() callback triggered
   ↓
4. Deferred update via timer (0.01s delay)
   ↓
5. update_outliner_from_blender_selection()
   ↓
6. Updates checkbox states based on viewport selection
```

#### Implementation Details:
```python
def update_outliner_from_blender_selection():
    # Get selected objects (context-safe)
    selected_objects = get_selected_objects_safe()
    selected_names = {obj.name for obj in selected_objects}

    # Update item checkboxes
    for item in scene.outliner_items:
        if item.item_type in ['DOMAIN', 'PROTEIN']:
            item.is_selected = (item.object_name in selected_names)
        elif item.item_type == 'CHAIN':
            # Chains don't auto-select (prevents cascade)
            # Only deselect if no domains selected
            if not any_domain_selected_in_chain:
                item.is_selected = False
```

### 2. Outliner to Viewport (Checkboxes → 3D View)

#### Trigger:
- User clicks checkbox in outliner UI

#### Process Flow:
```
1. Checkbox clicked in UI
   ↓
2. PROTEINBLENDER_OT_outliner_select operator executed
   ↓
3. Updates item.is_selected property
   ↓
4. sync_outliner_to_blender_selection() called
   ↓
5. Updates viewport selection to match checkboxes
```

#### Selection Rules by Type:

**DOMAIN**:
- Simple toggle of individual domain object
- No cascading effects
- Independent selection

**CHAIN**:
- Selects/deselects ALL domains in the chain
- Updates domain checkboxes for consistency
- Manual selection only (no auto-select)

**PROTEIN**:
- Selects protein object and ALL child domains
- Cascades through entire hierarchy

**PUPPET** (Group):
- Selects/deselects Empty controller object
- Members remain independent

## Key Mechanisms

### 1. Recursion Prevention

Uses depth counter to prevent infinite loops:
```python
_selection_update_depth = 0  # Global counter

def sync_function():
    global _selection_update_depth
    if _selection_update_depth > 2:
        return  # Prevent deep recursion

    _selection_update_depth += 1
    try:
        # Perform sync operations
        pass
    finally:
        _selection_update_depth -= 1
```

### 2. Message Bus Subscription

Subscribes to object selection changes:
```python
def subscribe_to_object_selection(obj):
    key = obj.path_resolve("select", False)
    bpy.msgbus.subscribe_rna(
        key=key,
        owner=_msgbus_owner,
        args=(),
        notify=on_selection_changed,
    )
```

### 3. Context-Safe Selection Retrieval

Handles various Blender contexts safely:
```python
def get_selected_objects_safe():
    try:
        return bpy.context.selected_objects
    except AttributeError:
        # Fallback methods for different contexts
        if view_layer := bpy.context.view_layer:
            return [obj for obj in view_layer.objects if obj.select_get()]
        else:
            return [obj for obj in scene.objects if obj.select_get()]
```

### 4. Chain Selection Independence

Prevents cascade bug where selecting a domain auto-selects the chain:
- Domains can be selected independently
- Chain checkbox only responds to explicit user interaction
- Chain deselects automatically when all domains are deselected

## Color System Integration

### Domain Color Independence

Each domain maintains independent color through unique node trees:

1. **Color Node Uniqueness**:
   - Each domain gets `Color Common_{domain_id}` node tree
   - Prevents color sharing between domains
   - Validated during color updates

2. **Update Mechanism**:
   ```python
   def update_domain_color(domain_id, color):
       # Check for shared node tree
       if node_tree_is_shared:
           create_unique_node_tree()
       # Apply color to unique node tree
       apply_color_to_node()
   ```

3. **Selection-Based Application**:
   - Colors apply only to selected items
   - No cascade through chain selection
   - Respects individual domain selection

## Special Cases

### 1. Puppet (Group) Items
- Groups have Empty controller objects
- Selection controls Empty visibility/selection
- Members maintain independent selection state
- No cascading to group members

### 2. Reference Items
- Created for items displayed within groups
- Format: `{group_id}_ref_{original_id}`
- Selection state mirrors original item
- One-way sync from original to reference

### 3. Chain Behavior
- No automatic selection when domains selected
- Explicit selection selects all child domains
- Deselects when no child domains selected
- Maintains UI consistency

## Handler Registration

### Initialization
```python
def register():
    # Clear existing handlers
    clear_selection_handlers()

    # Initialize msgbus subscriptions
    refresh_object_subscriptions()

    # Register depsgraph handler
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update_post)

    # Register file load handler
    bpy.app.handlers.load_post.append(on_load_post)
```

### Cleanup
```python
def unregister():
    # Clear msgbus subscriptions
    bpy.msgbus.clear_by_owner(_msgbus_owner)

    # Remove handlers
    bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update_post)
    bpy.app.handlers.load_post.remove(on_load_post)
```

## Performance Considerations

1. **Event-Driven Updates**: No polling timers; uses msgbus for efficiency
2. **Batch Processing**: Multiple selections processed together
3. **Deferred Updates**: Short delays prevent callback context issues
4. **Depth Limiting**: Recursion prevention maintains performance

## Future Improvements

1. **Batch Selection Operations**: Group multiple updates before syncing
2. **Selection History**: Track selection changes for debugging
3. **Performance Metrics**: Add timing measurements for optimization
4. **Unit Testing**: Comprehensive tests for all selection scenarios

## Debug Tips

### Enable Debug Output
Add debug prints to track selection flow:
```python
print(f"Selection sync: {item.name} -> {item.is_selected}")
print(f"Depth: {_selection_update_depth}")
```

### Common Issues
1. **Checkboxes not updating**: Check msgbus subscriptions
2. **Cascade occurring**: Verify chain selection logic
3. **Colors syncing**: Check Color Common node uniqueness
4. **Performance issues**: Monitor recursion depth

## API Reference

### Key Functions

#### `update_outliner_from_blender_selection()`
Updates outliner checkboxes based on viewport selection.

#### `sync_outliner_to_blender_selection(context, item_id)`
Updates viewport selection based on outliner checkbox state.

#### `subscribe_to_object_selection(obj)`
Creates msgbus subscription for object selection changes.

#### `refresh_object_subscriptions()`
Refreshes all msgbus subscriptions for scene objects.

### Operators

#### `PROTEINBLENDER_OT_outliner_select`
- **bl_idname**: "proteinblender.outliner_select"
- **Properties**: item_id (StringProperty)
- **Function**: Handles checkbox clicks in outliner

## Testing

### Manual Test Procedures

1. **Viewport to Checkbox**:
   - Select domain in 3D view → checkbox should check
   - Deselect in 3D view → checkbox should uncheck
   - Chain checkbox should not auto-check

2. **Checkbox to Viewport**:
   - Check domain checkbox → object selected in viewport
   - Check chain checkbox → all domains selected
   - Uncheck → corresponding deselection

3. **Color Independence**:
   - Split chain into domains
   - Select one domain
   - Change color → only selected domain affected

4. **Performance**:
   - Select/deselect rapidly
   - No lag or freezing
   - Consistent state maintained