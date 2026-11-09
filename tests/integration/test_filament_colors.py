"""Colouring a filament's subunits one by one, and animating the colours.

What is drawn is read out of the evaluated scene: every copy Blender draws,
as an instance or as the geometry a painted copy is realized into, with the
``Color`` attribute every style's material reads. Which subunit is which comes
from the structure - counted up the filament from the pointed end, which
actin's D-loop points at - not from the lattice code that numbers them.
"""

import math

import bpy
import numpy as np
import pytest

import filament_checks as F
import helpers as H
from filament_checks import build as _build

WORLD_SCALE = 0.01
RED = (1.0, 0.0, 0.0)
D_LOOP = range(40, 51)


def _colors():
    from proteinblender.core import subunit_colors
    return subunit_colors


def _object(molecule, chain):
    return next(d.object for d in molecule.domains.values()
                if str(d.chain_id) == chain)


def _drawn(molecule, chain="A"):
    """``(instances, painted)`` for one chain, each a list of ``(centre, colour)``.

    ``centre`` is the mean of the copy's vertices in world space (Angstrom) and
    ``colour`` the mean of its ``Color`` attribute.
    """
    obj = _object(molecule, chain)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    instances, painted = [], []
    for entry in depsgraph.object_instances:
        data = entry.object.data
        if not isinstance(data, bpy.types.Mesh) or not len(data.vertices):
            continue
        is_copy = (entry.is_instance and entry.parent is not None
                   and entry.parent.original.name == obj.name)
        is_painted = (not entry.is_instance
                      and entry.object.original.name == obj.name)
        if not (is_copy or is_painted):
            continue
        count = len(data.vertices)
        position = np.zeros(count * 3)
        data.attributes["position"].data.foreach_get("vector", position)
        colour = np.zeros(count * 4)
        data.attributes["Color"].data.foreach_get("color", colour)
        position, colour = position.reshape(-1, 3), colour.reshape(-1, 4)
        matrix = np.array(entry.matrix_world)
        world = position @ matrix[:3, :3].T + matrix[:3, 3]
        if is_copy:
            instances.append((world.mean(axis=0) / WORLD_SCALE, colour[:, :3].mean(axis=0)))
        else:
            painted.append((world, colour))
    return instances, _split_painted(painted, instances, molecule, chain)


def _vertices_per_copy(molecule, chain):
    """How many vertices one copy of a chain is drawn with: an instance's."""
    obj = _object(molecule, chain)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for entry in depsgraph.object_instances:
        if (entry.is_instance and entry.parent is not None
                and entry.parent.original.name == obj.name
                and isinstance(entry.object.data, bpy.types.Mesh)):
            return len(entry.object.data.vertices)
    return None


def _split_painted(painted, instances, molecule, chain):
    """Everything painted is realized into one mesh, a copy's worth of
    vertices after another; cut it back into copies."""
    if not painted:
        return []
    world, colour = painted[0]
    per_copy = _vertices_per_copy(molecule, chain)
    if not per_copy or len(world) % per_copy:
        per_copy = len(world)
    return [(world[i:i + per_copy].mean(axis=0) / WORLD_SCALE,
             colour[i:i + per_copy, :3].mean(axis=0))
            for i in range(0, len(world), per_copy)]



def _path_axis(molecule):
    from proteinblender.core import symmetry_bend
    nodes = [np.array(n.matrix_world.translation) / WORLD_SCALE
             for n in symmetry_bend.get_bend_nodes(molecule)]
    axis = nodes[-1] - nodes[0]
    return axis / np.linalg.norm(axis)


def _from_the_pointed_end(molecule):
    """Actin copies' centres, in order up the filament from its pointed end."""
    preset = F.presets().get("ACTIN")
    shipped = F.alpha_carbons(F.presets().structure_path(preset))
    everything = sorted(r for (c, r) in shipped if c == "A")
    loop = [r for r in everything if r in D_LOOP]
    whole = [copy.mean(axis=0) for copy in F.drawn_copies(molecule, "A", everything)]
    loops = [copy.mean(axis=0) for copy in F.drawn_copies(molecule, "A", loop)]
    axis = _path_axis(molecule)
    pointing = float(np.mean([(lp - c) @ axis for lp, c in zip(loops, whole)]))
    towards_barbed = -np.sign(pointing) * axis
    instances, _painted = _drawn(molecule)
    centres = np.array([centre for centre, _colour in instances])
    return centres[np.argsort(centres @ towards_barbed)]


def _paint(molecule, names, colour=RED, strength=1.0):
    """Select rows of the Subunits list and press Colour Selected."""
    colors = _colors()
    colors.sync_roster(molecule)
    rows = molecule.object.pb_filament.subunits
    for row in rows:
        row.select = row.name in names
    bpy.context.scene.pb_subunit_color = colour
    assert bpy.ops.molecule.color_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier) == {'FINISHED'}
    if strength != 1.0:
        for name in names:
            molecule.object.pb_filament.colors[name].strength = strength


def _near(centre, centres, tolerance=0.5):
    distances = np.linalg.norm(np.asarray(centres) - centre, axis=1)
    return float(distances.min()) < tolerance


# --------------------------------------------------------------------------
# One subunit, its own colour
# --------------------------------------------------------------------------

def test_colouring_the_fourth_actin_from_the_pointed_end_paints_only_it():
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    assert len(ordered) == 10

    # Rows count up from the minus end, which for actin is the pointed end.
    _paint(molecule, ["3:A"])

    instances, painted = _drawn(molecule)
    assert len(instances) == 9 and len(painted) == 1
    centre, colour = painted[0]
    assert _near(centre, [ordered[3]]), "the painted copy is not the fourth from the pointed end"
    assert np.allclose(colour, RED, atol=1e-3), colour
    for other_centre, other_colour in instances:
        assert not np.allclose(other_colour, RED, atol=0.05)
        assert not _near(other_centre, [ordered[3]])


def test_a_microtubule_paints_one_monomer_of_a_dimer():
    chains = F.tubulin_chains()
    molecule = _build("MICROTUBULE", 9.0)
    _paint(molecule, [f"5:{chains['beta']}"])

    beta_instances, beta_painted = _drawn(molecule, chains["beta"])
    alpha_instances, alpha_painted = _drawn(molecule, chains["alpha"])
    assert (len(beta_instances), len(beta_painted)) == (12, 1)
    assert (len(alpha_instances), len(alpha_painted)) == (13, 0)
    assert np.allclose(beta_painted[0][1], RED, atol=1e-3)


def test_strength_mixes_the_subunits_own_colour_with_its_paint():
    molecule = _build("ACTIN", 27.5)
    instances, _painted = _drawn(molecule)
    own = instances[0][1]
    _paint(molecule, ["2:A"], strength=0.5)
    _instances, painted = _drawn(molecule)
    assert np.allclose(painted[0][1], (own + np.array(RED)) / 2, atol=0.02)


def test_clearing_a_colour_gives_the_subunit_back_to_the_filament():
    molecule = _build("ACTIN", 27.5)
    _paint(molecule, ["2:A", "4:A"])
    assert len(_drawn(molecule)[1]) == 2
    for row in molecule.object.pb_filament.subunits:
        row.select = row.name == "2:A"
    assert bpy.ops.molecule.color_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier, clear=True) == {'FINISHED'}
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (9, 1)
    assert list(molecule.object.pb_filament.colors.keys()) == ["4:A"]


# --------------------------------------------------------------------------
# The colour stays with its subunit
# --------------------------------------------------------------------------

def _edit(molecule, **changes):
    from proteinblender.core import assembly
    from proteinblender.operators.assembly_operators import apply_symmetry_settings
    scene = bpy.context.scene
    apply_symmetry_settings(scene, assembly.built_build_params(molecule))
    for prop, value in changes.items():
        setattr(scene, f"pb_symmetry_{prop}", value)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier,
        source='GENERATED') == {'FINISHED'}


def test_a_colour_stays_with_its_subunit_when_the_minus_end_shrinks():
    molecule = _build("ACTIN", 27.5)
    _paint(molecule, ["5:A"])
    before = _drawn(molecule)[1][0][0]

    _edit(molecule, shrink_minus=2)

    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (7, 1)
    assert _near(painted[0][0], [before], tolerance=0.05)


def test_a_colour_stays_with_its_subunit_when_the_filament_grows():
    molecule = _build("ACTIN", 27.5)
    _paint(molecule, ["5:A"])
    before = _drawn(molecule)[1][0][0]

    _edit(molecule, count=20)

    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (19, 1)
    assert _near(painted[0][0], [before], tolerance=0.05)


def test_a_subunit_shrunk_away_takes_its_colour_out_of_sight_and_back():
    molecule = _build("ACTIN", 27.5)
    _paint(molecule, ["0:A"])
    _edit(molecule, shrink_minus=1)
    assert _drawn(molecule)[1] == []
    _edit(molecule, shrink_minus=0)
    assert len(_drawn(molecule)[1]) == 1


def test_a_build_from_before_colours_can_still_be_painted():
    """A filament saved before this existed has no tint stage; painting adds it."""
    from proteinblender.core import assembly
    molecule = _build("ACTIN", 27.5)
    for tree in bpy.data.node_groups:
        if not assembly.has_tint_stage(tree):
            continue
        for node in [n for n in tree.nodes if n.name.startswith("PB Tint")]:
            tree.nodes.remove(node)
        output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT')
        copies = next(n for n in tree.nodes if n.name == "PB Instance Copies")
        tree.links.new(copies.outputs[0], output.inputs[0])
    assert not any(assembly.has_tint_stage(t) for t in bpy.data.node_groups)

    _paint(molecule, ["1:A"])
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (9, 1)


# --------------------------------------------------------------------------
# Keyframes
# --------------------------------------------------------------------------

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


def test_a_keyed_colour_plays_back():
    """Red at frame 1, blue at frame 21: half way between at frame 11."""
    scene = bpy.context.scene
    molecule = _build("ACTIN", 27.5)
    scene.frame_set(1)
    _paint(molecule, ["3:A"], colour=RED)
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(21)
    molecule.object.pb_filament.colors["3:A"].color = (0.0, 0.0, 1.0)
    assert _key(molecule, 21) == {'FINISHED'}

    scene.frame_set(1)
    assert np.allclose(_drawn(molecule)[1][0][1], RED, atol=1e-3)
    scene.frame_set(21)
    assert np.allclose(_drawn(molecule)[1][0][1], (0, 0, 1), atol=1e-3)
    scene.frame_set(11)
    middle = _drawn(molecule)[1][0][1]
    assert 0.2 < middle[0] < 0.8 and 0.2 < middle[2] < 0.8, middle


def test_a_keyed_strength_fades_a_subunit_back():
    scene = bpy.context.scene
    molecule = _build("ACTIN", 27.5)
    scene.frame_set(1)
    _paint(molecule, ["3:A"])
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(11)
    molecule.object.pb_filament.colors["3:A"].strength = 0.0
    assert _key(molecule, 11) == {'FINISHED'}

    scene.frame_set(11)
    assert _drawn(molecule)[1] == []
    scene.frame_set(1)
    assert len(_drawn(molecule)[1]) == 1


def test_clearing_a_keyed_colour_takes_its_keys_too():
    scene = bpy.context.scene
    molecule = _build("ACTIN", 27.5)
    scene.frame_set(1)
    _paint(molecule, ["3:A"])
    assert _key(molecule, 1) == {'FINISHED'}
    for row in molecule.object.pb_filament.subunits:
        row.select = row.name == "3:A"
    assert bpy.ops.molecule.color_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier, clear=True) == {'FINISHED'}
    action = molecule.object.animation_data.action
    from proteinblender.utils.animation import get_fcurves_from_action
    assert not [c for c in get_fcurves_from_action(action, molecule.object.animation_data)
                if "colors" in c.data_path]
    scene.frame_set(2)
    assert _drawn(molecule)[1] == []


def test_clearing_one_colour_leaves_the_others_keys_on_their_subunits():
    """Keys follow an entry by position; removing an earlier one must not shift them."""
    scene = bpy.context.scene
    molecule = _build("ACTIN", 27.5)
    scene.frame_set(1)
    _paint(molecule, ["2:A"], colour=RED)
    _paint(molecule, ["6:A"], colour=(0.0, 0.0, 1.0))
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(11)
    molecule.object.pb_filament.colors["6:A"].color = (0.0, 1.0, 0.0)
    assert _key(molecule, 11) == {'FINISHED'}

    for row in molecule.object.pb_filament.subunits:
        row.select = row.name == "2:A"
    assert bpy.ops.molecule.color_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier, clear=True) == {'FINISHED'}

    scene.frame_set(1)
    (centre, colour), = _drawn(molecule)[1]
    assert np.allclose(colour, (0, 0, 1), atol=1e-3), colour
    scene.frame_set(11)
    (centre_later, colour), = _drawn(molecule)[1]
    assert np.allclose(colour, (0, 1, 0), atol=1e-3), colour
    assert np.allclose(centre, centre_later)


def _render(tmp_path, molecule, frames):
    """Render frames from the side under a sun; return each frame's pixels."""
    scene = bpy.context.scene
    if "colour_sun" not in bpy.data.objects:
        sun = bpy.data.objects.new("colour_sun", bpy.data.lights.new("colour_sun", 'SUN'))
        sun.data.energy = 4.0
        sun.rotation_euler = (math.pi / 2, 0.0, 0.0)
        scene.collection.objects.link(sun)
    cam_data = bpy.data.cameras.get("colour_cam") or bpy.data.cameras.new("colour_cam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 4.0
    cam = bpy.data.objects.get("colour_cam") or bpy.data.objects.new("colour_cam", cam_data)
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    middle = molecule.object.matrix_world.translation
    cam.location = (middle.x, middle.y - 30.0, middle.z + 1.3)
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)
    scene.camera = cam
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 4
    scene.cycles.device = "CPU"
    scene.render.resolution_x = scene.render.resolution_y = 96
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(tmp_path / "frame_")
    scene.frame_start, scene.frame_end = min(frames), max(frames)
    assert bpy.ops.render.render(animation=True) == {'FINISHED'}
    shots = {}
    for frame in frames:
        img = bpy.data.images.load(str(tmp_path / f"frame_{frame:04d}.png"))
        try:
            shots[frame] = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
        finally:
            bpy.data.images.remove(img)
    return shots


def _green(px):
    covered = px[:, 3] > 0.5
    # Lit, a green subunit is a pale green; actin's own colour is a pink.
    return int((covered & (px[:, 1] > 1.3 * px[:, 0])
                & (px[:, 1] > 1.3 * px[:, 2])).sum())


@pytest.mark.slow
def test_an_animation_render_draws_the_keyed_colour_at_each_frame(tmp_path):
    """Green at frame 1, faded out by frame 3, rendered with the viewport left at 3.

    An animation render evaluates into a depsgraph of its own, so the colours
    have to come from the keys, not from the properties the viewport set.
    """
    scene = bpy.context.scene
    molecule = _build("ACTIN", 27.5)
    scene.frame_set(1)
    _paint(molecule, ["4:A", "5:A"], colour=(0.0, 1.0, 0.0))
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(3)
    for name in ("4:A", "5:A"):
        molecule.object.pb_filament.colors[name].strength = 0.0
    assert _key(molecule, 3) == {'FINISHED'}

    shots = _render(tmp_path, molecule, (1, 3))
    assert _green(shots[1]) > 20, _green(shots[1])
    assert _green(shots[3]) == 0, _green(shots[3])


@pytest.mark.slow
def test_a_painted_subunit_renders_in_its_colour(tmp_path):
    """Cycles, from the side, under a sun: green pixels where there were none.

    Green because actin's own colour is a red-brown, which red paint would
    hide in.
    """
    molecule = _build("ACTIN", 27.5)
    sun = bpy.data.objects.new("colour_sun", bpy.data.lights.new("colour_sun", 'SUN'))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.pi / 2, 0.0, 0.0)
    bpy.context.scene.collection.objects.link(sun)

    def green_pixels():
        scene = bpy.context.scene
        cam_data = bpy.data.cameras.get("colour_cam") or bpy.data.cameras.new("colour_cam")
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = 4.0
        cam = bpy.data.objects.get("colour_cam") or bpy.data.objects.new("colour_cam", cam_data)
        if cam.name not in scene.collection.objects:
            scene.collection.objects.link(cam)
        middle = np.mean([c for c, _ in _drawn(molecule)[0]], axis=0) * WORLD_SCALE
        cam.location = (middle[0], middle[1] - 30.0, middle[2])
        cam.rotation_euler = (math.pi / 2, 0.0, 0.0)
        scene.camera = cam
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 4
        scene.cycles.device = "CPU"
        scene.render.resolution_x = scene.render.resolution_y = 96
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = "PNG"
        out = str(tmp_path / f"shot_{len(list(tmp_path.iterdir()))}.png")
        scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(out)
        try:
            px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
        finally:
            bpy.data.images.remove(img)
        covered = px[:, 3] > 0.5
        green = covered & (px[:, 1] > 1.3 * px[:, 0]) & (px[:, 1] > 1.3 * px[:, 2])
        return int(covered.sum()), int(green.sum())

    covered, green = green_pixels()
    assert covered > 0 and green == 0, (covered, green)
    _paint(molecule, ["4:A", "5:A"], colour=(0.0, 1.0, 0.0))
    covered, green = green_pixels()
    # Two of the ten subunits face the camera in green.
    assert green > covered // 20, (covered, green)


# --------------------------------------------------------------------------
# Realizing the copies
# --------------------------------------------------------------------------

def _drawn_protein(molecule_id, chain="A"):
    """``(centre, colour)`` one realized protein's chain is drawn with.

    Read from what the evaluated scene draws for the chain's object, so it is
    the colour on screen and not the one the domain model records.
    """
    obj = _object(H.sm().molecules[molecule_id], chain)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    worlds, colours = [], []
    for entry in depsgraph.object_instances:
        owner = entry.parent if entry.is_instance and entry.parent is not None else entry.object
        data = entry.object.data
        if (owner.original.name != obj.name or not isinstance(data, bpy.types.Mesh)
                or not len(data.vertices) or "Color" not in data.attributes):
            continue
        count = len(data.vertices)
        position = np.zeros(count * 3)
        data.attributes["position"].data.foreach_get("vector", position)
        colour = np.zeros(count * 4)
        data.attributes["Color"].data.foreach_get("color", colour)
        matrix = np.array(entry.matrix_world)
        worlds.append(position.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])
        colours.append(colour.reshape(-1, 4)[:, :3])
    assert worlds, f"nothing drawn for {molecule_id}"
    return (np.concatenate(worlds).mean(axis=0) / WORLD_SCALE,
            np.concatenate(colours).mean(axis=0))


def test_a_realized_copy_keeps_its_subunit_colour():
    """Paint the fourth actin from the pointed end, realize: the protein that
    stands there is drawn green, and no other is."""
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    green = (0.0, 1.0, 0.0)
    _paint(molecule, ["3:A"], colour=green)

    made = F.realize(molecule)
    assert len(made) == 9
    drawn = {mid: _drawn_protein(mid) for mid in [molecule.identifier, *made]}

    at_fourth = [mid for mid, (centre, _c) in drawn.items() if _near(centre, [ordered[3]], 1.0)]
    assert len(at_fourth) == 1, "no single protein stands where the fourth actin was"
    assert np.allclose(drawn[at_fourth[0]][1], green, atol=0.02), drawn[at_fourth[0]][1]
    # Its PB Outliner swatch says so too.
    row = next(item for item in bpy.context.scene.outliner_items
               if item.item_type == 'PROTEIN' and item.item_id == at_fourth[0])
    assert np.allclose(tuple(row.row_color)[:3], green, atol=0.02), tuple(row.row_color)
    for mid, (_centre, colour) in drawn.items():
        if mid != at_fourth[0]:
            assert not np.allclose(colour, green, atol=0.2), (mid, colour)


def test_the_original_keeps_its_own_subunit_colour_when_realized():
    """Copy 0 is the original itself: painted, it stays painted."""
    molecule = _build("ACTIN", 27.5)
    green = (0.0, 1.0, 0.0)
    _paint(molecule, ["0:A"], colour=green)
    made = F.realize(molecule)
    assert len(made) == 9
    _centre, colour = _drawn_protein(molecule.identifier)
    assert np.allclose(colour, green, atol=0.02), colour
    for mid in made:
        assert not np.allclose(_drawn_protein(mid)[1], green, atol=0.2), mid


# --------------------------------------------------------------------------
# The Subunits list and picking
# --------------------------------------------------------------------------

def test_the_list_names_every_monomer_of_a_microtubule():
    chains = F.tubulin_chains()
    molecule = _build("MICROTUBULE", 17.0)        # two dimers a protofilament
    _colors().sync_roster(molecule)
    rows = molecule.object.pb_filament.subunits
    assert len(rows) == 2 * 13 * 2
    labels = {row.name: row.label for row in rows}
    assert labels[f"0:{chains['alpha']}"] == "Alpha Tubulin 1 - Strand 1"
    assert labels[f"13:{chains['beta']}"] == "Beta Tubulin 2 - Strand 1"
    assert labels[f"1:{chains['beta']}"] == "Beta Tubulin 1 - Strand 2"


def test_select_all_selects_only_what_is_left():
    molecule = _build("ACTIN", 27.5)
    _edit(molecule, shrink_plus=3)
    _colors().sync_roster(molecule)
    assert bpy.ops.molecule.select_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier, action='ALL') == {'FINISHED'}
    assert sorted(_colors().selected_keys(molecule)) == sorted(f"{i}:A" for i in range(7))
    assert bpy.ops.molecule.select_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier, action='INVERT') == {'FINISHED'}
    assert _colors().selected_keys(molecule) == []


def test_select_all_of_one_tubulin_selects_only_that_tubulin():
    """On a microtubule, all alpha selects every alpha monomer and nothing else."""
    chains = F.tubulin_chains()
    molecule = _build("MICROTUBULE", 17.0)        # two dimers a protofilament
    _colors().sync_roster(molecule)
    rows = molecule.object.pb_filament.subunits
    rows[f"0:{chains['beta']}"].select = True     # a beta picked earlier is let go
    for tubulin, other in (("alpha", "beta"), ("beta", "alpha")):
        assert bpy.ops.molecule.select_subunits(
            'EXEC_DEFAULT', molecule_id=molecule.identifier, action='CHAIN',
            chain=chains[tubulin]) == {'FINISHED'}
        chosen = _colors().selected_keys(molecule)
        assert len(chosen) == 2 * 13, (tubulin, len(chosen))
        assert {key.split(":")[1] for key in chosen} == {chains[tubulin]}
        assert not any(row.select for row in rows if row.chain == chains[other])


def test_a_ray_at_a_subunit_picks_that_subunit():
    """Aimed in from outside the filament at the fourth subunit from the pointed end."""
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule) * WORLD_SCALE
    axis = _path_axis(molecule)
    middle = ordered.mean(axis=0)
    for index in (0, 3, 9):
        target = ordered[index]
        radial = (target - middle) - ((target - middle) @ axis) * axis
        radial /= np.linalg.norm(radial)
        origin = target + radial * 5.0
        assert _colors().subunit_on_ray(molecule, origin, -radial) == f"{index}:A"
    # And one that misses the filament altogether.
    assert _colors().subunit_on_ray(molecule, middle + axis * 50.0, axis) is None


# --------------------------------------------------------------------------
# Hiding a subunit: the eye on its row
# Reported 2026-11-03 (Dillon's notes): "make it so you can hide individual
# actin or microtubules". Which copy went is judged against the copies'
# order up the filament from its pointed end, read off the structure.
# --------------------------------------------------------------------------

def _row(molecule, name):
    _colors().sync_roster(molecule)
    return molecule.object.pb_filament.subunits[name]


def _centres(drawn):
    return [centre for centre, _colour in drawn]


def test_hiding_the_fourth_actin_from_the_pointed_end_takes_only_it_away():
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    assert len(ordered) == 10

    _row(molecule, "3:A").hide = True
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (9, 0)
    assert not _near(ordered[3], _centres(instances)), "the fourth actin is still drawn"
    for index in set(range(10)) - {3}:
        assert _near(ordered[index], _centres(instances)), f"actin {index + 1} went too"

    _row(molecule, "3:A").hide = False
    instances, _painted = _drawn(molecule)
    assert len(instances) == 10 and _near(ordered[3], _centres(instances))


def test_a_hidden_subunit_is_not_drawn_even_when_painted():
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    _paint(molecule, ["3:A"])
    _row(molecule, "3:A").hide = True
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (9, 0)
    assert not _near(ordered[3], _centres(instances))

    # Shown again, it is still its own colour.
    _row(molecule, "3:A").hide = False
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (9, 1)
    assert _near(painted[0][0], [ordered[3]])
    assert np.allclose(painted[0][1], RED, atol=1e-3)


def test_a_hidden_subunit_stays_hidden_when_the_filament_grows():
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    _row(molecule, "5:A").hide = True

    _edit(molecule, count=20)

    instances, _painted = _drawn(molecule)
    assert len(instances) == 19
    assert not _near(ordered[5], _centres(instances))
    assert _near(ordered[4], _centres(instances)) and _near(ordered[6], _centres(instances))
    assert _row(molecule, "5:A").hide


def test_a_subunit_hidden_then_shrunk_away_is_still_hidden_when_it_comes_back():
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    _row(molecule, "1:A").hide = True
    _edit(molecule, shrink_minus=2)                 # takes 0:A and 1:A away
    instances, _painted = _drawn(molecule)
    assert len(instances) == 8
    assert not _near(ordered[0], _centres(instances))

    _edit(molecule, shrink_minus=0)

    instances, _painted = _drawn(molecule)
    assert len(instances) == 9, "the hidden subunit came back shown"
    assert _near(ordered[0], _centres(instances))
    assert not _near(ordered[1], _centres(instances))
    assert _row(molecule, "1:A").hide


def test_hiding_one_tubulin_leaves_its_partner():
    chains = F.tubulin_chains()
    molecule = _build("MICROTUBULE", 9.0)
    _row(molecule, f"5:{chains['beta']}").hide = True
    assert len(_drawn(molecule, chains["beta"])[0]) == 12
    assert len(_drawn(molecule, chains["alpha"])[0]) == 13


def test_a_ray_at_a_hidden_subunit_does_not_pick_it():
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule) * WORLD_SCALE
    axis = _path_axis(molecule)
    target = ordered[3]
    radial = (target - ordered.mean(axis=0))
    radial -= (radial @ axis) * axis
    radial /= np.linalg.norm(radial)
    _row(molecule, "3:A").hide = True
    assert _colors().subunit_on_ray(molecule, target + radial * 5.0, -radial) != "3:A"


def _drawn_anywhere(chain="A"):
    """``(centre, colour)`` of every copy of a chain drawn anywhere in the scene,
    as the evaluated scene draws it: one entry per object or instance that
    draws atoms of that chain (meshes, as a filament's Surface style draws)."""
    names = {d.object.name for m in H.sm().molecules.values()
             for d in m.domains.values() if d.object and str(d.chain_id) == chain}
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    found = []
    for entry in depsgraph.object_instances:
        owner = entry.parent if entry.is_instance and entry.parent is not None else entry.object
        data = entry.object.data
        if (owner.original.name not in names or not isinstance(data, bpy.types.Mesh)
                or not len(data.vertices) or "Color" not in data.attributes):
            continue
        count = len(data.vertices)
        position = np.zeros(count * 3)
        data.attributes["position"].data.foreach_get("vector", position)
        colour = np.zeros(count * 4)
        data.attributes["Color"].data.foreach_get("color", colour)
        matrix = np.array(entry.matrix_world)
        world = position.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        found.append((world.mean(axis=0) / WORLD_SCALE,
                      colour.reshape(-1, 4)[:, :3].mean(axis=0)))
    return found


@pytest.mark.parametrize("painted", [False, True])
def test_realizing_keeps_a_hidden_actin_hidden(painted):
    """Hide the fourth actin from the pointed end and realize: nine actins are
    drawn, none where the fourth stood, and none red."""
    molecule = _build("ACTIN", 27.5)
    ordered = _from_the_pointed_end(molecule)
    if painted:
        _paint(molecule, ["3:A"])
    _row(molecule, "3:A").hide = True

    made = F.realize(molecule)

    drawn = _drawn_anywhere()
    assert len(drawn) == 9, f"{len(drawn)} actins drawn after realizing"
    assert not _near(ordered[3], _centres(drawn), 1.0), "the hidden actin came back"
    for index in set(range(10)) - {3}:
        assert _near(ordered[index], _centres(drawn), 1.0), f"actin {index + 1} is missing"
    for _centre, colour in drawn:
        assert not np.allclose(colour, RED, atol=0.05), colour

    # Still made, as a protein of its own whose PB Outliner eye shows it again.
    assert len(made) == 9
    hidden = [mid for mid in [molecule.identifier, *made]
              if _object(H.sm().molecules[mid], "A").hide_get()]
    assert len(hidden) == 1, hidden
    assert bpy.ops.proteinblender.toggle_visibility(
        'EXEC_DEFAULT', item_id=hidden[0]) == {'FINISHED'}
    centre, colour = _drawn_protein(hidden[0])
    assert _near(centre, [ordered[3]], 1.0)
    assert np.allclose(colour, RED, atol=0.02) == painted, colour


def test_realizing_keeps_a_hidden_tubulin_hidden_and_its_partner_shown():
    chains = F.tubulin_chains()
    molecule = _build("MICROTUBULE", 9.0)
    _row(molecule, f"5:{chains['beta']}").hide = True
    assert (len(_drawn(molecule, chains["beta"])[0]),
            len(_drawn(molecule, chains["alpha"])[0])) == (12, 13)

    F.realize(molecule)

    assert len(_drawn_anywhere(chains["beta"])) == 12
    assert len(_drawn_anywhere(chains["alpha"])) == 13


def _chain_centres(obj):
    """World centre (Angstrom) of every copy Blender draws through ``obj``."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    centres = []
    for entry in depsgraph.object_instances:
        owner = entry.parent if entry.is_instance and entry.parent is not None else entry.object
        data = entry.object.data
        count = len(getattr(data, "points", ()) or getattr(data, "vertices", ()))
        if owner.original.name != obj.name or not count:
            continue
        position = np.zeros(count * 3)
        data.attributes["position"].data.foreach_get("vector", position)
        matrix = np.array(entry.matrix_world)
        world = position.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        centres.append(world.mean(axis=0) / WORLD_SCALE)
    return centres


def test_realizing_copies_of_one_chain_keeps_its_hidden_copies_hidden():
    """The other realize branch: copies of one chain, made beside it in the
    same protein. Hidden there are the original's own copy and one other; the
    copies to keep and to hide are told apart by where Blender drew them
    before and after hiding, not by their numbering."""
    from proteinblender.core import assembly, subunit_colors, symmetry_builder
    from proteinblender.operators.assembly_realize import realize_assembly

    molecule = H.sm().molecules[H.import_local("1atn.pdb", "atn")]
    chain_a = _object(molecule, "A")
    other = next(d.object for d in molecule.domains.values() if str(d.chain_id) != "A")
    assert assembly.apply_operators(
        molecule, symmetry_builder.build_operators("C", order=4), "generated:C",
        targets=[chain_a])
    every = _chain_centres(chain_a)
    assert len(every) == 4

    # The data the eye on a Subunits row writes; only a filament lists rows.
    assert subunit_colors.set_hidden(molecule, ["0:A", "2:A"], True) == 2
    shown = _chain_centres(chain_a)
    assert len(shown) == 2
    gone = [c for c in every if not _near(c, shown)]
    assert len(gone) == 2

    made = realize_assembly(bpy.context, molecule)
    assert made and len(made.domains) == 3 and not made.proteins

    copies = [d.object for d in molecule.domains.values()
              if str(d.chain_id) == "A" and d.object is not None]
    assert len(copies) == 4
    visible = [c for obj in copies if not obj.hide_get() for c in _chain_centres(obj)]
    assert len(visible) == 2
    assert all(_near(c, visible) for c in shown)
    hidden = [obj for obj in copies if obj.hide_get()]
    assert len(hidden) == 2 and chain_a.name in {obj.name for obj in hidden}, (
        "the original's own copy was hidden; it should still be")
    assert not other.hide_get() and _chain_centres(other)

    # Kept so that its PB Outliner eye shows it again where it stood.
    for obj in hidden:
        row = next(item for item in bpy.context.scene.outliner_items
                   if item.object_name == obj.name)
        assert bpy.ops.proteinblender.toggle_visibility(
            'EXEC_DEFAULT', item_id=row.item_id) == {'FINISHED'}
        assert not obj.hide_get()
        (centre,) = _chain_centres(obj)
        assert _near(centre, gone)


def test_a_build_from_before_hiding_can_still_hide():
    """A filament saved before the eye existed has no hide stage; hiding adds it."""
    from proteinblender.core import assembly
    molecule = _build("ACTIN", 27.5)
    for tree in bpy.data.node_groups:
        hide = [n for n in tree.nodes if n.name.startswith("PB Hide")]
        if not hide:
            continue
        for node in hide:
            tree.nodes.remove(node)
        copies = next(n for n in tree.nodes if n.name == "PB Instance Copies")
        realize = next(n for n in tree.nodes if n.name == assembly.TINT_NODE_NAME)
        tree.links.new(copies.outputs[0], realize.inputs["Geometry"])
    assert not any(n.name.startswith("PB Hide")
                   for t in bpy.data.node_groups for n in t.nodes)
    assert len(_drawn(molecule)[0]) == 10

    _row(molecule, "1:A").hide = True
    assert len(_drawn(molecule)[0]) == 9


# --------------------------------------------------------------------------
# Highlights: the list's pointed-at row and the viewport picker
# --------------------------------------------------------------------------

def _tint_rows(molecule):
    """``{site: rgba}`` of the copies a filament's point cloud tints, read off the mesh."""
    from proteinblender.core import assembly
    found = {}
    for _obj, points in assembly.point_clouds_of(molecule):
        mesh = points.data
        attribute = mesh.attributes.get(assembly.TINT_ATTRIBUTE)
        if attribute is None:
            continue
        count = len(mesh.vertices)
        tints = np.zeros(count * 4)
        attribute.data.foreach_get("color", tints)
        sites = np.zeros(count, dtype=np.int32)
        mesh.attributes["site"].data.foreach_get("value", sites)
        for site, tint in zip(sites, tints.reshape(-1, 4)):
            if tint[3] > 0:
                found[int(site)] = tuple(np.round(tint, 3))
    return found


def test_the_picker_is_drawn_over_the_lists_highlight():
    colors = _colors()
    molecule = _build("ACTIN", 27.5)
    colors.set_overlay(molecule, {"4:A": colors.HOVER_TINT}, colors.LIST_LAYER)
    colors.set_overlay(molecule, {"4:A": colors.SELECTED_TINT, "6:A": colors.SELECTED_TINT})
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (8, 2)
    assert colors.overlay(molecule)["4:A"] == colors.SELECTED_TINT

    # Finishing the picker leaves the list's highlight as it was.
    colors.set_overlay(molecule, {})
    _instances, painted = _drawn(molecule)
    assert len(painted) == 1
    assert np.allclose(painted[0][1], colors.HOVER_TINT[:3], atol=1e-3)
    colors.set_overlay(molecule, {}, colors.LIST_LAYER)
    assert len(_drawn(molecule)[1]) == 0


def test_a_highlight_is_never_saved(tmp_path):
    """Saved with a row pointed at, the file keeps the subunit's own colour."""
    colors = _colors()
    molecule = _build("ACTIN", 27.5)
    _paint(molecule, ["2:A"])
    colors.set_overlay(molecule, {"5:A": colors.HOVER_TINT}, colors.LIST_LAYER)
    assert set(_tint_rows(molecule)) == {2, 5}

    written = {}

    @bpy.app.handlers.persistent
    def look(*_args):
        written.update(_tint_rows(molecule))

    bpy.app.handlers.save_pre.append(look)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(tmp_path / "hover.blend"), copy=True)
    finally:
        bpy.app.handlers.save_pre.remove(look)

    assert set(written) == {2}, written
    assert np.allclose(written[2][:3], RED, atol=1e-3)
    # And once saved, the highlight is back on screen.
    assert set(_tint_rows(molecule)) == {2, 5}


def test_a_highlight_does_not_pass_to_a_new_filament_of_the_same_name():
    """Delete a filament while a subunit is lit, build another: nothing is lit."""
    colors = _colors()
    first = _build("ACTIN", 27.5)
    name = first.object.name
    colors.set_overlay(first, {"5:A": colors.HOVER_TINT}, colors.LIST_LAYER)
    assert bpy.ops.molecule.delete('EXEC_DEFAULT', molecule_id=first.identifier) == {'FINISHED'}

    second = _build("ACTIN", 27.5)
    assert second.object.name == name, "the test needs the new filament to reuse the name"
    instances, painted = _drawn(second)
    assert (len(instances), len(painted)) == (10, 0)
    assert colors.overlay(second) == {}


# --------------------------------------------------------------------------
# The Subunits panel follows the filament ticked in the PB Outliner
# --------------------------------------------------------------------------

def _tick(molecule_id):
    """Click a top-level row's checkbox in the PB Outliner, as a user does."""
    assert bpy.ops.proteinblender.outliner_select(
        'EXEC_DEFAULT', item_id=molecule_id) == {'FINISHED'}


def _ticked():
    return sorted(row.item_id for row in bpy.context.scene.outliner_items
                  if row.is_selected and row.item_type == 'PROTEIN')


def _untick_all():
    for molecule_id in _ticked():
        _tick(molecule_id)
    assert _ticked() == []


def _panel_shows():
    from proteinblender.panels.subunit_panel import PROTEINBLENDER_PT_subunits
    return PROTEINBLENDER_PT_subunits.poll(bpy.context)


def test_the_subunits_panel_shows_only_while_its_filament_is_ticked():
    molecule = _build("ACTIN", 27.5)
    _untick_all()
    assert not _panel_shows()

    _tick(molecule.identifier)
    assert _ticked() == [molecule.identifier]
    assert _panel_shows()

    _tick(molecule.identifier)
    assert _ticked() == []
    assert not _panel_shows()


def test_the_subunits_list_shows_the_ticked_filament():
    from proteinblender.operators.subunit_operators import filament_items, subunit_filament
    actin = _build("ACTIN", 27.5)
    tube = _build("MICROTUBULE", 17.0)
    _untick_all()

    for ticked in (actin, tube, actin):
        _untick_all()
        _tick(ticked.identifier)
        assert subunit_filament(bpy.context).identifier == ticked.identifier
        # Its picker offers only what is ticked.
        offered = [item[0] for item in filament_items(None, bpy.context)]
        assert offered == [ticked.identifier], offered

    # With both ticked the picker offers both, and the list shows the one picked.
    _tick(tube.identifier)
    assert _ticked() == sorted([actin.identifier, tube.identifier])
    bpy.context.scene.pb_subunit_filament = tube.identifier
    assert subunit_filament(bpy.context).identifier == tube.identifier
    bpy.context.scene.pb_subunit_filament = actin.identifier
    assert subunit_filament(bpy.context).identifier == actin.identifier


# --------------------------------------------------------------------------
# The colour and strength fields apply to the selected subunits as they change
# --------------------------------------------------------------------------

GREEN = (0.0, 1.0, 0.0)


def _ticked_actin():
    molecule = _build("ACTIN", 27.5)
    _untick_all()
    _tick(molecule.identifier)
    _colors().sync_roster(molecule)
    return molecule


def _select(molecule, names):
    for row in molecule.object.pb_filament.subunits:
        row.select = row.name in names


def test_changing_the_colour_paints_the_selected_subunits_at_once():
    molecule = _ticked_actin()
    _select(molecule, ["3:A", "6:A"])
    bpy.context.scene.pb_subunit_color = GREEN
    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (8, 2)
    for _centre, colour in painted:
        assert np.allclose(colour, GREEN, atol=1e-3), colour


def test_changing_the_colour_with_nothing_selected_paints_nothing():
    molecule = _ticked_actin()
    _select(molecule, [])
    bpy.context.scene.pb_subunit_color = GREEN
    assert len(_drawn(molecule)[1]) == 0
    assert len(molecule.object.pb_filament.colors) == 0
    assert np.allclose(bpy.context.scene.pb_subunit_color, GREEN)


def test_the_strength_slider_fades_the_selected_subunits():
    molecule = _ticked_actin()
    own = _drawn(molecule)[0][0][1]
    _select(molecule, ["2:A"])
    bpy.context.scene.pb_subunit_color = RED
    bpy.context.scene.pb_subunit_strength = 0.5
    _instances, painted = _drawn(molecule)
    assert len(painted) == 1
    assert np.allclose(painted[0][1], (own + np.array(RED)) / 2, atol=0.02)
    # Back to full strength, the subunit is its own colour again.
    bpy.context.scene.pb_subunit_strength = 1.0
    assert np.allclose(_drawn(molecule)[1][0][1], RED, atol=1e-3)


def test_the_colour_field_shows_the_first_selected_subunit():
    molecule = _ticked_actin()
    own = _drawn(molecule)[0][0][1]
    _select(molecule, ["5:A"])
    bpy.context.scene.pb_subunit_color = GREEN
    bpy.context.scene.pb_subunit_strength = 0.3

    _select(molecule, ["2:A"])                    # not painted: as the filament draws it
    assert np.allclose(bpy.context.scene.pb_subunit_color, own, atol=0.02)
    assert bpy.context.scene.pb_subunit_strength == pytest.approx(1.0)
    _select(molecule, ["5:A", "2:A"])             # the first in the list
    assert np.allclose(bpy.context.scene.pb_subunit_color, own, atol=0.02)
    _select(molecule, ["5:A"])
    assert np.allclose(bpy.context.scene.pb_subunit_color, GREEN, atol=1e-3)
    assert bpy.context.scene.pb_subunit_strength == pytest.approx(0.3)


def test_the_same_colour_again_paints_the_next_subunits():
    """Paint one red, select another, choose red again: both are red."""
    molecule = _ticked_actin()
    _select(molecule, ["2:A"])
    bpy.context.scene.pb_subunit_color = RED
    _select(molecule, ["7:A"])
    bpy.context.scene.pb_subunit_color = RED
    assert sorted(molecule.object.pb_filament.colors.keys()) == ["2:A", "7:A"]
    _instances, painted = _drawn(molecule)
    assert len(painted) == 2
    for _centre, colour in painted:
        assert np.allclose(colour, RED, atol=1e-3), colour


# --------------------------------------------------------------------------
# Each row's own colour, at its right-hand side
# Reported 2026-11-03 (Dillon's notes): "make it so the color is on the
# right-hand side where the actin filiment individual pieces are", and "make
# sure color of individual actin (etc.) are keyframable".
# --------------------------------------------------------------------------

def test_every_rows_swatch_shows_the_colour_its_subunit_is_drawn():
    molecule = _ticked_actin()
    own = _drawn(molecule)[0][0][1]
    assert np.allclose(_row(molecule, "2:A").color, own, atol=0.02)
    _select(molecule, ["5:A"])
    bpy.context.scene.pb_subunit_color = GREEN
    assert np.allclose(_row(molecule, "5:A").color, GREEN, atol=1e-3)
    assert np.allclose(_row(molecule, "2:A").color, own, atol=0.02)


def test_a_rows_swatch_paints_only_its_own_subunit():
    molecule = _ticked_actin()
    ordered = _from_the_pointed_end(molecule)
    _select(molecule, ["6:A"])

    _row(molecule, "3:A").color = GREEN

    instances, painted = _drawn(molecule)
    assert (len(instances), len(painted)) == (9, 1)
    assert _near(painted[0][0], [ordered[3]])
    assert np.allclose(painted[0][1], GREEN, atol=1e-3)
    # The selection is the selection's business; the swatch did not touch it.
    assert _colors().selected_keys(molecule) == ["6:A"]
    assert list(molecule.object.pb_filament.colors.keys()) == ["3:A"]


def test_a_rows_swatch_hands_over_to_the_colour_it_made():
    """Unpainted, a row's swatch is a view through the disposable roster row,
    which cannot be keyed. Painted, the list draws the subunit's colour entry
    instead - the one Create Keyframe keys, and I over the swatch keys."""
    molecule = _ticked_actin()
    row = _row(molecule, "3:A")
    assert not row.bl_rna.properties["color"].is_animatable
    assert not row.bl_rna.properties["hide"].is_animatable

    row.color = GREEN
    entry = molecule.object.pb_filament.colors["3:A"]
    assert entry.bl_rna.properties["color"].is_animatable
    # Keyed where I over the swatch keys it: the entry's own path.
    index = list(molecule.object.pb_filament.colors.keys()).index("3:A")
    assert molecule.object.keyframe_insert(
        data_path=f"pb_filament.colors[{index}].color", frame=1)
    entry.color = RED
    bpy.context.scene.frame_set(1)
    assert np.allclose(_drawn(molecule)[1][0][1], GREEN, atol=1e-3)
    # The row shows the same colour the entry holds, whichever is drawn.
    assert np.allclose(row.color, entry.color, atol=1e-6)


def test_a_colour_set_on_its_row_can_be_keyed():
    scene = bpy.context.scene
    molecule = _ticked_actin()
    scene.frame_set(1)
    _row(molecule, "3:A").color = RED
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(21)
    _row(molecule, "3:A").color = (0.0, 0.0, 1.0)
    assert _key(molecule, 21) == {'FINISHED'}

    scene.frame_set(1)
    assert np.allclose(_drawn(molecule)[1][0][1], RED, atol=1e-3)
    scene.frame_set(11)
    middle = _drawn(molecule)[1][0][1]
    assert 0.2 < middle[0] < 0.8 and 0.2 < middle[2] < 0.8, middle
    scene.frame_set(21)
    assert np.allclose(_drawn(molecule)[1][0][1], (0, 0, 1), atol=1e-3)
