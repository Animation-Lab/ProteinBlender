"""Integration tests for the Membrane Builder + per-protein force fields.

Drives the real ProteinBlender operators against a headless Blender scene and
asserts observable state (new Blender objects, base-mesh geometry, hole
controllers parented to the root, lattice reset, and the per-object force-field
anchor Empty that a membrane force-field creates).

Covered operators (all in ``proteinblender.membrane_builder.membrane_operators``
plus ``proteinblender.membrane_builder.force_fields``):
  * proteinblender.build_membrane          (via helpers.build_membrane)
  * proteinblender.resize_membrane
  * proteinblender.membrane_add_hole / membrane_select_hole /
    membrane_remove_hole
  * proteinblender.membrane_reset_deform
  * proteinblender.delete_membrane
  * proteinblender.toggle_force_fields      (+ Object.pb_force_field_enabled)
  * proteinblender.membrane_edit_deform / membrane_finish_deform (edit-mode;
    tolerant — skipped when the headless context can't enter Lattice edit mode)

Geometry note: the membrane GN tree emits *instances* (Instance on Points, no
Realize Instances), so the evaluated mesh returned by ``H.geometry_summary`` /
``to_mesh`` contains ZERO realized vertices — the lipids are instances, not
mesh. The reliable "surface has geometry" signal is therefore the membrane
root's *base* mesh (``root.data.vertices``), which is the flat/curved patch the
lipids are distributed onto. Tests assert on that, and additionally call
``H.geometry_summary`` only to prove it runs without error.
"""

import bpy
import pytest

import helpers as H
import harness_contract as HC

from proteinblender.membrane_builder.membrane_geometry import (
    SHAPE_FLAT,
    SHAPE_SPHERE,
    SHAPE_HEMISPHERE,
    MAX_HOLES,
)

GN_MOD_NAME = "PB_Membrane_GN"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _membrane_root(created_names):
    """Return the ``pb_is_membrane`` root object among newly created names."""
    for name in created_names:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.get("pb_is_membrane", False):
            return obj
    return None


def _base_verts(root):
    """Vertex count of the membrane root's *base* mesh (pre-instancing)."""
    return len(root.data.vertices)


def _base_x_extent(root):
    xs = [v.co.x for v in root.data.vertices]
    return (max(xs) - min(xs)) if xs else 0.0


def _hole_count(root):
    return sum(1 for c in root.children if c.get("pb_is_membrane_hole", False))


def _hole_children(root):
    return [c for c in root.children if c.get("pb_is_membrane_hole", False)]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_build_membrane_creates_objects_with_geometry(scene):
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    # Build creates at least the root mesh + its lattice deformer.
    assert len(names) >= 2, f"build produced too few objects: {names}"

    root = _membrane_root(names)
    assert root is not None, "no pb_is_membrane root among created objects"

    # The GN modifier that turns the patch into a bilayer must be present.
    assert any(m.type == "NODES" and m.name == GN_MOD_NAME
               for m in root.modifiers), "membrane GN modifier missing"

    # The base surface has real vertices (the lipids themselves are GN
    # instances and don't show up in an evaluated to_mesh — see module docstring).
    assert _base_verts(root) > 0, "membrane base mesh has no vertices"

    # geometry_summary must at least run cleanly on the evaluated object.
    summary = H.geometry_summary(root)
    assert isinstance(summary, dict) and "verts" in summary

    # A dedicated lattice child exists for deformation.
    assert any(c.type == "LATTICE" for c in root.children), "no lattice child"


@pytest.mark.integration
@pytest.mark.parametrize("shape", [SHAPE_FLAT, SHAPE_SPHERE, SHAPE_HEMISPHERE])
def test_build_membrane_each_shape(scene, shape):
    names = H.build_membrane(shape=shape, width=20.0, height=20.0, radius=15.0)
    root = _membrane_root(names)
    assert root is not None, f"shape {shape!r} created no membrane root"
    assert root.get("pb_mem_shape") == shape
    assert _base_verts(root) > 0, f"shape {shape!r} base mesh has no vertices"


# --------------------------------------------------------------------------
# Resize
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_resize_membrane_changes_dimensions(scene):
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    assert root is not None
    before_x = _base_x_extent(root)
    assert before_x > 0.0

    # Build leaves the root active, which resize_membrane.poll requires.
    assert bpy.context.active_object is root

    # Widen the patch, then rebuild the grid to match.
    scene.membrane_builder_props.width = 40.0
    res = bpy.ops.proteinblender.resize_membrane()
    assert res == {'FINISHED'}

    after_x = _base_x_extent(root)
    assert after_x > before_x + 1e-4, (
        f"resize did not widen the base mesh ({before_x} -> {after_x})")


# --------------------------------------------------------------------------
# Holes
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_add_select_remove_hole(scene):
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    assert root is not None
    assert _hole_count(root) == 0

    # Add — poll resolves off the active object (the root, post-build).
    res = bpy.ops.proteinblender.membrane_add_hole()
    assert res == {'FINISHED'}
    assert _hole_count(root) == 1

    # Add a second (active is now the first hole, a membrane child — the
    # operator resolves it back to the root via pb_membrane_owner).
    res = bpy.ops.proteinblender.membrane_add_hole()
    assert res == {'FINISHED'}
    assert _hole_count(root) == 2

    # The hole names are cached on the root, pipe-delimited.
    cached = [n for n in (root.get("pb_mem_holes", "") or "").split("|") if n]
    assert len(cached) == 2

    # Select a specific hole — it becomes the active + selected object.
    target = _hole_children(root)[0]
    res = bpy.ops.proteinblender.membrane_select_hole(hole_name=target.name)
    assert res == {'FINISHED'}
    assert bpy.context.view_layer.objects.active is target
    assert target.select_get()

    # Remove that hole by name. Capture the name first — removing the hole
    # deletes the object, after which `target.name` raises ReferenceError.
    target_name = target.name
    res = bpy.ops.proteinblender.membrane_remove_hole(hole_name=target_name)
    assert res == {'FINISHED'}
    assert _hole_count(root) == 1
    assert bpy.data.objects.get(target_name) is None


@pytest.mark.integration
def test_hole_cap_constant_is_positive():
    # Sanity guard so the panel's "Holes: n / MAX" label always has a ceiling.
    assert isinstance(MAX_HOLES, int) and MAX_HOLES > 0


# --------------------------------------------------------------------------
# Deformation reset (+ tolerant edit/finish)
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_reset_deform_restores_rest_lattice(scene):
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    assert root is not None
    lattice = next(c for c in root.children if c.type == "LATTICE")

    # Perturb one lattice point so reset has something to undo.
    p0 = lattice.data.points[0]
    p0.co_deform = (p0.co[0] + 1.0, p0.co[1] + 1.0, p0.co[2] + 1.0)

    H.select_only(root)
    res = bpy.ops.proteinblender.membrane_reset_deform()
    assert res == {'FINISHED'}

    # Rest state is co_deform == co for every point (NOT (0,0,0)).
    for p in lattice.data.points:
        assert tuple(p.co_deform) == pytest.approx(tuple(p.co)), \
            "lattice point not returned to rest after reset"


@pytest.mark.integration
def test_edit_and_finish_deform_are_tolerant(scene):
    """Edit/finish flip Blender in and out of Lattice EDIT mode, which may not
    be reachable in headless ``--background``. Exercise them but treat a
    RuntimeError from the mode switch as a headless skip, not a failure."""
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    assert root is not None
    H.select_only(root)

    try:
        res = bpy.ops.proteinblender.membrane_edit_deform()
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"membrane_edit_deform needs interactive edit-mode: {e}")
    if res != {'FINISHED'}:
        HC.context_unavailable(pytest, f"membrane_edit_deform did not finish headless: {res}")

    # If we got here we're in edit mode on the lattice; finish should return
    # focus to the membrane root.
    try:
        bpy.ops.proteinblender.membrane_finish_deform()
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"membrane_finish_deform needs interactive context: {e}")
    assert bpy.context.mode == "OBJECT"


# --------------------------------------------------------------------------
# Delete
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_delete_membrane_removes_root_and_children(scene):
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    assert root is not None
    root_name = root.name
    child_names = [c.name for c in root.children]
    assert child_names, "membrane had no children to verify cascade delete"

    res = bpy.ops.proteinblender.delete_membrane(membrane_name=root_name)
    assert res == {'FINISHED'}

    assert bpy.data.objects.get(root_name) is None, "membrane root survived delete"
    for cn in child_names:
        assert bpy.data.objects.get(cn) is None, f"child {cn} survived delete"


# --------------------------------------------------------------------------
# Per-protein membrane force field
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_force_field_toggle_creates_anchor_and_flag(scene, sm, single_chain):
    """Enabling a protein's membrane force field (via the outliner selection +
    proteinblender.toggle_force_fields) flips ``pb_force_field_enabled`` on the
    protein object and spawns its hidden ``.ff_anchor`` Empty; disabling reaps
    it."""
    # A membrane must exist for the FF apply pass to create anchors.
    H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)

    obj = sm.molecules[single_chain].object
    assert obj is not None
    assert getattr(obj, "pb_force_field_enabled", False) is False

    # Select the protein in the PB Outliner so the operator resolves it.
    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)
    pit.is_selected = True

    res = bpy.ops.proteinblender.toggle_force_fields(target_state="on")
    assert res == {'FINISHED'}
    assert obj.pb_force_field_enabled is True

    anchor = bpy.data.objects.get(f"{obj.name}.ff_anchor")
    assert anchor is not None, "force-field anchor Empty was not created"
    assert anchor.get("pb_is_ff_anchor", False) is True

    # The anchor is deliberately NOT parented. Parenting a molecule failed to
    # carry the owner's Z to the child, so a protein lifted off the membrane
    # still carved a hole; the anchor is repositioned to the owner's world
    # centre on every FF apply instead. That it actually *tracks* the protein's
    # height is proven end-to-end by the live lane
    # (test_a_force_field_only_parts_the_membrane_when_it_is_near_it), through a
    # render - the only reliable observation, since a just-moved object's
    # matrix_world does not flush deterministically in a headless --background
    # session. Here we only assert the design: the anchor is unparented.
    assert anchor.parent is None, (
        "the anchor is parented; it must be unparented so it can be driven to "
        "the owner's world centre, height included")

    # Turning it off flips the flag back and sweeps the orphaned anchor.
    res = bpy.ops.proteinblender.toggle_force_fields(target_state="off")
    assert res == {'FINISHED'}
    assert obj.pb_force_field_enabled is False
    assert bpy.data.objects.get(f"{obj.name}.ff_anchor") is None, \
        "anchor Empty survived FF disable"


# --------------------------------------------------------------------------
# Multiple overlapping force fields must not conjure a hole from thin air
# --------------------------------------------------------------------------

def _lipid_density(root, center_xy, r_bu):
    """Count evaluated lipid instances within r_bu of center_xy (world)."""
    import numpy as np
    deps = bpy.context.evaluated_depsgraph_get()
    pts = [[i.matrix_world.translation.x, i.matrix_world.translation.y]
           for i in deps.object_instances
           if i.is_instance and i.parent and i.parent.original == root]
    if not pts:
        return 0
    d = np.linalg.norm(np.array(pts) - np.array(center_xy), axis=1)
    return int((d < r_bu).sum())


def _make_ff_cube(name, location, size=0.3, spacing=6.0):
    """A small mesh object that emits a membrane force field, at `location`."""
    me = bpy.data.meshes.new(name + "_m")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    o.location = location
    o.pb_force_field_enabled = True
    o.pb_force_field_spacing = spacing
    return o


def test_stacked_force_fields_do_not_carve_a_hole_from_afar(scene):
    """Several force fields overlapping in XY but all far above the membrane in
    Z must leave the bilayer intact - the field is a 3D body, and none of these
    bodies touches the sheet.

    The bug: the multi-field combiner formed the combined penetration as
    ``smin_sdf = -ln(Σ w_i)/α`` (log-sum-exp), which is biased below the true
    minimum by ``ln(N)/α``. N fields stacked at the same XY, each already
    Z-attenuated to radius 0 because it floats far above the sheet, still summed
    to ``total_w ≈ N`` and produced ``ln(N)/α`` (~0.69 BU for N=4 at α=2) of
    penetration - a hole carved from overlap alone. Enabling a force field on a
    whole protein AND each of its chains stacks exactly such fields, so the
    bilayer was bored through no matter how high the protein was lifted.

    This is observed the way a user would see it: the lipids that actually
    survive in the evaluated geometry. Ground truth is physical - four small
    bodies 5 BU (50 nm) above a flat sheet cannot displace it - and independent
    of the combiner code. A control run with the same fields lowered into the
    sheet proves the field still works.
    """
    H.build_membrane(shape=SHAPE_FLAT, width=40.0, height=40.0)
    root = next(o for o in bpy.data.objects if o.get("pb_is_membrane", False))
    import sys
    ff = sys.modules["proteinblender.membrane_builder.force_fields"]

    baseline = _lipid_density(root, (0.0, 0.0), 0.6)
    assert baseline > 20, f"membrane too sparse to measure a hole: {baseline}"

    # Four overlapping FF emitters, all stacked at the same XY, 5 BU up.
    cubes = [_make_ff_cube(f"pb_ff_cube_{i}", (0.0, 0.0, 5.0)) for i in range(4)]
    single_radius = ff.compute_force_field_radius_bu(cubes[0], 1.5)
    assert single_radius < 5.0, (
        f"emitter radius {single_radius:.2f} BU reaches a sheet 5 BU away; the "
        "test geometry no longer isolates the phantom-hole path")
    ff.apply_to_all_membranes(bpy.context.scene)
    bpy.context.view_layer.update()
    far = _lipid_density(root, (0.0, 0.0), 0.6)

    # Now drop them into the sheet: the field must genuinely carve here.
    for c in cubes:
        c.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    ff.apply_to_all_membranes(bpy.context.scene)
    bpy.context.view_layer.update()
    embedded = _lipid_density(root, (0.0, 0.0), 0.6)

    # Far above: the sheet is untouched (a phantom hole would drop this count).
    assert far > baseline * 0.9, (
        f"four force fields 5 BU (50 nm) above the membrane still carved it: "
        f"{baseline} lipids under them at rest, {far} with the fields on - a "
        "hole conjured from overlap alone")
    # Embedded: the field still does its job.
    assert embedded < far * 0.5, (
        f"the force field no longer carves when embedded: {far} lipids far, "
        f"{embedded} embedded - expected the sheet to part")


# --------------------------------------------------------------------------
# Lipid colours
#
# Head and tail colours are shared material datablocks. Ground truth for every
# assertion below is the colour constant the test picks, read back off the
# Blender material's Principled BSDF - never from the membrane code's own
# accessors.
# --------------------------------------------------------------------------

HEAD_MATERIAL_NAME = "PB_Membrane_Head"
TAIL_MATERIAL_NAME = "PB_Membrane_Tail"

BLUE = (0.0, 0.0, 1.0, 1.0)
CYAN = (0.0, 1.0, 1.0, 1.0)
BASELINE_PINK = (1.0, 0.5, 0.5, 1.0)


def _material_base_color(name):
    """The material's Principled BSDF base colour, or None if absent."""
    mat = bpy.data.materials.get(name)
    if mat is None or mat.node_tree is None:
        return None
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return None
    return tuple(round(v, 3) for v in bsdf.inputs["Base Color"].default_value)


def _only_membrane():
    return next(o for o in bpy.data.objects if o.get("pb_is_membrane", False))


@pytest.mark.integration
def test_head_and_tail_colors_write_through_to_the_active_membrane(scene):
    """Setting the head / tail colour must reach the membrane immediately, the
    way every other membrane property does.

    Regression: ``color_head`` and ``color_tail`` were the only membrane props
    without an ``update`` callback, so changing them left the value in the
    scene props and never touched the membrane. Two consequences the tester
    hit: no live preview, and - because the value lived nowhere but the props -
    the object->props resync that fires on any active-object change silently
    replaced the pick with the membrane's stale stored colour.
    """
    H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0,
                     render_style="STYLIZED")
    root = _only_membrane()
    H.select_only(root)
    props = scene.membrane_builder_props

    props.color_head = BLUE
    assert _material_base_color(HEAD_MATERIAL_NAME) == BLUE, (
        f"head material is {_material_base_color(HEAD_MATERIAL_NAME)}, "
        f"expected the picked {BLUE}")
    assert tuple(root["pb_mem_color_head"]) == BLUE, (
        "the head colour never reached the membrane, so the next "
        "object->props sync will overwrite the user's pick")

    props.color_tail = CYAN
    assert _material_base_color(TAIL_MATERIAL_NAME) == CYAN
    assert tuple(root["pb_mem_color_tail"]) == CYAN


@pytest.mark.integration
def test_head_color_survives_an_in_dialog_action(scene):
    """A head colour picked in the open Membrane dialog must survive using
    another control in that same dialog before pressing OK.

    Regression: in-dialog buttons (Add Hole, Edit Deformation, Select Hole)
    change the active object, which fires the membrane msgbus object->props
    sync. With the pick living only in the scene props it was overwritten by
    the membrane's stored colour, and OK then re-applied that stale value.
    This is the "change representations, change colors, repeat" path the
    tester reported as buggy.
    """
    from proteinblender.membrane_builder.membrane_props import (
        sync_props_from_object,
    )

    # Build with an explicit baseline colour so the membrane's STORED colour
    # is known and differs from the pick below. Without this the test would
    # inherit whatever colour a previous test left in the scene props, and
    # could pass vacuously when the stored colour already matched the pick.
    H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0,
                     render_style="STYLIZED", color_head=BASELINE_PINK)
    root = _only_membrane()
    H.select_only(root)
    props = scene.membrane_builder_props

    sync_props_from_object(props, root)     # what the dialog's invoke() does
    assert tuple(root["pb_mem_color_head"]) == BASELINE_PINK, (
        "test setup: the membrane did not store the baseline colour, so "
        "there is nothing for the resync to clobber")

    props.color_head = BLUE                 # the user picks a head colour

    bpy.ops.proteinblender.membrane_add_hole()   # an in-dialog button
    sync_props_from_object(props, root)          # what the msgbus then does

    assert tuple(round(v, 3) for v in props.color_head) == BLUE, (
        "the in-dialog action reverted the head colour the user had just "
        f"picked: props now {tuple(round(v, 3) for v in props.color_head)}")

    bpy.ops.proteinblender.build_membrane(
        'EXEC_DEFAULT', membrane_root_to_update=root.name)   # press OK
    assert _material_base_color(HEAD_MATERIAL_NAME) == BLUE, (
        f"after OK the head material is "
        f"{_material_base_color(HEAD_MATERIAL_NAME)}, expected {BLUE}")


# --------------------------------------------------------------------------
# Importing a protein after working on a membrane
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_import_protein_works_after_editing_membrane_deformation(scene, sm):
    """Importing a protein must work while the membrane's lattice deformer is
    still in edit mode.

    Regression: ``membrane_edit_deform`` deliberately leaves Blender in Lattice
    edit mode so the user can drag points. MolecularNodes' import appends its
    style node groups with ``bpy.ops.wm.append``, whose poll fails outside
    Object mode, so every protein import failed with "context is incorrect"
    until the user happened to tab out. Reported as "I can't seem to download a
    protein after creating and editing a membrane".

    Ground truth is the scene manager's registry plus a real Blender object -
    neither derived from the import code's own status flag.
    """
    H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root = _only_membrane()
    H.select_only(root)

    try:
        result = bpy.ops.proteinblender.membrane_edit_deform()
    except RuntimeError as e:
        HC.context_unavailable(
            pytest, f"membrane_edit_deform needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest,
            f"headless context could not enter Lattice edit mode "
            f"(result={result}, mode={bpy.context.mode})")

    mid = H.import_local("1ubq.pdb", "AFTER_MEMBRANE_EDIT")

    assert mid in sm.molecules, "the protein never reached the molecule registry"
    obj = sm.molecules[mid].object
    assert obj is not None and obj.name in bpy.data.objects, (
        "the import reported success but created no Blender object")
    assert len(obj.data.vertices) > 0, "the imported protein has no atoms"


@pytest.mark.integration
def test_builders_work_after_editing_membrane_deformation(scene):
    """The DNA builder and a second membrane must build while the first
    membrane's lattice deformer is still in edit mode.

    Same root cause as the protein-import regression above: these paths call
    ``bpy.ops.object.select_all`` and (for DNA) ``bpy.ops.wm.append``, neither
    of which polls outside Object mode. Edit Deformation parks the user there
    by design, so this was the state a tutorial author would naturally build
    from. Both raised "context is incorrect" and produced nothing.
    """
    H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root = _only_membrane()
    H.select_only(root)

    try:
        result = bpy.ops.proteinblender.membrane_edit_deform()
    except RuntimeError as e:
        HC.context_unavailable(
            pytest, f"membrane_edit_deform needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest,
            f"headless context could not enter Lattice edit mode "
            f"(result={result}, mode={bpy.context.mode})")

    dna = H.build_dna(seq="ATCGATCG", name_prefix="AFTER_MEM_EDIT", ds=True,
                      style="cartoon")
    assert dna.get("pb_is_nucleic_acid") is True
    assert len(dna.data.vertices) > 0, "the strand built from edit mode is empty"

    before = {o.name for o in bpy.data.objects if o.get("pb_is_membrane", False)}
    H.build_membrane(shape=SHAPE_FLAT, width=8.0, height=8.0)
    after = {o.name for o in bpy.data.objects if o.get("pb_is_membrane", False)}
    assert after - before, "no second membrane was created from edit mode"


# --------------------------------------------------------------------------
# Morphing / animation
# --------------------------------------------------------------------------

def _lipid_positions(root):
    """World-space translation of every lipid instance the membrane emits.

    The GN tree outputs instances (never realized), so the evaluated mesh is
    empty and ``eval_positions`` sees nothing. The depsgraph's instance list is
    what actually gets rendered, so it is the honest read of "where are the
    lipids" — and it is independent of anything inside the node tree.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    root_eval = root.evaluated_get(dg)
    return [tuple(inst.matrix_world.translation)
            for inst in dg.object_instances
            if inst.is_instance and inst.parent == root_eval]


def _bulge_lattice(lattice, amount_bu, frame):
    """Dome the lattice: lift interior points, leave the rim, keyframe it.

    The deformation is authored here, in the test, so the expected surface
    displacement never comes from the product code.
    """
    for p in lattice.data.points:
        radial = (p.co[0] ** 2 + p.co[1] ** 2) ** 0.5
        lift = amount_bu * max(0.0, 1.0 - radial * 2.0)
        p.co_deform = (p.co[0], p.co[1], p.co[2] + lift)
        p.keyframe_insert("co_deform", frame=frame)


@pytest.mark.integration
def test_lipids_keep_their_identity_while_the_membrane_morphs(scene):
    """Animating the lattice must glide the lipids, not re-scatter them.

    Regression: the GN tree fed the *lattice-deformed* mesh straight into
    Distribute Points on Faces. Poisson-disk sampling is a function of the
    triangle geometry, so every lattice move re-sampled the whole sheet from
    scratch — the lipid count changed frame to frame and each lipid teleported
    across the membrane. On screen that reads as violent flicker, and it made
    membranes effectively un-animatable.

    The invariants the bug violates, both measured on the depsgraph instance
    list (what actually renders):
      * the lipid count is the same on every frame;
      * no lipid moves further between two adjacent frames than the surface
        itself moves — a re-scatter throws lipids clear across the sheet.
    """
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0,
                             animate_bob=False)
    root = _membrane_root(names)
    assert root is not None
    lattice = next(c for c in root.children if c.type == "LATTICE")

    # Frame 1 = rest, frame 11 = domed. 0.4 BU = 4 nm of rise over 10 frames.
    BULGE_BU = 0.4
    FRAMES = list(range(1, 12))
    _bulge_lattice(lattice, 0.0, FRAMES[0])
    _bulge_lattice(lattice, BULGE_BU, FRAMES[-1])

    samples = []
    for f in FRAMES:
        bpy.context.scene.frame_set(f)
        samples.append(_lipid_positions(root))

    counts = {len(s) for s in samples}
    assert len(samples[0]) > 0, "the membrane emitted no lipid instances at all"
    assert len(counts) == 1, (
        f"the lipid count changed while the membrane morphed: {sorted(counts)} "
        "— the sheet is being re-scattered every frame, not deformed")

    # Per-lipid continuity. The surface itself rises BULGE_BU over 10 frames,
    # so no lipid should move more than roughly that per-frame step. A
    # re-scatter moves lipids by a large fraction of the membrane width
    # (20 nm = 2.0 BU), which is an order of magnitude larger.
    per_frame_surface_step = BULGE_BU / (len(FRAMES) - 1)
    tolerance = per_frame_surface_step * 4.0
    worst = 0.0
    for a, b in zip(samples, samples[1:]):
        for pa, pb in zip(a, b):
            d = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
            worst = max(worst, d)
    assert worst < tolerance, (
        f"a lipid jumped {worst:.3f} BU between adjacent frames while the "
        f"surface moved only {per_frame_surface_step:.3f} BU — the lipids are "
        "being re-scattered, not carried along by the deformation")


@pytest.mark.integration
def test_morphed_membrane_lipids_follow_the_deformed_surface(scene):
    """Stabilising the scatter must not freeze the lipids on the rest shape.

    The lipids are distributed on the rest shape, so the obvious wrong fix is
    to leave them there — a flat sheet of lipids floating through a domed
    surface. Ground truth is the dome the test itself authored: lifting the
    interior lattice points by ``BULGE_BU`` must lift the lipids over the
    middle of the sheet by a comparable amount.
    """
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0,
                             animate_bob=False)
    root = _membrane_root(names)
    lattice = next(c for c in root.children if c.type == "LATTICE")

    flat_z = [p[2] for p in _lipid_positions(root)]
    assert flat_z, "no lipid instances on the flat membrane"

    BULGE_BU = 0.4
    _bulge_lattice(lattice, BULGE_BU, frame=1)
    bpy.context.scene.frame_set(1)
    domed = _lipid_positions(root)
    assert domed, "no lipid instances on the domed membrane"

    # Lipids near the centre of the sheet (where the lattice lift is full).
    centre_z = [p[2] for p in domed
                if (p[0] ** 2 + p[1] ** 2) ** 0.5 < 0.2]
    assert centre_z, "no lipids near the centre of the domed membrane"

    rise = max(centre_z) - max(flat_z)
    assert rise > BULGE_BU * 0.5, (
        f"the centre lipids rose only {rise:.3f} BU for a {BULGE_BU} BU dome — "
        "the lipids are stuck on the rest shape instead of following the "
        "deformed surface")


def _instance_matrices(root):
    """World matrix of every lipid instance — the real rendered transform."""
    dg = bpy.context.evaluated_depsgraph_get()
    root_eval = root.evaluated_get(dg)
    return [inst.matrix_world.copy() for inst in dg.object_instances
            if inst.is_instance and inst.parent == root_eval]


def _worst_rotation_steps(samples):
    """(worst tilt step, worst total rotation step) in degrees, per lipid,
    between adjacent frames.

    Tilt is the swing of the lipid's long axis (local Z); the total step is the
    full quaternion difference, which also picks up spin *about* that axis. A
    lipid re-oriented smoothly by a morph has both small and comparable; a
    lipid whose azimuth frame flips has a small tilt and a ~180 deg total.
    """
    import math

    worst_tilt = 0.0
    worst_total = 0.0
    for before, after in zip(samples, samples[1:]):
        for ma, mb in zip(before, after):
            za = ma.to_3x3().col[2].normalized()
            zb = mb.to_3x3().col[2].normalized()
            worst_tilt = max(worst_tilt, math.degrees(
                math.acos(max(-1.0, min(1.0, za.dot(zb))))))
            delta = ma.to_quaternion().rotation_difference(mb.to_quaternion())
            total = math.degrees(delta.angle)
            if total > 180.0:
                total = 360.0 - total
            worst_total = max(worst_total, total)
    return worst_tilt, worst_total


@pytest.mark.integration
@pytest.mark.parametrize("shape,kwargs", [
    (SHAPE_FLAT, {"width": 20.0, "height": 20.0}),
    (SHAPE_SPHERE, {"radius": 15.0}),
])
def test_lipids_do_not_flip_about_their_own_axis_during_a_morph(scene, shape,
                                                                kwargs):
    """A morphing membrane must not snap lipids 180 deg about their long axis.

    Reported as lipids doing "a superfast flip, almost like they are going from
    a negative angle to a positive and they flip at a specific angle value".

    Regression: the per-instance rotation came from AlignRotationToVector with
    ``pivot_axis = "AUTO"``, which derives the azimuth frame from its own input
    vector and swaps to a different pivot as that input crosses a critical
    direction. While the surface was rigid the input never moved and the flip
    was dormant; making membranes morphable put a slowly-swinging normal back
    into it. Measured over a 20-frame lattice bulge, the lipid's long axis
    tracked the surface smoothly at 1.59 deg per frame while its SPIN about
    that axis jumped 179.91 deg in a single frame.

    The invariant: a lipid's total rotation between adjacent frames cannot
    greatly exceed how far its long axis actually tilted. Both numbers are
    measured from the rendered instance matrices, so neither side comes from
    the node tree. The tilt bound doubles as the vacuity check — if the
    membrane never actually moved, the test fails rather than passing on a
    frozen scene.
    """
    names = H.build_membrane(shape=shape, animate_bob=False, **kwargs)
    root = _membrane_root(names)
    assert root is not None
    lattice = next(c for c in root.children if c.type == "LATTICE")

    FRAMES = list(range(1, 22))
    _bulge_lattice(lattice, 0.0, FRAMES[0])
    _bulge_lattice(lattice, 0.5, FRAMES[-1])

    samples = []
    for f in FRAMES:
        bpy.context.scene.frame_set(f)
        samples.append(_instance_matrices(root))
    assert samples[0], "the membrane emitted no lipid instances"

    worst_tilt, worst_total = _worst_rotation_steps(samples)

    assert worst_tilt > 0.1, (
        f"the lipids barely moved ({worst_tilt:.3f} deg of tilt), so this run "
        "never exercised a morph and proves nothing")
    assert worst_total < max(10.0, worst_tilt * 3.0), (
        f"a lipid rotated {worst_total:.2f} deg between adjacent frames while "
        f"its long axis tilted only {worst_tilt:.2f} deg — it is snapping "
        "about its own axis, not being carried by the deformation")


def _fold_lattice(lattice, angle_deg, frame):
    """Fold the +X half of the lattice about the world X axis, and keyframe it.

    Rotating about X swings the deformed normal toward world Y. That direction
    matters: for a flat membrane the azimuth reference is exactly world Y, so
    this drives the deformed normal straight at the reference. A fold about Y
    instead keeps the normal permanently perpendicular to it and cannot expose
    the defect, which is why the gentler dome tests pass either way.

    The falloff is applied in the test so the deformation is authored here, not
    derived from anything the product code computes.
    """
    import math

    theta = math.radians(angle_deg)
    for p in lattice.data.points:
        x, y, z = p.co[0], p.co[1], p.co[2]
        if x > 0.0:
            a = theta * min(1.0, x * 4.0)
            ca, sa = math.cos(a), math.sin(a)
            p.co_deform = (x, y * ca + z * sa, -y * sa + z * ca)
        else:
            p.co_deform = (x, y, z)
        p.keyframe_insert("co_deform", frame=frame)


@pytest.mark.integration
def test_lipids_do_not_flip_when_a_fold_passes_the_azimuth_reference(scene):
    """A lipid tilted ~90 deg from rest must not snap about its own axis.

    Regression on the v37 fix, which did not remove the 180 deg flip so much as
    move it. v37 replaced AlignRotationToVector's AUTO pivot with
    AxesToRotation and fed the secondary axis from the REST normal, on the
    reasoning that a frame-invariant reference cannot flip. It can still fail:
    AxesToRotation projects the secondary onto the plane perpendicular to the
    primary, and that projection collapses when the two become parallel — which
    happens once the DEFORMED normal has swung ~90 deg from rest *in the
    direction of the reference*. The rest normal never moves; the primary axis
    moves onto it.

    Measured before the fix, folding a flat sheet 120 deg about X: a lipid's
    total rotation between adjacent frames hit 178.97 deg while its long axis
    tilted only 14.03 deg, and every culprit sat 80-90 deg from its rest
    orientation. That is the same user-visible symptom v37 was meant to end -
    "a superfast flip ... at a specific angle value" - and the specific angle is
    90 deg from rest.

    The existing dome tests cannot catch this: a radially symmetric bulge
    asymptotes at ~88 deg of tilt from rest no matter how hard it is driven
    (measured 87.71 deg at a 32 BU bulge), so it stops just short of the cliff.

    Invariant and ground truth are as in the dome flip test: a lipid's total
    rotation between adjacent frames cannot greatly exceed how far its long
    axis actually tilted, both read from the rendered instance matrices.
    """
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0,
                             animate_bob=False)
    root = _membrane_root(names)
    assert root is not None
    lattice = next(c for c in root.children if c.type == "LATTICE")

    FRAMES = list(range(1, 26))
    _fold_lattice(lattice, 0.0, FRAMES[0])
    _fold_lattice(lattice, 120.0, FRAMES[-1])

    samples = []
    for f in FRAMES:
        bpy.context.scene.frame_set(f)
        samples.append(_instance_matrices(root))
    assert samples[0], "the membrane emitted no lipid instances"

    # The fold has to actually carry lipids past ~90 deg from rest, or the run
    # never reaches the degenerate configuration and proves nothing.
    import math

    worst_from_rest = 0.0
    rest, last = samples[0], samples[-1]
    if len(rest) == len(last):
        for ma, mb in zip(rest, last):
            za = ma.to_3x3().col[2].normalized()
            zb = mb.to_3x3().col[2].normalized()
            worst_from_rest = max(worst_from_rest, math.degrees(
                math.acos(max(-1.0, min(1.0, za.dot(zb))))))
    assert worst_from_rest > 90.0, (
        f"the fold only tilted lipids {worst_from_rest:.1f} deg from rest, so "
        "it never reached the configuration that breaks the azimuth reference")

    worst_tilt, worst_total = _worst_rotation_steps(samples)
    assert worst_total < max(10.0, worst_tilt * 3.0), (
        f"a lipid rotated {worst_total:.2f} deg between adjacent frames while "
        f"its long axis tilted only {worst_tilt:.2f} deg — the azimuth "
        "reference collapsed as the deformed normal swung onto it")


@pytest.mark.integration
def test_a_membrane_survives_its_group_collection_being_unlinked(scene):
    """An unlinked <name>_Group must not strand or break the membrane.

    Every object a membrane owns - root, lattice, holes - lives in one
    ``<name>_Group`` collection, so unlinking that collection from the scene
    makes all of them disappear together. That is an ordinary thing for a user
    to do by accident: deleting the group's row in Blender's own outliner
    unlinks the collection without touching the objects.

    `_ensure_membrane_collection` looks the collection up by name and returns
    it as-is, so it hands back a collection that is not in the scene and the
    membrane never comes back. Worse, building a *new* membrane that resolves
    to the same group name then fails outright, because the operator selects
    the root it just made and Blender refuses:
    ``Object 'Membrane_001' cannot be selected because it is not in View Layer``.

    Ground truth is Blender's own scene graph - membership in
    ``scene.objects`` and ``scene.collection.children`` - never the helper
    under test.
    """
    names = H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root = _membrane_root(names)
    assert root is not None
    group_name = f"{root.name}_Group"
    group = bpy.data.collections.get(group_name)
    assert group is not None, f"no {group_name} collection was created"
    assert root.name in {o.name for o in bpy.context.scene.objects}

    # What deleting the group row in Blender's outliner does.
    bpy.context.scene.collection.children.unlink(group)
    assert root.name not in {o.name for o in bpy.context.scene.objects}, (
        "test setup: unlinking the group did not actually strand the membrane")

    # Free the names so a rebuild resolves to the same group, which is the
    # state in which the builder used to raise.
    for obj in [root] + list(root.children):
        bpy.data.objects.remove(obj, do_unlink=True)
    assert group_name in {c.name for c in bpy.data.collections}, (
        "test setup: the stranded group was cleaned up, nothing left to hit")
    assert group_name not in {c.name for c in bpy.context.scene.collection.children}

    # Building again must succeed and must be visible, not silently land in
    # the stranded collection.
    names2 = H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root2 = _membrane_root(names2)
    assert root2 is not None, "no membrane was built over the stranded group"
    assert root2.name in {o.name for o in bpy.context.scene.objects}, (
        f"{root2.name} was built into a collection that is not in the scene, "
        "so the whole membrane is invisible")
    assert root2.visible_get(), f"{root2.name} was built but is not visible"
    assert f"{root2.name}_Group" in {
        c.name for c in bpy.context.scene.collection.children}, (
        "the membrane's group collection is still not linked to the scene")


@pytest.mark.integration
def test_deform_mode_offers_a_visible_way_out(scene):
    """Entering deformation mode must put an exit on screen.

    Reported: "once you enter deformation, there is not an obvious way to exit
    it". Edit Deformation was a one-way door - the dialog that launches it
    closes behind the user, and `membrane_finish_deform` was registered but
    drawn nowhere, so the only exit was knowing to press Tab. The banner panel
    is the affordance; its poll is what decides whether the user can see it.
    """
    from proteinblender.membrane_builder.membrane_operators import (
        PROTEINBLENDER_PT_membrane_deform_banner as Banner,
        is_editing_membrane_deform,
    )

    names = H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root = _membrane_root(names)
    H.select_only(root)

    assert not is_editing_membrane_deform(bpy.context), (
        "not editing yet, but the deform state says otherwise")
    assert not Banner.poll(bpy.context), (
        "the deform banner is showing before the user entered deform mode")

    try:
        result = bpy.ops.proteinblender.membrane_edit_deform()
    except RuntimeError as e:
        HC.context_unavailable(
            pytest, f"membrane_edit_deform needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest,
            f"headless context could not enter Lattice edit mode "
            f"(result={result}, mode={bpy.context.mode})")

    assert is_editing_membrane_deform(bpy.context)
    assert Banner.poll(bpy.context), (
        "the user is in membrane deform mode but the banner offering the way "
        "out does not draw - this is the one-way door")

    assert bpy.ops.proteinblender.membrane_finish_deform() == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT', "Finish Deformation did not exit"
    assert not Banner.poll(bpy.context), (
        "the deform banner is still showing after finishing")


@pytest.mark.integration
def test_reset_deform_sticks_while_in_edit_mode(scene):
    """Reset Deformation must work from inside deformation mode.

    Regression: it wrote `lattice.data.points[*].co_deform` directly, but
    Blender holds an authoritative edit-mode copy of a lattice and overwrites
    the datablock from it on exit - so pressing Reset while editing did
    nothing at all, neither immediately nor after leaving. Edit mode is
    precisely where a user reaches for this button.

    Ground truth is each point's own rest `co`, which the operator never
    computes - the reset state is `co_deform == co` by definition of the
    lattice, not by anything in the product code.
    """
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    lattice = next(c for c in root.children if c.type == "LATTICE")

    for p in lattice.data.points:
        p.co_deform = (p.co[0], p.co[1], p.co[2] + 0.5)

    H.select_only(root)
    try:
        result = bpy.ops.proteinblender.membrane_edit_deform()
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest, f"headless context could not enter Lattice edit mode "
                    f"(result={result}, mode={bpy.context.mode})")

    assert bpy.ops.proteinblender.membrane_reset_deform() == {'FINISHED'}
    bpy.ops.proteinblender.membrane_finish_deform()

    for p in lattice.data.points:
        assert tuple(p.co_deform) == pytest.approx(tuple(p.co)), (
            "Reset Deformation pressed inside edit mode did not stick")


@pytest.mark.integration
def test_reset_deform_clears_lattice_keyframes(scene):
    """Reset Deformation must also drop the deformation's keyframes.

    Regression: on an animated lattice the reset wrote the rest positions and
    the F-curves immediately re-asserted the animated value on the next
    depsgraph evaluation - so the membrane snapped back the moment the frame
    changed and the button appeared to do nothing. Harmless while lattices
    were static; a lie once lattices became the way membranes are animated.

    Object-level animation on the lattice is a separate datablock and must
    survive, so this also asserts what is *not* cleared.
    """
    names = H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _membrane_root(names)
    lattice = next(c for c in root.children if c.type == "LATTICE")

    _bulge_lattice(lattice, 0.0, 1)
    _bulge_lattice(lattice, 0.5, 20)
    # Object-level animation, which Reset must leave alone.
    lattice.location = (0.0, 0.0, 0.0)
    lattice.keyframe_insert("location", frame=1)

    bpy.context.scene.frame_set(20)
    moved = [tuple(p.co_deform) for p in lattice.data.points]
    rest = [tuple(p.co) for p in lattice.data.points]
    assert moved != rest, "test setup: the lattice was never actually deformed"

    H.select_only(root)
    assert bpy.ops.proteinblender.membrane_reset_deform() == {'FINISHED'}

    # The real check: survive a frame evaluation, which is what used to undo it.
    bpy.context.scene.frame_set(20)
    for p in lattice.data.points:
        assert tuple(p.co_deform) == pytest.approx(tuple(p.co)), (
            "the lattice keyframes re-asserted the deformation after Reset")

    assert lattice.animation_data is not None \
        and lattice.animation_data.action is not None, (
            "Reset cleared the lattice OBJECT's animation, which it does not own")


@pytest.mark.integration
def test_esc_and_enter_leave_deform_mode(scene):
    """Esc / Enter must exit deformation mode, and nothing else may be eaten.

    Reported: "there isn't an easy way to go back to the regular editing (it
    stays in the deform edit mode)". Edit Deformation now stays resident as a
    modal operator so it can own an exit key without registering a global
    keymap item that would hijack Esc for every lattice in the file.

    The exit key is the easy half. The half that breaks the feature is
    swallowing keys normal lattice editing needs, so this pins down the whole
    decision table - every non-exit event must pass straight through.
    """
    from proteinblender.membrane_builder.membrane_operators import (
        deform_modal_step,
    )

    names = H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root = _membrane_root(names)
    H.select_only(root)

    # Outside deform mode the modal must never act.
    assert deform_modal_step(bpy.context, "ESC", "PRESS") == "stand_down"

    try:
        result = bpy.ops.proteinblender.membrane_edit_deform()
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest, f"headless context could not enter Lattice edit mode "
                    f"(result={result}, mode={bpy.context.mode})")

    for key in ("ESC", "RET", "NUMPAD_ENTER"):
        assert deform_modal_step(bpy.context, key, "PRESS") == "finish", (
            f"{key} does not leave deformation mode")

    # The editing keys a user actually needs, plus mouse traffic. If any of
    # these stop passing through, deform mode becomes unusable.
    for key in ("G", "S", "R", "X", "A", "B", "Z", "TAB", "I",
                "LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE", "MOUSEMOVE",
                "WHEELUPMOUSE", "LEFT_CTRL", "ONE"):
        assert deform_modal_step(bpy.context, key, "PRESS") == "pass", (
            f"the deform modal is swallowing {key}, which normal lattice "
            "editing needs")

    # Key releases must not fire a second exit.
    for key in ("ESC", "RET"):
        assert deform_modal_step(bpy.context, key, "RELEASE") == "pass"

    # And the exit itself works end to end.
    assert bpy.ops.proteinblender.membrane_finish_deform() == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT'
    assert deform_modal_step(bpy.context, "ESC", "PRESS") == "stand_down"


@pytest.mark.integration
def test_outliner_toggle_enters_and_leaves_deform_mode(scene):
    """One Outliner button must both enter and leave deformation mode.

    Reported: "when I click Edit Deformation on the popup then Okay it doesn't
    let me edit, it takes me out of that mode". The dialog's OK calls
    ensure_object_mode(), so launching a *mode* from a transient popup tore it
    straight back down - the lattice could only be reached by dismissing the
    dialog rather than confirming it. The entry point is now a toggle on the
    PB Outliner row, which stays on screen, so in and out are one control.
    """
    from proteinblender.membrane_builder.membrane_operators import (
        is_deforming_membrane,
    )

    names = H.build_membrane(shape=SHAPE_FLAT, width=10.0, height=10.0)
    root = _membrane_root(names)
    assert root is not None
    H.select_only(root)

    assert not is_deforming_membrane(bpy.context, root.name)

    try:
        result = bpy.ops.proteinblender.membrane_toggle_deform(
            membrane_name=root.name)
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest, f"headless context could not enter Lattice edit mode "
                    f"(result={result}, mode={bpy.context.mode})")

    assert is_deforming_membrane(bpy.context, root.name), (
        "the toggle entered edit mode but the row does not read as active")

    # The same button again must come back out.
    assert bpy.ops.proteinblender.membrane_toggle_deform(
        membrane_name=root.name) == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT', "the toggle did not leave deform mode"
    assert not is_deforming_membrane(bpy.context, root.name)


@pytest.mark.integration
def test_deform_toggle_is_per_membrane(scene):
    """Only the membrane actually being deformed may read as active.

    The Outliner draws a toggle on every membrane row, so a global "are we in
    lattice edit mode" check would light up all of them and let the wrong row
    claim to be the one open.
    """
    from proteinblender.membrane_builder.membrane_operators import (
        is_deforming_membrane,
    )

    first = _membrane_root(H.build_membrane(shape=SHAPE_FLAT, width=10.0,
                                            height=10.0))
    second = _membrane_root(H.build_membrane(shape=SHAPE_FLAT, width=8.0,
                                             height=8.0))
    assert first is not None and second is not None and first != second

    try:
        result = bpy.ops.proteinblender.membrane_toggle_deform(
            membrane_name=first.name)
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"needs an interactive context: {e}")
    if result != {'FINISHED'} or bpy.context.mode != 'EDIT_LATTICE':
        HC.context_unavailable(
            pytest, f"headless context could not enter Lattice edit mode "
                    f"(result={result}, mode={bpy.context.mode})")

    assert is_deforming_membrane(bpy.context, first.name)
    assert not is_deforming_membrane(bpy.context, second.name), (
        "the other membrane's row also reads as being deformed")

    # Toggling the second one must hand the mode over, not stack two.
    assert bpy.ops.proteinblender.membrane_toggle_deform(
        membrane_name=second.name) == {'FINISHED'}
    assert is_deforming_membrane(bpy.context, second.name)
    assert not is_deforming_membrane(bpy.context, first.name)
