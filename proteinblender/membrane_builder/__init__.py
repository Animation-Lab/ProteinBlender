"""Membrane Builder module for ProteinBlender.

Builds lipid bilayer membranes using Geometry Nodes. The user-facing
entry point is a "Create Membrane" button in the shared Builders panel
(see ``proteinblender.dna_builder.dna_panel``) — that fires the
``proteinblender.build_membrane`` popup dialog. The PB Outliner's edit
pencil reopens the same dialog pre-populated for an existing membrane.

Features:
- Specify width/height in nanometers
- Top view: bumpy from per-lipid random Y-rotation
- Side view: heads + tails (real bilayer cross-section)
- Optional pseudo-random bobbing animation
- Lattice-based surface deformation (keyframable)
- Up to 8 animatable circular holes per membrane (rename-able)
"""

from . import membrane_props
from . import membrane_operators
from . import force_fields


def register():
    membrane_props.register()
    membrane_operators.register()
    force_fields.register()


def unregister():
    force_fields.unregister()
    membrane_operators.unregister()
    membrane_props.unregister()
