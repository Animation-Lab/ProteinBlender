"""Shrinking a filament from its plus end, its minus end, or both.

Which end is which comes from the structure, not the preset: actin's D-loop
(residues 40-50, in subdomain 2) reaches towards the pointed (minus) end, and
in a tubulin dimer beta-tubulin sits on the plus-end side of alpha-tubulin.
Where every subunit stands is read out of the evaluated scene.
"""

import bpy
import numpy as np

import filament_checks as F
from filament_checks import build as _build
from filament_checks import realize as _realize
from filament_checks import tubulin_chains as _tubulin_chains

WORLD_SCALE = 0.01
D_LOOP = range(40, 51)


def _edit(molecule, **changes):
    """Reopen Edit Assembly on the filament, change settings, and OK."""
    from proteinblender.core import assembly
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )
    scene = bpy.context.scene
    apply_symmetry_settings(scene, assembly.built_build_params(molecule))
    for prop, value in changes.items():
        setattr(scene, f"pb_symmetry_{prop}", value)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier,
        source='GENERATED') == {'FINISHED'}


def _centres(molecule, chain):
    preset = F.presets().of_molecule(molecule)
    return F.chain_centres(molecule, preset, chain)


def _path_axis(molecule):
    from proteinblender.core import symmetry_bend
    nodes = [np.array(n.matrix_world.translation) / WORLD_SCALE
             for n in symmetry_bend.get_bend_nodes(molecule)]
    axis = nodes[-1] - nodes[0]
    return axis / np.linalg.norm(axis)


def _actin_barbed_direction(molecule):
    """Along the filament, towards the barbed end: away from where the D-loops point."""
    preset = F.presets().get("ACTIN")
    shipped = F.alpha_carbons(F.presets().structure_path(preset))
    everything = sorted(r for (c, r) in shipped if c == "A")
    # Part of the D-loop is too mobile to have been modelled.
    loop = [r for r in everything if r in D_LOOP]
    assert len(loop) >= 5
    whole = [copy.mean(axis=0) for copy in F.drawn_copies(molecule, "A", everything)]
    loops = [copy.mean(axis=0) for copy in F.drawn_copies(molecule, "A", loop)]
    axis = _path_axis(molecule)
    pointing = float(np.mean([(loop - centre) @ axis
                              for loop, centre in zip(loops, whole)]))
    assert abs(pointing) > 5.0, "the D-loops do not point along the filament"
    return -np.sign(pointing) * axis


def _matched(kept, before, tolerance=0.05):
    """Index in ``before`` of each copy in ``kept``; every one must not have moved."""
    found = []
    for centre in kept:
        distances = np.linalg.norm(before - centre, axis=1)
        assert distances.min() < tolerance, (
            f"a kept subunit moved {distances.min():.2f} A")
        found.append(int(distances.argmin()))
    assert len(set(found)) == len(found)
    return found


def test_shrinking_the_barbed_end_takes_subunits_off_the_barbed_end():
    molecule = _build("ACTIN", 27.5)
    before = _centres(molecule, "A")
    assert len(before) == 10
    barbed = _actin_barbed_direction(molecule)

    _edit(molecule, shrink_plus=3)

    after = _centres(molecule, "A")
    assert len(after) == 7
    gone = sorted(set(range(10)) - set(_matched(after, before)))
    reach = before @ barbed
    assert gone == sorted(np.argsort(reach)[-3:].tolist()), (
        "the subunits taken away are not the three at the barbed end")


def test_shrinking_the_pointed_end_takes_subunits_off_the_pointed_end():
    molecule = _build("ACTIN", 27.5)
    before = _centres(molecule, "A")
    barbed = _actin_barbed_direction(molecule)

    _edit(molecule, shrink_minus=2)

    after = _centres(molecule, "A")
    assert len(after) == 8
    gone = sorted(set(range(10)) - set(_matched(after, before)))
    assert gone == sorted(np.argsort(before @ barbed)[:2].tolist())


def _protofilaments(centres, axis):
    """Group a tube's subunits by protofilament: by their angle round ``axis``."""
    middle = centres.mean(axis=0)
    side = np.cross(axis, [1.0, 0.0, 0.0])
    side /= np.linalg.norm(side)
    other = np.cross(axis, side)
    radial = centres - middle
    angles = np.degrees(np.arctan2(radial @ other, radial @ side))
    groups = []
    for index in np.argsort(angles):
        if groups and abs(angles[index] - angles[groups[-1][-1]]) < 5.0:
            groups[-1].append(int(index))
        else:
            groups.append([int(index)])
    return groups


def test_shrinking_a_microtubules_minus_end_takes_a_dimer_off_every_protofilament():
    chains = _tubulin_chains()
    molecule = _build("MICROTUBULE", 25.0)
    alpha = _centres(molecule, chains["alpha"])
    beta = _centres(molecule, chains["beta"])
    assert len(alpha) == 39
    plus = (beta - alpha).mean(axis=0)
    plus /= np.linalg.norm(plus)

    _edit(molecule, shrink_minus=1)

    after = _centres(molecule, chains["alpha"])
    assert len(after) == 26
    gone = set(range(39)) - set(_matched(after, alpha))
    groups = _protofilaments(alpha, plus)
    assert len(groups) == 13
    for group in groups:
        minus_most = min(group, key=lambda i: float(alpha[i] @ plus))
        assert gone & set(group) == {minus_most}


def test_shrinking_a_microtubules_plus_end_takes_a_dimer_off_every_protofilament():
    chains = _tubulin_chains()
    molecule = _build("MICROTUBULE", 25.0)
    alpha = _centres(molecule, chains["alpha"])
    beta = _centres(molecule, chains["beta"])
    plus = (beta - alpha).mean(axis=0)
    plus /= np.linalg.norm(plus)

    _edit(molecule, shrink_plus=2)

    after = _centres(molecule, chains["alpha"])
    assert len(after) == 13
    kept = set(_matched(after, alpha))
    for group in _protofilaments(alpha, plus):
        minus_most = min(group, key=lambda i: float(alpha[i] @ plus))
        assert kept & set(group) == {minus_most}


def _drawn(molecule):
    obj_name = next(iter(molecule.domains.values())).object.name
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return len([i for i in depsgraph.object_instances
                if i.is_instance and i.parent is not None
                and i.parent.original.name == obj_name])


def test_both_ends_shrinking_meet_in_the_middle():
    molecule = _build("ACTIN", 27.5)
    _edit(molecule, shrink_plus=4, shrink_minus=5)
    assert _drawn(molecule) == 1
    _edit(molecule, shrink_plus=5, shrink_minus=5)
    assert _drawn(molecule) == 0
    # And back: nothing was lost on the way.
    _edit(molecule, shrink_plus=0, shrink_minus=0)
    assert _drawn(molecule) == 10


def test_shrinking_leaves_the_bend_path_alone():
    from proteinblender.core import symmetry_bend
    molecule = _build("ACTIN", 27.5)
    nodes = [n.matrix_world.translation.copy()
             for n in symmetry_bend.get_bend_nodes(molecule)]
    _edit(molecule, shrink_plus=3, shrink_minus=3)
    assert [n.matrix_world.translation for n in
            symmetry_bend.get_bend_nodes(molecule)] == nodes


def _key(molecule, frame):
    obj = molecule.object
    return bpy.ops.proteinblender.create_keyframe(
        'EXEC_DEFAULT', frame_number=frame,
        puppet_items=[{
            "name": molecule.identifier, "puppet_id": molecule.identifier,
            "puppet_name": molecule.identifier,
            "controller_object_name": obj.name, "item_kind": "FILAMENT",
            "use_puppet": True, "keyframe_location": True,
            "keyframe_rotation": True, "keyframe_scale": True,
            "keyframe_pose": False, "keyframe_color": False,
            "brownian_enabled": False,
        }])


def test_a_keyed_shrink_plays_back_as_a_shrinking_filament():
    """Nothing off at frame 1 and four off each end at frame 21: two each at frame 11."""
    scene = bpy.context.scene
    molecule = _build("ACTIN", 27.5)
    scene.frame_set(1)
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(21)
    _edit(molecule, shrink_plus=4, shrink_minus=4)
    assert _key(molecule, 21) == {'FINISHED'}

    scene.frame_set(11)
    assert _drawn(molecule) == 6
    scene.frame_set(21)
    assert _drawn(molecule) == 2
    scene.frame_set(1)
    assert _drawn(molecule) == 10


def test_a_shrunk_filament_realizes_only_what_is_left():
    molecule = _build("ACTIN", 27.5)
    _edit(molecule, shrink_plus=3, shrink_minus=3)
    made = _realize(molecule)
    # Four left: the original is shrunk away, so it stands in for one of them.
    assert len(made) == 3


def test_a_shrunk_filament_stays_shrunk_when_its_path_is_dragged():
    """Dragging a node re-lays the filament from a handler; it must keep its ends."""
    from mathutils import Vector

    from proteinblender.core import symmetry_bend
    molecule = _build("ACTIN", 27.5)
    _edit(molecule, shrink_plus=2, shrink_minus=3)
    assert _drawn(molecule) == 5

    node = symmetry_bend.get_bend_nodes(molecule)[1]
    node.location = node.location + Vector((60.0, 0.0, 0.0)) * WORLD_SCALE
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()

    assert _drawn(molecule) == 5


def test_a_new_assembly_does_not_inherit_shrunk_ends():
    """The dialog's controls are shared; a fresh build starts whole."""
    molecule = _build("ACTIN", 27.5)
    _edit(molecule, shrink_plus=2)
    other = _build("ACTIN", 27.5)
    assert _drawn(other) == 10
    assert _drawn(molecule) == 8
