"""Splitting the chain of a filament splits every subunit, not just one.

Janet (2026-10-30): "If you create an actin filament and then edit the chain
(for example, make two chunks) ... my assembly disappeared, and I have just a
monomer. I guess ideally this would just change every monomer in the filament?"

The filament's copies are drawn by an assembly node on each chain's object.
A split replaces the chain's object with one object per piece, so unless the
assembly reaches the new objects, each piece is drawn once and the filament
collapses to its original subunit.

Ground truth is what Blender draws: copies are counted from the evaluated
scene's instances, and the drawn C-alpha atoms are compared before and after
the split by residue, never asked of the assembly code.
"""
import bpy
import numpy as np
import pytest

import helpers as H

pytestmark = pytest.mark.integration

SUBUNITS = 10            # 27.5 nm of actin at 27.5 A a subunit
SPLIT_AT = 180           # actin's two lobes meet near residue 180


def _build_actin():
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=27.5) == {'FINISHED'}
    (new,) = set(H.sm().molecules) - before
    return H.sm().molecules[new]


def _domain_objects(molecule):
    return [d.object for d in molecule.domains.values() if d.object]


def _copies_drawn_by(obj):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return len([i for i in depsgraph.object_instances
                if i.is_instance and i.parent is not None
                and i.parent.original.name == obj.name])


def _drawn_alpha_carbons(molecule):
    """Every drawn C-alpha atom as (res_id, x, y, z) rows, in Angstrom, sorted.

    Read from the evaluated instances' point clouds, so it is what is on
    screen. Domains are drawn as spheres for the reading (a surface draws no
    atoms); where a copy stands does not depend on its style.
    """
    from proteinblender.core import visual_style

    for obj in _domain_objects(molecule):
        visual_style.apply_style_to_object(obj, "spheres", sync_morphsets=False)
    bpy.context.view_layer.update()
    wanted = {o.name for o in _domain_objects(molecule)}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    rows = []
    for inst in depsgraph.object_instances:
        if inst.parent is None or inst.parent.original.name not in wanted:
            continue
        data = inst.object.data
        n = len(getattr(data, "points", ()))
        if not n or "is_alpha_carbon" not in data.attributes:
            continue
        pos = np.zeros(n * 3)
        data.attributes["position"].data.foreach_get("vector", pos)
        ca = np.zeros(n, dtype=bool)
        data.attributes["is_alpha_carbon"].data.foreach_get("value", ca)
        res = np.zeros(n, dtype=np.int32)
        data.attributes["res_id"].data.foreach_get("value", res)
        pos = pos.reshape(-1, 3)
        mat = np.array(inst.matrix_world)
        world = pos @ mat[:3, :3].T + mat[:3, 3]
        for r, xyz in zip(res[ca], world[ca] / 0.01):
            rows.append((int(r), *np.round(xyz, 1)))
    return np.array(sorted(rows))


def test_splitting_a_filament_chain_splits_every_subunit():
    molecule = _build_actin()
    (chain_obj,) = _domain_objects(molecule)
    assert _copies_drawn_by(chain_obj) == SUBUNITS
    before = _drawn_alpha_carbons(molecule)
    assert len(before) > 0

    result = H.split_domain_from_outliner(molecule.identifier, "A", 1, SPLIT_AT)
    assert result == {'FINISHED'}

    pieces = _domain_objects(molecule)
    assert len(pieces) >= 2, "the split did not make two pieces"
    drawn = {obj.name: _copies_drawn_by(obj) for obj in pieces}
    assert all(count == SUBUNITS for count in drawn.values()), (
        f"each piece should be drawn once per subunit ({SUBUNITS}), got {drawn}")

    after = _drawn_alpha_carbons(molecule)
    assert after.shape == before.shape, (
        f"{len(before)} C-alpha atoms were drawn before the split, {len(after)} after")
    assert np.abs(after - before).max() < 0.5, "a split moved the filament's subunits"


def test_moving_a_filament_chain_pivot_moves_none_of_its_subunits():
    """A pivot is where an object turns about; setting it must not move atoms.

    The copies are placed from a pivot stored with them when they were built,
    so a pivot set afterwards (as a split does to each new piece) left every
    copy but the first standing somewhere else.
    """
    molecule = _build_actin()
    before = _drawn_alpha_carbons(molecule)

    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    row = next(item for item in bpy.context.scene.outliner_items
               if item.item_type == "CHAIN" and item.parent_id == molecule.identifier)
    assert bpy.ops.proteinblender.set_pivot_last(item_id=row.item_id) == {'FINISHED'}

    after = _drawn_alpha_carbons(molecule)
    assert after.shape == before.shape
    assert np.abs(after - before).max() < 0.5, "setting a pivot moved the filament's subunits"


def test_the_domain_splitter_cuts_every_subunit_of_a_filament():
    """Janet's "edit the chain (make two chunks)": the Domain Splitter dialog."""
    import json
    from proteinblender.core import assembly

    molecule = _build_actin()
    before = _drawn_alpha_carbons(molecule)
    built = assembly.built_build_params(molecule)
    assert built, "a new filament records the settings it was built from"
    (domain,) = molecule.domains.values()
    start, end = domain.start, domain.end

    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    row = next(item for item in bpy.context.scene.outliner_items
               if item.item_type == "CHAIN" and item.parent_id == molecule.identifier)
    layout = json.dumps([
        {"name": "Lower lobe", "start": start, "end": SPLIT_AT, "domain_id": ""},
        {"name": "Upper lobe", "start": SPLIT_AT + 1, "end": end, "domain_id": ""}])
    assert bpy.ops.proteinblender.edit_chain_domains(
        'EXEC_DEFAULT', item_id=row.item_id, layout_json=layout,
        chain_name=row.name) == {'FINISHED'}

    pieces = _domain_objects(molecule)
    assert len(pieces) == 2
    assert [_copies_drawn_by(obj) for obj in pieces] == [SUBUNITS, SUBUNITS]
    after = _drawn_alpha_carbons(molecule)
    assert after.shape == before.shape
    assert np.abs(after - before).max() < 0.5
    # Still the same filament: the Edit Assembly dialog reopens on its settings.
    assert assembly.built_build_params(molecule) == built


def test_a_split_filament_still_bends_as_one():
    """Dragging a bend node after a split carries both pieces of every subunit.

    Residues SPLIT_AT and SPLIT_AT + 1 are one peptide bond apart (3.8 A) in
    every subunit, one on each side of the cut. Were only one piece to follow
    the bend, the bent subunits would be torn apart across it.
    """
    from proteinblender.core import symmetry_bend

    molecule = _build_actin()
    assert H.split_domain_from_outliner(molecule.identifier, "A", 1, SPLIT_AT) == {'FINISHED'}
    straight = _drawn_alpha_carbons(molecule)

    nodes = symmetry_bend.get_bend_nodes(molecule)
    assert nodes, "a built filament comes with bend nodes"
    nodes[len(nodes) // 2].location.x += 0.5
    bpy.context.view_layer.update()
    bent = _drawn_alpha_carbons(molecule)

    assert np.abs(bent[:, 1:] - straight[:, 1:]).max() > 5, "the drag did not bend anything"
    left = bent[bent[:, 0] == SPLIT_AT][:, 1:]
    right = bent[bent[:, 0] == SPLIT_AT + 1][:, 1:]
    assert len(left) == len(right) == SUBUNITS
    gaps = np.linalg.norm(left[:, None, :] - right[None, :, :], axis=2).min(axis=1)
    assert gaps.max() < 4.5, f"a bent subunit is torn across the cut: {gaps.round(1)}"
