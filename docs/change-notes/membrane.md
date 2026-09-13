# Membrane force fields

Branch: `fix/weekly-membrane-force-fields`, based on `alpha` (`7ca96f0`).

## Reproduced defect

A protein's selected force field targeted its controller, even when a chain had moved elsewhere. The new regression measured lipid clearance around the displayed chain before and after selecting the protein: both were 0.025575 Blender units. The target assignment succeeded but the membrane did not part around the chain.

## Changes

Protein targets now expand to their displayed chains/domains. Duplicate selections are deduplicated, and the picker checks the resulting object count against field capacity. Geometry nodes derive each field's center and bounding sphere from evaluated geometry in membrane coordinates, including points and instances. Edited pivots no longer determine the field center. Spacing remains membrane-specific; legacy per-protein spacing is inherited by its displayed chains.

The membrane node-tree version advances to 39 so old saved trees rebuild through the existing migration path. The old Radius socket remains for compatibility, while active field size comes from geometry plus the new Spacing input. The gap remains a geometric illustration based on bounding spheres, not a molecular force simulation.

## Demonstration

1. Import ubiquitin and create a flat membrane.
2. Move its chain sideways, then choose the whole protein in the membrane's force-field picker. The gap follows the displayed chain.
3. Set the chain pivot to its first residue. The protein stays still and so does the gap.
4. Lift the chain well above the membrane. The gap closes; lower it and the gap returns.
5. Add a second membrane and assign targets only to the first. The second remains unchanged. Clear the first target list to restore it.

## Verification

The original geometry regression failed before the change. The 34-test Blender 5.2 membrane suite passes after the fix, covering target isolation, splits, rename, clear, moved chains, pivot invariance, height, existing builders and overlapping fields. Background tests process only the refresh scheduled by the actual depsgraph handler because background Blender does not tick timers. Foreground verification additionally observes movement through the real event loop. Final aggregate/version/persistence results are in the weekly demo notes.
