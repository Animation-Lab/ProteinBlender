---
layout: default
title: Manage Poses
---

# Manage Poses

[Back to Home](index.html)

Save and restore different protein conformations using the Pose Library.

## What is a Pose?

A **pose** is a saved snapshot of puppet positions. Poses capture:
- Location, rotation, and scale of objects in selected puppets
- Multiple puppets can be included in a single pose
- Poses can be applied to restore saved positions

Think of poses as "bookmarks" for different protein conformations or arrangements.

## Creating a Pose

### Prerequisites

Before creating poses, you need:
1. At least one puppet created (see [Protein Puppets](puppets.html))
2. Puppets positioned as desired in the 3D viewport

### Step-by-Step

1. **Position your puppets** in the 3D viewport
   - Use transform tools (G for move, R for rotate, S for scale)
   - Arrange proteins to show the conformation you want to save

2. **Open Pose Library** panel

3. Click **Create Pose**

4. In the dialog:
   - **Name the pose** (e.g., "Open State", "Bound", "Closed")
   - **Select which puppets** to include
   - Check the boxes next to puppets you want to save

5. Click **OK**

The new pose appears as a card in the Pose Library panel.

## Understanding Pose Cards

Each pose is displayed as a card showing:
- **Pose name**
- **Included puppets** (listed below name)
- **Screenshot placeholder** (for visual reference)
- **Action buttons**: Apply, Capture, Delete

## Applying a Pose

To restore a saved pose:

1. Find the pose card in the Pose Library panel
2. Click the **Apply** button
3. All puppets in the pose snap to their saved positions

This is useful for:
- Switching between conformational states
- Returning to a reference position
- Creating keyframes at specific poses

## Updating a Pose (Capture)

If you've adjusted puppet positions and want to update an existing pose:

1. **Position puppets** as desired
2. Find the pose card you want to update
3. Click the **Capture** button
4. Current positions overwrite the saved positions

## Deleting a Pose

To remove a pose from the library:

1. Find the pose card
2. Click the **Delete** (trash) button
3. The pose is removed permanently

## Multiple Poses Workflow

Create multiple poses to represent different states:

### Example: Enzyme Catalytic Cycle

1. **Pose 1: "Substrate Free"** - Open active site
2. **Pose 2: "Substrate Bound"** - Closed around substrate
3. **Pose 3: "Transition State"** - Intermediate conformation
4. **Pose 4: "Product Release"** - Reopening

### Example: Protein-Protein Interaction

1. **Pose 1: "Dissociated"** - Proteins far apart
2. **Pose 2: "Approaching"** - Proteins near each other
3. **Pose 3: "Bound"** - Proteins in complex

## Poses and Animation

Poses are designed to work with keyframe animation:

1. Create poses for key conformations
2. Apply a pose
3. Add a keyframe (see [Keyframe Animation](keyframes.html))
4. Move to next frame
5. Apply different pose
6. Add another keyframe

Blender interpolates between poses automatically!

## Tips and Best Practices

### Naming

Use descriptive pose names that indicate the biological state:
- "ATP_Bound"
- "Open_Conformation"
- "Active_State"
- "Inhibitor_Complex"

### Organization

- Create poses for distinct conformational states
- Save intermediate poses for smoother animations
- Group related poses by naming (e.g., "Complex_1", "Complex_2")

### Testing

Before creating final poses:
- Test that puppets return to correct positions when applied
- Verify all needed puppets are included
- Check that transformations look correct

## Pose Storage

Poses are stored:
- **Per-scene**: Poses are saved with the Blender file
- **Not per-file**: Poses don't transfer between different .blend files
- **In blend file**: Saving the .blend file preserves all poses

To share poses between files, you would need to manually recreate them.

## Troubleshooting

### Pose Doesn't Apply Correctly

- **Puppets deleted**: If puppets in the pose no longer exist, application fails
- **Puppets renamed**: Pose references puppets by ID, not name
- **Objects moved**: Make sure you're applying to the correct scene

### Can't Create Pose

- **No puppets exist**: Create at least one puppet first
- **No puppets selected**: Check at least one puppet in the creation dialog
- **Duplicate name**: Pose names should be unique (though not enforced)

### Puppets Don't Move When Applying Pose

- Check that the pose includes those puppets
- Verify puppets still exist in the scene
- Check Blender console for errors

## Advanced Usage

### Partial Pose Application

Currently, poses apply all included puppets at once. To apply only some puppets:
1. Create separate poses for different puppet groups
2. Apply poses selectively

### Pose Interpolation

For smooth transitions between poses:
1. Create keyframes at two different poses
2. Blender interpolates positions automatically
3. Adjust interpolation curve in Graph Editor

## Next Steps

Now that you understand poses, learn how to:

- [Keyframe Animation](keyframes.html) - Animate transitions between poses
- [Update Visuals](visuals.html) - Combine pose changes with color animations

---

[Back to Home](index.html) | [Previous: Create Puppets](puppets.html) | [Next: Keyframe Animation](keyframes.html)
