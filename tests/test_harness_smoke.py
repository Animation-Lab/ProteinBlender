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


@pytest.mark.integration
def test_reset_restores_the_import_settings(scene):
    """The import helpers set scene.protein_props; reset must put it back.

    A leaked remote_format of "pdb" (set by H.import_pdb) failed
    test_remote_format_defaults_to_mmcif whenever it ran after that helper,
    so the suite only passed because of the alphabetical file order.
    """
    props = scene.protein_props
    props.pdb_id = "leaked-id"
    props.remote_format = "pdb"
    props.uniprot_id = "leaked-uniprot"

    H.reset_scene()

    rna = props.bl_rna.properties
    assert props.remote_format == rna["remote_format"].default == "cif"
    assert props.pdb_id == rna["pdb_id"].default == ""
    assert props.uniprot_id == rna["uniprot_id"].default == ""


@pytest.mark.integration
def test_clean_scene_contract_flags_leaked_import_settings(scene):
    """The per-test contract must go red on leaked import settings."""
    import harness_contract as HC

    scene.protein_props.remote_format = "pdb"
    with pytest.raises(AssertionError, match=r"protein_props\.remote_format"):
        HC.assert_clean_scene()

    H.reset_scene()
    HC.assert_clean_scene()
