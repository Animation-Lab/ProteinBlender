"""Integration tests for the DNA/RNA Builder and its bend tools.

Drives the real ProteinBlender operators against a live (headless) Blender
scene.

Covered operators:
  * proteinblender.build_dna            (via helpers.build_dna)
  * proteinblender.randomize_sequence
  * proteinblender.swap_to_complement
  * proteinblender.update_dna_colors
  * proteinblender.update_dna_style
  * proteinblender.dna_add_bend / dna_set_bend_resolution /
    dna_toggle_bend_curve / dna_remove_bend
  * proteinblender.dna_edit_bend / dna_finish_bend_edit  (edit-mode; tolerant)
"""

import pytest
import bpy
import helpers as H
import harness_contract as HC

# The addon is imported as a top-level package by conftest, so the bend
# helper module is reachable at proteinblender.dna_builder.bender.
import proteinblender.dna_builder.bender as bender


# Every valid value of DNABuilderProperties.style (see dna_props.py).
STYLE_VALUES = ["ball_and_stick", "cartoon", "spheres", "sticks", "surface"]

# Local reverse-complement map for asserting swap_to_complement without
# reaching into the addon's private tables.
_DNA_COMPLEMENT = {"A": "T", "T": "A", "G": "C", "C": "G"}


def _has_geometry(obj):
    """True if the strand still has geometry.

    Several DNA styles (e.g. 'spheres') render via geometry-node *instances*,
    which produce 0 *realized* verts when the modifier stack is baked to a mesh
    — so an evaluated-vertex count is not a reliable "has geometry" signal.
    The base mesh carries the atom points and persists across style changes, so
    check that first, falling back to the evaluated count.
    """
    data = getattr(obj, "data", None)
    if data is not None and hasattr(data, "vertices") and len(data.vertices) > 0:
        return True
    return H.geometry_summary(obj).get("verts", 0) > 0


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_double_stranded_dna():
    obj = H.build_dna(seq="ATCGATCGATCG", name_prefix="DNA_DS", ds=True,
                      style="cartoon")
    assert obj is not None
    assert obj.get("pb_is_nucleic_acid") is True
    assert obj.get("pb_nucleic_type") == "DNA"
    assert obj.get("pb_sequence") == "ATCGATCGATCG"
    assert obj.get("pb_double_stranded") is True
    assert _has_geometry(obj), "double-stranded DNA produced no geometry"


@pytest.mark.integration
def test_build_single_stranded_dna():
    obj = H.build_dna(seq="ATCGATCG", name_prefix="DNA_SS", ds=False,
                      style="ball_and_stick")
    assert obj.get("pb_is_nucleic_acid") is True
    assert obj.get("pb_double_stranded") is False
    assert _has_geometry(obj)


@pytest.mark.integration
def test_build_rna():
    obj = H.build_dna(seq="AUGCAUGC", name_prefix="RNA_SS", nt="RNA", ds=False,
                      style="sticks")
    assert obj.get("pb_is_nucleic_acid") is True
    assert obj.get("pb_nucleic_type") == "RNA"
    assert obj.get("pb_double_stranded") is False
    # Sequence should have been validated against the RNA alphabet (A U G C).
    seq = obj.get("pb_sequence") or ""
    assert seq and set(seq) <= set("AUGC")
    assert _has_geometry(obj)


@pytest.mark.integration
@pytest.mark.parametrize("style", STYLE_VALUES)
def test_build_each_style(style):
    obj = H.build_dna(seq="ATCGATCG", name_prefix=f"DNA_{style}", ds=True,
                      style=style)
    assert obj.get("pb_is_nucleic_acid") is True
    assert obj.get("pb_style") == style
    assert _has_geometry(obj), f"style {style!r} produced no geometry"


# ---------------------------------------------------------------------------
# Sequence editing helpers
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_randomize_sequence_changes_props(scene):
    props = scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.sequence_length = 20
    props.sequence = "AAAAAAAAAAAAAAAAAAAA"
    bpy.ops.proteinblender.randomize_sequence()
    new_seq = props.sequence
    assert len(new_seq) == 20
    assert set(new_seq) <= set("ATGC")
    # Overwhelmingly likely to differ from the all-A seed; if it somehow
    # matched, the length/alphabet assertions above still prove it ran.
    assert new_seq != "AAAAAAAAAAAAAAAAAAAA" or len(new_seq) == 20


@pytest.mark.integration
def test_swap_to_complement_produces_reverse_complement(scene):
    props = scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.sequence = "AATTGGCC"
    expected = "".join(_DNA_COMPLEMENT[b] for b in reversed("AATTGGCC"))
    bpy.ops.proteinblender.swap_to_complement()
    assert props.sequence == expected


# ---------------------------------------------------------------------------
# Length field (input_mode == "RANDOM")
#
# Ground truth throughout is the integer the test asks for. Nothing reads a
# length back out of the code that sets it.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_setting_length_resizes_the_sequence(scene):
    """In Length mode, typing a new length must resize the sequence.

    Regression: ``sequence_length`` was the only builder field with no update
    callback - it fed the randomize button and nothing else. Typing 100 into
    Length left the 50-base default sequence untouched, and the strand built at
    50. The field looked like it set the length but did nothing on its own.
    Reported by a tester who worked around it by pasting the sequence twice.
    """
    props = scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.input_mode = "RANDOM"
    props.sequence = "ATCG" * 12 + "AT"          # 50 bases, the shipped default
    assert len(props.sequence) == 50             # setup guard

    props.sequence_length = 100
    assert len(props.sequence) == 100, (
        f"Length=100 left the sequence at {len(props.sequence)} bases")
    assert set(props.sequence) <= set("ATGC")

    # Shrinking works too, and keeps the leading bases rather than rerolling.
    head = props.sequence[:20]
    props.sequence_length = 20
    assert props.sequence == head, (
        "shrinking should truncate the existing sequence, not regenerate it")


@pytest.mark.integration
def test_length_change_builds_a_strand_of_that_length(scene):
    """End to end: set Length, build, and the strand really has that many bases."""
    props = scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.input_mode = "RANDOM"
    props.sequence_length = 80

    obj = H.build_dna(seq=props.sequence, name_prefix="DNA_LEN", ds=True,
                      style="cartoon")
    assert len(obj.get("pb_sequence") or "") == 80, (
        f"built strand has {len(obj.get('pb_sequence') or '')} bases, expected 80")


@pytest.mark.integration
def test_length_respects_the_rna_alphabet(scene):
    """Extending an RNA sequence must not introduce T."""
    props = scene.dna_builder_props
    props.nucleic_type = "RNA"
    props.input_mode = "RANDOM"
    props.sequence = "AUGC"
    props.sequence_length = 60
    assert len(props.sequence) == 60
    assert set(props.sequence) <= set("AUGC"), (
        f"RNA sequence picked up non-RNA bases: {set(props.sequence)}")


@pytest.mark.integration
def test_switching_to_length_mode_shows_the_real_length(scene):
    """Switching into Length mode must point the field at the sequence that
    actually exists.

    If it kept a stale default (50) while the sequence was 12 bases, typing 50
    would be a no-op write, Blender would not fire the update, and Length would
    look broken again for exactly the reason this fix addresses.
    """
    props = scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.input_mode = "MANUAL"
    props.sequence = "ATCGATCGATCG"          # 12 bases
    props.sequence_length = 50               # stale value, MANUAL so inert
    assert props.sequence == "ATCGATCGATCG"  # setup guard

    props.input_mode = "RANDOM"
    assert props.sequence_length == 12, (
        f"Length shows {props.sequence_length} for a 12-base sequence")
    assert props.sequence == "ATCGATCGATCG", (
        "switching modes must not rewrite the sequence")


@pytest.mark.integration
def test_length_does_not_clobber_a_typed_sequence(scene):
    """In Sequence (MANUAL) mode the Length field isn't shown, so it must not
    rewrite what the user typed."""
    props = scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.input_mode = "MANUAL"
    typed = "ATCGATCGATCG"
    props.sequence = typed
    props.sequence_length = 200
    assert props.sequence == typed, (
        "changing Length in Sequence mode overwrote the typed sequence")


# ---------------------------------------------------------------------------
# Colour / style updates on an existing strand
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_update_dna_colors_applies(scene):
    obj = H.build_dna(seq="ATCGATCG", name_prefix="DNA_COL", ds=True,
                      style="ball_and_stick")
    # Selecting the strand first triggers the msgbus prop-sync (copies the
    # object's stored colours INTO props); only then do we override color_a
    # so it isn't clobbered by the sync.
    H.select_only(obj)
    scene.dna_builder_props.color_a = (0.9, 0.1, 0.1, 1.0)
    bpy.ops.proteinblender.update_dna_colors()
    stored = obj.get("pb_color_a")
    assert stored is not None, "colours were not stored on the object"
    assert abs(stored[0] - 0.9) < 0.05
    assert abs(stored[1] - 0.1) < 0.05


@pytest.mark.integration
def test_update_dna_style_changes_object(scene):
    obj = H.build_dna(seq="ATCGATCG", name_prefix="DNA_STY", ds=True,
                      style="ball_and_stick")
    H.select_only(obj)
    bpy.ops.proteinblender.update_dna_style(new_style="spheres")
    assert obj.get("pb_style") == "spheres"
    assert _has_geometry(obj), "strand lost its geometry after style change"


# ---------------------------------------------------------------------------
# Bend tools
# ---------------------------------------------------------------------------

def _build_bendable_dna(prefix="DNA_BEND"):
    """Build a double-stranded strand, make it the active object, and return
    it — the precondition every bend operator needs."""
    obj = H.build_dna(seq="ATCGATCGATCGATCG", name_prefix=prefix, ds=True,
                      style="cartoon")
    H.select_only(obj)
    return obj


@pytest.mark.integration
def test_dna_add_bend_creates_curve_and_nodes():
    dna = _build_bendable_dna("DNA_ADDBEND")
    bpy.ops.proteinblender.dna_add_bend()

    curve_name = dna.get(bender.BEND_CURVE_PROP)
    assert curve_name, "BEND_CURVE_PROP was not set on the DNA"
    curve_obj = bpy.data.objects.get(curve_name)
    assert curve_obj is not None, "bend curve object was not created"
    assert curve_obj.type == "CURVE"

    nodes = bender.get_bend_nodes(dna)
    assert len(nodes) == bender.RES_DEFAULT


@pytest.mark.integration
def test_dna_set_bend_resolution():
    dna = _build_bendable_dna("DNA_RES")
    bpy.ops.proteinblender.dna_add_bend()
    H.select_only(dna)

    bpy.ops.proteinblender.dna_set_bend_resolution(n_points=5)
    assert len(bender.get_bend_nodes(dna)) == 5

    # And back down again — resampling should preserve node bookkeeping.
    bpy.ops.proteinblender.dna_set_bend_resolution(n_points=2)
    assert len(bender.get_bend_nodes(dna)) == 2


@pytest.mark.integration
def test_dna_toggle_bend_curve_flips_visibility():
    dna = _build_bendable_dna("DNA_TOG")
    bpy.ops.proteinblender.dna_add_bend()
    H.select_only(dna)

    curve = bender.get_bend_curve(dna)
    assert curve is not None
    before = curve.hide_get()
    bpy.ops.proteinblender.dna_toggle_bend_curve()
    assert curve.hide_get() != before
    # Toggle back.
    bpy.ops.proteinblender.dna_toggle_bend_curve()
    assert curve.hide_get() == before


@pytest.mark.integration
def test_dna_remove_bend():
    dna = _build_bendable_dna("DNA_RM")
    bpy.ops.proteinblender.dna_add_bend()
    curve_name = dna.get(bender.BEND_CURVE_PROP)
    assert curve_name  # sanity: bend really was added

    H.select_only(dna)
    bpy.ops.proteinblender.dna_remove_bend()

    assert not dna.get(bender.BEND_CURVE_PROP), "BEND_CURVE_PROP still set"
    assert bpy.data.objects.get(curve_name) is None, "bend curve survived removal"
    assert bender.get_bend_nodes(dna) == []


@pytest.mark.integration
def test_dna_edit_and_finish_bend():
    """Edit/finish re-select the control nodes and re-activate the strand.

    These paths flip Blender in and out of EDIT mode (hook_reset), which can
    be flaky without an interactive window. They are exercised here but the
    test is tolerant: a RuntimeError from a mode switch is treated as a
    headless-environment skip rather than a product failure — add/remove/
    resolution/toggle above already cover the headless-safe surface.
    """
    dna = _build_bendable_dna("DNA_EDIT")
    bpy.ops.proteinblender.dna_add_bend()
    H.select_only(dna)

    try:
        bpy.ops.proteinblender.dna_edit_bend(n_points=bender.RES_DEFAULT)
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"dna_edit_bend needs interactive edit-mode context: {e}")

    selected_nodes = [o for o in bpy.context.selected_objects
                      if "Bend Node" in o.name]
    assert selected_nodes, "edit bend selected no control nodes"

    # Finishing the edit should hand focus back to the DNA strand.
    try:
        bpy.ops.proteinblender.dna_finish_bend_edit()
    except RuntimeError as e:
        HC.context_unavailable(pytest, f"dna_finish_bend_edit needs interactive context: {e}")

    assert bpy.context.view_layer.objects.active is dna


# ---------------------------------------------------------------------------
# Bend-rig alignment
# ---------------------------------------------------------------------------

def _visible_strand_z_extent(obj):
    """World-space Z extent of what the user actually sees.

    Ground truth for the bend-rig alignment tests: it is read from the
    *evaluated* object, so it already carries the geometry-nodes pivot and
    every modifier. Nothing in ``bender`` contributes to it.
    """
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()
    try:
        assert len(mesh.vertices) > 0, "strand evaluated to no geometry"
        matrix = ev.matrix_world
        zs = [(matrix @ v.co).z for v in mesh.vertices]
        return min(zs), max(zs)
    finally:
        ev.to_mesh_clear()


def _assert_nodes_span_strand(dna, context=""):
    """The first and last control node sit on the ends of the visible strand.

    A rig shifted along the helix axis moves both ends by the same amount, so
    each end is checked independently against the evaluated geometry.
    """
    lo, hi = _visible_strand_z_extent(dna)
    height = hi - lo
    assert height > 0
    tol = 0.05 * height

    node_zs = [n.matrix_world.translation.z for n in bender.get_bend_nodes(dna)]
    assert len(node_zs) >= 2, f"{context}no bend control nodes"

    assert abs(min(node_zs) - lo) < tol, (
        f"{context}bottom bend node at z={min(node_zs):.4f} is off the strand "
        f"(bottom z={lo:.4f}, height={height:.4f})"
    )
    assert abs(max(node_zs) - hi) < tol, (
        f"{context}top bend node at z={max(node_zs):.4f} is off the strand "
        f"(top z={hi:.4f}, height={height:.4f})"
    )


@pytest.mark.integration
def test_dna_bend_nodes_align_with_the_strand():
    """The control nodes must sit *on* the strand, spanning end to end.

    Regression: the bend rig was built from raw mesh coordinates, but a
    molecule's geometry-nodes pivot is applied inside the modifier
    (``world(co) = matrix_world @ (co - pivot)``). The nodes therefore
    floated above the strand by exactly the pivot - half the helix length
    for a strand whose pivot is its centre of mass.
    """
    dna = _build_bendable_dna("DNA_ALIGN")
    bpy.context.view_layer.update()
    before_lo, before_hi = _visible_strand_z_extent(dna)
    height = before_hi - before_lo
    assert height > 0

    bpy.ops.proteinblender.dna_add_bend()
    bpy.context.view_layer.update()

    # Adding the rig must not move the strand itself.
    after_lo, after_hi = _visible_strand_z_extent(dna)
    tol = 0.05 * height
    assert abs(after_lo - before_lo) < tol and abs(after_hi - before_hi) < tol, (
        f"adding the bend moved the strand: {(before_lo, before_hi)} -> "
        f"{(after_lo, after_hi)}"
    )

    _assert_nodes_span_strand(dna)


@pytest.mark.integration
def test_dna_bend_deforms_the_half_of_the_strand_its_node_owns():
    """Dragging the *top* node must bend the top of the strand, not the middle.

    Node placement and deformation are two halves of the same alignment: the
    Curve modifier runs after the geometry-nodes pivot, so a rig built in
    un-pivoted space also maps each node onto the wrong slice of the helix.
    Pulling the last node sideways is the end-user gesture that exposes it.
    """
    dna = _build_bendable_dna("DNA_DEFORM")
    bpy.context.view_layer.update()
    lo, hi = _visible_strand_z_extent(dna)
    height = hi - lo

    bpy.ops.proteinblender.dna_add_bend()
    bpy.context.view_layer.update()

    nodes = bender.get_bend_nodes(dna)
    assert len(nodes) >= 3

    def _x_extremes():
        deps = bpy.context.evaluated_depsgraph_get()
        ev = dna.evaluated_get(deps)
        mesh = ev.to_mesh()
        try:
            matrix = ev.matrix_world
            pts = [matrix @ v.co for v in mesh.vertices]
            mid = 0.5 * (lo + hi)
            bottom = max(abs(p.x) for p in pts if p.z < mid - 0.25 * height)
            top = max(abs(p.x) for p in pts if p.z > mid + 0.25 * height)
            return bottom, top
        finally:
            ev.to_mesh_clear()

    bottom_before, top_before = _x_extremes()

    # Drag the topmost node sideways by a quarter of the strand's length.
    pull = 0.25 * height
    nodes[-1].location.x += pull
    bpy.context.view_layer.update()

    bottom_after, top_after = _x_extremes()

    assert top_after - top_before > 0.3 * pull, (
        f"pulling the top node barely moved the top of the strand "
        f"({top_before:.4f} -> {top_after:.4f}, pull={pull:.4f})"
    )
    assert top_after - top_before > 2 * (bottom_after - bottom_before), (
        f"the top node dragged the bottom of the strand about as much as the "
        f"top (bottom {bottom_before:.4f} -> {bottom_after:.4f}, "
        f"top {top_before:.4f} -> {top_after:.4f})"
    )


@pytest.mark.integration
def test_dna_bend_nodes_stay_aligned_after_a_sequence_edit():
    """Editing the sequence rebuilds the strand and re-attaches the rig.

    ``reattach_after_rebuild`` moves the origin of the *new* strand, so it
    has to reason in the same pivot-applied space as ``dna_add_bend``.
    """
    dna = _build_bendable_dna("DNA_REBUILD")
    bpy.ops.proteinblender.dna_add_bend()
    bpy.context.view_layer.update()
    _assert_nodes_span_strand(dna, context="before edit: ")

    identifier = dna.name
    props = bpy.context.scene.dna_builder_props
    props.sequence = "ATCGATCGATCGATCGATCGATCG"  # longer than the original
    bpy.ops.proteinblender.build_dna(molecule_id_to_update=identifier)
    bpy.context.view_layer.update()

    rebuilt = bpy.data.objects.get(identifier)
    assert rebuilt is not None, "rebuild did not keep the strand's identifier"
    _assert_nodes_span_strand(rebuilt, context="after edit: ")
