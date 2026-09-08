---
layout: default
title: Scene Lighting
---

# Scene Lighting

Click **Set Up Lighting**, just below **Create Keyframe** in the animation
panel. Choose a style and click **OK** to fit a neutral light rig to the visible
scene at the current frame.

| Style | Use it for |
|---|---|
| **Soft Studio** (default) | Balanced shading and soft shadows for most molecular scenes. |
| **Surface Detail** | Stronger directional shading to reveal pockets and solid surface shape. |
| **Bright Illustration** | Even illumination without cast shadows for ribbons, sticks, and readable diagrams. |

**Brightness** adjusts the whole setup. **Camera / View** orients the lights
from the active render camera, falling back to the viewport if no camera exists.
Choose **Current View** to use the viewport even when the scene has a camera.

**Mute Other Lights** hides existing lights without deleting them. To restore
their previous visibility, uncheck it and apply the setup again. The original
world is retained in the file; the setup uses its own neutral world. Molecular
materials, colors, transparency, camera framing, and animation are preserved.

**Show Lighting in Viewport** switches to Material Preview with scene lights
and world enabled. The rig also works in Eevee and Cycles renders. Material
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

ProteinBlender translates those principles into broad white area lights, fill
from below, and a rear light for separating overlapping forms. These presets are
starting points; their exact powers are ProteinBlender's choices, not published
scientific optima. They avoid adding ambient-occlusion nodes to molecular
materials. Shadowed area lights provide depth in both supported render engines;
Cycles also evaluates the neutral world's indirect illumination.
[Blender's light documentation](https://docs.blender.org/api/5.0/bpy.types.Light.html)
explains normalized power and light size, which the setup adjusts together.
