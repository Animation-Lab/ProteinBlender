---
layout: default
title: Update Visuals
---

# Update Visuals

[Back to Home](index.html)

Customize the appearance of your proteins with colors and molecular representation styles.

## Overview

The **Visual Setup** panel lets you:
- Change protein colors
- Switch between molecular representation styles
- Apply changes to selected proteins, chains, or domains

## Accessing Visual Setup

1. Import a protein (see [Import Proteins](import.html))
2. Find the **Visual Setup** panel below the Protein Outliner
3. The panel shows color and style options

## Changing Colors

### Apply Color to Selection

1. **Select** an item in the Protein Outliner (protein, chain, or domain)
2. In the **Visual Setup** panel, click the **color picker**
3. Choose your desired color
4. Click **Apply Color**

The color will be applied based on your selection:
- **Protein selected**: All chains and domains get the color
- **Chain selected**: All domains in that chain get the color  
- **Domain selected**: Only that specific domain gets the color

### Color Tips

- **Distinct chains**: Use different colors for each chain
- **Functional domains**: Color active sites or binding sites differently
- **Emphasis**: Use bright colors for regions of interest
- **Publication**: Use standard color schemes (e.g., blue/red for charges)

## Changing Molecular Styles

### Available Styles

ProteinBlender supports multiple molecular representations:

- **Cartoon**: Classic ribbon/cartoon representation (default)
- **Surface**: Molecular surface (good for visualizing shape)
- **Ribbon**: Simplified backbone ribbon
- **Ball and Stick**: Atomic detail with bonds
- **Spheres**: Space-filling representation
- **And more**: Additional styles from MolecularNodes

### Apply Style to Selection

1. **Select** an item in the Protein Outliner
2. In the **Visual Setup** panel, choose a **Style** from the dropdown
3. Click **Apply Style**

Like colors, styles are applied hierarchically based on selection.

## Independent Domain Styling

One of ProteinBlender's powerful features is **independent domain styling**:

1. Split a chain into domains (see Domain Maker panel)
2. Select individual domains
3. Apply different colors and styles to each domain

Example: Show an active site as ball-and-stick while keeping the rest as cartoon.

## Combining Colors and Styles

You can apply both colors and styles together:

1. Select your target (protein/chain/domain)
2. Choose a color
3. Choose a style
4. Apply both (or apply one at a time)

## Tips and Best Practices

### For Publications

- Use consistent color schemes
- High contrast for clarity
- Cartoon for overall structure, ball-and-stick for details

### For Presentations

- Bold, distinct colors
- Larger molecular styles (surface, spheres)
- Color code by function or region

### For Animations

- Start with simpler styles (faster rendering)
- Use color changes to highlight dynamics
- Test render times before committing

## Troubleshooting

### Color Doesn't Change

- Make sure you clicked **Apply Color** after selecting the color
- Check that the correct item is selected in the outliner
- If domain is in a puppet, color the puppet instead

### Style Doesn't Update

- Styles may take a moment to update (especially surface)
- Check Blender console for errors
- Try switching to another style and back

### Colors Look Different Than Expected

- Blender's lighting affects color appearance
- Adjust viewport shading (top-right of viewport)
- Try Material Preview or Rendered view mode

## Advanced: Custom Colors

For more advanced color control:

1. Select a domain
2. Use Blender's shader editor to modify materials
3. ProteinBlender creates unique materials per domain

Note: Manual material edits may be overwritten if you use Apply Color again.

## Next Steps

Now that you know how to style proteins, learn how to:

- [Create Puppets](puppets.html) - Group parts for coordinated changes
- [Manage Poses](poses.html) - Save different conformations

---

[Back to Home](index.html) | [Previous: Import Proteins](import.html) | [Next: Create Puppets](puppets.html)
