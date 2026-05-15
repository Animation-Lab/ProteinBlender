"""Membrane Builder module for ProteinBlender.

Builds lipid bilayer membranes using Geometry Nodes:
- Specify width/height in nanometers
- Top view: bumpy from per-lipid random Y-rotation
- Side view: heads + tails (real bilayer cross-section)
- Optional pseudo-random bobbing animation
- Lattice-based surface deformation (keyframable)
- Up to 8 animatable circular holes per membrane
"""

from . import membrane_props
from . import membrane_operators
from . import membrane_panel


def register():
    membrane_props.register()
    membrane_operators.register()
    membrane_panel.register()


def unregister():
    membrane_panel.unregister()
    membrane_operators.unregister()
    membrane_props.unregister()
