"""Smoke tests for the test harness itself.

If these fail, nothing else in the suite is trustworthy — they prove the addon
registered, scene properties exist, per-test reset works, and both the offline
and (optionally) network import paths function.
"""

import pytest

import helpers as H


@pytest.mark.integration
def test_addon_registered(scene):
    assert hasattr(scene, "protein_props")
    assert hasattr(scene, "molecule_list_items")
    assert hasattr(scene, "outliner_items")


@pytest.mark.integration
def test_scene_starts_empty(scene, sm):
    # The autouse reset fixture must hand every test a clean scene.
    assert len(scene.molecule_list_items) == 0
    assert len(sm.molecules) == 0


@pytest.mark.integration
def test_offline_import_single_chain(scene, sm):
    mol_id = H.import_local("1ubq.pdb", "1ubq")
    assert mol_id in sm.molecules
    assert H.list_item(mol_id) is not None


@pytest.mark.integration
def test_reset_isolates_tests(scene, sm):
    # This test must ALSO see an empty scene despite the previous test importing
    # a molecule — proves reset runs between tests.
    assert len(sm.molecules) == 0
