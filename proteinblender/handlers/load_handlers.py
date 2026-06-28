import bpy
from bpy.app.handlers import persistent
from ..layout import workspace_setup
from ..utils.scene_manager import ProteinBlenderScene

_workspace_manager = None


def _resync_domain_colors_from_rna(*, log_prefix: str = "") -> int:
    """For every multidomain chain object in the scene, push its saved
    ``domain_color`` RNA property back into the matching ``Color Common``
    node's ``Carbon`` socket.

    Tester report (Janet, Windows): "color of multidomain protein reset
    (to green) after saving and reopening file. This appears to happen
    if I don't change the colors of the chains from the default color
    chosen when the protein was built."

    We couldn't reproduce on a fresh build of 1ATN — both the per-domain
    ``Color Common_*`` tree's Carbon value AND the object's RNA
    ``domain_color`` property survive a save → wm.open_mainfile round
    trip. So the underlying lossy step is environment-dependent (likely
    Blender's purge-orphans or an MN version diff that resets the per-
    domain tree). The RNA prop is the reliable source-of-truth (it's a
    registered ``FloatVectorProperty`` on ``bpy.types.Object``, which
    Blender persists), so on every file open we walk every chain object
    and re-push the RNA value into Carbon. Idempotent — re-applying the
    same colour is a no-op."""
    n_synced = 0
    for obj in bpy.data.objects:
        # Only domain objects have the registered RNA domain_color prop +
        # the parent_molecule_id marker. Cheap pre-filter avoids walking
        # every Mesh in the scene.
        if "parent_molecule_id" not in obj.keys():
            continue
        rna_color = getattr(obj, "domain_color", None)
        if rna_color is None:
            continue
        target = tuple(rna_color)
        for mod in obj.modifiers:
            if mod.type != "NODES" or not mod.node_group:
                continue
            for n in mod.node_group.nodes:
                if (n.bl_idname == "GeometryNodeGroup"
                        and n.node_tree
                        and "Color Common" in n.node_tree.name
                        and "Carbon" in n.inputs):
                    current = tuple(n.inputs["Carbon"].default_value)
                    if current != target:
                        n.inputs["Carbon"].default_value = target
                        n_synced += 1
    if n_synced:
        print(f"ProteinBlender:{log_prefix} re-synced {n_synced} chain "
              f"colour(s) from saved RNA domain_color props")
    return n_synced


@persistent
def reset_scene_manager_on_load(dummy):
    """Reset scene manager when a new file is loaded/created.
    
    This ensures clean state and prevents stale references to deleted objects.
    Called before workspace creation to ensure fresh start.
    
    Following Blender addon best practices:
    - Use @persistent decorator for file lifecycle handlers
    - Reset state before any operations
    - Handle errors gracefully
    """
    try:
        ProteinBlenderScene.reset()
    except Exception as e:
        # Log error but don't fail - reset is best-effort
        print(f"ProteinBlender: Warning during scene manager reset: {e}")
        # Force reset even if cleanup failed
        ProteinBlenderScene._instance = None


@persistent
def create_workspace_on_load(dummy):
    """Recreate the Protein Blender workspace after loading/creating a file."""
    global _workspace_manager

    if "Protein Blender" in bpy.data.workspaces:
        return

    if _workspace_manager is None:
        _workspace_manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

    try:
        _workspace_manager.create_custom_workspace()
        _workspace_manager.add_panels_to_workspace()
        _workspace_manager.set_properties_context()
    except Exception as e:
        print(f"ProteinBlender: Error creating workspace: {e}")
        import traceback
        traceback.print_exc()


@persistent
def resync_domain_colors_on_load(dummy):
    """Re-push every domain's saved domain_color RNA prop into its
    Color Common Carbon socket. Defense-in-depth against the tester-
    reported bug where multidomain chain colours appear to reset to
    green on reopen — see ``_resync_domain_colors_from_rna`` for the
    full rationale.

    Runs after scene_manager reset + workspace setup so any rebuild
    those handlers do (which may rewrite Carbon defaults from the MN
    template) is overwritten by the RNA-prop source-of-truth."""
    try:
        _resync_domain_colors_from_rna(log_prefix=" load_post:")
    except Exception as e:
        # Best-effort — colour resync failure is never worth blocking
        # the load. Log and continue.
        print(f"ProteinBlender: domain colour resync failed: {e}")
        import traceback
        traceback.print_exc()


def _register_handler(handler_list, handler):
    """Helper to register a handler if not already registered."""
    if handler not in handler_list:
        handler_list.append(handler)


def _unregister_handler(handler_list, handler):
    """Helper to unregister a handler if registered."""
    if handler in handler_list:
        handler_list.remove(handler)


def register_load_handlers():
    """Register all persistent handlers.

    Order matters: reset_scene_manager_on_load must run before create_workspace_on_load
    to ensure clean state before workspace operations.
    """
    global _workspace_manager
    _workspace_manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")
    # Register reset handler first (runs before workspace creation)
    _register_handler(bpy.app.handlers.load_post, reset_scene_manager_on_load)
    # Register workspace creation handler
    _register_handler(bpy.app.handlers.load_post, create_workspace_on_load)
    # Re-sync chain colours from the RNA source-of-truth (runs last so
    # any rebuild the prior handlers do is overwritten)
    _register_handler(bpy.app.handlers.load_post, resync_domain_colors_on_load)


def unregister_load_handlers():
    """Unregister all load handlers."""
    _unregister_handler(bpy.app.handlers.load_post, reset_scene_manager_on_load)
    _unregister_handler(bpy.app.handlers.load_post, create_workspace_on_load)
    _unregister_handler(bpy.app.handlers.load_post, resync_domain_colors_on_load)


CLASSES = []
