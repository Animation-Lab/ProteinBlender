# Lighting

The later [ChimeraX-style silhouette update](chimerax-illustration.md) replaces
the curvature-based contours described in this historical change note.

Branch: `fix/weekly-lighting`, based on `alpha` (`7ca96f0`).

Bright Illustration now uses flat molecular colors and optional dark contours in Material Preview, Eevee, and Cycles. Apply updates the scene while the settings dialog remains open. Closing after Apply keeps the applied result. Reapplying reuses the existing rig and shader wrappers; Studio/Surface restore the original shaders through a bypass. Molecular transparency continues to work.

ChimeraX's flat preset uses ambient-only illumination, no shadows, and silhouettes ([official Graphics toolbar](https://www.cgl.ucsf.edu/chimerax/docs/user/tools/graphics.html)). ProteinBlender uses emission for uniform colors and view-dependent surface contours. Contour width depends on curvature; this is not an exact implementation of ChimeraX's screen-space depth outlines. Custom shader graphs without a directly connected Principled shader remain unchanged.

## Demonstration

1. Import a protein, open Set Up Lighting, and choose Bright Illustration.
2. Press Apply. The model becomes flat while the dialog stays open.
3. Toggle Outlines and Apply again. Compare the contours, then adjust Brightness.
4. Apply Studio to restore shading. Switch back and forth; there is still one four-light rig.
5. Close after Apply to retain the result. Save/reopen using the weekly persistence checks.

## Verification

The 17-test Blender 5.2 lighting suite passes, including real molecular renders, neutral color, instance bounds, mute/restore, flat sphere pixels, visible dark contours, idempotent reapplication, restored Studio shading, and molecular opacity. The foreground suite checks the Apply operator while the parent dialog is modal, then verifies that Escape still reaches the parent and preserves applied settings. Aggregate results are recorded in the weekly demo notes.

Integration adds an eighteenth regression for morph-context opacity and animated
fades. The existing frame-change handler synchronizes the flat wrapper with the
original shader's animated alpha. A fresh-process save/reopen test caught a
dependency cycle in the first synchronization approach; the final implementation
uses no shader-socket driver and passes that persistence check.
