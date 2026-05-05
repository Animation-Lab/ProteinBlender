"""DNA/RNA Builder module for ProteinBlender.

Allows users to generate DNA and RNA structures from nucleotide sequences,
with per-base colouring and full outliner integration.
"""

from . import dna_props
from . import dna_operators
from . import dna_panel


def register():
    dna_props.register()
    dna_operators.register()
    dna_panel.register()


def unregister():
    dna_panel.unregister()
    dna_operators.unregister()
    dna_props.unregister()
