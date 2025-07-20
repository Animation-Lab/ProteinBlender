# PRP: ProteinBlender UI Redesign Implementation

## Feature Overview

Complete redesign of ProteinBlender's UI layout to match the specified mockup (ui-development/proteinblender-proposed-layout.png), creating a unified workspace with hierarchical protein outliner, synchronized selection/visibility, domain management, and integrated timeline.

## Context and Research Findings

### Current Architecture
- **Workspace Layout**: Located in `proteinblender/layout/workspace_setup.py`
- **Panel System**: Multiple panels split across property contexts (COLLECTION, SCENE)
- **Property Management**: Uses Blender's RNA PropertyGroups in `molecule_props.py`
- **Selection State**: Tracked via `scene.selected_molecule_id` and UI list indices
- **Undo/Redo**: Custom handlers in `scene_manager.py` to maintain molecule integrity

### Key Limitations Discovered
1. **No Native Tree View in Python**: Blender's C++ tree view API isn't exposed to Python yet
2. **UIList Hierarchical Workarounds Required**: Must fake tree structure using visual indentation
3. **Synchronization Complexity**: Two-way binding requires msgbus subscriptions and depsgraph handlers

### Existing Patterns to Follow
- **Operator-Based Updates**: All state changes go through operators for undo/redo support
- **Scene Properties as UI State**: Store UI state in scene properties
- **Singleton Scene Manager**: `ProteinBlenderScene` manages all molecule data
- **Property Update Callbacks**: Use update functions for validation and cascading changes

## Implementation Blueprint

### 1. Data Structure Enhancement

```python
# proteinblender/protein_props.py

class ProteinOutlinerItem(PropertyGroup):
    """Unified item for protein outliner display"""
    item_type: EnumProperty(
        items=[('PROTEIN', 'Protein', ''),
               ('CHAIN', 'Chain', ''), 
               ('DOMAIN', 'Domain', ''),
               ('GROUP', 'Group', '')]
    )
    item_id: StringProperty()  # Unique identifier
    parent_id: StringProperty()  # For hierarchy
    
    # Visual states
    is_expanded: BoolProperty(default=True)
    is_selected: BoolProperty(default=False)
    is_visible: BoolProperty(default=True)
    
    # Display properties
    indent_level: IntProperty(default=0)
    icon: StringProperty(default='DOT')

class ProteinBlenderScene:
    # Add outliner collection
    outliner_items: CollectionProperty(type=ProteinOutlinerItem)
    outliner_index: IntProperty(update=on_outliner_selection_change)
```

### 2. Workspace Redesign

```python
# proteinblender/layout/workspace_setup.py

class ProteinWorkspaceManager:
    def create_workspace(self):
        # Remove left panel setup
        # Create single right-side panel area
        # Add timeline at bottom
        
        # Area split logic:
        # 1. Main viewport (70% width)
        # 2. Right panel (30% width) 
        # 3. Bottom timeline (20% height)
        
        viewport = self.split_area(area, 'VERTICAL', 0.7)
        panel_area = area  # Remaining right side
        timeline = self.split_area(viewport, 'HORIZONTAL', 0.8)
        
        # Configure areas
        viewport.ui_type = 'VIEW_3D'
        panel_area.ui_type = 'PROPERTIES'
        panel_area.context = 'SCENE'  # All panels in scene context
        timeline.ui_type = 'DOPESHEET'
```

### 3. Hierarchical Protein Outliner

```python
# proteinblender/panels/protein_outliner_panel.py

class PROTEINBLENDER_UL_outliner(UIList):
    """Custom UIList for hierarchical protein display"""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        # Visual hierarchy through indentation
        row = layout.row(align=True)
        
        # Indentation based on hierarchy level
        for i in range(item.indent_level):
            row.separator(factor=2.0)
        
        # Expand/collapse for proteins and groups only
        if item.item_type in ['PROTEIN', 'GROUP']:
            icon = 'TRIA_DOWN' if item.is_expanded else 'TRIA_RIGHT'
            row.prop(item, "is_expanded", icon=icon, text="", emboss=False)
        else:
            row.label(icon='BLANK1')  # Spacing
            
        # Selection toggle (unlabeled checkbox in mockup)
        row.prop(item, "is_selected", text="", 
                 icon='CHECKBOX_HLT' if item.is_selected else 'CHECKBOX_DEHLT')
        
        # Item label
        row.label(text=item.name, icon=item.icon)
        
        # Visibility toggle
        icon = 'HIDE_OFF' if item.is_visible else 'HIDE_ON'
        op = row.operator("proteinblender.toggle_visibility", text="", icon=icon)
        op.item_id = item.item_id

class PROTEINBLENDER_PT_outliner(Panel):
    bl_label = "Protein Outliner"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # UIList
        layout.template_list(
            "PROTEINBLENDER_UL_outliner", "",
            scene, "outliner_items",
            scene, "outliner_index",
            rows=10
        )
```

### 4. Selection Synchronization System

```python
# proteinblender/operators/outliner_ops.py

class PROTEINBLENDER_OT_outliner_select(Operator):
    """Handle outliner selection with hierarchy rules"""
    bl_idname = "proteinblender.outliner_select"
    
    item_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        item = self.get_item_by_id(self.item_id)
        
        # Hierarchical selection logic
        if item.item_type == 'PROTEIN':
            # Select protein and all children
            self.select_hierarchy(item, True)
        elif item.item_type == 'CHAIN':
            # Select chain and its domains
            self.select_chain_hierarchy(item, True)
            
        # Sync to Blender selection
        self.sync_to_blender_selection(item)
        
        # Trigger UI update
        context.area.tag_redraw()
        return {'FINISHED'}

# proteinblender/handlers/selection_sync.py

def register_selection_handlers():
    """Set up msgbus subscriptions for two-way sync"""
    
    # Subscribe to object selection changes
    subscribe_to = (bpy.types.Object, "select")
    bpy.msgbus.subscribe_rna(
        key=subscribe_to,
        owner=handle_owner,
        args=(None,),
        notify=on_blender_selection_change
    )
    
def on_blender_selection_change(dummy):
    """When user selects in viewport/outliner"""
    selected_objects = bpy.context.selected_objects
    
    # Update protein outliner selection state
    for obj in selected_objects:
        if obj.get("protein_item_id"):
            update_outliner_selection(obj["protein_item_id"])
```

### 5. Domain Management System

```python
# proteinblender/operators/domain_ops.py

class PROTEINBLENDER_OT_split_domain(Operator):
    """Split domain with auto-generation of complementary domains"""
    bl_idname = "proteinblender.split_domain"
    
    def execute(self, context):
        scene = context.scene
        chain = self.get_selected_chain()
        
        # Get split parameters from UI
        split_start = scene.domain_split_start
        split_end = scene.domain_split_end
        
        # Validate range
        if not self.validate_split_range(chain, split_start, split_end):
            return {'CANCELLED'}
            
        # Auto-generate domains to cover full chain
        domains = self.auto_generate_domains(chain, split_start, split_end)
        
        # Auto-naming logic
        for i, domain in enumerate(domains):
            domain.name = f"Domain {chain.name}{chr(65 + i)}"  # A, B, C...
            
        return {'FINISHED'}
```

### 6. Panel Registration and Layout

```python
# proteinblender/panels/__init__.py

# Ordered panel classes for vertical stacking
PANEL_CLASSES = [
    PROTEINBLENDER_PT_importer,      # Keep existing
    PROTEINBLENDER_PT_outliner,      # New hierarchical outliner
    PROTEINBLENDER_PT_visual_setup,  # Context-aware styling
    PROTEINBLENDER_PT_domain_maker,  # Conditional display
    PROTEINBLENDER_PT_group_maker,   # Group management
    PROTEINBLENDER_PT_pose_library,  # Placeholder
    PROTEINBLENDER_PT_animation,     # Placeholder
]

# proteinblender/addon.py

def register():
    # Register in correct order for stacking
    for cls in PANEL_CLASSES:
        bpy.utils.register_class(cls)
    
    # Set up selection sync handlers
    register_selection_handlers()
    
    # Create workspace with delay
    bpy.app.timers.register(
        lambda: ProteinWorkspaceManager().create_workspace(),
        first_interval=0.25
    )
```

## External Resources and Documentation

### Blender API References
- **UIList Documentation**: https://docs.blender.org/api/current/bpy.types.UIList.html
- **Message Bus System**: https://docs.blender.org/api/current/bpy.msgbus.html
- **Panel System**: https://docs.blender.org/api/current/bpy.types.Panel.html

### Implementation Examples
- **UIList with Custom Drawing**: https://github.com/dfelinto/blender/blob/master/doc/python_api/examples/bpy.types.UIList.2.py
- **Material UIList Demo**: https://gist.github.com/p2or/30b8b30c89871b8ae5c97803107fd494
- **Collapsible Subpanels**: https://gist.github.com/SuddenDevelopment/9eca499bc3916e8fdb41d9d6c442c365

### Key Gotchas
1. **UIList Index Updates**: The index property update callback is called during undo/redo - must handle gracefully
2. **Message Bus Lifetime**: Subscriptions are cleared on file load - must re-register in load_post handler
3. **Draw Performance**: UIList draw_item is called frequently - keep logic minimal
4. **Property Update Recursion**: Prevent infinite loops in update callbacks with flag checks

## Implementation Tasks (In Order)

1. **Refactor Workspace Layout** (`workspace_setup.py`)
   - Remove left panel creation
   - Implement new area split logic
   - Add timeline at bottom

2. **Create Outliner Data Structure** (`protein_props.py`)
   - Define ProteinOutlinerItem PropertyGroup
   - Add scene collection for outliner items
   - Implement hierarchy building logic

3. **Implement Hierarchical UIList** (`panels/protein_outliner_panel.py`)
   - Create custom UIList with indentation
   - Handle expand/collapse states
   - Implement selection/visibility toggles

4. **Build Selection Sync System** (`handlers/selection_sync.py`)
   - Set up msgbus subscriptions
   - Implement two-way sync logic
   - Handle hierarchical selection rules

5. **Create Domain Management** (`operators/domain_ops.py`)
   - Implement split domain operator
   - Add auto-generation logic
   - Create smart naming system

6. **Update Panel Registration** (`panels/__init__.py`, `addon.py`)
   - Order panels for vertical stacking
   - Ensure proper context and display
   - Add conditional visibility logic

7. **Implement Visual Setup Panel** (`panels/visual_setup_panel.py`)
   - Context-aware application logic
   - Hierarchical style inheritance

8. **Add Group Management** (`panels/group_maker_panel.py`)
   - Create/edit group functionality
   - Handle group member relationships

9. **Create Placeholder Panels** (`panels/pose_panel.py`, `panels/animation_panel.py`)
   - Basic panel structure
   - "Coming soon" messaging

10. **Integration Testing**
    - Test undo/redo behavior
    - Verify selection sync
    - Validate domain splitting

## Validation Gates

```bash
# 1. Code Quality Check
cd /mnt/c/Users/dlee1/BlenderProjects/ProteinBlender
python -m ruff check proteinblender/ --fix
python -m mypy proteinblender/ --ignore-missing-imports

# 2. Addon Registration Test
blender --background --python-expr "import bpy; bpy.ops.preferences.addon_enable(module='proteinblender')"

# 3. UI Layout Verification
blender --python tests/test_ui_layout.py

# 4. Selection Sync Test
blender --python tests/test_selection_sync.py

# 5. Domain Splitting Test
blender --python tests/test_domain_splitting.py

# 6. Full Integration Test
blender --python tests/test_full_integration.py
```

## Success Criteria

1. ✓ Workspace matches mockup layout exactly
2. ✓ Hierarchical outliner displays proteins/chains/domains/groups
3. ✓ Two-way selection sync works flawlessly
4. ✓ Visibility toggles sync with Blender
5. ✓ Domain splitting auto-generates complementary domains
6. ✓ Undo/redo maintains UI state correctly
7. ✓ Multiple proteins handled without conflicts
8. ✓ Performance remains smooth with many items

## Confidence Score: 8.5/10

Strong confidence due to:
- Comprehensive research of Blender patterns
- Clear understanding of limitations and workarounds
- Detailed implementation blueprint
- Existing codebase patterns to follow

Minor risks:
- UIList hierarchical display complexity
- Message bus subscription edge cases
- Performance with very large protein structures