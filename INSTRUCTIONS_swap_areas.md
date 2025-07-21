# How to Move Dope Sheet to Bottom in Blender

## Method 1: Quick Keyboard Swap (Recommended)

1. **Position your mouse cursor** on the border line between the Dope Sheet (top) and 3D Viewport (bottom)
   - The cursor will change to a resize cursor (↕)

2. **Right-click** on this border

3. **Select "Swap Areas"** from the context menu

The areas will instantly swap positions while keeping their exact sizes!

## Method 2: Using Area Options

1. In the Dope Sheet (currently at top), look for the small icon in the top-left corner of the editor
2. Click and drag this icon down to the 3D Viewport area
3. The areas will swap

## Method 3: Manual Recreation

If the above doesn't work:

1. Change the top area (Dope Sheet) temporarily to another editor type (like Outliner)
2. Change the bottom area (3D View) to Dope Sheet  
3. Change the top area back to 3D View
4. Adjust the border between them to get the desired size

## Why the Script Might Not Work

Blender's area management is deeply integrated with its UI system. While we can change area types programmatically, the actual position swapping is better done through Blender's built-in UI operations.

The coordinate system in Blender can be confusing:
- Y=0 is at the bottom of the screen
- Y increases as you go up
- But the visual layout may not directly correspond to these coordinates due to how Blender manages its interface