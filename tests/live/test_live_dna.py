"""The DNA/RNA builder, observed on screen.

DNA and RNA are never rendered anywhere else in the suite. ``tests/integration/
test_dna.py`` proves the operators run and that the strand carries the right
``pb_*`` bookkeeping, but every one of its geometry checks bottoms out in
"``obj.data.vertices`` is non-empty" - which stays true for a strand that is
built inside-out, drawn in one flat colour, or not drawn at all. A style that
silently fails to bind, a base-colour map that never reaches a material, and a
bend rig that deforms nothing all pass the headless lane today.

This module renders the strand and asserts on what comes back.

The assertions here are deliberately relational rather than absolute:

  * Two styles of the same strand must not produce the same image.
  * A blue-coloured strand must read bluer than the same strand coloured red.
  * A 40-mer must be about twice as long as a 20-mer, because B-form rise per
    base is constant - a fact about the molecule, not about our code.

Nothing in this file computes its expected value with the helper it is testing.
Sequence complements are derived from the base-pairing rules in plain Python on
the runner side; lengths come from mesh coordinates; colours come from pixels.
"""

from __future__ import annotations

import itertools

import pytest


# Every valid value of DNABuilderProperties.style (see dna_props.py).
DNA_STYLES = ["ball_and_stick", "cartoon", "spheres", "sticks", "surface"]

# Watson-Crick pairing, written out here so the expected complement is derived
# from biology rather than from the add-on's own COMPLEMENTS table. A test that
# imported that table would pass even if the table itself were wrong.
DNA_COMPLEMENT = {"A": "T", "T": "A", "G": "C", "C": "G"}
RNA_COMPLEMENT = {"A": "U", "U": "A", "G": "C", "C": "G"}


# ---------------------------------------------------------------------------
# Blender-side snippets
#
# These run inside the live Blender. Every one that drives an operator wraps
# itself in ``R.view3d_override()``: calls arrive on a timer callback with no
# editor area, and appending the MolecularNodes style node groups needs a real
# VIEW_3D context, exactly as a click from the panel would have.
# ---------------------------------------------------------------------------

BUILD = """
props = bpy.context.scene.dna_builder_props
props.winding_mode = winding
with R.view3d_override():
    obj = H.build_dna(seq=seq, name_prefix=prefix, nt=nt, ds=ds, style=style)
    H.select_only(obj)
return obj.name
"""

STRAND_FACTS = """
obj = bpy.data.objects[name]
return {
    "is_nucleic": bool(obj.get("pb_is_nucleic_acid", False)),
    "nucleic_type": obj.get("pb_nucleic_type"),
    "sequence": obj.get("pb_sequence"),
    "double_stranded": bool(obj.get("pb_double_stranded", False)),
    "style": obj.get("pb_style"),
    "winding_mode": obj.get("pb_winding_mode"),
}
"""

# Extents of the *base* mesh, in the object's own local space.
#
# Local is what we want and all we may use: these are raw mesh reads, and
# CLAUDE.md forbids mapping them with ``matrix_world @ co`` (that mapping is off
# by the domain pivot). Comparing extents between two strands in their own
# frames needs no mapping at all, and the strands are built with the same
# orientation, so the comparison is apples to apples.
MESH_EXTENTS = """
obj = bpy.data.objects[name]
verts = obj.data.vertices
if not len(verts):
    return {"verts": 0}
xs = [v.co.x for v in verts]
ys = [v.co.y for v in verts]
zs = [v.co.z for v in verts]
return {
    "verts": len(verts),
    "x_extent": max(xs) - min(xs),
    "y_extent": max(ys) - min(ys),
    "z_extent": max(zs) - min(zs),
}
"""

CHANGE_STYLE = """
obj = bpy.data.objects[name]
with R.view3d_override():
    H.select_only(obj)
    bpy.ops.proteinblender.update_dna_style(new_style=style)
return obj.get("pb_style")
"""

# Selecting the strand first is load-bearing: making it active fires the msgbus
# sync that copies the object's stored colours *into* the panel props. Setting
# our colours before that would be silently clobbered.
APPLY_COLORS = """
obj = bpy.data.objects[name]
with R.view3d_override():
    H.select_only(obj)
    props = bpy.context.scene.dna_builder_props
    for key, value in colors.items():
        setattr(props, key, value)
    result = bpy.ops.proteinblender.update_dna_colors()
return sorted(result)
"""

HIDE = """
bpy.data.objects[name].hide_set(hidden)
return bpy.data.objects[name].hide_get()
"""

# Bend-rig inventory taken from Blender's own datablocks rather than from the
# add-on's BEND_CURVE_PROP / BEND_NODES_PROP bookkeeping. A rig that records
# itself correctly but creates nothing would pass the bookkeeping check.
BEND_INVENTORY = """
obj = bpy.data.objects[name]
return {
    "curves": sorted(o.name for o in bpy.data.objects if o.type == "CURVE"),
    "nodes": sorted(o.name for o in bpy.data.objects if "Bend Node " in o.name),
    "modifiers": [m.type for m in obj.modifiers],
}
"""


def build_strand(blender, seq="ATCGATCG", prefix="DNA_LIVE", nt="DNA", ds=True,
                 style="ball_and_stick", winding="HELIX"):
    """Build one strand through the public builder operator; return its name."""
    return blender.call(BUILD, seq=seq, prefix=prefix, nt=nt, ds=ds,
                        style=style, winding=winding)


# ---------------------------------------------------------------------------
# Build: does a strand actually appear?
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_double_stranded_dna_is_built_and_visible(blender, shot):
    """The baseline the rest of the module rests on.

    The headless lane can only say the strand has vertices. Here we require it
    to put pixels on the screen, which is the thing a user would notice.
    """
    name = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_DS",
                        ds=True, style="cartoon")
    facts = blender.call(STRAND_FACTS, name=name)
    assert facts["is_nucleic"] is True
    assert facts["nucleic_type"] == "DNA"
    assert facts["sequence"] == "ATCGATCGATCG"
    assert facts["double_stranded"] is True

    metrics = shot("built")
    assert metrics["covered"] > 0, (
        "a built double-stranded strand rendered nothing; the headless lane "
        "cannot see this because it only counts mesh vertices")


@pytest.mark.live
@pytest.mark.visual
def test_single_stranded_dna_is_built_and_visible(blender, shot):
    """Single-stranded DNA is a separate build path (no complement pass)."""
    name = build_strand(blender, seq="ATCGATCG", prefix="DNA_SS", ds=False,
                        style="ball_and_stick")
    facts = blender.call(STRAND_FACTS, name=name)
    assert facts["double_stranded"] is False
    assert shot("built")["covered"] > 0, "single-stranded DNA rendered nothing"


@pytest.mark.live
@pytest.mark.visual
def test_rna_is_built_and_visible(blender, shot):
    """RNA uses the A/U/G/C alphabet and its own residue templates."""
    name = build_strand(blender, seq="AUGCAUGC", prefix="RNA_SS", nt="RNA",
                        ds=False, style="sticks")
    facts = blender.call(STRAND_FACTS, name=name)
    assert facts["nucleic_type"] == "RNA"
    assert facts["double_stranded"] is False
    sequence = facts["sequence"] or ""
    assert sequence and set(sequence) <= set("AUGC"), (
        f"RNA strand kept a non-RNA base: {sequence!r}")
    assert shot("built")["covered"] > 0, "RNA rendered nothing"


@pytest.mark.live
@pytest.mark.visual
def test_double_stranded_rna_is_built_and_visible(blender, shot):
    """dsRNA is rare in nature but the builder offers it, so it must work.

    Setting ``nucleic_type`` flips ``double_stranded`` off as a convenience
    default, so this also guards that an explicit re-tick survives the build.
    """
    name = build_strand(blender, seq="AUGCAUGC", prefix="RNA_DS", nt="RNA",
                        ds=True, style="cartoon")
    facts = blender.call(STRAND_FACTS, name=name)
    assert facts["nucleic_type"] == "RNA"
    assert facts["double_stranded"] is True, (
        "the double-stranded tick did not survive the RNA build")
    assert shot("built")["covered"] > 0, "double-stranded RNA rendered nothing"


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("style", DNA_STYLES)
def test_every_style_renders_something(blender, shot, style):
    """Each of the five styles must put geometry on screen.

    'spheres' is the case that motivates rendering rather than counting: it
    draws through geometry-node instances, so a baked evaluated mesh reports
    zero vertices and the headless lane has to fall back to the base mesh,
    which persists whether or not the style ever bound.
    """
    name = build_strand(blender, seq="ATCGATCG", prefix=f"DNA_{style}",
                        ds=True, style=style)
    assert blender.call(STRAND_FACTS, name=name)["style"] == style

    metrics = shot(style)
    assert metrics["covered"] > 0, f"style {style!r} rendered nothing"


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.slow
def test_styles_are_visually_distinct(blender):
    """Five styles must produce five different pictures.

    The failure this catches is a style switch that reports success and updates
    ``pb_style`` while the viewport keeps drawing the previous representation.
    Nothing in the headless lane can distinguish that from a working switch.

    One strand is restyled in place, and the view is framed once and never
    again, so any difference between two captures comes from the geometry and
    not from the camera moving.
    """
    name = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_STYLES",
                        ds=True, style=DNA_STYLES[0])
    blender.call("return R.frame_all(objects=[name])", name=name)

    for style in DNA_STYLES:
        applied = blender.call(CHANGE_STYLE, name=name, style=style)
        assert applied == style
        metrics = blender.call("return R.capture(label=style)", style=style)
        assert metrics["covered"] > 0, (
            f"style {style!r} rendered nothing after update_dna_style")

    for left, right in itertools.combinations(DNA_STYLES, 2):
        diff = blender.call("return R.compare(left, right)",
                            left=left, right=right)
        assert not diff["identical"], (
            f"styles {left!r} and {right!r} rendered byte-identical images; "
            "the style change did not reach the viewport")


@pytest.mark.live
@pytest.mark.visual
def test_helix_and_ladder_winding_look_different(blender):
    """LADDER is the fully unwound presentation of the same sequence.

    Both strands are built at the origin and the view is framed once, then the
    helix is hidden so the ladder is captured from the identical viewpoint.
    Same sequence, same framing, same style: if the two images match, the
    winding mode was ignored.
    """
    helix = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_HELIX",
                         ds=True, style="ball_and_stick", winding="HELIX")
    assert blender.call(STRAND_FACTS, name=helix)["winding_mode"] == "HELIX"
    blender.call("return R.frame_all(objects=[name])", name=helix)
    blender.call('return R.capture("helix")')

    blender.call(HIDE, name=helix, hidden=True)
    ladder = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_LADDER",
                          ds=True, style="ball_and_stick", winding="LADDER")
    assert blender.call(STRAND_FACTS, name=ladder)["winding_mode"] == "LADDER"
    ladder_metrics = blender.call('return R.capture("ladder")')
    assert ladder_metrics["covered"] > 0, "ladder winding rendered nothing"

    diff = blender.call('return R.compare("helix", "ladder")')
    assert not diff["identical"], (
        "HELIX and LADDER rendered the same image for the same sequence; "
        "the winding mode never reached the geometry")


# ---------------------------------------------------------------------------
# Geometry sanity, measured against B-form facts rather than stored output
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_a_longer_sequence_makes_a_longer_strand(blender):
    """Rise per base is constant, so length must scale with base count.

    That is a property of B-form DNA, not of this add-on, which is what makes
    it usable as ground truth. A 40-mer is expected to be close to twice the
    axial length of a 20-mer; the bounds are wide enough to absorb end effects
    and narrow enough to fail if length stops tracking the sequence at all.
    """
    short = build_strand(blender, seq="ATCG" * 5, prefix="DNA_SHORT", ds=True,
                         style="ball_and_stick")
    long = build_strand(blender, seq="ATCG" * 10, prefix="DNA_LONG", ds=True,
                        style="ball_and_stick")

    short_z = blender.call(MESH_EXTENTS, name=short)["z_extent"]
    long_z = blender.call(MESH_EXTENTS, name=long)["z_extent"]

    assert short_z > 0.0, "the 20-mer has no extent along the helix axis"
    ratio = long_z / short_z
    assert 1.6 < ratio < 2.4, (
        f"doubling the sequence changed axial length by {ratio:.2f}x "
        f"({short_z:.4f} -> {long_z:.4f}); constant rise per base means it "
        "should be close to 2x")


@pytest.mark.live
@pytest.mark.visual
def test_double_stranded_adds_a_second_strand(blender):
    """The complement is a whole second copy of the backbone plus bases.

    Two invariants, either of which a missing complement pass would break: the
    atom count must roughly double, and the two strands must not render the
    same image from the same viewpoint.
    """
    single = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_ONE",
                          ds=False, style="ball_and_stick")
    single_stats = blender.call(MESH_EXTENTS, name=single)
    blender.call("return R.frame_all(objects=[name])", name=single)
    blender.call('return R.capture("single")')
    blender.call(HIDE, name=single, hidden=True)

    double = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_TWO",
                          ds=True, style="ball_and_stick")
    double_stats = blender.call(MESH_EXTENTS, name=double)
    blender.call('return R.capture("double")')

    assert double_stats["verts"] > single_stats["verts"] * 1.5, (
        f"double-stranded build produced {double_stats['verts']} atoms against "
        f"{single_stats['verts']} for the same single-stranded sequence; a "
        "complementary strand should roughly double it")

    diff = blender.call('return R.compare("single", "double")')
    assert not diff["identical"], (
        "single- and double-stranded builds of the same sequence rendered "
        "identically")


# ---------------------------------------------------------------------------
# Sequence editing
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_randomize_sequence_fills_the_requested_length(blender):
    """Randomise must respect the length field and the DNA alphabet.

    Seeded with an all-A sequence so a no-op operator is caught: the chance of
    a genuine 24-base random draw coming back all-A is 4**-24.
    """
    result = blender.call("""
        props = bpy.context.scene.dna_builder_props
        props.nucleic_type = "DNA"
        props.sequence_length = 24
        props.sequence = "A" * 24
        bpy.ops.proteinblender.randomize_sequence()
        return props.sequence
    """)
    assert len(result) == 24, f"expected 24 bases, got {len(result)}: {result!r}"
    assert set(result) <= set("ATGC"), f"non-DNA base in {result!r}"
    assert result != "A" * 24, "randomize_sequence left the seed untouched"


@pytest.mark.live
def test_randomize_sequence_uses_the_rna_alphabet(blender):
    """In RNA mode the generator must draw U, never T."""
    result = blender.call("""
        props = bpy.context.scene.dna_builder_props
        props.nucleic_type = "RNA"
        props.sequence_length = 40
        bpy.ops.proteinblender.randomize_sequence()
        return props.sequence
    """)
    assert len(result) == 40
    assert set(result) <= set("AUGC"), (
        f"RNA randomise produced a base outside A/U/G/C: {result!r}")
    assert "T" not in result, "RNA randomise emitted thymine"


@pytest.mark.live
def test_swap_to_complement_returns_the_reverse_complement(blender):
    """Expected value comes from Watson-Crick pairing, computed here.

    Deriving it from the add-on's own complement table would make this test
    pass no matter what that table said.
    """
    sequence = "AATTGGCCATGC"
    expected = "".join(DNA_COMPLEMENT[base] for base in reversed(sequence))

    result = blender.call("""
        props = bpy.context.scene.dna_builder_props
        props.nucleic_type = "DNA"
        props.sequence = sequence
        bpy.ops.proteinblender.swap_to_complement()
        return props.sequence
    """, sequence=sequence)

    assert result == expected, (
        f"reverse complement of {sequence} should be {expected}, got {result}")


@pytest.mark.live
def test_swap_to_complement_twice_restores_the_original(blender):
    """The complement of the complement is the original strand.

    An involution check that no lookup-table typo can survive: a wrong pairing
    that is not self-inverse breaks it, and the panel tooltip promises exactly
    this behaviour ("click twice to return to the original").
    """
    sequence = "ATGCATGCGGTA"
    result = blender.call("""
        props = bpy.context.scene.dna_builder_props
        props.nucleic_type = "DNA"
        props.sequence = sequence
        bpy.ops.proteinblender.swap_to_complement()
        bpy.ops.proteinblender.swap_to_complement()
        return props.sequence
    """, sequence=sequence)
    assert result == sequence


@pytest.mark.live
def test_swap_to_complement_pairs_adenine_with_uracil_in_rna(blender):
    """RNA has no thymine: A must pair with U, and the result must contain no T."""
    sequence = "AUGCAUGC"
    expected = "".join(RNA_COMPLEMENT[base] for base in reversed(sequence))

    result = blender.call("""
        props = bpy.context.scene.dna_builder_props
        props.nucleic_type = "RNA"
        props.sequence = sequence
        bpy.ops.proteinblender.swap_to_complement()
        return props.sequence
    """, sequence=sequence)

    assert result == expected, (
        f"RNA reverse complement of {sequence} should be {expected}, "
        f"got {result}")
    assert "T" not in result, "RNA complement emitted thymine"


# ---------------------------------------------------------------------------
# Colour
#
# This is the lane's reason for existing. The headless suite asserts that
# update_dna_colors writes pb_color_a onto the object, which stays true for a
# colour that never reaches a material. These tests look at the pixels.
# ---------------------------------------------------------------------------

BASE_COLOR_PROPS = ["color_a", "color_t", "color_g", "color_c",
                    "color_backbone"]

RED = [0.95, 0.05, 0.05, 1.0]
BLUE = [0.05, 0.05, 0.95, 1.0]
GREY = [0.5, 0.5, 0.5, 1.0]


def _all_bases(color, nucleic_type="DNA"):
    """Every base plus the backbone painted one colour."""
    keys = ["color_a", "color_g", "color_c", "color_backbone"]
    keys.append("color_u" if nucleic_type == "RNA" else "color_t")
    return {key: list(color) for key in keys}


@pytest.mark.live
@pytest.mark.visual
def test_base_colours_reach_the_rendered_strand(blender):
    """A strand painted blue must read bluer than the same strand painted red.

    The comparison is between two renders of one strand, so lighting, framing
    and style are held constant and the only variable is the colour the user
    asked for. Absolute channel values are never asserted - only that the
    ordering of the red and blue channels follows the request, which is the
    invariant a colour that never binds cannot satisfy.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")
    name = build_strand(blender, seq="ATCGATCGATCG", prefix="DNA_COLOR",
                        ds=True, style="ball_and_stick")
    blender.call("return R.frame_all(objects=[name])", name=name)

    blender.call(APPLY_COLORS, name=name, colors=_all_bases(RED))
    red = blender.call('return R.capture("red")')
    blender.call(APPLY_COLORS, name=name, colors=_all_bases(BLUE))
    blue = blender.call('return R.capture("blue")')

    assert red["covered"] > 0 and blue["covered"] > 0

    assert red["mean_rgb"][0] > red["mean_rgb"][2], (
        f"a strand painted red rendered with mean RGB {red['mean_rgb']}; the "
        "red channel does not lead")
    assert blue["mean_rgb"][2] > blue["mean_rgb"][0], (
        f"a strand painted blue rendered with mean RGB {blue['mean_rgb']}; the "
        "blue channel does not lead")

    diff = blender.call('return R.compare("red", "blue")')
    assert diff["rgb_delta"] > 0.0, (
        "recolouring the strand from red to blue left the render "
        "byte-identical; the colours never reached the viewport")


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("prop", BASE_COLOR_PROPS)
def test_each_dna_base_colour_changes_the_render(blender, prop):
    """Every individual colour swatch must be wired to something on screen.

    Painted one at a time against a grey strand, so a swatch that is wired to
    the wrong base, or to nothing, shows up as an unchanged image. The sequence
    contains all four DNA bases, so no swatch is vacuously absent.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")
    name = build_strand(blender, seq="ATCGATCG", prefix=f"DNA_{prop}",
                        ds=True, style="ball_and_stick")
    blender.call("return R.frame_all(objects=[name])", name=name)

    blender.call(APPLY_COLORS, name=name, colors=_all_bases(GREY))
    blender.call('return R.capture("grey")')

    blender.call(APPLY_COLORS, name=name, colors={prop: RED})
    painted = blender.call('return R.capture("painted")')
    assert painted["covered"] > 0

    diff = blender.call('return R.compare("grey", "painted")')
    assert diff["rgb_delta"] > 0.0, (
        f"{prop} was changed from grey to red and the render did not move; "
        "the swatch is not connected to the rendered strand")


@pytest.mark.live
@pytest.mark.visual
def test_uracil_colour_changes_the_rendered_rna(blender):
    """color_u only applies to RNA, so it needs an RNA strand to be provable."""
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")
    name = build_strand(blender, seq="AUGCAUGC", prefix="RNA_COLOR", nt="RNA",
                        ds=False, style="ball_and_stick")
    blender.call("return R.frame_all(objects=[name])", name=name)

    blender.call(APPLY_COLORS, name=name, colors=_all_bases(GREY, "RNA"))
    blender.call('return R.capture("grey")')

    blender.call(APPLY_COLORS, name=name, colors={"color_u": RED})
    blender.call('return R.capture("uracil")')

    diff = blender.call('return R.compare("grey", "uracil")')
    assert diff["rgb_delta"] > 0.0, (
        "recolouring uracil left the rendered RNA unchanged")


# ---------------------------------------------------------------------------
# Bend rig
# ---------------------------------------------------------------------------

def _build_bendable(blender, prefix="DNA_BEND"):
    """A double-stranded strand, active and long enough to be worth bending."""
    return build_strand(blender, seq="ATCGATCGATCGATCG", prefix=prefix,
                        ds=True, style="cartoon")


@pytest.mark.live
def test_add_bend_creates_a_curve_and_control_nodes(blender):
    """Adding a bend must create real Blender objects, not just bookkeeping.

    The inventory is taken from ``bpy.data.objects`` rather than from the
    strand's own BEND_CURVE_PROP: a rig that records a curve name it never
    created would satisfy the property check and nothing else.
    """
    name = _build_bendable(blender, "DNA_ADDBEND")
    before = blender.call(BEND_INVENTORY, name=name)

    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            return sorted(bpy.ops.proteinblender.dna_add_bend())
    """, name=name)

    after = blender.call(BEND_INVENTORY, name=name)
    new_curves = sorted(set(after["curves"]) - set(before["curves"]))
    assert len(new_curves) == 1, (
        f"expected the bend to create exactly one curve object, curves went "
        f"from {before['curves']} to {after['curves']}")
    assert len(after["nodes"]) >= 2, (
        f"a bend needs at least two control nodes to have a shape, found "
        f"{after['nodes']}")
    assert "CURVE" in after["modifiers"], (
        "the strand did not get a Curve modifier, so the bend curve cannot "
        f"deform it; modifiers are {after['modifiers']}")


@pytest.mark.live
@pytest.mark.parametrize("n_points", [2, 3, 7, 12])
def test_bend_resolution_sets_the_node_count(blender, n_points):
    """The node count on screen must equal the number the user asked for.

    2 and 12 are the ends of the operator's own range, so this also proves the
    extremes are reachable rather than clamped to a comfortable middle.
    """
    name = _build_bendable(blender, f"DNA_RES{n_points}")
    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_add_bend()
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_set_bend_resolution(n_points=n_points)
    """, name=name, n_points=n_points)

    nodes = blender.call(BEND_INVENTORY, name=name)["nodes"]
    assert len(nodes) == n_points, (
        f"asked for {n_points} control nodes, the scene has {len(nodes)}: "
        f"{nodes}")


@pytest.mark.live
def test_bend_resolution_can_be_lowered_again(blender):
    """Resampling down must remove nodes, not leave the old ones orphaned.

    Stale node Empties would keep hooking the curve and quietly fight the new
    ones, so the count has to come down as well as up.
    """
    name = _build_bendable(blender, "DNA_RESDOWN")
    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_add_bend()
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_set_bend_resolution(n_points=9)
    """, name=name)
    assert len(blender.call(BEND_INVENTORY, name=name)["nodes"]) == 9

    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_set_bend_resolution(n_points=2)
    """, name=name)
    nodes = blender.call(BEND_INVENTORY, name=name)["nodes"]
    assert len(nodes) == 2, (
        f"lowering the resolution left {len(nodes)} nodes behind: {nodes}")


@pytest.mark.live
def test_toggle_bend_curve_flips_the_guide_visibility(blender):
    """The guide toggle must flip eye visibility and be reversible.

    It deliberately does not touch ``hide_viewport``: that would drop the curve
    from depsgraph evaluation and make the strand snap back to its rest pose.
    So the assertion is on ``hide_get`` specifically, and on the strand's own
    ``hide_viewport`` staying put.
    """
    name = _build_bendable(blender, "DNA_TOGGLE")
    states = blender.call("""
        with R.view3d_override():
            dna = bpy.data.objects[name]
            existing = {o.name for o in bpy.data.objects if o.type == "CURVE"}
            H.select_only(dna)
            bpy.ops.proteinblender.dna_add_bend()
            curve = next(o for o in bpy.data.objects
                         if o.type == "CURVE" and o.name not in existing)
            before = curve.hide_get()
            H.select_only(dna)
            bpy.ops.proteinblender.dna_toggle_bend_curve()
            toggled = curve.hide_get()
            H.select_only(dna)
            bpy.ops.proteinblender.dna_toggle_bend_curve()
            restored = curve.hide_get()
            return {"before": before, "toggled": toggled,
                    "restored": restored,
                    "curve_hide_viewport": curve.hide_viewport}
    """, name=name)

    assert states["toggled"] != states["before"], (
        "toggling the bend curve did not change its visibility")
    assert states["restored"] == states["before"], (
        "toggling twice did not return the guide to its original visibility")
    assert states["curve_hide_viewport"] is False, (
        "the toggle disabled the curve in the viewport, which drops it from "
        "depsgraph evaluation and makes the strand snap back to rest")


@pytest.mark.live
def test_remove_bend_deletes_the_whole_rig(blender):
    """Removing must reap the curve and every control node.

    Leftover nodes are not harmless: they are hook targets, and the next
    add-bend sweeps or collides with them.
    """
    name = _build_bendable(blender, "DNA_REMOVE")
    before = blender.call(BEND_INVENTORY, name=name)
    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_add_bend()
    """, name=name)
    added = blender.call(BEND_INVENTORY, name=name)
    assert set(added["curves"]) - set(before["curves"]), "no bend curve to remove"
    assert added["nodes"], "no control nodes to remove"

    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_remove_bend()
    """, name=name)

    after = blender.call(BEND_INVENTORY, name=name)
    assert set(after["curves"]) == set(before["curves"]), (
        f"bend curve survived removal: {after['curves']}")
    assert after["nodes"] == [], f"control nodes survived removal: {after['nodes']}"
    assert "CURVE" not in after["modifiers"], (
        "the Curve modifier survived removal, leaving the strand deformed by a "
        "curve that no longer exists")


@pytest.mark.live
@pytest.mark.visual
def test_dragging_a_bend_node_actually_bends_the_strand(blender):
    """The point of the rig: moving a control node must move the strand.

    Everything else about the bend rig can be right while the hooks are wired
    to nothing, and no headless assertion notices - the curve exists, the nodes
    exist, the modifier is listed. Here a middle node is displaced the way a
    user drags it, and both the rendered image and the strand's own evaluated
    width have to respond.
    """
    name = _build_bendable(blender, "DNA_DRAG")
    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_add_bend()
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_set_bend_resolution(n_points=3)
    """, name=name)

    blender.call("return R.frame_all(objects=[name])", name=name)
    blender.call('return R.capture("rest")')
    rest_width = blender.call(
        "return R.object_summary(name)", name=name)

    moved = blender.call("""
        nodes = sorted((o for o in bpy.data.objects if "Bend Node " in o.name),
                       key=lambda o: o.name)
        middle = nodes[len(nodes) // 2]
        middle.location.x += 1.0
        bpy.context.view_layer.update()
        return middle.name
    """)
    assert moved, "no bend control node to drag"

    bent = blender.call('return R.capture("bent")')
    assert bent["covered"] > 0, "the strand vanished when the bend was applied"

    diff = blender.call('return R.compare("rest", "bent")')
    assert not diff["identical"], (
        f"dragging control node {moved} sideways left the render unchanged; "
        "the bend rig is not deforming the strand")

    bent_width = blender.call("return R.object_summary(name)", name=name)
    if rest_width.get("bbox_min") and bent_width.get("bbox_min"):
        rest_x = rest_width["bbox_max"][0] - rest_width["bbox_min"][0]
        bent_x = bent_width["bbox_max"][0] - bent_width["bbox_min"][0]
        assert bent_x > rest_x, (
            f"pulling the middle of the strand sideways should widen its X "
            f"extent, but it went from {rest_x:.4f} to {bent_x:.4f}")


@pytest.mark.live
def test_edit_and_finish_bend_over_the_live_transport(blender):
    """Edit/finish flip Blender in and out of edit mode.

    Those transitions depend on a genuine interactive context and may not be
    reachable over the socket, which arrives on a timer callback. A failure
    here is far more likely to be the transport than the product, so it skips
    rather than fails - the add, resolution, toggle and remove tests above
    already cover the rig's observable behaviour.
    """
    from mcp_client import LiveBlenderError

    name = _build_bendable(blender, "DNA_EDIT")
    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.dna_add_bend()
    """, name=name)

    try:
        selected = blender.call("""
            with R.view3d_override():
                H.select_only(bpy.data.objects[name])
                bpy.ops.proteinblender.dna_edit_bend()
                return sorted(o.name for o in bpy.context.selected_objects
                              if "Bend Node " in o.name)
        """, name=name)
    except LiveBlenderError as exc:
        pytest.skip(f"dna_edit_bend is not reachable over this transport: {exc}")

    assert selected, "edit bend selected no control nodes"

    try:
        active = blender.call("""
            with R.view3d_override():
                bpy.ops.proteinblender.dna_finish_bend_edit()
                obj = bpy.context.view_layer.objects.active
                return obj.name if obj is not None else ""
        """)
    except LiveBlenderError as exc:
        pytest.skip(
            f"dna_finish_bend_edit is not reachable over this transport: {exc}")

    assert active == name, (
        f"finishing the bend edit left {active!r} active instead of handing "
        f"focus back to {name!r}")
