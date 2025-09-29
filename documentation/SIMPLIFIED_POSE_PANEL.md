# Simplified Pose Panel Implementation

## Overview
Successfully implemented a simplified, group-based pose panel that works independently of molecule selection. The panel provides a clean interface for saving and restoring group positions.

## What Changed

### From (Complex):
- Poses tied to specific molecules
- Required molecule selection to function
- Complex dual-system architecture (MoleculeWrapper + MoleculeListItem)
- Validation checks and molecule lookups throughout

### To (Simple):
- Poses work directly with groups
- No molecule selection required
- Scene-level pose storage
- Direct group-to-pose relationship

## Implementation Details

### 1. New Property System (`proteinblender/properties/pose_props.py`)
```python
class ScenePose(PropertyGroup):
    name: StringProperty()           # Pose name
    group_ids: StringProperty()      # Comma-separated group IDs
    group_names: StringProperty()    # Display names
    transforms: CollectionProperty() # Object transforms
```

- Poses stored at scene level: `bpy.context.scene.pose_library`
- Each pose captures transforms for all objects in selected groups

### 2. Simplified Panel (`proteinblender/panels/pose_library_panel.py`)

#### Main Features:
- **Create Pose Button**: Opens dialog to select groups and name pose
- **Pose Cards**: Grid layout showing:
  - Pose name
  - Groups included
  - Screenshot placeholder
  - Three action buttons

#### Operators:
- `proteinblender.create_pose`: Select groups and save their positions
- `proteinblender.apply_pose`: Restore groups to saved positions
- `proteinblender.capture_pose`: Update pose with current positions
- `proteinblender.delete_pose`: Remove pose from library

### 3. Panel Layout
```
┌──────────────────────────────┐
│    [Create Pose]             │
├──────────────────────────────┤
│ ┌─────────┐  ┌─────────┐    │
│ │ Pose 1  │  │ Pose 2  │    │
│ │         │  │         │    │
│ │ Groups: │  │ Groups: │    │
│ │ - A,B   │  │ - C,D   │    │
│ │         │  │         │    │
│ │ [📷]    │  │ [📷]    │    │
│ │         │  │         │    │
│ │ [Apply] │  │ [Apply] │    │
│ │[Capture]│  │[Capture]│    │
│ │[Delete] │  │[Delete] │    │
│ └─────────┘  └─────────┘    │
└──────────────────────────────┘
```

## How It Works

### Creating a Pose:
1. User clicks "Create Pose"
2. Dialog shows all available groups (from outliner)
3. User selects which groups to include
4. System captures current positions of all objects in those groups
5. Pose is saved to scene.pose_library

### Applying a Pose:
1. User clicks "Apply" on a pose card
2. System looks up all transforms stored for that pose
3. Objects are moved to their saved positions

### Capturing (Updating) a Pose:
1. User adjusts group positions
2. Clicks "Capture" on existing pose
3. Current positions overwrite stored positions

## Key Improvements

1. **Simplicity**: No molecule dependencies or validation
2. **Clarity**: Direct group-to-pose relationship
3. **Flexibility**: Works with any groups in the scene
4. **Clean UI**: Simple card-based layout with clear actions

## Files Modified

### Created:
- `proteinblender/properties/pose_props.py` - Scene-level pose properties
- `proteinblender/panels/pose_library_panel.py` - Simplified panel (rewritten)

### Modified:
- `proteinblender/panels/__init__.py` - Updated imports and registration
- `proteinblender/addon.py` - Added pose property registration

## Usage

1. **Create groups** using the Group Maker panel
2. **Position groups** as desired in the viewport
3. **Click "Create Pose"** and select which groups to save
4. **Use pose cards** to Apply, Capture, or Delete poses

## Technical Notes

- Poses are stored per-scene (not per-file)
- Group membership determined by `outliner_items` with `item_type == 'GROUP'`
- Object lookup simplified but may need refinement for complex domain objects
- Screenshot functionality is placeholder - can be enhanced with actual viewport capture

## Future Enhancements

1. **Better object resolution**: Improve how group members map to Blender objects
2. **Screenshot implementation**: Capture actual viewport images
3. **Import/Export**: Save/load pose libraries
4. **Interpolation**: Smooth transitions between poses
5. **Group validation**: Handle cases where groups are deleted after pose creation