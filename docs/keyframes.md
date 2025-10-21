---
layout: default
title: Keyframe Animation
---

# Keyframe Animation

[Back to Home](index.html)

Create animations by keyframing puppet positions, poses, and colors.

## What is Keyframing?

**Keyframing** is the process of defining specific values at specific points in time. Blender automatically interpolates between keyframes to create smooth animation.

In ProteinBlender, you can keyframe:
- **Puppet positions** (location, rotation, scale)
- **Poses** (apply different conformations)
- **Colors** (change appearance over time)

## Animation Panel

The **Animation** panel provides tools for creating keyframes.

### Panel Sections

- **Puppet Selection**: Choose which puppet to animate
- **Keyframe Options**: Select what to keyframe (Location, Rotation, Scale, Pose, Color)
- **Create Keyframe** button: Adds keyframe at current frame

## Creating Your First Animation

### Simple Position Animation

1. **Select a puppet** from the dropdown in Animation panel

2. **Set first keyframe** at frame 1:
   - Move to frame 1 in timeline (bottom of screen)
   - Position the puppet where you want it to start
   - Check **Location** in Keyframe Options
   - Click **Create Keyframe**

3. **Set second keyframe** at frame 60:
   - Move to frame 60 in timeline
   - Move the puppet to a different position
   - Check **Location**  
   - Click **Create Keyframe**

4. **Play animation**:
   - Press Spacebar or click Play in timeline
   - Watch the puppet move smoothly from start to end position

## Keyframe Options

### Location, Rotation, Scale

- **Location (L)**: Keyframe position in 3D space
- **Rotation (R)**: Keyframe rotation angles
- **Scale (S)**: Keyframe size changes

You can keyframe any combination:
- **L + R**: Movement and rotation
- **L + R + S**: Full transformation
- **Just R**: Rotation in place

### Pose

The **Pose** option works with your saved poses:

1. Create poses in Pose Library (see [Manage Poses](poses.html))
2. At keyframe 1: Apply Pose A, check Pose, create keyframe
3. At keyframe 60: Apply Pose B, check Pose, create keyframe
4. Blender interpolates between the two conformations!

**Important**: Pose must be applied BEFORE creating the keyframe.

### Color

Animate color changes:

1. At keyframe 1: Set color in Visual Setup, check Color, create keyframe
2. At keyframe 60: Set different color, check Color, create keyframe
3. Domain smoothly transitions between colors

## Advanced Animation Workflows

### Conformational Change Animation

1. **Create poses** for different states (e.g., Open, Closed)
2. **Timeline**:
   - Frame 1: Apply "Open" pose, keyframe Pose
   - Frame 30: Apply "Closed" pose, keyframe Pose
   - Frame 60: Apply "Open" pose, keyframe Pose
3. **Result**: Protein opens and closes smoothly

### Multi-Property Animation

Combine multiple properties for richer animations:

**Frame 1:**
- Position puppet at (0, 0, 0)
- Apply "Unbound" pose
- Set color to blue
- Keyframe: Location + Pose + Color

**Frame 60:**
- Position puppet at (10, 0, 0)
- Apply "Bound" pose
- Set color to red
- Keyframe: Location + Pose + Color

**Result**: Protein moves, changes conformation, and changes color simultaneously.

### Multi-Puppet Coordination

Animate multiple puppets in the same scene:

1. **Puppet A** (Enzyme):
   - Keyframe at frames 1, 30, 60

2. **Puppet B** (Substrate):
   - Keyframe at frames 1, 30, 60
   - Coordinate timing to show binding

3. **Result**: Choreographed interaction between proteins

## Timeline Tips

### Navigating the Timeline

- **Scrub**: Drag the blue playhead to preview
- **Jump to frame**: Click in timeline or type frame number
- **Play**: Spacebar
- **Step forward/back**: Left/Right arrow keys

### Frame Rate

- Default: 24 frames per second (fps)
- 60 frames = 2.5 seconds of animation at 24fps
- Adjust in Output Properties panel

## Editing Keyframes

### Graph Editor

For precise control over interpolation:

1. Switch an editor to **Graph Editor**
2. Select your puppet object
3. See keyframes as curves
4. Edit curves to control animation timing

### Dope Sheet

For overview of all keyframes:

1. Switch an editor to **Dope Sheet**
2. See all keyframes across timeline
3. Move, copy, or delete keyframes

## Rendering Animation

Once you're happy with the animation:

1. Set output format in Output Properties
2. Set frame range (start and end frames)
3. Choose output path
4. Render > Render Animation (Ctrl+F12)

## Common Animation Scenarios

### Protein Folding

1. Create poses: Unfolded, Intermediate, Folded
2. Keyframe pose transitions
3. Add rotation for visual interest

### Enzyme-Substrate Binding

1. **Puppet 1** (Enzyme): Static or small movement
2. **Puppet 2** (Substrate): Approaches enzyme
3. Both change to "Bound" pose when close
4. Color changes to show activation

### Conformational Dynamics

1. Create multiple poses representing motion
2. Keyframe through poses in sequence
3. Loop by returning to first pose at end

## Tips and Best Practices

### Planning

- Sketch out key moments before keyframing
- Create all necessary poses first
- Test timing with rough keyframes

### Timing

- Fast movements: Fewer frames between keyframes
- Slow movements: More frames between keyframes
- Hold pose: Create two keyframes at same position

### Smooth vs. Mechanical

- Use Graph Editor to adjust curves for natural motion
- Ease-in and ease-out for realistic acceleration
- Linear interpolation for mechanical movements

### Performance

- Complex animations may slow viewport playback
- Reduce viewport complexity while animating
- Final render will be smoother

## Troubleshooting

### Keyframe Not Created

- Check that a puppet is selected
- Make sure at least one option is checked (Location, Rotation, etc.)
- Look for error messages in console

### Animation Jumps Instead of Interpolating

- Make sure you have keyframes at both start and end
- Check that you're keyframing the same properties
- Verify puppet wasn't deleted/recreated between keyframes

### Pose Changes Don't Animate Smoothly

- Poses must have same puppets
- Objects in poses must exist at both keyframes
- Check that pose was applied before keyframing

### Color Doesn't Animate

- Color keyframes affect geometry node inputs
- Make sure Color option is checked when keyframing
- Verify domain has material

## Next Steps

You now have the tools to create complete protein animations!

For more advanced topics:
- [Update Visuals](visuals.html) - Advanced coloring techniques
- [Manage Poses](poses.html) - Creating complex pose libraries

## Resources

- **Blender Animation Manual**: https://docs.blender.org/manual/en/latest/animation/
- **Graph Editor**: https://docs.blender.org/manual/en/latest/editors/graph_editor/
- **Rendering**: https://docs.blender.org/manual/en/latest/render/

---

[Back to Home](index.html) | [Previous: Manage Poses](poses.html)
