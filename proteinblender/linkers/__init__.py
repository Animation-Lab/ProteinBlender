"""Puppet-scoped Flexible Linkers module for ProteinBlender.

Linkers connect chains/domains within a puppet, with catenary curve
physics, rigid binding zones, and hard distance constraints.
"""

from . import linker_props
from . import linker_geometry
from . import linker_operators
from . import linker_panel
from . import linker_handlers


def register():
    """Register all linker-related classes and properties."""
    linker_props.register()
    linker_geometry.register()
    linker_operators.register()
    linker_panel.register()
    linker_handlers.register()


def unregister():
    """Unregister all linker-related classes and properties."""
    linker_handlers.unregister()
    linker_panel.unregister()
    linker_operators.unregister()
    linker_geometry.unregister()
    linker_props.unregister()
