---
layout: default
title: Scene Lighting
---

# Scene Lighting

Click **Set Up Lighting**, just below **Create Keyframe** in the animation
panel. Choose a style and click **Apply** to see the result while the dialog stays
open. **OK** applies and closes. Closing after Apply keeps the applied result;
pending changes to the controls are discarded. The setup fits the visible scene
at the current frame.

| Style | Use it for |
|---|---|
| **Soft Studio** (default) | Balanced shading and soft shadows for most molecular scenes. |
| **Surface Detail** | Stronger directional shading to reveal pockets and solid surface shape. |
| **Bright Illustration** | Flat colors with optional dark contours for a 2D illustration. |

**Brightness** adjusts the whole setup. **Camera / View** orients the lights
from the active render camera, falling back to the viewport if no camera exists.
Choose **Current View** to use the viewport even when the scene has a camera.

Bright Illustration uses flat emission colors, a white background, and Standard
color management to keep molecular colors clear. **Outlines** draws black
silhouettes where a foreground surface meets a deeper surface or the background.
**Width (px)** sets their thickness from 1–4 pixels; the default is 1. Turn
Outlines off for plain flat shading. Switching to Studio or Surface Detail
restores the original surface shading, compositor, and color-management settings. Molecular opacity and animated fades continue to work. Automatic
conversion supports directly connected Principled materials; custom shader graphs
may retain their own shading.

**Mute Other Lights** hides existing lights without deleting them. To restore
their previous visibility, uncheck it and apply the setup again. The original
world is retained in the file; the setup uses its own neutral world. Molecular
materials, colors, transparency, camera framing, and animation are preserved.

**Show Lighting in Viewport** switches to Material Preview with scene lights
and world enabled. Bright Illustration enables viewport compositing and hides
floor/axis, cursor, relationship, and light/camera guides. Selection and editing
overlays remain available. Changing to another preset restores the saved guide
and compositor-display settings. The rig also works in Eevee and Cycles renders. Material
Preview uses Eevee, so transparent surfaces and indirect illumination may look
different from a final Cycles render. If the scene uses Workbench, the setup
switches the render engine to Eevee so the lights affect the render.

The rig fits evaluated geometry, including molecular point clouds, assembly
instances, DNA, and membranes. Hidden geometry, cameras, lights, and empty
controllers do not influence its size. Light power scales with the square of
scene size, keeping similar illumination for small proteins and large assemblies.

Run the button again after moving models, changing the camera angle, or adding
geometry. It updates the same **PB Scene Lighting** collection. It fits the
current frame, and does not follow moving models or cameras automatically.
Use Blender's **Undo** to undo a setup.

## Lighting approach and sources

Molecular visualization emphasizes readable shape and scientific colors.
[ChimeraX's lighting guide](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/lighting.html)
describes key, fill, and ambient lighting, and cautions that ambient shadowing
works better for surfaces than for sparse cartoons and sticks. Its gentle
lighting option emphasizes larger indentations instead of darkening every small
crevice. [VMD's rendering documentation](https://www-s.ks.uiuc.edu/Research/vmd/vmd-1.9.2/ug.pdf)
also describes broad, indirect illumination as a way to improve molecular depth
perception.

Studio and Surface Detail translate those principles into broad white area lights, fill
from below, and a rear light for separating overlapping forms. These presets are
starting points; their exact powers are ProteinBlender's choices, not published
scientific optima. They avoid adding ambient-occlusion nodes to molecular
materials. Shadowed area lights provide depth in both supported render engines;
Cycles also evaluates the neutral world's indirect illumination.
[Blender's light documentation](https://docs.blender.org/api/5.0/bpy.types.Light.html)
explains normalized power and light size, which the setup adjusts together.

Bright Illustration follows the flat-color and silhouette approach described by
the [ChimeraX Graphics toolbar](https://www.cgl.ucsf.edu/chimerax/docs/user/tools/graphics.html).
Its directional lights have zero power; emission supplies the flat color.
The silhouette compositor independently implements the depth comparison in
[ChimeraX's silhouette shader](https://github.com/RBVI/ChimeraX/blob/develop/src/bundles/graphics/src/fragmentShader.txt):
compare each pixel to the nearest surface within a circular pixel neighborhood,
then ink the farther side if the depth difference exceeds 1% of the fitted scene
depth. The fitted depth uses the bounding sphere and 1% padding, following
[ChimeraX's view calculation](https://github.com/RBVI/ChimeraX/blob/develop/src/bundles/graphics/src/view.py).
A bounded depth encoding preserves that comparison for perspective and
orthographic views. Existing compositor graphs are copied and the outline is
inserted before their image adjustments; switching presets restores the original.

This matches ChimeraX's flat-color/depth-silhouette method, rather than promising
identical pixels between different renderers. Molecular surface construction,
transparency handling, and antialiasing can differ. At very small image sizes,
steep continuous depth changes can also trigger the silhouette threshold.
[Blender's viewport compositor](https://docs.blender.org/manual/en/5.0/compositing/types/input/scene/render_layers.html)
supplies depth in Eevee Material Preview; a Cycles *Rendered viewport* does not
supply the same passes. Final Eevee and Cycles renders both support the effect.

See [before/after images and demonstration notes](change-notes/chimerax-illustration.md).


## Background and restoring default lighting

In **Bright Illustration**, choose **Background Color** in the lighting dialog,
then **Apply** or **OK**. This sets the world background in scene-lit preview and
renders; transparent-film exports still have a transparent background.

Choose **Remove Lighting** to remove the ProteinBlender rig and restore the world,
other lights, viewport shading, color management, and compositor from before the
preset was applied. In a new project this returns you to its default lighting.
