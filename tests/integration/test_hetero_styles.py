"""Ligands, ions and water can be restyled, recolored, resized and keyframed.

The Ligands / Ions / Water rows under a protein (core/hetero_groups.py) get
the same pencil as a chain or a domain: representation, color and size. Their
visibility, color and size can be keyed from Create Keyframe, so a drug can
fade in, change color or swell while the protein stays put.

Ground truth is read from what Blender draws - the evaluated geometry's
positions, atomic numbers and colors - and from the mmCIF text, never from
the add-on's own node values.
"""

import gzip

import numpy as np
import pytest
import bpy

import helpers as H

FIXTURE = "4bv3.cif.gz"
LIGAND_NAMES = {"NAD", "APR", "OCZ", "GOL"}
CARBON = 6

GREEN = (0.0, 1.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)


def _ligand_res_ids():
    """auth_seq_id of every ligand residue in author chain A, from the file."""
    found = set()
    with gzip.open(H.data_path(FIXTURE), "rt") as handle:
        for line in handle:
            if not line.startswith("HETATM"):
                continue
            fields = line.split()
            if fields[5] in LIGAND_NAMES and fields[18] == "A":
                found.add(int(fields[16]))
    return found


def _drawn(obj):
    """Per drawn vertex of *obj*: res_id, atomic_number, RGBA, position.

    Ball and Stick stores its color per face corner, Spheres per point, so a
    corner color is folded back onto the vertex it belongs to. Empty arrays
    when Blender draws nothing for the object.
    """
    bpy.context.view_layer.update()
    for instance in bpy.context.evaluated_depsgraph_get().object_instances:
        owner = (instance.parent.original if instance.is_instance
                 else instance.object.original)
        if owner.name != obj.name or instance.object.type not in ("MESH", "POINTCLOUD"):
            continue
        mesh = instance.object.data
        n = (len(mesh.vertices) if instance.object.type == "MESH"
             else len(mesh.points))
        if not n:
            continue   # an empty mesh beside the point cloud that draws
        res_id = np.zeros(n, dtype=np.int32)
        mesh.attributes["res_id"].data.foreach_get("value", res_id)
        atomic = np.zeros(n, dtype=np.int32)
        mesh.attributes["atomic_number"].data.foreach_get("value", atomic)
        position = np.zeros(n * 3, dtype=np.float32)
        mesh.attributes["position"].data.foreach_get("vector", position)
        color_attr = mesh.attributes["Color"]
        values = np.zeros(len(color_attr.data) * 4, dtype=np.float32)
        color_attr.data.foreach_get("color", values)
        values = values.reshape(-1, 4)
        if color_attr.domain == "CORNER":
            corner_vert = np.zeros(len(mesh.loops), dtype=np.int32)
            mesh.loops.foreach_get("vertex_index", corner_vert)
            color = np.zeros((n, 4), dtype=np.float32)
            color[corner_vert] = values
        else:
            color = values
        return res_id, atomic, color, position.reshape(-1, 3)
    return (np.zeros(0, np.int32), np.zeros(0, np.int32),
            np.zeros((0, 4), np.float32), np.zeros((0, 3), np.float32))


def _single_atom_res_ids():
    """Chain A residues the file gives exactly one atom (Zn, Na, Cl)."""
    atoms = {}
    with gzip.open(H.data_path(FIXTURE), "rt") as handle:
        for line in handle:
            if line.startswith("HETATM"):
                fields = line.split()
                if fields[18] == "A" and fields[5] != "HOH":
                    key = int(fields[16])
                    atoms[key] = atoms.get(key, 0) + 1
    return {res for res, count in atoms.items() if count == 1}


def _ion_extent(obj):
    """Mean width (x extent) of the drawn sphere of each single-atom ion.

    Nitrate is left out: its width is its three oxygens' spread plus their
    spheres, which does not scale with sphere size.
    """
    res_id, _atomic, _color, position = _drawn(obj)
    singles = _single_atom_res_ids()
    widths = [np.ptp(position[res_id == r, 0]) for r in np.unique(res_id)
              if int(r) in singles]
    assert widths
    return float(np.mean(widths))


@pytest.fixture
def sirt3(scene):
    mid = H.import_local(FIXTURE, "4bv3")
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    return mid


def _row(scene, mid, label):
    return next(it for it in scene.outliner_items
                if it.item_type == "HETERO" and it.parent_id == mid
                and it.name.startswith(label))


def _edit(row, **fields):
    return bpy.ops.proteinblender.edit_hetero_group(
        'EXEC_DEFAULT', item_id=row.item_id, **fields)


def _key(row, frame, **channels):
    """Tick the group's row in Create Keyframe, with the chosen channels."""
    settings = dict(visibility=False, color=False, size=False)
    settings.update(channels)
    return bpy.ops.proteinblender.create_keyframe(
        'EXEC_DEFAULT', frame_number=frame,
        hetero_items=[{
            "item_id": row.item_id,
            "name": row.name,
            "object_name": row.object_name,
            "use_group": True,
            "keyframe_visibility": settings["visibility"],
            "keyframe_color": settings["color"],
            "keyframe_size": settings["size"],
        }])


# ---------------------------------------------------------------------------
# The pencil: style, color, size
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_ligands_can_be_drawn_as_sticks(scene, sirt3):
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    before = len(_drawn(ligands)[0])

    assert _edit(row, vs_style='sticks') == {'FINISHED'}

    res_id = _drawn(ligands)[0]
    # Still the ligands and only the ligands: the swap kept the selection.
    assert set(res_id.tolist()) == _ligand_res_ids()
    # And it is a different drawing: sticks have no atom spheres.
    assert len(res_id) != before


@pytest.mark.integration
def test_styles_offered_suit_each_group(scene, sirt3):
    from proteinblender.operators import hetero_edit
    ligand_styles = hetero_edit.styles_for(_row(scene, sirt3, "Ligands"))
    ion_styles = hetero_edit.styles_for(_row(scene, sirt3, "Ions"))
    # Cartoon and Ribbon follow a backbone a ligand does not have; an ion has
    # no bonds for sticks to draw.
    assert set(ligand_styles) == {'ball_and_stick', 'sticks', 'spheres', 'surface'}
    assert ion_styles == ['spheres']


@pytest.mark.integration
def test_color_by_element_recolors_only_the_carbons(scene, sirt3):
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    assert _edit(row, vs_color=GREEN, vs_by_element=True) == {'FINISHED'}

    _res, atomic, color, _pos = _drawn(ligands)
    carbons = atomic == CARBON
    assert carbons.any() and (~carbons).any()
    assert np.allclose(color[carbons, :3], GREEN[:3], atol=1e-3)
    # N, O, P keep their element colors.
    assert not np.allclose(color[~carbons, :3], GREEN[:3], atol=1e-3)


@pytest.mark.integration
def test_solid_color_paints_every_atom(scene, sirt3):
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    assert _edit(row, vs_color=GREEN, vs_by_element=False) == {'FINISHED'}
    _res, _atomic, color, _pos = _drawn(ligands)
    assert len(color) and np.allclose(color[:, :3], GREEN[:3], atol=1e-3)


@pytest.mark.integration
def test_size_scales_the_ion_spheres(scene, sirt3):
    row = _row(scene, sirt3, "Ions")
    ions = bpy.data.objects[row.object_name]
    base = _ion_extent(ions)
    assert _edit(row, vs_size=2.0) == {'FINISHED'}
    assert _ion_extent(ions) == pytest.approx(2.0 * base, rel=0.02)


@pytest.mark.integration
def test_size_survives_a_style_change(scene, sirt3):
    """A size set on ball and stick still applies after switching to spheres."""
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    assert _edit(row, vs_style='spheres') == {'FINISHED'}
    one = np.ptp(_drawn(ligands)[3], axis=0)
    assert _edit(row, vs_size=1.5) == {'FINISHED'}
    assert _edit(row, vs_style='sticks') == {'FINISHED'}
    assert _edit(row, vs_style='spheres') == {'FINISHED'}
    # Overall extent grows by the sphere growth on each side; it must grow.
    assert (np.ptp(_drawn(ligands)[3], axis=0) > one + 1e-4).all()


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_visibility_can_be_keyframed(scene, sirt3):
    from proteinblender.panels.protein_outliner_panel import PROTEINBLENDER_UL_outliner as UL
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    item_id = row.item_id

    scene.frame_set(1)
    assert bpy.ops.proteinblender.toggle_visibility(item_id=item_id) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ligands"), 1, visibility=True) == {'FINISHED'}

    scene.frame_set(20)
    assert bpy.ops.proteinblender.toggle_visibility(item_id=item_id) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ligands"), 20, visibility=True) == {'FINISHED'}

    for frame, shown in ((1, False), (10, False), (20, True), (30, True)):
        scene.frame_set(frame)
        drawn = len(_drawn(ligands)[0]) > 0
        assert drawn == shown, frame
        assert ligands.hide_render == (not shown), frame
        assert UL._get_item_visibility(bpy.context, _row(scene, sirt3, "Ligands")) == shown

    # Scrubbing back keeps working after the playhead visited the hidden key.
    scene.frame_set(20)
    assert len(_drawn(ligands)[0]) > 0


@pytest.mark.integration
def test_color_can_be_keyframed(scene, sirt3):
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]

    scene.frame_set(1)
    assert _edit(row, vs_color=GREEN, vs_by_element=True) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ligands"), 1, color=True) == {'FINISHED'}
    scene.frame_set(21)
    assert _edit(_row(scene, sirt3, "Ligands"), vs_color=BLUE) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ligands"), 21, color=True) == {'FINISHED'}

    def carbon_color(frame):
        scene.frame_set(frame)
        _res, atomic, color, _pos = _drawn(ligands)
        return color[atomic == CARBON, :3].mean(axis=0)

    assert np.allclose(carbon_color(1), GREEN[:3], atol=1e-3)
    assert np.allclose(carbon_color(21), BLUE[:3], atol=1e-3)
    # Halfway between two eased keys is the halfway color.
    assert np.allclose(carbon_color(11), (0.0, 0.5, 0.5), atol=0.02)


@pytest.mark.integration
def test_size_can_be_keyframed(scene, sirt3):
    row = _row(scene, sirt3, "Ions")
    ions = bpy.data.objects[row.object_name]
    base = _ion_extent(ions)

    scene.frame_set(1)
    assert _key(row, 1, size=True) == {'FINISHED'}
    scene.frame_set(21)
    assert _edit(_row(scene, sirt3, "Ions"), vs_size=2.0) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ions"), 21, size=True) == {'FINISHED'}

    scene.frame_set(1)
    assert _ion_extent(ions) == pytest.approx(base, rel=0.02)
    scene.frame_set(11)
    assert _ion_extent(ions) == pytest.approx(1.5 * base, rel=0.02)
    scene.frame_set(21)
    assert _ion_extent(ions) == pytest.approx(2.0 * base, rel=0.02)


@pytest.mark.integration
def test_keyframes_show_in_the_list_and_can_be_deleted(scene, sirt3):
    from proteinblender.operators.keyframe_operators import get_keyframe_frames
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]

    scene.frame_set(1)
    assert _edit(row, vs_color=GREEN, vs_by_element=True) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ligands"), 1, color=True) == {'FINISHED'}
    scene.frame_set(21)
    assert _edit(_row(scene, sirt3, "Ligands"), vs_color=BLUE) == {'FINISHED'}
    assert _key(_row(scene, sirt3, "Ligands"), 21, color=True, visibility=True,
                size=True) == {'FINISHED'}

    frames = get_keyframe_frames(bpy.context)
    assert 1 in frames and 21 in frames

    assert bpy.ops.proteinblender.delete_keyframe(frame=21) == {'FINISHED'}
    assert 21 not in get_keyframe_frames(bpy.context)
    # Only the frame-1 key is left, so frame 11 holds its color.
    scene.frame_set(11)
    _res, atomic, color, _pos = _drawn(ligands)
    assert np.allclose(color[atomic == CARBON, :3].mean(axis=0), GREEN[:3], atol=1e-3)


# ---------------------------------------------------------------------------
# The outliner color swatch
# ---------------------------------------------------------------------------

def _carbon_color(obj):
    _res, atomic, color, _pos = _drawn(obj)
    assert (atomic == CARBON).any(), f"{obj.name} draws no carbons"
    return color[atomic == CARBON, :3].mean(axis=0)


@pytest.mark.integration
def test_group_rows_have_a_swatch_showing_their_drawn_color(scene, sirt3):
    from proteinblender.core.outliner_colors import row_has_swatch
    for label in ("Ligands", "Ions"):
        row = _row(scene, sirt3, label)
        assert row_has_swatch(row), label
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    assert np.allclose(tuple(row.row_color)[:3], _carbon_color(ligands), atol=2e-3)


@pytest.mark.integration
def test_picking_the_swatch_recolors_the_group(scene, sirt3):
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    _res, atomic, before, _pos = _drawn(ligands)

    row.row_color = BLUE

    _res, atomic, after, _pos = _drawn(ligands)
    carbons = atomic == CARBON
    assert np.allclose(after[carbons, :3], BLUE[:3], atol=1e-3)
    # Still by element: whatever was drawn in the old carbon color (the carbon
    # atoms and their half of each bond) turns blue, and nothing else changes,
    # so nitrogen, oxygen and phosphorus keep their colors.
    old_carbon = before[carbons, :3].mean(axis=0)
    was_carbon = np.isclose(before[:, :3], old_carbon, atol=1e-3).all(axis=1)
    assert np.allclose(after[was_carbon, :3], BLUE[:3], atol=1e-3)
    assert (~was_carbon).any()
    assert np.allclose(after[~was_carbon], before[~was_carbon], atol=1e-4)
    # The protein is not repainted with it.
    domain = next(iter(H.sm().molecules[sirt3].domains.values())).object
    assert not np.allclose(_carbon_color(domain), BLUE[:3], atol=1e-3)


@pytest.mark.integration
def test_swatch_follows_a_pencil_edit(scene, sirt3):
    row = _row(scene, sirt3, "Ions")
    assert _edit(row, vs_color=GREEN, vs_by_element=False) == {'FINISHED'}
    assert np.allclose(tuple(_row(scene, sirt3, "Ions").row_color), GREEN, atol=1e-3)


@pytest.mark.integration
def test_protein_swatch_leaves_the_ligands_their_color(scene, sirt3):
    row = _row(scene, sirt3, "Ligands")
    ligands = bpy.data.objects[row.object_name]
    before = _carbon_color(ligands)
    protein = next(it for it in scene.outliner_items if it.item_id == sirt3)
    protein.row_color = BLUE
    assert np.allclose(_carbon_color(ligands), before, atol=1e-4)
