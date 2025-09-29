# Pose System Documentation

## Overview

A **pose** in ProteinBlender is a saved configuration that records the spatial positions of groups (collections of chains/domains) relative to their parent protein's alpha carbon center. Poses are fundamental to the animation workflow, allowing users to save, manage, and transition between different protein conformations.

## Core Concepts

### What is a Pose?

A pose consists of:
1. **Groups**: Specific collections of protein chains and/or domains
2. **Relative Positions**: Spatial coordinates of each group relative to the protein's alpha carbon center
3. **Visual Snapshot**: A screenshot showing only the groups in that pose
4. **Metadata**: Name, creation time, and group associations

### Why Alpha Carbon Relative Positioning?

Positions are stored relative to the parent protein's **alpha carbon center of mass** rather than the protein's pivot point because:
- **Pivot Independence**: A protein's pivot point can change during editing, but the alpha carbon center remains constant
- **Biological Relevance**: Alpha carbons form the protein backbone and provide a stable reference frame
- **Animation Stability**: Ensures poses remain valid even after pivot adjustments
- **Consistency**: Provides a universal reference point across all proteins

### Default Pose

When a protein is first imported into ProteinBlender:
- A **"default" pose** is automatically created
- This pose captures the initial conformation from the PDB/structure file
- Serves as the baseline reference for all subsequent poses
- Cannot be deleted (only modified)

## User Interface Design

### Pose Grid View

The main pose interface displays poses as a **grid of thumbnails**:
- Each thumbnail shows a screenshot of the pose's groups
- All non-pose elements are hidden in the screenshot
- Thumbnails are clickable for interaction
- Visual indicators show the currently active pose
- Grid layout adapts to panel width

### Pose Interaction Panel

Clicking a pose thumbnail opens a control panel with four primary actions:

#### 1. Edit
- **Purpose**: Modify pose composition and properties
- **Functions**:
  - Add or remove groups from the pose
  - Rename the pose
  - Update pose description/notes
- **UI Elements**:
  - Group selection checklist
  - Text field for pose name
  - Save/Cancel buttons

#### 2. Capture Positions
- **Purpose**: Record current positions of all groups in the pose
- **Process**:
  1. Calculate each group's position relative to alpha carbon center
  2. Store transformation matrices (location, rotation, scale)
  3. Update pose timestamp
  4. Regenerate thumbnail screenshot
- **Feedback**: Visual confirmation when positions are captured

#### 3. Apply
- **Purpose**: Restore groups to their saved positions
- **Actions**:
  - Snap all pose groups to stored positions
  - Maintain relative positioning to alpha carbon
  - Trigger viewport update
- **Use Cases**:
  - Animation keyframing
  - Resetting after manual adjustments
  - Comparing different conformations

#### 4. Delete
- **Purpose**: Remove a pose from the system
- **Constraints**:
  - Cannot delete the default pose
  - Requires confirmation dialog
  - Removes associated screenshots and data

## Technical Implementation

### Data Structure

```python
class Pose:
    # Identification
    pose_id: str           # Unique identifier
    name: str              # User-friendly name
    protein_id: str        # Parent protein reference
    
    # Composition
    group_ids: List[str]   # Groups included in this pose
    
    # Spatial Data (per group)
    positions: Dict[str, Matrix4x4]  # Group ID -> Transform matrix
    # Transform matrix includes:
    # - Translation relative to alpha carbon
    # - Rotation (quaternion or euler)
    # - Scale factors
    
    # Metadata
    screenshot_path: str   # Thumbnail image location
    created_at: datetime   # Creation timestamp
    modified_at: datetime  # Last modification time
    is_default: bool      # True for the default pose
```

### Coordinate System

1. **Reference Point Calculation**:
   - Identify all alpha carbons (CA atoms) in the parent protein
   - Calculate center of mass of alpha carbons
   - Use as origin for relative positioning

2. **Position Storage**:
   ```python
   # For each group in pose
   relative_position = group.world_position - alpha_carbon_center
   relative_rotation = group.world_rotation
   relative_scale = group.world_scale
   ```

3. **Position Application**:
   ```python
   # When applying a pose
   group.world_position = alpha_carbon_center + stored_relative_position
   group.world_rotation = stored_relative_rotation
   group.world_scale = stored_relative_scale
   ```

### Screenshot Generation

- **Visibility Control**: Hide all scene elements except pose groups
- **Camera Setup**: Frame groups optimally for thumbnail
- **Resolution**: Standardized thumbnail size (e.g., 256x256)
- **Storage**: Save as PNG with pose ID as filename

## Animation Integration

### Keyframe Workflow

1. **Setup**: Create poses for key conformations
2. **Timeline**: Apply poses at specific frames
3. **Interpolation**: Blender handles transitions between poses
4. **Export**: Poses provide reproducible animation states

### Best Practices

- **Naming Convention**: Use descriptive names (e.g., "Open Conformation", "Substrate Bound")
- **Group Organization**: Keep related structural elements in the same pose
- **Version Control**: Capture positions before major edits
- **Documentation**: Add notes about biological significance

## Future Considerations

### Planned Enhancements

1. **Pose Interpolation**: Smooth transitions between poses
2. **Pose Libraries**: Share poses between projects
3. **Batch Operations**: Apply poses to multiple proteins
4. **Undo/Redo Support**: Full history for pose modifications
5. **Animation Curves**: Custom easing between poses

### API Extensions

```python
# Proposed API methods
pose_manager.create_pose(name, group_ids)
pose_manager.duplicate_pose(pose_id)
pose_manager.interpolate_poses(pose_a, pose_b, factor)
pose_manager.export_pose(pose_id, format='json')
pose_manager.import_pose(file_path)
```

## Error Handling

### Common Issues and Solutions

1. **Missing Groups**: Groups deleted after pose creation
   - Solution: Mark pose as incomplete, prompt for update

2. **Alpha Carbon Changes**: Protein structure modified
   - Solution: Recalculate reference point, update positions

3. **Coordinate System Mismatch**: Import/export between versions
   - Solution: Version markers in pose data, migration utilities

## Developer Notes

### Key Files

- `panels/pose_library_panel.py`: UI implementation
- `operators/pose_operators.py`: Core pose operations
- `utils/pose_manager.py`: Pose data management
- `properties.py`: Pose property definitions

### Testing Checklist

- [ ] Default pose creation on protein import
- [ ] Position capture with various group configurations
- [ ] Apply pose maintains relative positioning
- [ ] Screenshot generation and display
- [ ] Edit functionality updates all references
- [ ] Delete confirmation and cleanup
- [ ] Pivot change doesn't affect poses
- [ ] Multiple proteins with independent poses

## Glossary

- **Alpha Carbon (CA)**: The central carbon atom in an amino acid, forming the protein backbone
- **Group**: A collection of protein chains and/or domains treated as a unit
- **Conformation**: A specific 3D arrangement of a protein structure
- **Transform Matrix**: Mathematical representation of position, rotation, and scale