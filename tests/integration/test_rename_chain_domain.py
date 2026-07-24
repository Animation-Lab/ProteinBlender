"""Feature: rename chains and domains from the Protein Outliner.

The Rename button drives ``proteinblender.rename_domain`` with an explicit
``target_item_id`` + ``item_type``. A rename must (a) show on the outliner row
immediately and (b) survive an outliner rebuild - domains persist through the
wrapper's domain.name, chains through the list item's ``chain_custom_names``
JSON map (chain rows are otherwise regenerated from auth_chain_id_map).
"""

import json
import pytest
import bpy
import helpers as H


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _row(item_id):
    return next((it for it in bpy.context.scene.outliner_items
                 if it.item_id == item_id), None)


@pytest.mark.integration
def test_rename_chain_persists_across_outliner_rebuild(scene, sm, multi_chain):
    mid = multi_chain
    _build_outliner()
    chain = _chain_items(mid)[0]
    chain_item_id = chain.item_id
    chain_idx = str(chain.chain_id)
    assert chain.name != "Heavy Chain"

    res = bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=chain_item_id, item_type='CHAIN',
        new_name="Heavy Chain")
    assert res == {'FINISHED'}

    # Immediate: the row shows the new name.
    assert _row(chain_item_id).name == "Heavy Chain"

    # Persisted on the list item as JSON (independent of the outliner row).
    list_item = H.list_item(mid)
    stored = json.loads(list_item.chain_custom_names)
    assert stored.get(chain_idx) == "Heavy Chain"

    # Survives a full outliner rebuild (chain rows are otherwise regenerated).
    _build_outliner()
    assert _row(chain_item_id).name == "Heavy Chain"


@pytest.mark.integration
def test_rename_chain_blank_restores_default(scene, sm, multi_chain):
    mid = multi_chain
    _build_outliner()
    chain = _chain_items(mid)[0]
    cid = chain.item_id
    default_name = chain.name

    bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=cid, item_type='CHAIN', new_name="Temp")
    assert _row(cid).name == "Temp"

    # A blank name clears the override, restoring the default after a rebuild.
    bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=cid, item_type='CHAIN', new_name="")
    _build_outliner()
    assert _row(cid).name == default_name


@pytest.mark.integration
def test_rename_domain_persists_on_the_wrapper(scene, sm, multi_chain):
    mid = multi_chain
    scene.selected_molecule_id = mid
    # Split chain A so real DOMAIN rows exist.
    assert H.split_domain_from_outliner(mid, "A", 1, 50) == {"FINISHED"}
    _build_outliner()

    dom_row = next(it for it in scene.outliner_items if it.item_type == "DOMAIN")
    dom_id = dom_row.item_id

    res = bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=dom_id, item_type='DOMAIN',
        new_name="Catalytic")
    assert res == {'FINISHED'}
    assert _row(dom_id).name == "Catalytic"

    # Ground truth: the wrapper's domain model carries the new name.
    mol = sm.molecules[mid]
    assert mol.domains[dom_id].name == "Catalytic"

    # And it survives an outliner rebuild.
    _build_outliner()
    assert _row(dom_id).name == "Catalytic"
