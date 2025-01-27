import bpy
from bpy.props import PointerProperty
from .core import CLASSES as core_classes
from .handlers import CLASSES as handler_classes
from .operators import CLASSES as operator_classes
from .panels import CLASSES as panel_classes
from .properties.protein_props import  register as register_protein_props, unregister as unregister_protein_props
from .properties.molecule_props import register as register_molecule_props, unregister as unregister_molecule_props
from .utils import scene_manager

from .utils.molecularnodes import session

# Track registered classes
registered_classes = set()

all_pb_classes = (
    core_classes,
    handler_classes,
    operator_classes,
    panel_classes,
    session.CLASSES,
)

def _test_register():
    try:
        register()
    except Exception as e:
        print(e)
        unregister()
        register()

def register():
    for op in all_pb_classes:
        for cls in op:
            try:
                print(f"Registering {cls}")
                bpy.utils.register_class(cls)
            except Exception as e:
                print(e)
                pass
    bpy.types.Scene.MNSession = session.MNSession()  # type: ignore
    register_protein_props()
    register_molecule_props()
    scene_manager.ProteinBlenderScene.get_instance()
    

def unregister():
    for op in reversed(all_pb_classes):
        for cls in op:
            try:
                print(f"Unregistering {cls}")
                bpy.utils.unregister_class(cls)
            except Exception as e:
                print(e)
    unregister_protein_props()
    unregister_molecule_props()
    del bpy.types.Scene.MNSession

'''
# Import all classes that need registration
from .operators import CLASSES as operator_classes
from .panels import CLASSES as panel_classes
from .properties import CLASSES as property_classes
from .panels.molecule_list_panel import (
    MOLECULE_PT_list,
    MOLECULE_OT_select,
    MOLECULE_OT_edit,
    MOLECULE_OT_delete
)
from .panels.molecule_edit_panel import MOLECULE_PT_edit
from .properties.molecule_props import MoleculeListItem

# Import other modules
from . import handlers
from .utils.scene_manager import ProteinBlenderScene

# Collect all classes that need registration
all_classes = (
    operator_classes +
    panel_classes +
    property_classes +
    MOLECULE_PT_list,
    MOLECULE_OT_select,
    MOLECULE_OT_edit,
    MOLECULE_OT_delete,
    MOLECULE_PT_edit,
    
    # Properties
    MoleculeListItem,
)

def _test_register():
    try:
        register()
    except Exception as e:
        print(e)
        unregister()
        register()

def register():
    # Register all classes
    for cls in all_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"Failed to register {cls}: {e}")
            pass
            
    # Register scene properties
    bpy.types.Scene.protein_props = PointerProperty(type=MoleculeListItem)
    
    # Initialize scene manager
    ProteinBlenderScene.initialize()
    
    # Register handlers
    handlers.register()

def unregister():
    # Unregister handlers first
    handlers.unregister()
    
    # Remove scene properties
    del bpy.types.Scene.protein_props
    
    # Unregister all classes
    for cls in reversed(all_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"Failed to unregister {cls}: {e}")
            pass
'''

