---
layout: default
title: Update Visuals
---

# Update Visuals

[Back to Home](index.html)

Customize the appearance of your proteins with colors and molecular representation styles.

## Overview

Every protein, chain and domain carries its own **Visual Set-up**:
- Color
- Molecular representation style
- Membrane force field
- Pivot point

You reach it from the item itself, so what you are editing is never in doubt.

## Accessing Visual Set-up

1. Import a protein (see [Import Proteins](import.html))
2. In the **Protein Outliner**, find the row you want to change
3. Click the **pencil** button on that row

Each row opens the dialog that suits it:

| Row | Pencil opens | Contains |
|-----|--------------|----------|
| Protein | **Edit Protein** | Visual Set-up for the whole molecule |
| Chain | **Edit Chain** | chain name, domain layout, and Visual Set-up |
| Domain | **Edit Domain** | domain name and Visual Set-up |

## Changing Colors

1. Click the **pencil** on the row you want to recolor
2. Click the **Color** swatch and pick a color

The color applies as you pick it, to everything that row covers:
- **Protein row**: the molecule and all of its chains and domains
- **Chain row**: every domain in that chain
- **Domain row**: only that domain

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

### Apply a Style

1. Click the **pencil** on the row you want to restyle
2. Choose a **Representation** from the dropdown

Like colors, the style reaches everything the row covers, immediately.

The dialog opens showing what the item currently looks like. If its parts
disagree - say a chain whose domains are half cartoon and half surface - the
dropdown reads **Multiple**, and the colour swatch shows a neutral grey with a
note saying so, since a swatch has no way to draw "mixed". Picking a real value
resolves them all; leaving it alone changes nothing.

## Independent Domain Styling

One of ProteinBlender's powerful features is **independent domain styling**:

1. Split a chain into domains with the **pencil** on its chain row
2. Open each domain's own **pencil**
3. Give each one its own color and style

Example: Show an active site as ball-and-stick while keeping the rest as cartoon.

## Pivot Point

The same dialog sets what the item rotates about:

- **Start** - the first residue (N-terminus)
- **Center** - the centroid of the item's alpha carbons
- **End** - the last residue (C-terminus)

A protein gets a *single* pivot shared by all of its chains and domains, so the
whole molecule swings about one point.

### Edit Pivot

To place a pivot by hand, use the **pivot** button on the outliner row rather
than the dialog - it needs the viewport for as long as you are dragging, and a
dialog would close over it.

1. Click the **pivot** button on the row. An orange helper appears on the
   item's current pivot and the Move tool activates
2. Drag the helper where you want the pivot
3. Click the **pivot** button again. The helper's position becomes the pivot
   and the helper disappears

The button stays pressed for as long as the mode is open, so you can orbit,
select other things and come back - only the button ends it. Opening and
closing it without dragging changes nothing.

Clicking another row's pivot button applies the one you are holding and moves
on to that row. Choosing Start, Center or End abandons an open placement.

## Membrane Force Field

Turn **Membrane Force Field** on to make the lipids of any membrane part around
the item, and set how far they stand off with **Spacing**.

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

- Check you opened the pencil on the row you meant - the dialog names the item
- If the domain is in a puppet, color the puppet instead

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

Note: Manual material edits may be overwritten the next time you pick a color
in the dialog.

## Next Steps

Now that you know how to style proteins, learn how to:

- [Create Puppets](puppets.html) - Group parts for coordinated changes
- [Manage Poses](poses.html) - Save different conformations

---

[Back to Home](index.html) | [Previous: Import Proteins](import.html) | [Next: Create Puppets](puppets.html)
