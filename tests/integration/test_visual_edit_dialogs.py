"""The per-item Visual Set-up dialogs, and the pivot controls they expose.

Colour, representation, membrane force field and pivot used to live in one
selection-driven panel. They are now edited on the item itself, from the pencil
button on its outliner row:

    protein  ->  proteinblender.edit_protein_visuals
    domain   ->  proteinblender.rename_domain
    chain    ->  proteinblender.edit_chain_domains  (covered in
                 test_domain_splitter.py, which already drives that dialog)

Headless Blender routes INVOKE_DEFAULT straight to ``execute()``, so these
tests drive the dialogs the way a script would - by passing the fields as
operator properties - which is the same code path OK runs.

Ground truth is deliberately *not* the add-on's own readers. Colour is checked
by reading the geometry-nodes Combine Color node's channels, style by reading
the Style group node's tree name, and the pivot residues come from parsing the
PDB fixture with biotite. ``get_object_color`` / ``get_object_style`` are the
functions the dialog writes through, so asserting on them would pass whether
the write was right or wrong.
"""

import numpy as np
import pytest
import bpy

import helpers as H


# --------------------------------------------------------------------------
# Independent readers: raw geometry-nodes state, no add-on helpers
# --------------------------------------------------------------------------

def _combine_color_rgb(obj):
    """The RGB the object's node tree actually paints with, or None.

    Read off the "Custom Combine Color" node's three channel sockets - the
    node the colour writer creates - rather than through
    ``visual_style.get_object_color``.
    """
    for modifier in obj.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group:
            continue
        node = modifier.node_group.nodes.get("Custom Combine Color")
        if node is not None:
            return tuple(round(node.inputs[c].default_value, 4)
                         for c in ("Red", "Green", "Blue"))
    return None


def _style_node_tree_name(obj):
    """The name of the MolecularNodes Style group the object is wearing."""
    for modifier in obj.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group:
            continue
        for node in modifier.node_group.nodes:
            if (node.type == 'GROUP' and node.node_tree
                    and 'Style' in node.node_tree.name):
                return node.node_tree.name
    return None


def _protein_objects(molecule):
    """The molecule mesh plus every domain object hanging off it."""
    objects = {}
    if molecule.object is not None:
        objects[molecule.object.name] = molecule.object
    for domain in molecule.domains.values():
        if domain.object is not None:
            objects[domain.object.name] = domain.object
    return list(objects.values())


def _origin(obj):
    bpy.context.view_layer.update()
    return obj.matrix_world.translation.copy()


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


# --------------------------------------------------------------------------
# Colour and style reach every object the item owns
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_protein_dialog_colors_the_molecule_and_every_domain(scene, sm,
                                                             multi_chain):
    _build_outliner()
    molecule = sm.molecules[multi_chain]
    objects = _protein_objects(molecule)
    assert len(objects) > 1, "fixture must have a molecule object and domains"

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=multi_chain, vs_color=(0.25, 0.5, 0.75, 1.0)) == {'FINISHED'}

    for obj in objects:
        assert _combine_color_rgb(obj) == (0.25, 0.5, 0.75), (
            f"{obj.name} was not repainted by the protein dialog")


@pytest.mark.integration
def test_protein_dialog_style_reaches_every_domain(scene, sm, multi_chain):
    _build_outliner()
    molecule = sm.molecules[multi_chain]
    objects = _protein_objects(molecule)

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=multi_chain, vs_style='cartoon') == {'FINISHED'}

    for obj in objects:
        name = _style_node_tree_name(obj)
        assert name is not None and 'Style Cartoon' in name, (
            f"{obj.name} is wearing {name!r}, not the cartoon style")

    # The model has to agree, or the next domain built on this chain inherits
    # the style the protein no longer has.
    assert molecule.style == 'cartoon'
    for domain in molecule.domains.values():
        assert domain.style == 'cartoon'


@pytest.mark.integration
def test_dialog_leaves_fields_the_caller_did_not_set_alone(scene, sm,
                                                           single_chain):
    """Setting only the style must not repaint the colour.

    Every field on the dialog has a default, and applying them all
    unconditionally would paint the default purple over an object whose colour
    the caller never mentioned - silently, since a colour write cannot fail.
    """
    _build_outliner()
    molecule = sm.molecules[single_chain]

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, vs_color=(0.9, 0.1, 0.1, 1.0)) == {'FINISHED'}
    painted = [_combine_color_rgb(obj) for obj in _protein_objects(molecule)]
    assert painted and all(rgb == (0.9, 0.1, 0.1) for rgb in painted)

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, vs_style='ribbon') == {'FINISHED'}

    for obj in _protein_objects(molecule):
        assert _combine_color_rgb(obj) == (0.9, 0.1, 0.1), (
            f"{obj.name} was recoloured by a call that only set the style")


@pytest.mark.integration
def test_domain_dialog_renames_and_recolors_in_one_pass(scene, sm,
                                                        multi_chain):
    """The domain dialog is rename *plus* the Visual Set-up block."""
    _build_outliner()
    molecule = sm.molecules[multi_chain]
    domain_id, domain = next(iter(molecule.domains.items()))

    assert bpy.ops.proteinblender.rename_domain(
        target_item_id=domain_id, item_type='DOMAIN',
        new_name="Recoloured", vs_color=(0.1, 0.8, 0.2, 1.0)) == {'FINISHED'}

    assert molecule.domains[domain_id].name == "Recoloured"
    assert _combine_color_rgb(domain.object) == (0.1, 0.8, 0.2)


# --------------------------------------------------------------------------
# Pivot: a protein gets ONE pivot, shared by every object it owns
# --------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("operator_id", [
    "set_pivot_first", "set_pivot_center", "set_pivot_last",
])
def test_protein_pivot_moves_only_the_molecule_object(scene, sm, multi_chain,
                                                      operator_id):
    """A protein's pivot is the molecule object's origin, and nothing else.

    Every chain domain is *parented* to the molecule object, so the protein
    already rotates as one about that origin - that is what the protein's
    pivot is. Writing the same pivot onto each domain as well would silently
    overwrite the pivot the user set on that domain from its own row, so the
    presets must leave every domain exactly as they found it.
    """
    from mathutils import Vector
    from proteinblender.core import domain_space
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    molecule = sm.molecules[multi_chain]
    parent = molecule.object
    domains = [d.object for d in molecule.domains.values() if d.object]
    assert parent is not None and len(domains) > 1

    # Displace the protein's pivot first, so every preset has somewhere to
    # move it back *from*. Import already parks it on the centre of mass, so
    # without this the Center case would assert nothing at all.
    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=multi_chain) == {"FINISHED"}
    helper = bpy.data.objects[P.PIVOT_HELPER]
    helper.location = helper.location + Vector((6.0, 6.0, 6.0))
    bpy.context.view_layer.update()
    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=multi_chain) == {"FINISHED"}

    before_origin = _origin(parent)
    domains_before = [(obj, _origin(obj), domain_space.get_pivot(obj).copy())
                      for obj in domains]

    assert getattr(bpy.ops.proteinblender, operator_id)(
        item_id=multi_chain) == {"FINISHED"}

    assert (_origin(parent) - before_origin).length > 1e-4, (
        "the protein's own origin did not move")
    for obj, origin, pivot in domains_before:
        assert (_origin(obj) - origin).length < 1e-6, (
            f"{obj.name} was dragged when only the protein's pivot was set")
        assert (domain_space.get_pivot(obj) - pivot).length < 1e-6, (
            f"{obj.name}'s own pivot was overwritten by the protein's")


@pytest.mark.integration
def test_protein_pivot_lands_on_the_real_termini(scene, sm, single_chain):
    """First / Center / End land on the protein's N-terminus, centroid and
    C-terminus.

    Ground truth is 1ubq re-parsed with biotite, compared through pairwise
    distances (invariant under the unknown scale + recentring between PDB
    Angstrom space and Blender world space). A single-chain protein is used so
    "the protein's first residue" is unambiguous.
    """
    _build_outliner()
    molecule = sm.molecules[single_chain]
    probe = _protein_objects(molecule)[0]

    def run(operator_id):
        assert getattr(bpy.ops.proteinblender, operator_id)(
            item_id=single_chain) == {"FINISHED"}
        return _origin(probe)

    first = run("set_pivot_first")
    center = run("set_pivot_center")
    last = run("set_pivot_last")

    letter = list(probe.get("chain_ids") or ["A"])[0]
    cas = H.pdb_amino_acid_cas("1ubq.pdb", letter)
    residues = sorted(cas)
    H.assert_world_points_match_residues(
        {"first": first, "center": center, "last": last},
        {
            "first": cas[residues[0]],
            "center": tuple(np.mean([cas[r] for r in residues], axis=0)),
            "last": cas[residues[-1]],
        },
    )


@pytest.mark.integration
def test_pivot_item_id_does_not_disturb_the_rest_of_the_scene(scene, sm,
                                                              multi_chain):
    """Addressing one chain by item_id must leave its siblings alone.

    The selection route acts on every selected row, and toggling a protein row
    selects all of its children - so an item_id that quietly fell back to the
    selection would move pivots the caller never named.
    """
    _build_outliner()
    for row in scene.outliner_items:
        row.is_selected = True

    chain_rows = [row for row in scene.outliner_items
                  if row.item_type == 'CHAIN' and row.object_name]
    assert len(chain_rows) > 1, "fixture must have several chains"

    target, *others = chain_rows
    other_objects = [bpy.data.objects.get(row.object_name) for row in others]
    before = [_origin(obj) for obj in other_objects]

    assert bpy.ops.proteinblender.set_pivot_first(
        item_id=target.item_id) == {"FINISHED"}

    for obj, origin in zip(other_objects, before):
        assert (_origin(obj) - origin).length < 1e-6, (
            f"{obj.name} moved, but only {target.item_id} was addressed")


# --------------------------------------------------------------------------
# The Custom Pivot toggle
# --------------------------------------------------------------------------

def _first_domain_row(scene):
    row = next((r for r in scene.outliner_items
                if r.item_type == 'DOMAIN' and r.object_name), None)
    if row is None:
        row = next((r for r in scene.outliner_items
                    if r.item_type == 'CHAIN' and r.object_name), None)
    assert row is not None, "no chain or domain row with a backing object"
    return row, bpy.data.objects.get(row.object_name)


@pytest.mark.integration
def test_edit_pivot_opens_a_session_with_a_helper_on_the_current_pivot(
        scene, sm, multi_chain):
    """First click drops the helper exactly where the pivot is now.

    Opening the mode and closing it again without dragging must therefore be
    a no-op - a user who clicks the button to see what it does has not
    silently moved anything.
    """
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    row, obj = _first_domain_row(scene)
    before = _origin(obj)

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=row.item_id) == {"FINISHED"}

    assert P.pivot_edit_key(scene) == row.item_id
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    assert helper is not None, "no pivot helper was created"
    assert (helper.matrix_world.translation - before).length < 1e-4, (
        "the helper did not start on the item's current pivot")

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=row.item_id) == {"FINISHED"}
    assert P.pivot_edit_key(scene) == ""
    assert bpy.data.objects.get(P.PIVOT_HELPER) is None
    assert (_origin(obj) - before).length < 1e-4, (
        "opening and closing Edit Pivot without dragging moved the pivot")


@pytest.mark.integration
def test_edit_pivot_second_click_applies_where_the_helper_was_left(
        scene, sm, multi_chain):
    """Move the helper, click again: that position becomes the pivot.

    Ground truth is the helper's own world position, captured before the
    second click, and the atoms are checked separately so "the pivot moved"
    cannot be confused with "the molecule moved".
    """
    from mathutils import Vector
    from proteinblender.core import domain_space
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    row, obj = _first_domain_row(scene)

    probe_co = Vector(obj.data.vertices[0].co)
    atom_before = domain_space.local_to_world(obj, probe_co)

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=row.item_id) == {"FINISHED"}
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    helper.location = helper.location + Vector((2.0, -1.0, 0.5))
    bpy.context.view_layer.update()
    dropped_at = helper.matrix_world.translation.copy()

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=row.item_id) == {"FINISHED"}

    assert (_origin(obj) - dropped_at).length < 1e-4, (
        "the pivot did not land where the helper was left")
    assert (domain_space.local_to_world(obj, probe_co)
            - atom_before).length < 1e-4, (
        "applying the pivot moved the atoms")


@pytest.mark.integration
def test_edit_pivot_on_a_protein_moves_only_the_molecule_object(scene, sm,
                                                                multi_chain):
    """Edit Pivot on a protein rehomes the molecule object and nothing else.

    Same contract as the presets above: the domains are children of the
    molecule object and keep both their positions and their own pivots.
    """
    from mathutils import Vector
    from proteinblender.core import domain_space
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    molecule = sm.molecules[multi_chain]
    parent = molecule.object
    domains = [d.object for d in molecule.domains.values() if d.object]
    domains_before = [(obj, _origin(obj), domain_space.get_pivot(obj).copy())
                      for obj in domains]

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=multi_chain) == {"FINISHED"}
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    helper.location = helper.location + Vector((1.0, 1.0, -1.0))
    bpy.context.view_layer.update()
    dropped_at = helper.matrix_world.translation.copy()

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=multi_chain) == {"FINISHED"}

    assert (_origin(parent) - dropped_at).length < 1e-4, (
        "the protein's origin did not land where the helper was left")
    for obj, origin, pivot in domains_before:
        assert (_origin(obj) - origin).length < 1e-6, (
            f"{obj.name} was dragged by the protein's pivot change")
        assert (domain_space.get_pivot(obj) - pivot).length < 1e-6, (
            f"{obj.name}'s own pivot was overwritten")


@pytest.mark.integration
def test_a_preset_pivot_abandons_an_open_edit_pivot_session(scene, sm,
                                                            multi_chain):
    """Choosing Start / Center / End supersedes a placement in progress.

    Left open, the helper would still be sitting there ready to overwrite the
    preset the next time Edit Pivot was clicked.
    """
    from mathutils import Vector
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    row, obj = _first_domain_row(scene)

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=row.item_id) == {"FINISHED"}
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    helper.location = helper.location + Vector((5.0, 5.0, 5.0))
    # matrix_world only catches up on the next depsgraph evaluation; reading it
    # straight after the write hands back the position from before the move.
    bpy.context.view_layer.update()
    stranded = helper.matrix_world.translation.copy()

    assert bpy.ops.proteinblender.set_pivot_center(
        item_id=row.item_id) == {"FINISHED"}

    assert P.pivot_edit_key(scene) == "", "the preset left the session open"
    assert bpy.data.objects.get(P.PIVOT_HELPER) is None, (
        "the preset left the helper in the scene")
    assert (_origin(obj) - stranded).length > 1e-3, (
        "the abandoned helper position was applied anyway")


@pytest.mark.integration
def test_edit_pivot_on_a_second_row_commits_the_first(scene, sm, multi_chain):
    """Two helpers must never be on screen at once.

    Clicking another row's Edit Pivot commits the open session rather than
    discarding it: the user placed that pivot, and silently throwing it away
    would be worse than applying it.
    """
    from mathutils import Vector
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    chains = [r for r in scene.outliner_items
              if r.item_type == 'CHAIN' and r.object_name]
    assert len(chains) > 1
    first, second = chains[0], chains[1]
    first_obj = bpy.data.objects.get(first.object_name)

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=first.item_id) == {"FINISHED"}
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    helper.location = helper.location + Vector((3.0, 0.0, 0.0))
    bpy.context.view_layer.update()
    dropped_at = helper.matrix_world.translation.copy()

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=second.item_id) == {"FINISHED"}

    assert P.pivot_edit_key(scene) == second.item_id, (
        "the session did not move to the row that was clicked")
    assert (_origin(first_obj) - dropped_at).length < 1e-4, (
        "the first row's placement was discarded instead of committed")
    assert len([o for o in bpy.data.objects
                if o.name.startswith(P.PIVOT_HELPER)]) == 1, (
        "two pivot helpers exist at once")

    bpy.ops.proteinblender.set_pivot_custom(item_id=second.item_id)


@pytest.mark.integration
def test_a_deleted_helper_ends_the_session(scene, sm, multi_chain):
    """Deleting the helper by hand must not strand the button lit forever."""
    from proteinblender.operators import pivot_operators as P

    _build_outliner()
    row, _obj = _first_domain_row(scene)

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=row.item_id) == {"FINISHED"}
    bpy.data.objects.remove(bpy.data.objects[P.PIVOT_HELPER], do_unlink=True)

    assert P.pivot_edit_key(scene) == "", (
        "the session outlived its helper, so the row's button would stay lit "
        "with no way to finish")


@pytest.mark.integration
def test_edit_pivot_on_a_protein_moves_the_pivot_not_the_protein(scene, sm,
                                                                 tmp_path):
    """Reported: Edit Pivot on a protein translated the whole molecule.

    Import 1atn, open Edit Pivot on the protein row, drag the helper along X,
    click again. The pivot must end up where the helper was left and the
    molecule must not have moved a pixel.

    Measured with Blender's *renderer*, not the add-on's coordinate maths:
    setting a pivot rewrites ``matrix_world`` and the geometry-nodes Pivot
    input together, so a self-consistent-but-wrong pair would still have
    ``local_to_world`` reporting "nothing moved". The rendered image is the
    only witness that cannot move with the bug - it is what the user saw.
    """
    from mathutils import Vector
    from proteinblender.operators import pivot_operators as P

    molecule_id = H.import_local("1atn.pdb", "1atn")
    _build_outliner()
    objects = _protein_objects(sm.molecules[molecule_id])
    assert len(objects) > 1, "1atn must import as a molecule plus domains"

    bpy.context.view_layer.update()
    before = H.render_coverage(tmp_path)
    assert before.sum() > 0, "nothing rendered to begin with"

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=molecule_id) == {"FINISHED"}
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    assert helper is not None
    helper.location = helper.location + Vector((2.0, 0.0, 0.0))
    bpy.context.view_layer.update()
    dropped_at = helper.matrix_world.translation.copy()

    assert bpy.ops.proteinblender.set_pivot_custom(
        item_id=molecule_id) == {"FINISHED"}
    bpy.context.view_layer.update()

    after = H.render_coverage(tmp_path)
    changed = int(np.logical_xor(before, after).sum())
    assert changed == 0, (
        f"{changed} pixels changed after moving the protein's pivot; the "
        f"molecule was translated instead of just its pivot")

    parent = sm.molecules[molecule_id].object
    offset = (parent.matrix_world.translation - dropped_at).length
    assert offset < 1e-4, (
        f"the protein's origin is {offset:.6f} from where the helper was "
        f"left; the pivot was not applied")


# --------------------------------------------------------------------------
# What a dialog shows when it opens
# --------------------------------------------------------------------------

def _carbon_rgb(obj):
    """The colour an untouched object draws with, straight off its per-object
    "Color Common" node's Carbon socket.

    Independent of ``visual_style.get_object_color``, which is the reader the
    seeding goes through: asserting on that would pass whether it picked the
    right object or not. A freshly imported protein has no "Custom Combine
    Color" node yet, so this is where its per-chain colours actually live.
    """
    for modifier in obj.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group:
            continue
        for node in modifier.node_group.nodes:
            if (node.type == 'GROUP' and node.node_tree
                    and 'Color Common' in node.node_tree.name
                    and 'Carbon' in node.inputs):
                return tuple(round(c, 4)
                             for c in node.inputs['Carbon'].default_value[:3])
    return None


def _seed(scene, item_id):
    """(color, mixed, style) the dialog for this row would open showing."""
    from proteinblender.operators import visual_edit as VE
    from proteinblender.operators.pivot_operators import find_row

    row = find_row(scene, item_id)
    assert row is not None, f"no outliner row for {item_id}"
    return VE.seed_from_objects(VE.appearance_objects_for_row(bpy.context, row))


@pytest.mark.integration
def test_protein_with_differently_colored_chains_seeds_grey(scene, sm,
                                                            multi_chain):
    """4hhb imports with a distinct colour per chain, so the swatch is grey.

    Ground truth that the chains really do disagree is their own Color Common
    Carbon sockets, read directly - not the reader the seeding uses.
    """
    from proteinblender.operators.visual_edit import MIXED_COLOR

    _build_outliner()
    molecule = sm.molecules[multi_chain]
    carbons = {_carbon_rgb(d.object) for d in molecule.domains.values()
               if d.object}
    assert len(carbons) > 1, (
        f"fixture must import with several chain colours, got {carbons}")

    color, mixed, _style = _seed(scene, multi_chain)
    assert mixed is True, "a multi-coloured protein did not report as mixed"
    assert color == MIXED_COLOR, (
        f"expected the neutral grey placeholder, got {color}")


@pytest.mark.integration
def test_protein_seeds_the_real_color_once_its_chains_agree(scene, sm,
                                                            multi_chain):
    """Paint the whole protein, reopen: the swatch shows that colour, not grey."""
    _build_outliner()
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=multi_chain, vs_color=(0.3, 0.6, 0.9, 1.0)) == {'FINISHED'}

    color, mixed, _style = _seed(scene, multi_chain)
    assert mixed is False, "a uniformly coloured protein reported as mixed"
    assert color == (0.3, 0.6, 0.9, 1.0), (
        f"the dialog would open on {color}, not the protein's colour")


@pytest.mark.integration
def test_protein_seeding_ignores_the_molecule_object(scene, sm, multi_chain):
    """The molecule object is written to but is not a witness.

    It keeps its own untouched Color Common carbon grey, which is nothing that
    appears on screen. Seeding read it first, so a freshly imported protein in
    four colours opened showing that one grey - looking exactly like a correct
    "mixed" answer while being an accident.
    """
    from proteinblender.operators import visual_edit as VE
    from proteinblender.operators.pivot_operators import find_row, row_objects

    _build_outliner()
    parent = sm.molecules[multi_chain].object
    row = find_row(scene, multi_chain)

    assert parent in row_objects(bpy.context, row), (
        "the molecule object must still be written to")
    appearance = VE.appearance_objects_for_row(bpy.context, row)
    assert parent not in appearance, (
        "the molecule object must not be read as the protein's appearance")
    assert appearance, "a protein must have something to read its colour from"

    # And the grey it would have contributed is genuinely a different answer.
    assert _carbon_rgb(parent) not in {_carbon_rgb(obj) for obj in appearance}


@pytest.mark.integration
def test_style_seeds_multiple_only_when_the_parts_disagree(scene, sm,
                                                           multi_chain):
    _build_outliner()
    molecule = sm.molecules[multi_chain]

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=multi_chain, vs_style='surface') == {'FINISHED'}
    _color, _mixed, style = _seed(scene, multi_chain)
    assert style == 'surface', f"expected the protein's real style, got {style!r}"

    # Restyle one domain from its own row: the protein now has no single style.
    domain_id = next(iter(molecule.domains))
    assert bpy.ops.proteinblender.rename_domain(
        target_item_id=domain_id, item_type='DOMAIN',
        new_name=molecule.domains[domain_id].name,
        vs_style='cartoon') == {'FINISHED'}

    _color, _mixed, style = _seed(scene, multi_chain)
    assert style == '', (
        f"a protein whose domains disagree must show Multiple, got {style!r}")


@pytest.mark.integration
def test_each_chain_seeds_its_own_color_not_a_siblings(scene, sm, multi_chain):
    """Opening one chain's dialog shows that chain, not whichever came first.

    Chain rows rather than domain rows: a full-chain auto-domain has no DOMAIN
    row of its own (it renders as the CHAIN row), so the chain row is the one
    the user actually clicks the pencil on.
    """
    from proteinblender.operators.visual_edit import appearance_objects_for_row

    _build_outliner()
    molecule = sm.molecules[multi_chain]
    chain_rows = [r for r in scene.outliner_items if r.item_type == 'CHAIN']
    assert len(chain_rows) > 1

    painted = []
    for row, rgba in zip(chain_rows[:2], ((1.0, 0.0, 0.0, 1.0),
                                          (0.0, 0.0, 1.0, 1.0))):
        objects = appearance_objects_for_row(bpy.context, row)
        assert len(objects) == 1, f"{row.item_id} resolved to {objects}"
        domain_id = next(
            did for did, d in molecule.domains.items()
            if d.object is not None and d.object.name == objects[0].name)
        assert bpy.ops.proteinblender.rename_domain(
            target_item_id=domain_id, item_type='DOMAIN',
            new_name=molecule.domains[domain_id].name,
            vs_color=rgba) == {'FINISHED'}
        painted.append((row.item_id, rgba))

    for item_id, expected in painted:
        color, mixed, _style = _seed(scene, item_id)
        assert mixed is False, f"{item_id} reported as mixed"
        assert color == expected, (
            f"{item_id} would open showing {color}, not its own {expected}")
