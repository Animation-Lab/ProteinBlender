"""Building a deposited biological assembly inside ProteinBlender.

Phase 1 of symmetry support: reading which assemblies a structure offers,
deciding which are worth showing, and wiring the copies into the objects that
are actually on screen.

The trap this file exists to guard is that a ProteinBlender import creates one
object per domain on top of the molecule object, and the molecule object draws
only the atoms no domain covers - nothing at all after a normal import. An
assembly built into the molecule object alone is therefore invisible while
looking entirely correct in the node graph, so the assertions here are about
*instances the depsgraph actually places* and pixels rendered, never about the
node tree's own account of itself.

Ground truth is the fixture's `REMARK 350` text, read by the independent
parser in ``test_biological_assembly``.
"""

import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H
from test_biological_assembly import _remark_350_transforms

#: MolecularNodes stores structures at 1/100 scale, so an Angstrom in the file
#: is 0.01 Blender units on screen.
WORLD_SCALE = 0.01

FIXTURE = "4ins.pdb"

# From tests/data/4ins.pdb REMARK 350, read by eye: assemblies 1, 2 and 7 hold
# a single identity transform (the asymmetric unit relabelled), while 3, 4 and
# 5 hold an identity plus two thirds of a three-fold, and 6 holds an identity
# on chains A,B and a three-fold on C,D.
IDENTITY_ONLY = {"1", "2", "7"}
WITH_SYMMETRY = {"3", "4", "5", "6"}


def _assembly_core():
    from proteinblender.core import assembly
    return assembly


def _import(fixture=FIXTURE, ident="4ins"):
    """Import exactly the way the UI does - and set nothing else.

    Deliberately does *not* assign ``scene.selected_molecule_id``. Nothing in
    the add-on writes that property except the rename operator, so a test that
    sets it by hand would hide a panel that never appears in a real session.
    """
    mol_id = H.import_local(fixture, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _instances_by_object():
    """How many instances the depsgraph places for each originating object.

    The only measure that reflects what is drawn. Keyed by object name because
    bpy returns a fresh wrapper on every attribute access, so identity
    comparison between structs is meaningless.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    counts = {}
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None:
            continue
        name = instance.parent.original.name
        counts[name] = counts.get(name, 0) + 1
    return counts


def _instance_matrices():
    """World matrices of every instance, keyed by originating object name."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    matrices = {}
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None:
            continue
        name = instance.parent.original.name
        matrices.setdefault(name, []).append(instance.matrix_world.copy())
    return matrices


def _instance_positions():
    """World positions of every instance, keyed by originating object name."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    positions = {}
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None:
            continue
        name = instance.parent.original.name
        positions.setdefault(name, []).append(
            np.array(instance.matrix_world.translation))
    return positions


def _domain_object_names(molecule):
    names = []
    for domain in molecule.domains.values():
        obj = domain.object
        if obj is not None:
            names.append(obj.name)
    return names


# --------------------------------------------------------------------------
# What the file offers
# --------------------------------------------------------------------------

def test_available_assemblies_match_the_file(scene, sm):
    """Every assembly in REMARK 350, with the right transform count."""
    molecule = _import()
    truth = _remark_350_transforms(FIXTURE)

    infos = {i.assembly_id: i for i in _assembly_core().available_assemblies(molecule)}

    assert sorted(infos) == sorted(truth)
    for assembly_id, expected in truth.items():
        assert infos[assembly_id].transform_count == len(expected), (
            f"assembly {assembly_id}: reported "
            f"{infos[assembly_id].transform_count} copies, REMARK 350 declares "
            f"{len(expected)}")


def test_identity_only_assemblies_are_not_offered(scene, sm):
    """An assembly that is purely the identity would build nothing visible.

    Every deposited structure carries an assembly record; for a monomer it is
    one identity transform. Offering it would be a button that does nothing.
    """
    molecule = _import()

    buildable = {i.assembly_id for i in _assembly_core().buildable_assemblies(molecule)}

    assert buildable == WITH_SYMMETRY
    assert not (buildable & IDENTITY_ONLY)


@pytest.mark.parametrize("fixture,ident,expected", [
    ("4ins.pdb", "4ins", True),
    ("1ubq.pdb", "1ubq", False),
    ("1aki.pdb", "1aki", False),
    ("4hhb.pdb", "4hhb", False),
])
def test_symmetry_is_detected_only_where_it_exists(scene, sm, fixture, ident, expected):
    """The gate the Symmetry panel polls on."""
    molecule = _import(fixture, ident)
    assert _assembly_core().has_buildable_symmetry(molecule) is expected


@pytest.mark.parametrize("fixture,ident,expected", [
    ("4ins.pdb", "4ins", True),
    ("1ubq.pdb", "1ubq", False),
])
def test_panel_polls_itself_away_without_symmetry(scene, sm, fixture, ident, expected):
    """The meeting's requirement: no symmetry in the file, no panel."""
    from proteinblender.panels.symmetry_panel import PROTEINBLENDER_PT_symmetry

    _import(fixture, ident)
    assert PROTEINBLENDER_PT_symmetry.poll(bpy.context) is expected


def test_panel_appears_after_a_plain_import(scene, sm):
    """Importing a symmetric structure is enough to get the panel.

    Nothing writes ``scene.selected_molecule_id`` except the rename operator,
    so a panel resolving the active protein through that alone would be
    invisible in every real session while still passing any test that set the
    property by hand.
    """
    from proteinblender.panels.symmetry_panel import PROTEINBLENDER_PT_symmetry

    _import()
    assert not bpy.context.scene.selected_molecule_id, (
        "import set selected_molecule_id after all - this test is now moot")
    assert PROTEINBLENDER_PT_symmetry.poll(bpy.context) is True


def test_operators_find_the_active_protein_without_being_told(scene, sm):
    """The panel passes molecule_id, but the operators must stand alone too."""
    molecule = _import()

    assert bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", assembly_id="3") == {"FINISHED"}
    assert _assembly_core().built_assembly_id(molecule) == "3"

    assert bpy.ops.molecule.clear_assembly("EXEC_DEFAULT") == {"FINISHED"}
    assert _assembly_core().built_assembly_id(molecule) is None


# --------------------------------------------------------------------------
# Building - measured on screen, not in the node graph
# --------------------------------------------------------------------------

def test_building_places_one_copy_per_deposited_operator(scene, sm):
    """Each domain object must be instanced once per operator for its chain.

    The count comes from REMARK 350, not from the assembly code: assembly 3
    applies three transforms to chains A, B, C and D, so every chain's domain
    object should be placed three times.
    """
    molecule = _import()
    truth = _remark_350_transforms(FIXTURE)

    expected_per_chain = {}
    for chain_ids, _matrix in truth["3"]:
        for chain in chain_ids:
            expected_per_chain[chain] = expected_per_chain.get(chain, 0) + 1
    assert set(expected_per_chain.values()) == {3}, (
        "fixture changed - assembly 3 no longer applies 3 operators per chain")

    assert _assembly_core().build_assembly(molecule, "3")

    counts = _instances_by_object()
    for domain in molecule.domains.values():
        obj = domain.object
        assert obj is not None
        expected = expected_per_chain.get(str(domain.chain_id))
        if expected is None:
            continue
        assert counts.get(obj.name, 0) == expected, (
            f"{obj.name} (chain {domain.chain_id}) was placed "
            f"{counts.get(obj.name, 0)} times, REMARK 350 declares {expected}")


def _chain_centroid_angstrom(chain_letter):
    """Centroid of a chain, read straight out of the fixture's ATOM records.

    Ground truth for *where* a copy belongs, from the file rather than from
    anything the add-on computed.
    """
    coords = []
    with open(H.data_path(FIXTURE)) as handle:
        for line in handle:
            if line.startswith("ATOM") and line[21] == chain_letter:
                coords.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return np.array(coords).mean(axis=0)


def test_copies_land_where_the_operators_put_them(scene, sm):
    """The copies must be placed by the operator, in the deposited frame.

    This is the assertion that copy-counting cannot make. MolecularNodes'
    assembly node splits the structure into per-chain *centred* instances
    before transforming, which discards where each chain sits relative to the
    crystallographic origin - the very thing a BIOMT operator is defined
    against. The copies then rotate about each chain's own centroid and land
    on top of each other: correct in number, wrong in space.

    Chain A of 4ins sits 19.2 A off the origin, so the three-fold of assembly
    3 must separate consecutive copies by ~30.3 A - 0.303 in Blender units at
    MolecularNodes' 0.01 world scale. The observed separation before this was
    fixed was 0.0095, a factor of 32 too small.

    ChimeraX's `sym` gets this right by never touching coordinates: it applies
    each operator as a placement matrix on the whole model, in the frame the
    file deposited it in.
    """
    molecule = _import()

    centroid = _chain_centroid_angstrom("A")
    truth = _remark_350_transforms(FIXTURE)
    rotations = [np.array(matrix)[:3, :3] for _chains, matrix in truth["3"]]

    placed = [rotation @ centroid for rotation in rotations]
    expected = [
        float(np.linalg.norm(placed[i] - placed[j])) * WORLD_SCALE
        for i in range(len(placed)) for j in range(i + 1, len(placed))
    ]
    assert min(expected) > 0.1, (
        "fixture changed - assembly 3 no longer separates its copies")

    assert _assembly_core().build_assembly(molecule, "3")

    chain_a = next(d.object for d in molecule.domains.values()
                   if str(d.chain_id) == "A")

    # Compare where the chain's *atoms* land, not where the instance origins
    # land. An instance origin sits at the object origin, so the gap between
    # origins is governed by ProteinBlender's pivot rather than by the chain's
    # position - close to the right answer for the wrong reason, and off by a
    # few percent because the pivot is mass-weighted.
    #
    # Transforming one known point by each instance matrix removes that: the
    # pivot cancels out of the *difference* between two copies, leaving exactly
    # s*(R_i - R_j) @ centroid.
    from proteinblender.core import domain_space

    pivot = np.array(domain_space.get_pivot(chain_a))
    local = np.array(centroid) * WORLD_SCALE - pivot

    matrices = _instance_matrices()[chain_a.name]
    assert len(matrices) == len(placed)
    landed = [np.array(m @ Vector(local.tolist())) for m in matrices]

    observed = sorted(
        float(np.linalg.norm(landed[i] - landed[j]))
        for i in range(len(landed)) for j in range(i + 1, len(landed))
    )

    for got, want in zip(observed, sorted(expected)):
        assert got == pytest.approx(want, rel=0.01), (
            f"a copy's atoms land {got:.4f} from its neighbour but the "
            f"operators put them {want:.4f} apart - the copies are being "
            f"rotated about the wrong origin")


def test_building_puts_the_copies_on_screen(scene, sm, tmp_path):
    """The copies must actually render.

    An assembly wired only into the molecule object passes every node-graph
    check and still shows nothing, because that object draws only the atoms no
    domain covers - none, after a normal import.
    """
    molecule = _import()

    before = int(H.render_coverage(tmp_path).sum())
    assert before > 0, "the protein rendered nothing before the assembly was built"

    assert _assembly_core().build_assembly(molecule, "3")
    bpy.context.view_layer.update()
    after = int(H.render_coverage(tmp_path).sum())

    assert after > before, (
        f"building the assembly changed nothing on screen ({before} -> {after} "
        "px) - the copies are probably on the invisible molecule object")


def test_clearing_restores_the_asymmetric_unit(scene, sm):
    """Build then clear must land exactly back where it started."""
    molecule = _import()
    baseline = _instances_by_object()

    assert _assembly_core().build_assembly(molecule, "3")
    assert _instances_by_object() != baseline

    assert _assembly_core().clear_assembly(molecule)
    assert _instances_by_object() == baseline
    assert _assembly_core().built_assembly_id(molecule) is None


def test_rebuilding_does_not_stack_copies(scene, sm):
    """Building twice replaces, never accumulates."""
    molecule = _import()

    assert _assembly_core().build_assembly(molecule, "3")
    once = _instances_by_object()

    assert _assembly_core().build_assembly(molecule, "3")
    assert _instances_by_object() == once

    # And switching assemblies replaces rather than adding a second node.
    assert _assembly_core().build_assembly(molecule, "4")
    assert _assembly_core().built_assembly_id(molecule) == "4"


def test_built_assembly_id_reads_back_what_was_built(scene, sm):
    molecule = _import()
    assert _assembly_core().built_assembly_id(molecule) is None

    assert _assembly_core().build_assembly(molecule, "5")
    assert _assembly_core().built_assembly_id(molecule) == "5"


def test_unknown_assembly_is_refused(scene, sm):
    molecule = _import()
    assert _assembly_core().build_assembly(molecule, "99") is False
    assert _assembly_core().built_assembly_id(molecule) is None


# --------------------------------------------------------------------------
# Through the operators the panel actually calls
# --------------------------------------------------------------------------

def test_build_operator_builds(scene, sm):
    molecule = _import()

    result = bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, assembly_id="3")

    assert result == {"FINISHED"}
    assert _assembly_core().built_assembly_id(molecule) == "3"


def test_clear_operator_clears(scene, sm):
    molecule = _import()
    bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, assembly_id="3")

    result = bpy.ops.molecule.clear_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier)

    assert result == {"FINISHED"}
    assert _assembly_core().built_assembly_id(molecule) is None


def test_clear_operator_on_nothing_is_cancelled(scene, sm):
    molecule = _import()
    result = bpy.ops.molecule.clear_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier)
    assert result == {"CANCELLED"}


def test_assembly_enum_offers_only_symmetric_assemblies(scene, sm):
    """The picker must not list the identity-only assemblies either."""
    from proteinblender.operators.assembly_operators import assembly_enum_items

    _import()
    identifiers = {item[0] for item in assembly_enum_items(None, bpy.context)}

    assert identifiers == WITH_SYMMETRY


# --------------------------------------------------------------------------
# Animation - the assemble / disassemble factor
# --------------------------------------------------------------------------

def _landing_points(molecule, chain_letter="A"):
    """Where the chain's centroid lands under each copy, in world space.

    Transforming one known point by each instance matrix, rather than reading
    instance origins, so the pivot cancels out of any comparison between two
    copies.
    """
    from proteinblender.core import domain_space

    obj = next(d.object for d in molecule.domains.values()
               if str(d.chain_id) == chain_letter)
    pivot = np.array(domain_space.get_pivot(obj))
    local = np.array(_chain_centroid_angstrom(chain_letter)) * WORLD_SCALE - pivot

    return [np.array(m @ Vector(local.tolist()))
            for m in _instance_matrices()[obj.name]]


def _expected_spread(factor, chain_letter="A"):
    """How far apart the copies should be at this factor, from the file.

    Interpolating from the identity to an operator means rotating about that
    operator's own axis by a fraction of its angle, so the expected geometry at
    any factor is computable from `REMARK 350` alone.
    """
    from mathutils import Matrix as BM, Vector as V

    centroid = V((np.array(_chain_centroid_angstrom(chain_letter)) * WORLD_SCALE).tolist())
    truth = _remark_350_transforms(FIXTURE)

    placed = []
    for _chains, matrix in truth["3"]:
        quaternion = BM([row[:3] for row in matrix[:3]]).to_quaternion()
        angle = quaternion.angle
        axis = quaternion.axis if abs(angle) > 1e-9 else V((0.0, 0.0, 1.0))
        partial = BM.Rotation(angle * factor, 3, axis)
        placed.append(np.array(partial @ centroid))

    return max(
        float(np.linalg.norm(placed[i] - placed[j]))
        for i in range(len(placed)) for j in range(i + 1, len(placed))
    )


def _observed_spread(molecule):
    points = _landing_points(molecule)
    return max(
        float(np.linalg.norm(points[i] - points[j]))
        for i in range(len(points)) for j in range(i + 1, len(points))
    )


def test_factor_zero_puts_every_copy_back_on_the_asymmetric_unit(scene, sm):
    """Fully disassembled means the copies coincide with the original.

    Not "close to" - exactly. Factor 0 must make the assembly indistinguishable
    from the unbuilt structure, otherwise an animation starting at 0 opens with
    a visible jolt.
    """
    molecule = _import()
    assert _assembly_core().build_assembly(molecule, "3")

    _assembly_core().set_assembly_factor(molecule, 0.0)
    points = _landing_points(molecule)

    assert len(points) > 1
    for point in points[1:]:
        assert np.allclose(point, points[0], atol=1e-6), (
            "at factor 0 the copies should sit exactly on top of each other")


def test_factor_one_reproduces_the_deposited_assembly(scene, sm):
    """The end of the animation must be the assembly Phase 1 builds."""
    molecule = _import()
    assert _assembly_core().build_assembly(molecule, "3")

    _assembly_core().set_assembly_factor(molecule, 1.0)

    assert _observed_spread(molecule) == pytest.approx(_expected_spread(1.0), rel=0.01)


@pytest.mark.parametrize("factor", [0.25, 0.5, 0.75])
def test_intermediate_factors_are_real_intermediates(scene, sm, factor):
    """Halfway through must be halfway rotated, not halfway faded.

    The expected spread comes from rotating the file's own centroid about the
    operator's own axis by a fraction of its angle - independent of how the
    node tree chooses to interpolate.
    """
    molecule = _import()
    assert _assembly_core().build_assembly(molecule, "3")

    _assembly_core().set_assembly_factor(molecule, factor)

    assert _observed_spread(molecule) == pytest.approx(
        _expected_spread(factor), rel=0.02)


def test_the_assembly_opens_monotonically(scene, sm):
    """Sweeping the factor must open the assembly, never jump about.

    Measured as each copy's displacement from where it started, *not* as the
    spread between copies. For a three-fold the widest gap is genuinely not
    monotonic: the two outer copies swing past each other, so the chord
    2r*sin(theta/2) peaks at 180 degrees (factor 0.75) and closes again by
    240 degrees. Asserting on the spread would fail on correct geometry.
    """
    core = _assembly_core()
    molecule = _import()
    assert core.build_assembly(molecule, "3")

    core.set_assembly_factor(molecule, 0.0)
    start = _landing_points(molecule)

    tracks = [[] for _ in start]
    for factor in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        core.set_assembly_factor(molecule, factor)
        for i, point in enumerate(_landing_points(molecule)):
            tracks[i].append(float(np.linalg.norm(point - start[i])))

    moved = 0
    for i, track in enumerate(tracks):
        assert track[0] == pytest.approx(0.0, abs=1e-6)
        for earlier, later in zip(track, track[1:]):
            assert later > earlier - 1e-6, (
                f"copy {i} moved backwards as the factor rose: {track}")
        if track[-1] > 1e-4:
            moved += 1

    assert moved >= 2, f"the copies never travelled anywhere: {tracks}"


def test_stagger_makes_the_copies_arrive_at_different_times(scene, sm):
    """With stagger on, copies must be at different stages mid-animation.

    Without it every copy shares one factor and they move in lockstep; the
    interesting version has them arriving in sequence.
    """
    core = _assembly_core()
    molecule = _import()
    assert core.build_assembly(molecule, "3")

    def progress():
        """Each copy's distance from where it started, as a spread."""
        points = _landing_points(molecule)
        origin = points[0]
        return [float(np.linalg.norm(p - origin)) for p in points[1:]]

    core.set_assembly_factor(molecule, 0.5, stagger=0.0)
    together = progress()

    core.set_assembly_factor(molecule, 0.5, stagger=1.0)
    staggered = progress()

    assert together, "no copies to compare"
    # In lockstep the copies are symmetric about the original; staggered, the
    # later ones have not caught up.
    assert max(staggered) < max(together) + 1e-6
    assert min(staggered) < min(together) - 1e-6, (
        f"stagger changed nothing: together={together} staggered={staggered}")


def test_the_factor_can_be_keyframed(scene, sm):
    """The animation has to survive as keyframes, not just a live slider."""
    core = _assembly_core()
    molecule = _import()
    assert core.build_assembly(molecule, "3")

    core.set_assembly_factor(molecule, 0.0)
    assert core.keyframe_assembly(molecule, frame=1) > 0
    core.set_assembly_factor(molecule, 1.0)
    assert core.keyframe_assembly(molecule, frame=50) > 0

    scene.frame_set(1)
    assert _observed_spread(molecule) == pytest.approx(0.0, abs=1e-5)

    scene.frame_set(50)
    assert _observed_spread(molecule) == pytest.approx(_expected_spread(1.0), rel=0.02)

    scene.frame_set(25)
    midway = _observed_spread(molecule)
    assert 0.0 < midway < _expected_spread(1.0)


def test_keyframe_operator_keys_the_assembly(scene, sm):
    molecule = _import()
    bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, assembly_id="3")

    scene.frame_set(1)
    _assembly_core().set_assembly_factor(molecule, 0.0)
    assert bpy.ops.molecule.keyframe_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}

    scene.frame_set(40)
    _assembly_core().set_assembly_factor(molecule, 1.0)
    assert bpy.ops.molecule.keyframe_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}

    scene.frame_set(1)
    assert _observed_spread(molecule) == pytest.approx(0.0, abs=1e-5)
    scene.frame_set(40)
    assert _observed_spread(molecule) > 0.1


def test_keyframing_without_an_assembly_is_refused(scene, sm):
    molecule = _import()
    assert bpy.ops.molecule.keyframe_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"CANCELLED"}


def test_the_panel_sliders_reach_the_nodes(scene, sm):
    """The scene sliders are only a handle - they must drive the real value."""
    molecule = _import()
    bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, assembly_id="3")

    scene.pb_assembly_factor = 0.0
    assert _assembly_core().get_assembly_factor(molecule) == pytest.approx(0.0)
    assert _observed_spread(molecule) == pytest.approx(0.0, abs=1e-6)

    scene.pb_assembly_factor = 1.0
    assert _assembly_core().get_assembly_factor(molecule) == pytest.approx(1.0)

    scene.pb_assembly_stagger = 1.0
    assert _assembly_core().get_assembly_stagger(molecule) == pytest.approx(1.0)


def test_clearing_removes_the_animation_too(scene, sm):
    """Clearing must not leave orphaned point clouds or node groups behind."""
    core = _assembly_core()
    molecule = _import()
    core.build_assembly(molecule, "3")

    prefix = f".pb_assembly_{molecule.identifier}_"
    assert [o for o in bpy.data.objects if o.name.startswith(prefix)]

    core.clear_assembly(molecule)
    assert not [o for o in bpy.data.objects if o.name.startswith(prefix)]
