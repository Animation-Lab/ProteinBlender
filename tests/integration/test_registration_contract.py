"""Registration, handler, timer, and reload contracts.

Unlike the older hand-maintained panel list, these tests derive the expected
classes from the same public registration inventories the add-on ships.
"""

import bpy
import pytest

import harness_contract as HC


def _declared_classes():
    from proteinblender import addon
    from proteinblender.dna_builder import dna_operators, dna_panel, dna_props, bender
    from proteinblender.linkers import linker_geometry, linker_operators, linker_panel, linker_props
    from proteinblender.membrane_builder import membrane_operators, membrane_props

    classes = []
    for group in addon.ALL_PB_CLASSES:
        classes.extend(group)
    for module in (
        dna_operators, dna_panel, dna_props, bender,
        linker_geometry, linker_operators, linker_panel, linker_props,
        membrane_operators, membrane_props,
    ):
        classes.extend(getattr(module, "CLASSES", ()))
    # Preserve order while removing classes exposed by more than one inventory.
    return list(dict.fromkeys(classes))


@pytest.mark.integration
def test_every_declared_class_is_registered():
    missing = []
    for cls in _declared_classes():
        if not getattr(cls, "is_registered", False):
            missing.append(f"{cls.__module__}.{cls.__name__}")
    assert not missing, "declared Blender classes were not registered:\n  " + "\n  ".join(missing)


@pytest.mark.integration
def test_every_declared_operator_resolves_through_bpy_ops():
    missing = []
    for cls in _declared_classes():
        if not issubclass(cls, bpy.types.Operator):
            continue
        idname = getattr(cls, "bl_idname", "")
        if "." not in idname:
            missing.append(f"{cls.__name__}: invalid bl_idname {idname!r}")
            continue
        namespace, operator = idname.split(".", 1)
        try:
            getattr(getattr(bpy.ops, namespace), operator).get_rna_type()
        except Exception as exc:
            missing.append(f"{idname}: {type(exc).__name__}: {exc}")
    assert not missing, "declared operators unavailable through bpy.ops:\n  " + "\n  ".join(missing)


@pytest.mark.integration
def test_proteinblender_handlers_are_unique():
    assert not HC.proteinblender_handler_duplicates(), (
        "duplicate persistent handlers: "
        + "; ".join(HC.proteinblender_handler_duplicates()))


@pytest.mark.integration
def test_every_required_handler_is_installed_exactly_once():
    from proteinblender.handlers import frame_change_handler, load_handlers, selection_sync
    from proteinblender.linkers import linker_handlers
    from proteinblender.dna_builder import dna_props, bender
    from proteinblender.membrane_builder import force_fields, membrane_props
    from proteinblender.operators import pivot_operators
    from proteinblender.utils import scene_manager

    expected = {
        "load_post": (
            load_handlers.reset_scene_manager_on_load,
            load_handlers.create_workspace_on_load,
            load_handlers.resync_domain_colors_on_load,
            selection_sync.on_load_post,
            scene_manager.purge_orphaned_molecules_on_load,
            linker_handlers.linker_load_post_handler,
            dna_props._load_post_handler,
            bender._load_post_cleanup,
            membrane_props._load_post_handler,
            force_fields._on_load_post,
        ),
        "undo_post": (
            scene_manager.sync_molecule_list_after_undo,
            linker_handlers.linker_undo_post_handler,
        ),
        "redo_post": (
            scene_manager.sync_molecule_list_after_undo,
            linker_handlers.linker_redo_post_handler,
        ),
        "depsgraph_update_post": (
            scene_manager.detect_deleted_molecules,
            pivot_operators.custom_pivot_deselection_handler,
            linker_handlers.linker_constraint_and_update_handler,
            bender._on_depsgraph_update,
            force_fields._on_depsgraph_check,
        ),
        "frame_change_post": (
            frame_change_handler.update_colors_on_frame_change,
            linker_handlers.linker_frame_change_handler,
        ),
    }
    problems = []
    for list_name, functions in expected.items():
        installed = getattr(bpy.app.handlers, list_name)
        for function in functions:
            count = sum(item == function for item in installed)
            if count != 1:
                problems.append(f"{list_name}:{function.__module__}.{function.__name__} count={count}")
    assert not problems, "required handler registration mismatch:\n  " + "\n  ".join(problems)

    assert bpy.app.timers.is_registered(selection_sync._selection_poll), (
        "persistent selection poll timer is not registered")


@pytest.mark.integration
def test_registration_is_idempotent_and_does_not_duplicate_handlers():
    import proteinblender

    proteinblender._test_register()
    first = HC.proteinblender_handler_duplicates()
    proteinblender._test_register()
    second = HC.proteinblender_handler_duplicates()
    assert not first and not second, f"handler leak across reload: {first=} {second=}"
    assert all(getattr(cls, "is_registered", False) for cls in _declared_classes())
