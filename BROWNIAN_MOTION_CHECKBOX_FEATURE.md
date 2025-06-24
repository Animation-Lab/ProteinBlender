# Brownian Motion Checkbox Feature

## Overview

The Brownian Motion Checkbox feature gives users granular control over protein animation between keyframes. Users can now choose whether the animation between any two keyframes uses Brownian motion simulation or linear interpolation.

## How It Works

### Keyframe Behavior

- **Keyframe 1**: The first keyframe doesn't have a Brownian motion checkbox since there's no previous keyframe to animate from
- **Keyframe 2 and beyond**: Each keyframe has a "Use Brownian Motion" checkbox that controls the animation from the previous keyframe to the current keyframe

### Animation Types

1. **Brownian Motion** (checkbox checked):
   - Adds random jitter and organic movement between keyframes
   - Uses the intensity, frequency, seed, and resolution parameters
   - Creates intermediate keyframes with randomized transforms

2. **Linear Motion** (checkbox unchecked):
   - Uses smooth linear interpolation between keyframes
   - Provides predictable, straight-line movement
   - No intermediate keyframes are created

## User Interface Changes

### Keyframe Creation Dialog

When creating a new keyframe:
- If it's the first keyframe: No Brownian motion checkbox is shown
- If it's the second or later keyframe: A "Use Brownian Motion" checkbox appears
- Brownian motion parameters are only enabled when the checkbox is checked

### Keyframe List Panel

In the molecule list panel, each keyframe (except the first) displays:
- A toggle showing either "Brownian Motion" or "Linear Motion" 
- An icon indicating the current state (checkmark for Brownian, X for linear)
- The toggle can be clicked to change the animation type

### Edit Keyframe Dialog

When editing an existing keyframe:
- The Brownian motion checkbox is shown for keyframes after the first
- Brownian motion parameters are only enabled when the checkbox is checked
- Changes trigger immediate recomputation of the animation path

## Implementation Details

### Property Changes

Added to `MoleculeKeyframe` class:
```python
use_brownian_motion: BoolProperty(
    name="Use Brownian Motion", 
    description="Use Brownian motion for animation to this keyframe from the previous keyframe",
    default=True,
    update=lambda self, context: self.recompute_brownian_motion(context)
)
```

### Automatic Recomputation

When the checkbox state changes:
1. Existing intermediate keyframes between the affected keyframes are cleared
2. If Brownian motion is enabled, new intermediate keyframes are baked with random motion
3. If linear motion is selected, only the endpoint keyframes remain for smooth interpolation

### Operator Updates

- `MOLECULE_PB_OT_keyframe_protein`: Updated to include the checkbox and respect its state
- `MOLECULE_PB_OT_edit_keyframe`: Updated to allow editing the checkbox and recompute paths

## Usage Examples

### Creating Mixed Animation

1. Create keyframe 1 at frame 1 (protein at start position)
2. Create keyframe 2 at frame 50 with Brownian motion enabled (organic movement)
3. Create keyframe 3 at frame 100 with Brownian motion disabled (smooth linear movement)
4. Result: Organic motion from frame 1-50, smooth motion from frame 50-100

### Changing Animation Style

1. Select a keyframe in the list panel
2. Click the "Brownian Motion" / "Linear Motion" toggle
3. The animation path automatically updates between the affected keyframes

## Technical Benefits

- **Performance**: Linear interpolation uses fewer keyframes and is more performant
- **Flexibility**: Users can mix animation styles within a single sequence
- **Predictability**: Linear segments provide predictable motion when needed
- **Artistic Control**: Users can choose the right animation style for each segment

## Backward Compatibility

- Existing keyframes default to `use_brownian_motion = True` to maintain current behavior
- All existing functionality remains unchanged
- The feature is additive and doesn't break existing workflows

## Testing

Run the test script to verify functionality:
```bash
python test_brownian_motion_checkbox.py
```

The test verifies:
- Property creation and access
- UI integration
- Toggle functionality
- Recomputation behavior 