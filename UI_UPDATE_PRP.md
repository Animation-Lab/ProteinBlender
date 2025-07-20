# UI Update Project Requirements Plan (PRP)

## Overview

This document outlines the comprehensive UI update for ProteinBlender, transforming it into a dedicated workspace with a unified right-side panel containing all protein management tools. The new UI will provide a more intuitive and professional interface for molecular visualization and animation.

## 1. Workspace Creation

### 1.1 ProteinBlender Workspace
- **Requirement**: Create a new workspace named "ProteinBlender" that becomes the default workspace when the addon is enabled
- **Layout**: 
  - Left side: 3D Viewport (maximum real estate)
  - Right side: Single vertical panel area containing all protein tools
  - Bottom: Timeline editor
- **Implementation**:
  ```python
  # In addon registration or workspace operator
  def create_protein_workspace():
      # Check if workspace exists
      if "ProteinBlender" not in bpy.data.workspaces:
          # Create new workspace
          bpy.ops.workspace.append_activate(
              idname="ProteinBlender", 
              filepath=os.path.join(os.path.dirname(__file__), "startup.blend")
          )
      # Or programmatically create workspace
      workspace = bpy.data.workspaces.new("ProteinBlender")
      # Configure screens and areas
  ```

### 1.2 Panel Organization
- All panels in `VIEW_3D` space, `UI` region
- Stacked vertically in this exact order:
  1. Importer (placeholder)
  2. Protein Outliner
  3. Visual Set-up
  4. Domain Maker
  5. Group Maker
  6. Protein Pose Library (mock)
  7. Animate Scene (mock)

## 2. Protein Outliner Panel

### 2.1 Structure
- **Header**: "Protein outliner" (exact text from UI)
- **Hierarchy Display**:
  - Proteins (top level) with expand/collapse triangle
  - Chains (indented) without expand/collapse
  - Domains (further indented)
  - Groups (top level) with expand/collapse triangle
- **Checkboxes**: Two checkboxes on right side of each item:
  - Select checkbox (left)
  - Visibility checkbox (right)

### 2.2 Behavior
- **Import Behavior**: When a protein is imported, automatically split all chains into individual domains
- **2-way Sync**: 
  - Clicking select checkbox → Select object in viewport
  - Selecting in viewport → Update checkbox
  - Same for visibility
- **Selection Context**: Selecting items updates context for Visual Set-up and Domain Maker panels

### 2.3 Implementation Updates
```python
# Update outliner_panel.py
class VIEW3D_PT_protein_outliner(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_label = "Protein outliner"
    bl_order = 2  # After Importer
    
    def draw(self, context):
        # Draw hierarchical list with dual checkboxes
        # Add group support to existing outliner
```

## 3. Visual Set-up Panel

### 3.1 Structure
- **Header**: "Visual Set-up"
- **Controls**:
  - Color wheel selector
  - Representation dropdown (ribbon, surface, ball-and-stick, etc.)
- **Context Sensitive**: Updates based on selected items in outliner

### 3.2 Behavior
- **Single Selection**: Shows current color/representation
- **Multiple Selection**: Shows common values or mixed state
- **Live Update**: Changes apply immediately to selected items

### 3.3 Implementation
```python
class VIEW3D_PT_visual_setup(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_label = "Visual Set-up"
    bl_order = 3
    
    def draw(self, context):
        layout = self.layout
        # Color wheel
        layout.prop(context.scene, "pb_visual_color", text="Color")
        # Representation dropdown
        layout.prop(context.scene, "pb_visual_representation", text="Representation")
```

## 4. Domain Maker Panel

### 4.1 Structure
- **Header**: "Domain Maker"
- **Dynamic Label**: Shows selected chain name (e.g., "Chain A")
- **Button**: "Split Chain" (only active when single chain selected)

### 4.2 Behavior
- **Chain Selection**: Enable button and update label
- **Multiple/No Selection**: Disable button, show default label
- **Domain Rules**: 
  - Domains must span entire chain (no gaps)
  - Cannot span multiple chains
  - Chain is the largest domain unit

### 4.3 Implementation
```python
class VIEW3D_PT_domain_maker(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_label = "Domain Maker"
    bl_order = 4
    
    def draw(self, context):
        layout = self.layout
        selected = get_selected_outliner_items(context)
        
        if len(selected) == 1 and selected[0].type == 'CHAIN':
            layout.label(text=selected[0].name)
            layout.operator("pb.split_chain", text="Split Chain")
        else:
            layout.label(text="Select a single chain")
            layout.operator("pb.split_chain", text="Split Chain").enabled = False
```

## 5. Group Maker Panel

### 5.1 Structure
- **Header**: "Group Maker"
- **Button**: "Create New Group" (top right)
- **Group List**: Expandable tree showing groups and their contents
  - Groups show chains and domains as children

### 5.2 Create/Edit Group Popup
- **Title**: "Group ###" (editable text field) or "Select Group" dropdown
- **Contents**: 
  - Tree view of all proteins, chains, domains
  - Single checkbox per item for add/remove
  - Text: "PDBs, chains or domains added to the group will be grayed out and no longer selectable unless selecting them within the group."
- **Buttons**: "Create New Group" / "Edit Group"

### 5.3 Behavior
- **Group Creation**: Opens popup with empty group
- **Group Editing**: Opens popup with current members checked
- **Grayed Out**: Items in groups become grayed and non-selectable in main outliner
- **Group Outliner**: Groups appear in main protein outliner

### 5.4 Implementation
```python
class VIEW3D_PT_group_maker(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_label = "Group Maker"
    bl_order = 5
    
    def draw(self, context):
        layout = self.layout
        layout.operator("pb.create_edit_group", text="Create New Group")
        
        # Draw group tree
        for group in context.scene.pb_groups:
            # Draw expandable group with contents

class PB_OT_create_edit_group(Operator):
    bl_idname = "pb.create_edit_group"
    bl_label = "Create/Edit Group"
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        # Draw group name field
        # Draw tree with checkboxes
        # Draw info text
```

## 6. Mock Panels

### 6.1 Protein Pose Library
```python
class VIEW3D_PT_protein_pose_library(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_label = "Protein Pose Library"
    bl_order = 6
    
    def draw(self, context):
        layout = self.layout
        layout.operator("pb.create_edit_pose", text="Create/Edit Pose")
        layout.label(text="Pose 1")
        row = layout.row()
        row.operator("pb.apply_pose", text="Apply")
        row.operator("pb.update_pose", text="Update Positions")
```

### 6.2 Animate Scene
```python
class VIEW3D_PT_animate_scene(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_label = "Animate Scene"
    bl_order = 7
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="Pivot")
        layout.operator("pb.move_pivot", text="Move Pivot")
        layout.operator("pb.snap_to_center", text="Snap to Center")
        
        layout.label(text="Add Keyframe")
        layout.prop(context.scene, "pb_brownian_motion", text="Brownian Motion")
```

## 7. Data Structure Updates

### 7.1 Group Properties
```python
# In properties/group_props.py (new file)
class GroupMember(PropertyGroup):
    identifier: StringProperty()
    type: EnumProperty(items=[
        ('PROTEIN', 'Protein', ''),
        ('CHAIN', 'Chain', ''),
        ('DOMAIN', 'Domain', '')
    ])

class ProteinGroup(PropertyGroup):
    name: StringProperty(default="Group")
    members: CollectionProperty(type=GroupMember)
    is_expanded: BoolProperty(default=True)

# Register in Scene
bpy.types.Scene.pb_groups = CollectionProperty(type=ProteinGroup)
```

### 7.2 Visual Properties
```python
# Add to Scene properties
bpy.types.Scene.pb_visual_color = FloatVectorProperty(
    subtype='COLOR',
    size=3,
    min=0.0,
    max=1.0,
    default=(0.5, 0.5, 0.5),
    update=update_visual_color
)

bpy.types.Scene.pb_visual_representation = EnumProperty(
    items=[
        ('ribbon', 'Ribbon', ''),
        ('surface', 'Surface', ''),
        ('ball_stick', 'Ball & Stick', ''),
        ('cartoon', 'Cartoon', '')
    ],
    update=update_visual_representation
)
```

## 8. Implementation Order

1. **Phase 1: Workspace Setup**
   - Create workspace operator
   - Register panels in correct order
   - Set up panel categories

2. **Phase 2: Update Protein Outliner**
   - Add group support
   - Implement dual checkboxes
   - Update hierarchy display

3. **Phase 3: Visual Set-up Panel**
   - Create panel with color/representation
   - Implement update callbacks
   - Handle multi-selection

4. **Phase 4: Domain Maker**
   - Create context-sensitive panel
   - Implement chain detection
   - Add split chain operator (placeholder)

5. **Phase 5: Group Maker**
   - Create group data structures
   - Implement create/edit popup
   - Add group management logic
   - Update outliner for group display

6. **Phase 6: Mock Panels**
   - Create pose library panel
   - Create animate scene panel

7. **Phase 7: Integration**
   - Update import operators to auto-split chains
   - Ensure 2-way sync works with groups
   - Test all context-sensitive behaviors

## 9. Key Technical Considerations

### 9.1 Workspace Management
- Use `bpy.ops.workspace.append_activate()` or programmatic creation
- Store workspace setup in addon preferences
- Handle workspace switching on addon enable/disable

### 9.2 2-way Sync with Groups
- Extend existing outliner sync system
- Handle group member selection rules
- Implement visual feedback for grouped items

### 9.3 Domain Rules Engine
- Implement validation for domain spanning
- Prevent gaps in chain coverage
- Handle domain splitting logic

### 9.4 UI Performance
- Use `UIList` for large hierarchies
- Implement lazy loading for groups
- Cache selection states

## 10. Testing Requirements

1. **Workspace Tests**
   - Workspace creation on addon enable
   - Panel visibility and order
   - Layout persistence

2. **Outliner Tests**
   - Hierarchy display
   - 2-way sync with viewport
   - Group integration

3. **Context Sensitivity Tests**
   - Visual setup updates
   - Domain maker enabling
   - Multi-selection handling

4. **Group Tests**
   - Group creation/editing
   - Member management
   - Selection rules

## 11. Documentation Updates

- Update CLAUDE.md with new UI structure
- Create user documentation for group system
- Document domain rules and constraints

## 12. Future Considerations

- Animation timeline integration
- Pose interpolation system
- Advanced domain splitting algorithms
- Group-based batch operations

This PRP provides a comprehensive roadmap for implementing the new UI system while maintaining compatibility with existing functionality and preparing for future enhancements.