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


@pytest.mark.integration
def test_hole_operators_work_from_lattice_edit_mode(scene):
    """Add / select / remove hole must work while the deformer is in edit mode.

    Regression: the three hole operators end by calling
    ``bpy.ops.object.select_all``, which does not poll outside Object mode -
    and ``membrane_edit_deform`` parks the user in Lattice edit mode by design.
    ``build_membrane`` and the importers got ``ensure_object_mode`` when this
    was fixed for the builders; these three were missed.

    Add Hole was the worst of them: it created the hole, linked it, and rebuilt
    the GN assignments, and only THEN hit select_all and raised. The user saw a
    red error and reasonably concluded nothing happened, while a hole silently
    existed in the scene - a half-completed operator rather than a clean failure.

    Ground truth is the hole count this test tracks itself, plus whether the
    controller object exists in ``bpy.data`` - neither derived from the
    operators' own return values.
    """
    H.build_membrane(shape=SHAPE_FLAT, width=20.0, height=20.0)
    root = _only_membrane()
    H.select_only(root)

    # One hole to act on, created from Object mode where this always worked.
    assert bpy.ops.proteinblender.membrane_add_hole() == {'FINISHED'}
    first = _hole_children(root)[0]
    first_name = first.name
    assert _hole_count(root) == 1

    def _enter_edit_mode():
        """Re-select the membrane and open the deformer. Returns True if the
        headless context managed to get into Lattice edit mode."""
        H.select_only(root)
        try:
            res = bpy.ops.proteinblender.membrane_edit_deform()
        except RuntimeError:
            return False
        return res == {'FINISHED'} and bpy.context.mode == 'EDIT_LATTICE'

    if not _enter_edit_mode():
        HC.context_unavailable(
            pytest, "headless context could not enter Lattice edit mode")

    # --- Add a second hole from edit mode -------------------------------
    assert bpy.ops.proteinblender.membrane_add_hole() == {'FINISHED'}, \
        "add_hole failed from Lattice edit mode"
    assert _hole_count(root) == 2, (
        f"expected 2 holes after adding from edit mode, got {_hole_count(root)}")

    # --- Select a hole from edit mode -----------------------------------
    assert _enter_edit_mode()
    assert bpy.ops.proteinblender.membrane_select_hole(
        hole_name=first_name) == {'FINISHED'}, \
        "select_hole failed from Lattice edit mode"
    assert bpy.context.view_layer.objects.active.name == first_name
    assert bpy.data.objects[first_name].select_get()

    # --- Remove a hole from edit mode -----------------------------------
    assert _enter_edit_mode()
    assert bpy.ops.proteinblender.membrane_remove_hole(
        hole_name=first_name) == {'FINISHED'}, \
        "remove_hole failed from Lattice edit mode"
    assert bpy.data.objects.get(first_name) is None, \
        "the hole controller object survived removal"
    assert _hole_count(root) == 1
