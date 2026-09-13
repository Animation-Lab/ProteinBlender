# Outliner usability

Branch: `fix/weekly-outliner`, based on `alpha` (`7ca96f0`).

## Changes

- Mixed swatches use two, three, or four equal native color bands in the same space as a solid swatch. More than four colors remain intact in the model; only the preview is capped. The middle color is no longer split across separate icon images.
- Clicking any band opens Blender's color picker and edits the shared color for that row. Merely opening the picker does not recolor the object.
- The PB Outliner right-click menu spells out the actions belonging to the clicked row, including color, duplicate, pivot, edit, delete, selection, and visibility where applicable. It reuses the icon actions and their target resolution.
- Edit Chain and copied-chain dialogs omit Start / Center / End pivot buttons. The outliner Edit Pivot action remains available.
- Removed the obsolete generated palette-image cache.

## Demonstration

1. Import a protein and split a chain into three domains. Give them red, green, and blue colors.
2. Compare the protein/chain swatch with solid domain swatches: equal total width, three bands, uninterrupted green center.
3. Split into six differently colored domains. The parent shows only four colors, while all six domain colors remain intact.
4. Right-click the protein name, then a chain, domain, and membrane. The menu reflects that exact row and uses readable labels. Try Select, Hide, Show, and Edit.
5. Open Edit Chain and show the simplified Visual Set-up section. Use Edit Pivot from the outliner if needed.

## Verification

- Initial focused Blender 5.2 baseline: 42 passed across outliner colors, conformations, lighting, and membrane targets.
- Outliner changes: 52 passed across colors, hierarchy, visual-edit dialogs, and registration.
- Foreground UI suite exercised real dialogs, selection, undo/redo, and measured the three-color swatch against solid swatches in screenshot pixels (118 pixels on this display). It also right-clicked the actual protein row and verified context targeting.
- Final aggregate and supported-version results are recorded in the weekly demo notes.
