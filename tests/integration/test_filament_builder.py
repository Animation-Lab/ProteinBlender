"""Building filaments from the UI: strands in the dialog, and the Cytoskeleton builder.

``test_symmetry_lattice.py`` settles what a lattice of strands *is*, against
trigonometry, and ``test_filament_presets.py`` that the shipped actin and
microtubule are the real ones, against the PDB entries they were cut from.
This file is about the road from a button to those: the Assembly dialog's
strand controls, the tools that work on a built filament, and the builder that
makes one in a single step.

The numbers a user would type are written out here from the literature, not
read from the presets: a 13-protofilament microtubule has tubulin dimers
81.5 A apart along each protofilament, and one trip round the tube climbs a
dimer and a half, left-handed.

What was built is always read back out of the evaluated scene - how many
copies Blender drew, where their atoms are, where the control nodes stand -
and judged against the deposit or against arithmetic done in the test.
"""

import math

import bpy
import numpy as np
import pytest
from mathutils import Vector

import filament_checks as F
import helpers as H

WORLD_SCALE = 0.01              # Blender units per Angstrom

#: A 13-protofilament microtubule, as the literature gives it.
MT_STRANDS = 13
MT_RISE = 81.5                              # one tubulin dimer, in Angstrom
MT_STAGGER = 1.5 * MT_RISE / MT_STRANDS     # a dimer and a half per turn
MT_STRAND_TWIST = -360.0 / MT_STRANDS       # left-handed

#: F-actin: Angstrom and degrees per subunit.
ACTIN_RISE = 27.5

#: How closely built copies have to reproduce a deposited neighbour pair, in
#: Angstrom. See ``test_filament_presets.TOLERANCE``.
TOLERANCE = 1.0


def _assembly_core():
    from proteinblender.core import assembly
    return assembly


def _bend():
    from proteinblender.core import symmetry_bend
    return symmetry_bend


def _import(preset_id):
    """One subunit, imported the ordinary way - nothing built from it yet."""
    preset = F.presets().get(preset_id)
    mol_id = H.import_local(F.presets().structure_path(preset), preset_id.lower())
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id), preset


def _set_tube(count):
    """Put the dialog's controls where a user building a microtubule would."""
    scene = bpy.context.scene
    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = count
    scene.pb_symmetry_rise = MT_RISE
    scene.pb_symmetry_twist = 0.0
    scene.pb_symmetry_strands = MT_STRANDS
    scene.pb_symmetry_stagger = MT_STAGGER
    scene.pb_symmetry_strand_twist = MT_STRAND_TWIST


def _ok(molecule, **extra):
    """The dialog's OK."""
    return bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier, source='GENERATED',
        **extra)


def _copies(molecule, chain="A"):
    """How many copies of one chain Blender drew."""
    obj_name = next(d.object.name for d in molecule.domains.values()
                    if str(d.chain_id) == chain)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return len([i for i in depsgraph.object_instances
                if i.is_instance and i.parent is not None
                and i.parent.original.name == obj_name])


def _assert_stands_as_the_deposit_does(molecule, preset):
    for neighbour in F.truth(preset.id)["neighbours"]:
        miss = F.worst_miss(molecule, preset, neighbour)
        assert miss < TOLERANCE, (
            f"no two copies stand as the subunit and deposited chain "
            f"{neighbour['deposit_chain']} do: the closest pair is "
            f"{miss:.1f} A out")


def _nodes(molecule):
    """The bend's control nodes, in Angstrom, in the order they run."""
    bpy.context.view_layer.update()
    return [np.array(node.matrix_world.translation) / WORLD_SCALE
            for node in _bend().get_bend_nodes(molecule)]


def _distance_to_path(points, path):
    """How far each point is from the polyline ``path``, segment by segment."""
    starts, ends = path[:-1], path[1:]
    spans = ends - starts
    lengths = np.maximum((spans ** 2).sum(axis=1), 1e-12)
    out = []
    for point in points:
        t = np.clip(((point - starts) * spans).sum(axis=1) / lengths, 0.0, 1.0)
        nearest = starts + spans * t[:, None]
        out.append(np.linalg.norm(nearest - point, axis=1).min())
    return np.array(out)


def _drag(molecule, index, offset):
    """Drag one control node by ``offset`` Angstrom, as a user would."""
    node = _bend().get_bend_nodes(molecule)[index]
    node.location = node.location + Vector(offset) * WORLD_SCALE
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def _drawn_path(molecule, resolution=256):
    """The bend path as Blender draws it after any drag, in Angstrom.

    Blender's own evaluation of the curve, hooks and all, flattened to a
    polyline: nothing of the sampler that places the subunits is involved.
    The curve's bevel is taken off for the measurement so the mesh is the
    centre line itself.
    """
    curve = _bend().get_bend_curve(molecule)
    assert curve is not None, "the filament has no bend path"
    data = curve.data
    kept = (data.bevel_depth, data.resolution_u)
    data.bevel_depth, data.resolution_u = 0.0, resolution
    try:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = curve.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            world = evaluated.matrix_world
            ordered = _polyline_order(mesh)
            points = [tuple(world @ mesh.vertices[i].co) for i in ordered]
        finally:
            evaluated.to_mesh_clear()
    finally:
        data.bevel_depth, data.resolution_u = kept
        bpy.context.view_layer.update()
    return np.array(points) / WORLD_SCALE


def _polyline_order(mesh):
    """Vertex indices of an open polyline mesh, end to end."""
    neighbours = {v.index: [] for v in mesh.vertices}
    for edge in mesh.edges:
        a, b = edge.vertices
        neighbours[a].append(b)
        neighbours[b].append(a)
    if not mesh.edges:
        return list(neighbours)
    start = next(i for i, linked in neighbours.items() if len(linked) == 1)
    order, previous = [start], None
    while True:
        here = order[-1]
        onward = [n for n in neighbours[here] if n != previous]
        if not onward:
            return order
        previous = here
        order.append(onward[0])


def _axis_distance(preset, chain="A"):
    """How far a chain's centre is from the filament axis, from the PDB text.

    The shipped subunit stands with the axis along Z through the origin, so
    this is plain arithmetic on the file.
    """
    shipped = F.alpha_carbons(F.presets().structure_path(preset))
    centre = np.mean([xyz for (c, _r), xyz in shipped.items() if c == chain],
                     axis=0)
    return float(math.hypot(centre[0], centre[1]))


def _new_molecule(before):
    after = set(H.sm().molecules) - set(before)
    assert len(after) == 1, f"expected one new molecule, got {sorted(after)}"
    return H.sm().molecules[after.pop()]


# --------------------------------------------------------------------------
# Strands in the Assembly dialog
# --------------------------------------------------------------------------

def test_the_dialog_builds_the_strands_it_shows():
    """Thirteen strands of two dimers is twenty-six, standing as a microtubule."""
    molecule, preset = _import("MICROTUBULE")
    _set_tube(count=2)
    assert _ok(molecule) == {'FINISHED'}

    assert _copies(molecule) == 2 * MT_STRANDS
    _assert_stands_as_the_deposit_does(molecule, preset)


def test_the_outliner_names_a_tube_as_a_tube():
    """A row reading "Helix (2)" for twenty-six copies would be a lie."""
    molecule, _preset = _import("MICROTUBULE")
    _set_tube(count=2)
    assert _ok(molecule) == {'FINISHED'}

    names = [item.name for item in bpy.context.scene.outliner_items
             if item.item_type == 'SYMMETRY']
    assert len(names) == 1
    assert "13 x 2" in names[0], f"the row is called {names[0]!r}"


def test_reopening_a_tube_shows_its_strands():
    """The Edit pencil seeds the controls from the build, strands included."""
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )

    molecule, _preset = _import("MICROTUBULE")
    _set_tube(count=2)
    assert _ok(molecule) == {'FINISHED'}

    # The user goes off and builds an ordinary helix of something else.
    scene = bpy.context.scene
    scene.pb_symmetry_strands = 1
    scene.pb_symmetry_stagger = 0.0
    scene.pb_symmetry_strand_twist = 0.0

    apply_symmetry_settings(scene, _assembly_core().built_build_params(molecule))
    assert scene.pb_symmetry_strands == MT_STRANDS
    assert scene.pb_symmetry_stagger == pytest.approx(MT_STAGGER, abs=1e-3)
    assert scene.pb_symmetry_strand_twist == pytest.approx(MT_STRAND_TWIST,
                                                           abs=1e-3)


def _helix_recorded_before_strands_existed(molecule, count):
    """A one-strand filament whose record has no strand settings in it.

    Which is every helix saved by a version of the add-on older than strands.
    """
    scene = bpy.context.scene
    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = count
    scene.pb_symmetry_rise = MT_RISE
    scene.pb_symmetry_twist = 0.0
    assert _ok(molecule) == {'FINISHED'}
    assert _copies(molecule) == count

    record = _assembly_core().built_build_params(molecule)
    for key in ("strands", "stagger", "strand_twist"):
        record.pop(key, None)
    assert _assembly_core().record_build_params(molecule, record)
    return record


def test_an_older_helix_reopens_as_one_strand():
    """No strand settings in the record means one strand, not "whatever is set".

    The scene's controls are one set standing in for whichever assembly was
    last worked on. Reopening an old helix after building a microtubule must
    not show it thirteen strands it does not have.
    """
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )

    molecule, _preset = _import("MICROTUBULE")
    record = _helix_recorded_before_strands_existed(molecule, count=3)

    _set_tube(count=3)
    apply_symmetry_settings(bpy.context.scene, record)

    scene = bpy.context.scene
    assert scene.pb_symmetry_strands == 1
    assert scene.pb_symmetry_stagger == pytest.approx(0.0)
    assert scene.pb_symmetry_strand_twist == pytest.approx(0.0)


def test_an_older_helix_stays_one_strand_when_it_is_bent():
    """The tools read the build's own record, never the scene's controls."""
    molecule, _preset = _import("MICROTUBULE")
    _helix_recorded_before_strands_existed(molecule, count=3)

    _set_tube(count=3)          # the scene has since moved on to a tube
    assert bpy.ops.molecule.add_filament_bend(
        molecule_id=molecule.identifier) == {'FINISHED'}
    assert _copies(molecule) == 3


# --------------------------------------------------------------------------
# Length
# --------------------------------------------------------------------------

def test_a_length_sets_the_subunit_count():
    """A micron of microtubule: 10,000 A at 81.5 A a dimer is 122.7, so 123."""
    scene = bpy.context.scene
    scene.pb_symmetry_rise = MT_RISE
    scene.pb_symmetry_length = 1000.0           # nanometres
    assert scene.pb_symmetry_count == 123


def test_the_length_shown_is_the_length_built():
    """Ten actin subunits 27.5 A apart are 27.5 nm, whichever way they run."""
    scene = bpy.context.scene
    scene.pb_symmetry_count = 10
    scene.pb_symmetry_rise = ACTIN_RISE
    assert scene.pb_symmetry_length == pytest.approx(27.5)

    scene.pb_symmetry_rise = -ACTIN_RISE
    assert scene.pb_symmetry_length == pytest.approx(27.5)


def test_a_length_always_leaves_at_least_one_subunit():
    scene = bpy.context.scene
    scene.pb_symmetry_rise = ACTIN_RISE
    scene.pb_symmetry_length = 0.0
    assert scene.pb_symmetry_count == 1


def test_a_filament_with_no_rise_has_no_length_to_set():
    """Rise 0 is a ring's worth of copies on one spot; a length cannot count them."""
    scene = bpy.context.scene
    scene.pb_symmetry_count = 7
    scene.pb_symmetry_rise = 0.0
    assert scene.pb_symmetry_length == pytest.approx(0.0)
    scene.pb_symmetry_length = 50.0
    assert scene.pb_symmetry_count == 7


# --------------------------------------------------------------------------
# Bending a tube
# --------------------------------------------------------------------------

def test_adding_a_bend_leaves_a_tube_exactly_where_it_was():
    """A fresh bend is straight, so nothing may move - and nothing may vanish."""
    molecule, preset = _import("MICROTUBULE")
    _set_tube(count=3)
    assert _ok(molecule) == {'FINISHED'}
    before = F.chain_centres(molecule, preset)
    assert len(before) == 3 * MT_STRANDS

    assert bpy.ops.molecule.add_filament_bend(
        molecule_id=molecule.identifier) == {'FINISHED'}

    after = F.chain_centres(molecule, preset)
    assert len(after) == 3 * MT_STRANDS, "the bend dropped strands from the tube"
    # The same set of places, whatever order Blender lists the copies in.
    moved = [np.linalg.norm(before - centre, axis=1).min() for centre in after]
    assert max(moved) < 0.05, f"a straight bend moved a dimer {max(moved):.2f} A"
    _assert_stands_as_the_deposit_does(molecule, preset)


def test_the_bend_path_is_as_long_as_the_tube():
    """Two dimers up a strand and twelve staggers round: 163 + 112.8 A.

    A path that stopped at the first strand's last dimer would leave the far
    end of every other strand hanging off the end of its curve.
    """
    molecule, _preset = _import("MICROTUBULE")
    _set_tube(count=3)
    assert _ok(molecule) == {'FINISHED'}
    assert bpy.ops.molecule.add_filament_bend(
        molecule_id=molecule.identifier) == {'FINISHED'}

    nodes = _nodes(molecule)
    expected = (3 - 1) * MT_RISE + (MT_STRANDS - 1) * MT_STAGGER
    assert expected == pytest.approx(275.85, abs=0.01)
    assert np.linalg.norm(nodes[-1] - nodes[0]) == pytest.approx(expected,
                                                                 abs=0.5)


def test_the_bend_path_runs_down_the_middle_of_the_tube():
    """The path is the filament's axis, so it belongs in the lumen.

    One ring of thirteen dimers is a regular 13-gon, and its middle is the
    mean of its corners - found from the drawn copies. Every control node
    must stand on the line through that middle, not out in the tube's wall
    where the first dimer happens to be.
    """
    molecule, preset = _import("MICROTUBULE")
    _set_tube(count=1)
    assert _ok(molecule) == {'FINISHED'}
    assert bpy.ops.molecule.add_filament_bend(
        molecule_id=molecule.identifier) == {'FINISHED'}

    centres = F.chain_centres(molecule, preset)
    assert len(centres) == MT_STRANDS
    middle = centres.mean(axis=0)

    for node in _nodes(molecule):
        off = math.hypot(node[0] - middle[0], node[1] - middle[1])
        assert off < 2.0, (
            f"a control node is {off:.0f} A from the middle of the tube")


# --------------------------------------------------------------------------
# The Cytoskeleton builder
# --------------------------------------------------------------------------

def test_the_builder_makes_a_microtubule_of_the_length_asked_for():
    """50 nm at 81.5 A a dimer is 6.1, so six dimers up each of thirteen strands."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='MICROTUBULE', length=50.0) == {'FINISHED'}

    molecule = _new_molecule(before)
    assert _copies(molecule) == 6 * MT_STRANDS
    _assert_stands_as_the_deposit_does(molecule,
                                       F.presets().get("MICROTUBULE"))


def test_the_builder_makes_an_actin_filament_of_the_length_asked_for():
    """27.5 nm at 27.5 A a subunit is ten subunits."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=27.5) == {'FINISHED'}

    molecule = _new_molecule(before)
    assert _copies(molecule) == 10
    _assert_stands_as_the_deposit_does(molecule, F.presets().get("ACTIN"))


def test_building_twice_makes_two_filaments():
    """A second filament must not replace the first."""
    for _ in range(2):
        assert bpy.ops.molecule.build_filament(
            'EXEC_DEFAULT', preset='ACTIN', length=11.0) == {'FINISHED'}

    molecules = list(H.sm().molecules.values())
    assert len(molecules) == 2
    assert all(_copies(molecule) == 4 for molecule in molecules)


def test_a_built_filament_shows_up_as_an_assembly_in_the_outliner():
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='MICROTUBULE', length=25.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    rows = [item for item in bpy.context.scene.outliner_items
            if item.item_type == 'SYMMETRY']
    assert len(rows) == 1
    assert rows[0].parent_id == molecule.identifier
    assert "13 x 3" in rows[0].name, f"the row is called {rows[0].name!r}"


def test_a_built_filament_is_edited_like_any_other_assembly():
    """Its pencil opens the Assembly dialog on it, and a new length rebuilds it.

    Opened and OK'd with nothing changed it must be left alone; with a longer
    length asked for, it must become that long and still be a microtubule.
    """
    from types import SimpleNamespace

    from proteinblender.operators import symmetry_dialog
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )

    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='MICROTUBULE', length=25.0) == {'FINISHED'}
    molecule = _new_molecule(before)
    assert _copies(molecule) == 3 * MT_STRANDS

    # What invoke does when the pencil opens the dialog.
    scene = bpy.context.scene
    apply_symmetry_settings(scene, _assembly_core().built_build_params(molecule))
    opened_on = symmetry_dialog.dialog_signature(
        SimpleNamespace(target_id=molecule.identifier, source='GENERATED',
                        assembly_id=''), scene)
    assert scene.pb_symmetry_length == pytest.approx(3 * MT_RISE / 10.0)

    assert _ok(molecule, opened_on=opened_on) == {'CANCELLED'}
    assert _copies(molecule) == 3 * MT_STRANDS

    scene.pb_symmetry_length = 40.0             # 400 / 81.5 = 4.9, so five
    assert _ok(molecule, opened_on=opened_on) == {'FINISHED'}
    assert _copies(molecule) == 5 * MT_STRANDS
    _assert_stands_as_the_deposit_does(molecule,
                                       F.presets().get("MICROTUBULE"))


def test_a_built_filament_comes_with_a_path_to_bend_it_by():
    """The spline is the point of the builder, so it is there from the start."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    nodes = _nodes(molecule)
    assert len(nodes) >= 2, "there is nothing to drag"
    # Twenty subunits: nineteen gaps of 27.5 A.
    assert np.linalg.norm(nodes[-1] - nodes[0]) == pytest.approx(
        19 * ACTIN_RISE, abs=0.5)


def _bent_actin(length=110.0):
    """An actin filament with its middle node pulled 300 A to one side."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=length) == {'FINISHED'}
    molecule = _new_molecule(before)
    _drag(molecule, 1, (300.0, 0.0, 0.0))
    return molecule


def test_a_new_filament_starts_straight():
    """There is no shape to choose: a new filament runs straight up its axis.

    Every subunit centre is the same distance from the axis, and the path is
    a straight line, so every one of its points lies on the line from the
    first node to the last.
    """
    preset = F.presets().get("ACTIN")
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    path = _drawn_path(molecule)
    start, end = path[0], path[-1]
    direction = (end - start) / np.linalg.norm(end - start)
    sideways = path - start - np.outer((path - start) @ direction, direction)
    assert np.linalg.norm(sideways, axis=1).max() < 0.5, (
        "the path of a new filament is not a straight line")

    off = _distance_to_path(F.chain_centres(molecule, preset), path)
    assert np.abs(off - _axis_distance(preset)).max() < 1.0


def test_the_builder_no_longer_offers_starting_shapes():
    """Arc, S-curve and Coil are gone: the nodes make any shape there is."""
    props = bpy.ops.molecule.build_filament.get_rna_type().properties
    assert "shape" not in props.keys()
    assert not hasattr(bpy.types, "MOLECULE_PB_OT_filament_bend_preset")


def test_a_new_filament_is_drawn_as_a_surface():
    """Every object of the filament draws through MolecularNodes' surface style."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=11.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    objects = [molecule.object] + [d.object for d in molecule.domains.values()]
    for obj in objects:
        group = next(m for m in obj.modifiers if m.type == 'NODES').node_group
        styles = [node.node_tree.name for node in group.nodes
                  if node.type == 'GROUP' and node.node_tree is not None
                  and node.node_tree.name.startswith('Style ')]
        assert styles and all(name.startswith('Style Surface') for name in styles), (
            f"{obj.name} is drawn with {styles}")


def test_a_dragged_filament_lies_along_its_path():
    """Every subunit must sit beside the path that is drawn, all the way along.

    An actin subunit's centre is 15.6 A from the filament axis, so on a path
    that *is* the axis every copy's centre is that far from it. A filament
    that had swung away from its control curve would have copies hundreds of
    Angstrom off - and nodes that no longer touch what they shape.
    """
    preset = F.presets().get("ACTIN")
    molecule = _bent_actin()

    centres = F.chain_centres(molecule, preset)
    assert len(centres) == 40

    expected = _axis_distance(preset)
    assert expected == pytest.approx(15.6, abs=0.5)
    off = _distance_to_path(centres, _drawn_path(molecule))
    assert np.abs(off - expected).max() < 4.0, (
        f"a subunit's centre is {off.max():.0f} A from the path, "
        f"not the {expected:.1f} A it is from the axis")


def test_a_new_filament_fills_its_path():
    """The path ends where the filament does.

    Forty subunits are thirty-nine gaps of 27.5 A, so the path is 1072.5 A
    long, and its last control node stands beside the last subunit - 15.6 A
    from its centre, like the axis it marks. A path longer than its filament
    has nodes out in empty space; a shorter one leaves subunits running off
    the end of it.
    """
    preset = F.presets().get("ACTIN")
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=110.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    path = _drawn_path(molecule)
    length = np.linalg.norm(np.diff(path, axis=0), axis=1).sum()
    assert length == pytest.approx(39 * ACTIN_RISE, rel=0.005)

    centres = F.chain_centres(molecule, preset)
    last_node = _nodes(molecule)[-1]
    nearest = np.linalg.norm(centres - last_node, axis=1).min()
    assert nearest == pytest.approx(_axis_distance(preset), abs=4.0), (
        f"the last control node is {nearest:.0f} A from the nearest subunit")


def test_a_dragged_filament_is_bent_and_its_subunits_are_not():
    """Bent: the ends are closer together than the filament is long.
    Rigid: every copy's atoms stand to one another exactly as in the file.
    """
    preset = F.presets().get("ACTIN")
    molecule = _bent_actin()

    shipped = F.alpha_carbons(F.presets().structure_path(preset))
    residues = sorted(r for (chain, r) in shipped if chain == "A")[::25]
    in_the_file = np.array([shipped[("A", r)] for r in residues])
    copies = F.drawn_copies(molecule, "A", residues)
    assert len(copies) == 40
    for copy in copies:
        strain = np.abs(F.between(copy, copy)
                        - F.between(in_the_file, in_the_file)).max()
        assert strain < 0.01, f"a subunit was distorted by {strain:.3f} A"

    centres = np.array([copy.mean(axis=0) for copy in copies])
    spread = max(np.linalg.norm(centres - centre, axis=1).max()
                 for centre in centres)
    straight = 39 * ACTIN_RISE
    assert spread < 0.97 * straight, (
        f"the filament spans {spread:.0f} A, as a straight one would")


def test_a_dragged_microtubule_keeps_its_path_down_the_middle():
    """A bent tube is still a tube round its path: every dimer at the wall.

    An alpha tubulin's centre is 112 A from the axis; on a curve whose bends
    are much wider than that, it stays that far from the path.
    """
    preset = F.presets().get("MICROTUBULE")
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='MICROTUBULE', length=300.0) == {'FINISHED'}
    molecule = _new_molecule(before)
    _drag(molecule, 1, (600.0, 0.0, 0.0))

    centres = F.chain_centres(molecule, preset)
    assert len(centres) == 37 * MT_STRANDS       # 3000 / 81.5 = 36.8

    expected = _axis_distance(preset)
    assert expected == pytest.approx(112.0, abs=1.5)
    off = _distance_to_path(centres, _drawn_path(molecule))
    assert np.abs(off - expected).max() < 10.0, (
        f"dimers are between {off.min():.0f} and {off.max():.0f} A from the "
        f"path, not {expected:.0f}")


# --------------------------------------------------------------------------
# Changing the length of a filament that has a path
# --------------------------------------------------------------------------

def _edit_length(molecule, nanometres):
    """Reopen the filament's dialog, ask for a new length, and OK it."""
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )

    scene = bpy.context.scene
    apply_symmetry_settings(scene, _assembly_core().built_build_params(molecule))
    scene.pb_symmetry_length = nanometres
    assert _ok(molecule) == {'FINISHED'}


def test_a_longer_filament_gets_a_longer_path():
    """Twice the filament on the same path would run off the end of it.

    Twenty subunits bent into a bow, then forty: the path must grow with
    them, so the filament still lies along it from the first node to the
    last and is still the same bow - not a bow with a straight tail.
    """
    preset = F.presets().get("ACTIN")
    molecule = _bent_actin(55.0)
    assert _copies(molecule) == 20
    nodes_before = _nodes(molecule)
    path = _drawn_path(molecule)
    length_before = np.linalg.norm(np.diff(path, axis=0), axis=1).sum()

    _edit_length(molecule, 110.0)
    assert _copies(molecule) == 40

    # The bow is longer than the filament it was pulled out of; it grows by
    # as much as the filament did.
    path = _drawn_path(molecule)
    length = np.linalg.norm(np.diff(path, axis=0), axis=1).sum()
    assert length == pytest.approx(length_before * 39 / 19, rel=0.005)

    centres = F.chain_centres(molecule, preset)
    off = _distance_to_path(centres, path)
    assert np.abs(off - _axis_distance(preset)).max() < 4.0, (
        f"a subunit's centre is {off.max():.0f} A from the path")

    # The same shape, 39 gaps for 19: every node as far again from the first.
    nodes_after = _nodes(molecule)
    assert len(nodes_after) == len(nodes_before)
    for was, now in zip(nodes_before, nodes_after):
        expected = nodes_before[0] + (was - nodes_before[0]) * (39 / 19)
        assert np.linalg.norm(now - expected) < 1.0


def test_a_path_the_user_shaped_keeps_its_shape_when_the_length_changes():
    """Dragged nodes are someone's work; resizing must scale it, not reset it."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    # Pull the middle node 100 A sideways.
    middle = _bend().get_bend_nodes(molecule)[1]
    middle.location.x += 100.0 * WORLD_SCALE
    bpy.context.view_layer.update()
    nodes_before = _nodes(molecule)
    assert abs(nodes_before[1][0] - nodes_before[0][0]) == pytest.approx(
        100.0, abs=0.5)

    _edit_length(molecule, 110.0)

    nodes_after = _nodes(molecule)
    assert len(nodes_after) == len(nodes_before)
    for was, now in zip(nodes_before, nodes_after):
        expected = nodes_before[0] + (was - nodes_before[0]) * (39 / 19)
        assert np.linalg.norm(now - expected) < 1.0, (
            f"a node went to {np.round(now)}, not {np.round(expected)}")


def test_a_shorter_filament_gets_a_shorter_path():
    """And the other way: no control nodes left out past the end."""
    preset = F.presets().get("ACTIN")
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=110.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    _edit_length(molecule, 55.0)
    assert _copies(molecule) == 20

    centres = F.chain_centres(molecule, preset)
    nearest = np.linalg.norm(centres - _nodes(molecule)[-1], axis=1).min()
    assert nearest == pytest.approx(_axis_distance(preset), abs=4.0), (
        f"the last control node is {nearest:.0f} A from the nearest subunit")


def test_a_keyframed_path_is_left_alone_when_the_length_changes():
    """Resizing rebuilds the control nodes, and an animation is keyed to them.

    Losing keys the user cannot see have gone is worse than a path that no
    longer matches its filament, so a keyed path stays exactly as it is and
    the longer filament carries straight on past its end.
    """
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    keyed = _bend().get_bend_nodes(molecule)[-1]
    assert keyed.keyframe_insert("location", frame=1)
    names_before = [node.name for node in _bend().get_bend_nodes(molecule)]
    nodes_before = _nodes(molecule)

    _edit_length(molecule, 110.0)
    assert _copies(molecule) == 40

    nodes_after = _nodes(molecule)
    assert [node.name for node in _bend().get_bend_nodes(molecule)] == names_before
    for was, now in zip(nodes_before, nodes_after):
        assert np.linalg.norm(now - was) < 1e-3
    kept = bpy.data.objects[names_before[-1]]
    assert kept.animation_data is not None and kept.animation_data.action is not None


def test_a_rebuild_that_fails_gives_the_path_back():
    """The path is resized before the build, so a failed build must undo it.

    Otherwise the filament on screen is the old one on a path sized for the
    new - and the next attempt resizes that path a second time.
    """
    from proteinblender.operators.assembly_operators import (
        build_generated_symmetry,
    )

    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)
    nodes_before = _nodes(molecule)

    # Twice the length, built from a row that is not there.
    asked = dict(_assembly_core().built_build_params(molecule),
                 count=40, source_item_id="no-such-row")
    ok, _message = build_generated_symmetry(molecule, asked)
    assert not ok, "the build was supposed to fail"

    assert _copies(molecule) == 20
    for was, now in zip(nodes_before, _nodes(molecule)):
        assert np.linalg.norm(now - was) < 0.01, (
            f"a node was left at {np.round(now)}, not {np.round(was)}")


# --------------------------------------------------------------------------
# The Nodes field in Edit Assembly
# --------------------------------------------------------------------------

class _EditDialog:
    """What the dialog's Nodes field is handed: the filament it is open on."""

    def __init__(self, molecule):
        self.molecule_id_to_update = molecule.identifier


def _nodes_field(molecule):
    from proteinblender.operators import symmetry_dialog
    return symmetry_dialog._get_bend_nodes(_EditDialog(molecule))


def _set_nodes_field(molecule, value):
    from proteinblender.operators import symmetry_dialog
    symmetry_dialog._set_bend_nodes(_EditDialog(molecule), value)
    bpy.context.view_layer.update()


def _rig(molecule):
    """The path as the file has it: ``(draggable nodes, curve points)``.

    A node is one the user can drag only if it is an Empty in the scene that
    one of the curve's hooks holds a control point to, so that is what is
    counted - off Blender's data, not asked of the bend code.
    """
    curve = _bend().get_bend_curve(molecule)
    assert curve is not None, "the filament has no bend path"
    in_scene = {obj.name for obj in bpy.context.scene.objects
                if obj.type == 'EMPTY'}
    hooked = {modifier.object.name for modifier in curve.modifiers
              if modifier.type == 'HOOK' and modifier.object is not None}
    return len(hooked & in_scene), len(curve.data.splines[0].bezier_points)


@pytest.mark.parametrize("preset_id, length, copies", [
    ("ACTIN", 55.0, 20),
    ("MICROTUBULE", 50.0, 78),
])
def test_the_nodes_field_gives_the_path_that_many_nodes(preset_id, length, copies):
    """Raising Nodes is the whole gesture: there is nothing else to press.

    It once set a number that a tick beside it had to be clicked to apply, so
    a filament built here kept its three nodes whatever the field said.
    """
    preset = F.presets().get(preset_id)
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset=preset_id, length=length) == {'FINISHED'}
    molecule = _new_molecule(before)
    _drag(molecule, 1, (200.0, 0.0, 0.0))
    assert _rig(molecule) == (3, 3)
    assert _nodes_field(molecule) == 3
    centres_before = F.chain_centres(molecule, preset)

    _set_nodes_field(molecule, 7)

    assert _rig(molecule) == (7, 7)
    assert _nodes_field(molecule) == 7
    # More nodes are a finer grip on the same filament, not a new one.
    assert _copies(molecule) == copies
    moved = np.linalg.norm(
        F.chain_centres(molecule, preset) - centres_before, axis=1).max()
    # A few Angstrom at most: a tube's dimers stand 112 A out from the path,
    # where a twentieth of a degree of frame is already an Angstrom.
    assert moved < 5.0, (
        f"a subunit moved {moved:.1f} A when the path was given more nodes")

    # And back down again.
    _set_nodes_field(molecule, 4)
    assert _rig(molecule) == (4, 4)
    assert _nodes_field(molecule) == 4


def test_the_nodes_field_stays_within_what_a_path_can_have():
    """Asked for more than the most there can be, it gives the most."""
    from proteinblender.core import bend_rig

    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    _set_nodes_field(molecule, 500)
    assert _rig(molecule) == (bend_rig.RES_MAX, bend_rig.RES_MAX)
    _set_nodes_field(molecule, 0)
    assert _rig(molecule) == (bend_rig.RES_MIN, bend_rig.RES_MIN)


def test_the_nodes_field_leaves_a_keyframed_path_alone():
    """New nodes are new objects, and the animation is keyed to the old ones."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)

    keyed = _bend().get_bend_nodes(molecule)[-1]
    assert keyed.keyframe_insert("location", frame=1)
    names_before = sorted(obj.name for obj in bpy.context.scene.objects
                          if obj.type == 'EMPTY')

    _set_nodes_field(molecule, 7)

    assert _rig(molecule) == (3, 3)
    assert _nodes_field(molecule) == 3
    assert sorted(obj.name for obj in bpy.context.scene.objects
                  if obj.type == 'EMPTY') == names_before
    kept = bpy.data.objects[keyed.name]
    assert kept.animation_data is not None and kept.animation_data.action is not None


def test_a_bend_added_afterwards_starts_with_the_nodes_last_chosen():
    """Taking a bend away and putting one back does not forget the count."""
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=55.0) == {'FINISHED'}
    molecule = _new_molecule(before)
    _set_nodes_field(molecule, 6)

    assert bpy.ops.molecule.remove_filament_bend(
        'EXEC_DEFAULT', molecule_id=molecule.identifier) == {'FINISHED'}
    # With no path there is nothing for the field to change, or to break.
    _set_nodes_field(molecule, 9)
    assert _bend().get_bend_curve(molecule) is None

    assert bpy.ops.molecule.add_filament_bend(
        'EXEC_DEFAULT', molecule_id=molecule.identifier) == {'FINISHED'}
    assert _rig(molecule) == (6, 6)
