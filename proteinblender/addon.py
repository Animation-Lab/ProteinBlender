import bpy
from bpy.props import PointerProperty
from .core import CLASSES as core_classes
from .handlers import CLASSES as handler_classes
from .operators import CLASSES as operator_classes
from .panels import CLASSES as panel_classes
from .properties.protein_props import  register as register_protein_props, unregister as unregister_protein_props
from .properties.molecule_props import register as register_molecule_props, unregister as unregister_molecule_props
from .utils import scene_manager
from .layout.workspace_setup import ProteinWorkspaceManager

from .utils.molecularnodes import session
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
    for op in all_pb_classes:
        for cls in op:
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                print(e)
                pass
    bpy.types.Scene.MNSession = session.MNSession()  # type: ignore
    register_protein_props()
    register_molecule_props()
    # scene_manager.ProteinBlenderScene.get_instance()
    
    # Schedule workspace creation after 0.5 seconds
    bpy.app.timers.register(create_workspace_callback, first_interval=0.25)

    # Register undo handler if not already registered
    # if sync_molecule_list_after_undo not in bpy.app.handlers.undo_post:
        # bpy.app.handlers.undo_post.append(sync_molecule_list_after_undo)

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
    if hasattr(bpy.types.Scene, "MNSession"):
        del bpy.types.Scene.MNSession

    # Remove undo handler
    # if sync_molecule_list_after_undo in bpy.app.handlers.undo_post:
        # bpy.app.handlers.undo_post.remove(sync_molecule_list_after_undo)