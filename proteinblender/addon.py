import bpy
from bpy.props import PointerProperty, BoolProperty
from .core import CLASSES as core_classes
from .handlers import CLASSES as handler_classes
from .operators import CLASSES as operator_classes
from .panels import CLASSES as panel_classes
from .properties.protein_props import  register as register_protein_props, unregister as unregister_protein_props
from .properties.molecule_props import register as register_molecule_props, unregister as unregister_molecule_props
from .utils import scene_manager
from .layout.workspace_setup import ProteinWorkspaceManager

from .utils.molecularnodes import session
from .utils.molecularnodes.props import MolecularNodesObjectProperties
# from .utils.scene_manager import ProteinBlenderScene, sync_molecule_list_after_undo

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

def create_workspace_callback():
    workspace_manager = ProteinWorkspaceManager()
    workspace_manager.create_custom_workspace()
    workspace_manager.add_panels_to_workspace()
    workspace_manager.set_properties_context()
    return None  # Remove the timer

def register():
    # Try unregistering first to clean up any previous state
    try:
        unregister()
    except Exception as e:
        print(f"Unregister during startup failed: {e}")
        pass
    
    # Register classes
    for op in all_pb_classes:
        for cls in op:
            try:
                bpy.utils.register_class(cls)
                registered_classes.add(cls)
            except Exception as e:
                print(f"Failed to register {cls.__name__}: {e}")
                pass
    
    # Register MolecularNodes session
    if not hasattr(bpy.types.Scene, "MNSession"):
        bpy.types.Scene.MNSession = session.MNSession()  # type: ignore
    
    # Register properties
    register_protein_props()
    register_molecule_props()
    
    # Register domain expanded property if not already registered
    if not hasattr(bpy.types.Object, "domain_expanded"):
        bpy.types.Object.domain_expanded = BoolProperty(default=False)
    
    # Register MolecularNodes object properties
    try:
        bpy.utils.register_class(MolecularNodesObjectProperties)
    except Exception as e:
        print(f"Failed to register MolecularNodesObjectProperties: {e}")
        pass
    
    # Register object properties if not already registered
    if not hasattr(bpy.types.Object, "mn"):
        bpy.types.Object.mn = PointerProperty(type=MolecularNodesObjectProperties)
    
    # Schedule workspace creation after 0.5 seconds
    bpy.app.timers.register(create_workspace_callback, first_interval=0.25)

    # Register undo handler if not already registered
    # if sync_molecule_list_after_undo not in bpy.app.handlers.undo_post:
        # bpy.app.handlers.undo_post.append(sync_molecule_list_after_undo)

def unregister():
    # Clear any pending timers to prevent creation of new workspace during unregistration
    if hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(create_workspace_callback):
        bpy.app.timers.unregister(create_workspace_callback)

    # Unregister properties
    try:
        unregister_protein_props()
    except Exception as e:
        print(f"Failed to unregister protein props: {e}")
        pass
    
    try:
        unregister_molecule_props()
    except Exception as e:
        print(f"Failed to unregister molecule props: {e}")
        pass
    
    # Unregister domain expanded property
    if hasattr(bpy.types.Object, "domain_expanded"):
        del bpy.types.Object.domain_expanded
    
    # Remove session
    if hasattr(bpy.types.Scene, "MNSession"):
        del bpy.types.Scene.MNSession
    
    # Remove object properties
    if hasattr(bpy.types.Object, "mn"):
        del bpy.types.Object.mn
    
    # Unregister MolecularNodesObjectProperties
    try:
        bpy.utils.unregister_class(MolecularNodesObjectProperties)
    except Exception as e:
        print(f"Failed to unregister MolecularNodesObjectProperties: {e}")
        pass

    # Unregister classes
    for op in reversed(all_pb_classes):
        for cls in reversed(op):
            try:
                bpy.utils.unregister_class(cls)
                if cls in registered_classes:
                    registered_classes.remove(cls)
            except Exception as e:
                print(f"Failed to unregister {cls.__name__}: {e}")
                pass