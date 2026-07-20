"""Colour, observed on screen. The reason this lane exists.

Every pixel assertion in the rest of the suite reduces a render to an alpha mask
(``px[:, 3] > 0.01``) and throws the RGB channels away. That is a deliberate,
sensible choice for the questions those tests ask - "is anything drawn", "did
the geometry move" - and it means the entire colour dimension of this add-on is
currently unasserted. A domain drawn in the wrong colour, every domain drawn
identically, a colour picker wired to a property nothing reads, a material that
records a value and never binds: all of them render a perfectly healthy alpha
mask, and all of them pass the existing suite.

This module measures the channels.

Two pieces of setup are load-bearing and neither is optional:

* **MATERIAL shading.** In SOLID/studio shading the molecule renders flat grey,
  and every assertion below would be measuring the viewport theme rather than
  the add-on. Each test sets it explicitly rather than relying on whatever the
  live session was left in.
* **``view_transform = 'Standard'``**, forced by ``remote._render_viewport``
  around every capture. Blender's default filmic-style transform remaps all
  three channels, and "is this domain red" stops being stably answerable.

Assertions here are relationships, never the literal numbers a current build
produces. Setting the picker to red must make red the dominant channel and must
move the image substantially away from the blue version; that is a property of
"the colour reached the renderer" and is true on any GPU, driver and Blender
build. Recording ``mean_rgb == [0.918, 0.186, 0.177]`` would instead be a
fingerprint of one machine on one day.

One test in this module is expected to fail. See
``test_update_domain_color_repaints_the_domain`` - it is not marked xfail, it is
not weakened, and it documents a real product bug.
"""

from __future__ import annotations

import pytest


RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)
GREEN = (0.0, 1.0, 0.0, 1.0)

# Channel index each colour must dominate. Independent of the add-on: it is what
# "red" and "blue" mean in an RGB buffer.
CHANNEL = {"red": 0, "green": 1, "blue": 2}


# ---------------------------------------------------------------------------
# Remote snippets
# ---------------------------------------------------------------------------

# Select exactly one outliner row through the public checkbox operator, clearing
# any prior selection first so the colour applies where the test intends.
_SELECT_ONLY = """
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
for item in scene.outliner_items:
    item.is_selected = False
with R.view3d_override():
    bpy.ops.proteinblender.outliner_select(item_id=item_id)
row = next((i for i in scene.outliner_items if i.item_id == item_id), None)
assert row is not None and row.is_selected, "row %r did not select" % item_id
return item_id
"""

# Drive the Visual Set-up colour picker. Assigning the whole FloatVector fires
# its ``update=`` callback once, which is the same path a user's click takes.
# The override supplies the window/screen the callback walks to tag redraws.
_SET_PICKER_COLOUR = """
scene = bpy.context.scene
with R.view3d_override():
    scene.visual_setup_color = colour
bpy.context.view_layer.update()
return [float(c) for c in scene.visual_setup_color]
"""

_SET_PICKER_STYLE = """
scene = bpy.context.scene
with R.view3d_override():
    scene.visual_setup_style = style
bpy.context.view_layer.update()
return scene.visual_setup_style
"""

# Per-pixel colour populations, for "are there two different colours on screen".
#
# ``distinct_colors`` alone cannot answer that: shading gradients across a single
# red surface already produce dozens of quantised colours. What distinguishes one
# colour from two is whether pixels exist that are *dominated by different
# channels*. ``lead`` (top channel minus middle channel) filters out neutral
# greys and antialiased edges, which would otherwise be assigned a dominant
# channel essentially at random.
#
# This reaches into ``R._render_viewport`` because remote.py is shared lane
# infrastructure and must not accumulate a helper per test module; the
# lane's rule is that Blender-side logic for one module lives inline.
_COLOUR_POPULATIONS = """
import numpy as np

rgba = R._render_viewport(resolution, True, True)
alpha = rgba[:, :, 3] > 0.01
covered = int(alpha.sum())
if not covered:
    return {"covered": 0, "strong": 0, "channel_counts": [0, 0, 0],
            "left_dominant": None, "right_dominant": None}

rgb = rgba[:, :, :3]
dominant = np.argmax(rgb, axis=2)
lead = np.max(rgb, axis=2) - np.median(rgb, axis=2)
strong = alpha & (lead > 0.15)

ys, xs = np.nonzero(alpha)
middle = int((int(xs.min()) + int(xs.max())) / 2)
left = strong.copy()
left[:, middle:] = False
right = strong.copy()
right[:, :middle] = False

def region_dominant(mask):
    if not int(mask.sum()):
        return None
    return int(np.bincount(dominant[mask], minlength=3).argmax())

return {
    "covered": covered,
    "strong": int(strong.sum()),
    "channel_counts": [int(((dominant == c) & strong).sum()) for c in range(3)],
    "left_dominant": region_dominant(left),
    "right_dominant": region_dominant(right),
}
"""


def _material_shading(blender):
    """Colour is only measurable in MATERIAL shading; SOLID renders flat grey."""
    return blender.call(
        "return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")


def _capture(blender, label: str) -> dict:
    return blender.call("return R.capture(label=label)", label=label)


def _compare(blender, left: str, right: str) -> dict:
    return blender.call("return R.compare(left, right)", left=left, right=right)


def _populations(blender, resolution: int = 480) -> dict:
    return blender.call(_COLOUR_POPULATIONS, resolution=resolution)


def _assert_dominant(metrics, colour_name, context=""):
    """The requested colour must be the one leading the rendered mean."""
    expected = CHANNEL[colour_name]
    actual = metrics["dominant_channel"]
    assert actual == expected, (
        f"{context}asked for {colour_name} (channel {expected}) but the render "
        f"is dominated by channel {actual}; mean_rgb={metrics['mean_rgb']}")
    mean = metrics["mean_rgb"]
    others = [value for index, value in enumerate(mean) if index != expected]
    assert mean[expected] > max(others), (
        f"{context}{colour_name} channel ({mean[expected]}) does not lead the "
        f"others in mean_rgb={mean}")


# ---------------------------------------------------------------------------
# The control path: scene.visual_setup_color
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_visual_setup_colour_picker_repaints_the_molecule(blender,
                                                          single_chain):
    """Setting the picker red then blue must move what is rendered.

    This is the add-on's primary colouring path - the swatch in the Visual
    Set-up panel, applied live to the current outliner selection through a
    property ``update=`` callback - and it is the control that every other
    colour assertion in this module is measured against.

    Three independent claims, each of which a different bug breaks:

      * red renders red-dominant, and blue renders blue-dominant. A picker wired
        to the wrong socket typically produces *some* colour, just not the one
        asked for, and would satisfy "the render changed" while failing this.
      * the two images differ substantially. A picker that records the value and
        never reaches the renderer produces two identical frames.
      * both frames actually contain geometry. Comparing two empty renders is
        the classic way a colour test passes while showing nothing.

    The thresholds are shape, not magnitude: which channel leads is a strict
    ordering, and "substantially different" is set far below a red-to-blue swing
    but far above render noise, so it cannot be satisfied by dithering.
    """
    _material_shading(blender)

    protein = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return next(i.item_id for i in scene.outliner_items if i.item_type == 'PROTEIN')
""")
    blender.call(_SELECT_ONLY, item_id=protein)
    blender.call("return R.frame_all()")

    blender.call(_SET_PICKER_COLOUR, colour=list(RED))
    red = _capture(blender, "red")
    blender.call(_SET_PICKER_COLOUR, colour=list(BLUE))
    blue = _capture(blender, "blue")

    assert red["covered"] > 0 and blue["covered"] > 0, (
        f"nothing rendered (red={red['covered']}, blue={blue['covered']}); a "
        f"colour comparison over an empty frame proves nothing")

    _assert_dominant(red, "red")
    _assert_dominant(blue, "blue")

    diff = _compare(blender, "red", "blue")
    assert diff["rgb_delta"] > 0.05, (
        f"a red molecule and a blue molecule rendered near-identically "
        f"(rgb_delta={diff['rgb_delta']}). The colour picker is not reaching "
        f"the renderer.")
    assert diff["xor"] == 0, (
        f"recolouring moved {diff['xor']} pixels of geometry; changing a "
        f"colour must not change the shape of what is drawn")


@pytest.mark.live
@pytest.mark.visual
def test_visual_setup_colour_reaches_a_single_selected_chain(blender,
                                                            multi_chain):
    """The picker applies to the *selection*, not to everything loaded.

    With one chain of a tetramer selected, red must appear on screen and the
    other three chains must not become red. Asserting only "the render changed"
    would pass an implementation that repainted all four - a bug a user notices
    immediately and no state assertion catches, since each chain's stored colour
    would look plausible in isolation.

    The invariant used is population-based rather than positional: after
    colouring one chain of four red on a default-coloured protein, red-dominant
    pixels must exist *and* non-red-dominant pixels must still exist. Both
    "nothing turned red" and "everything turned red" fail it.
    """
    _material_shading(blender)

    chain = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return next(i.item_id for i in scene.outliner_items if i.item_type == 'CHAIN')
""")
    blender.call(_SELECT_ONLY, item_id=chain)
    blender.call("return R.frame_all()")

    blender.call(_SET_PICKER_COLOUR, colour=list(RED))
    populations = _populations(blender)

    assert populations["covered"] > 0, "the tetramer rendered nothing"
    counts = populations["channel_counts"]
    assert counts[0] > 0, (
        f"colouring one chain red produced no red-dominant pixels "
        f"(channel counts {counts}); the selection did not receive the colour")
    assert sum(counts) - counts[0] > 0, (
        f"colouring one chain of four red left the entire frame red-dominant "
        f"(channel counts {counts}); the picker ignored the selection and "
        f"repainted the whole protein")


@pytest.mark.live
@pytest.mark.visual
def test_chains_can_hold_different_colours_at_the_same_time(blender,
                                                            multi_chain):
    """Two chains, two colours, one frame.

    The failure this catches is the one the lane README calls out as invisible
    to the existing suite: every object drawn identically. Each chain's stored
    colour would read back correctly while a single shared material or a single
    shared node group flattened them all to one colour on screen.

    Ground truth is that red and blue are different: the frame must contain
    pixels dominated by channel 0 *and* pixels dominated by channel 2. That is
    unsatisfiable by any implementation that paints both chains the same,
    whatever colour it picks.
    """
    _material_shading(blender)

    chains = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return [i.item_id for i in scene.outliner_items if i.item_type == 'CHAIN']
""")
    assert len(chains) >= 2, f"need two chains to colour differently: {chains}"

    blender.call("return R.frame_all()")

    blender.call(_SELECT_ONLY, item_id=chains[0])
    blender.call(_SET_PICKER_COLOUR, colour=list(RED))
    one_colour = _populations(blender)

    blender.call(_SELECT_ONLY, item_id=chains[1])
    blender.call(_SET_PICKER_COLOUR, colour=list(BLUE))
    two_colours = _populations(blender)
    both = _capture(blender, "two-chain-colours")

    assert two_colours["covered"] > 0, "the tetramer rendered nothing"

    counts = two_colours["channel_counts"]
    assert counts[0] > 0 and counts[2] > 0, (
        f"a red chain and a blue chain do not both appear on screen "
        f"(channel counts {counts}). Either the second colour overwrote the "
        f"first, or both chains share one material.")

    assert both["distinct_colors"] > 1, (
        "the whole frame quantises to a single colour")
    assert two_colours["strong"] >= one_colour["strong"], (
        f"adding a second strongly-coloured chain reduced the strongly-coloured "
        f"pixel count ({one_colour['strong']} -> {two_colours['strong']}); the "
        f"second colour displaced the first instead of joining it")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
@pytest.mark.slow
def test_each_style_renders_something_and_no_two_look_alike(blender,
                                                            single_chain):
    """The six real ``visual_setup_style`` identifiers must be visually distinct.

    Cartoon, spheres, surface, ribbon, sticks and ball-and-stick are genuinely
    different representations of the same atoms, so their renders cannot
    legitimately match. Two identical images mean the style dropdown wrote an
    RNA value that never reached the geometry-nodes output - the style node was
    not swapped, or was swapped in a tree nothing downstream consumes.

    This is the metamorphic form the headless suite already uses for styles, run
    here against the viewport shading path rather than a Cycles render, which is
    what the user is actually looking at.
    """
    _material_shading(blender)

    protein = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return next(i.item_id for i in scene.outliner_items if i.item_type == 'PROTEIN')
""")
    blender.call(_SELECT_ONLY, item_id=protein)
    blender.call("return R.frame_all()")

    styles = ["spheres", "cartoon", "surface", "ribbon", "sticks",
              "ball_and_stick"]
    for style in styles:
        applied = blender.call(_SET_PICKER_STYLE, style=style)
        assert applied == style, (
            f"the style property would not accept {style!r}, it holds "
            f"{applied!r}")
        metrics = _capture(blender, style)
        assert metrics["covered"] > 0, (
            f"style {style!r} rendered an empty frame; the representation "
            f"produces no geometry at all")

    for index, left in enumerate(styles):
        for right in styles[index + 1:]:
            diff = _compare(blender, left, right)
            assert diff["xor"] > 0, (
                f"styles {left!r} and {right!r} produced identical images "
                f"(iou={diff['iou']}). These are different representations of "
                f"the same atoms and cannot legitimately match, so the style "
                f"change is not reaching the geometry output.")


@pytest.mark.live
@pytest.mark.visual
def test_the_multiple_style_sentinel_changes_nothing(blender, single_chain):
    """The empty identifier is a "Multiple styles selected" placeholder.

    ``visual_setup_style`` carries ``('', "Multiple", ...)`` so a mixed
    selection has something to display. It is a label, not a representation, and
    ``update_style`` returns early on it. Writing it must therefore leave the
    viewport untouched - if the empty value ever fell through to
    ``apply_style_to_object`` it would map to no style node and the sensible
    failure mode is a blank molecule.
    """
    _material_shading(blender)

    protein = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return next(i.item_id for i in scene.outliner_items if i.item_type == 'PROTEIN')
""")
    blender.call(_SELECT_ONLY, item_id=protein)
    blender.call("return R.frame_all()")

    blender.call(_SET_PICKER_STYLE, style="spheres")
    before = _capture(blender, "spheres")
    assert before["covered"] > 0

    blender.call(_SET_PICKER_STYLE, style="")
    after = _capture(blender, "multiple-sentinel")
    diff = _compare(blender, "spheres", "multiple-sentinel")

    assert after["covered"] > 0, (
        "selecting the 'Multiple' placeholder blanked the molecule; the empty "
        "identifier is being applied as if it were a real style")
    assert diff["xor"] == 0 and diff["rgb_delta"] < 1e-3, (
        f"the 'Multiple' placeholder changed the render (xor={diff['xor']}, "
        f"rgb_delta={diff['rgb_delta']}); it is a label, not a style")


# ---------------------------------------------------------------------------
# The known product bug
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_update_domain_color_repaints_the_domain(blender, single_chain):
    """EXPECTED TO FAIL. ``molecule.update_domain_color`` never reaches a pixel.

    This asserts the correct behaviour and currently fails. It is deliberately
    not xfailed and not weakened: the operator is wired to the UI, a user
    clicking it sees nothing happen, and a test that quietly tolerates that is
    worse than no test.

    **The evidence.** The operator records the colour on the domain model and
    builds a per-domain colour node tree, and both of those succeed - which is
    exactly why the existing suite stays green, since it asserts on
    ``mol.domains[id].color``. But neither ``obj.domain_color`` nor the rendered
    pixels change. Driving it red and then blue over a molecule that fills the
    entire frame yields ``rgb_delta`` of exactly 0.0: not "small", not "within
    tolerance", byte-identical.

    **The control is in this test.** The same molecule, the same frame, the same
    capture path is first driven through ``scene.visual_setup_color``, which
    moves the mean colour and flips the dominant channel (README records
    ``[0.918, 0.186, 0.177]`` to ``[0.186, 0.186, 0.920]``, ``rgb_delta`` about
    0.49). So a 0.0 delta here cannot be blamed on shading mode, view transform,
    GPU or framing - those are all held identical and demonstrably working
    microseconds earlier. The difference is the code path.

    1ubq is chosen because its single chain is one domain filling the whole
    render, so "the domain is only a small part of the frame" is not available
    as an explanation for a small delta - and the delta is not small, it is zero.

    Implementation note for whoever fixes this: the operator reads
    ``scene.temp_domain_color``, but its own ``color`` operator property
    overrides that whenever it is passed (domain_operators.py, around line 579,
    guarded by ``self.color[0] >= 0`` - which is true for every legal colour, so
    the argument always wins). This test passes ``color`` explicitly, so the
    value reaching ``molecule.update_domain_color`` is unambiguous.
    """
    _material_shading(blender)

    setup = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
scene.selected_molecule_id = "1ubq"
molecule = H.sm().molecules["1ubq"]
domain_id, domain = next(iter(molecule.domains.items()))
protein = next(i.item_id for i in scene.outliner_items
               if i.item_type == 'PROTEIN')
return {"domain_id": domain_id, "object_name": domain.object.name,
        "protein": protein}
""")

    blender.call(_SELECT_ONLY, item_id=setup["protein"])
    blender.call("return R.frame_all()")

    # --- control: the path that is known to work -------------------------
    blender.call(_SET_PICKER_COLOUR, colour=list(RED))
    control_red = _capture(blender, "control-red")
    blender.call(_SET_PICKER_COLOUR, colour=list(BLUE))
    control_blue = _capture(blender, "control-blue")
    control = _compare(blender, "control-red", "control-blue")

    assert control_red["covered"] > 0, "nothing rendered during the control"
    assert control["rgb_delta"] > 0.05, (
        f"the CONTROL failed (rgb_delta={control['rgb_delta']}). "
        f"scene.visual_setup_color did not move the render either, so this "
        f"session cannot measure colour at all and the domain-colour result "
        f"below is not interpretable. Check MATERIAL shading and the view "
        f"transform before reading anything else into this run.")

    # --- the operator under test -----------------------------------------
    def recolour(colour):
        return blender.call("""
with R.view3d_override():
    outcome = bpy.ops.molecule.update_domain_color(
        domain_id=domain_id, color=colour)
bpy.context.view_layer.update()
obj = bpy.data.objects[object_name]
return {
    "result": sorted(outcome),
    "domain_color": [float(c) for c in (obj.get("domain_color") or [])],
}
""", domain_id=setup["domain_id"], object_name=setup["object_name"],
             colour=list(colour))

    applied_red = recolour(RED)
    assert applied_red["result"] == ["FINISHED"], (
        "update_domain_color did not even report success")
    domain_red = _capture(blender, "domain-red")

    applied_blue = recolour(BLUE)
    assert applied_blue["result"] == ["FINISHED"]
    domain_blue = _capture(blender, "domain-blue")

    diff = _compare(blender, "domain-red", "domain-blue")

    assert domain_red["covered"] > 0 and domain_blue["covered"] > 0, (
        "update_domain_color blanked the render")

    assert diff["rgb_delta"] > 0.05, (
        f"molecule.update_domain_color did not repaint the domain: recolouring "
        f"it red and then blue changed the render by rgb_delta="
        f"{diff['rgb_delta']}, while the control (scene.visual_setup_color, "
        f"same molecule, same frame, same capture) moved it by "
        f"{control['rgb_delta']}. The operator returns FINISHED and updates the "
        f"domain model, so every existing state-based test stays green while "
        f"nothing on screen changes. "
        f"obj['domain_color'] after red={applied_red['domain_color']}, "
        f"after blue={applied_blue['domain_color']}.")

    _assert_dominant(domain_red, "red", "after update_domain_color(red): ")
    _assert_dominant(domain_blue, "blue", "after update_domain_color(blue): ")


@pytest.mark.live
@pytest.mark.visual
def test_split_domains_can_hold_different_colours(blender, actin):
    """EXPECTED TO FAIL, for the same root cause as the test above.

    Splitting a chain and colouring the two halves differently must put two
    colours in one frame. It goes through the *picker*, not the operator, but
    ``update_color`` routes a DOMAIN row to ``apply_domain_color_direct``, which
    resolves the parent molecule and calls ``molecule.update_domain_color`` -
    the same method that does not reach a pixel. Chains take the other branch
    (``apply_color_to_object``), which is why
    ``test_chains_can_hold_different_colours_at_the_same_time`` passes and this
    does not.

    It is kept as a separate test rather than folded into the one above because
    it is the user-facing symptom - "I split a chain and cannot colour the
    halves differently" - and because it is the assertion that should turn green
    when the domain-colour path is fixed, confirming the fix reached the picker
    route as well as the operator route.

    The invariant is unfakeable by any single-colour implementation: pixels
    dominated by channel 0 and pixels dominated by channel 2 must both exist.
    """
    _material_shading(blender)

    domains = blender.call("""
scene = bpy.context.scene
manager = H.sm()
molecule = manager.molecules["1atn"]
scene.selected_molecule_id = "1atn"

original_id = next(did for did, d in molecule.domains.items()
                   if d.chain_id == "A")
assert sorted(H.split_domain_from_outliner(
    "1atn", "A", 1, 50, domain_id=original_id)) == ["FINISHED"]
H.scene_manager_module().build_outliner_hierarchy(bpy.context)

rows = [(int(i.domain_start), i.item_id) for i in scene.outliner_items
        if i.item_type == 'DOMAIN' and int(i.domain_end) > 0]
return [item_id for _, item_id in sorted(rows)]
""")
    assert len(domains) >= 2, f"the split produced too few domains: {domains}"

    blender.call("return R.frame_all()")

    blender.call(_SELECT_ONLY, item_id=domains[0])
    blender.call(_SET_PICKER_COLOUR, colour=list(RED))
    blender.call(_SELECT_ONLY, item_id=domains[1])
    blender.call(_SET_PICKER_COLOUR, colour=list(BLUE))

    populations = _populations(blender)
    frame = _capture(blender, "split-domain-colours")

    assert populations["covered"] > 0, "the split molecule rendered nothing"
    counts = populations["channel_counts"]
    assert counts[0] > 0 and counts[2] > 0, (
        f"a red domain and a blue domain do not both appear on screen "
        f"(channel counts {counts}, left-half dominant "
        f"{populations['left_dominant']}, right-half dominant "
        f"{populations['right_dominant']}, distinct_colors="
        f"{frame['distinct_colors']}). Domain colouring routes through "
        f"molecule.update_domain_color, which records the colour and never "
        f"repaints - see test_update_domain_color_repaints_the_domain.")


# ---------------------------------------------------------------------------
# Builders: does their colour configuration reach the render?
# ---------------------------------------------------------------------------
#
# Structural coverage of the DNA and membrane builders lives in their own
# modules. These two tests deliberately assert on nothing but the colour
# dimension, which is the axis only this lane can see.

@pytest.mark.live
@pytest.mark.visual
def test_dna_base_colours_reach_the_render(blender):
    """The DNA builder's per-base colours must survive into the viewport.

    ``dna_builder_props`` carries ``color_a``/``color_t``/``color_g``/``color_c``
    and ``color_backbone``, none of which has an ``update=`` callback: they are
    read at build time and baked into the strand's materials. That makes them
    invisible to any test that inspects properties, because the property holds
    whatever was set whether or not the builder ever consulted it.

    So the strand is built twice, from the same sequence, differing only in the
    colour properties. Two builds of identical geometry that render the same
    colour prove the builder ignored them.

    The comparison is on the *mean colour* rather than a pixel mask, because
    each build is framed independently and pixel-exact overlay is not
    guaranteed; which channel leads the mean is unaffected by framing.
    """
    _material_shading(blender)

    def build(colour):
        return blender.call("""
H.reset_scene()
props = bpy.context.scene.dna_builder_props
for key in ("color_a", "color_t", "color_g", "color_c", "color_u",
            "color_backbone"):
    setattr(props, key, colour)
with R.view3d_override():
    obj = H.build_dna(seq="ATCGATCGATCG", name_prefix="DNA")
bpy.context.view_layer.update()
return obj.name
""", colour=list(colour))

    build(RED)
    blender.call("return R.frame_all()")
    red = _capture(blender, "dna-red")

    build(BLUE)
    blender.call("return R.frame_all()")
    blue = _capture(blender, "dna-blue")

    assert red["covered"] > 0 and blue["covered"] > 0, (
        f"the DNA strand rendered nothing (red={red['covered']}, "
        f"blue={blue['covered']})")

    _assert_dominant(red, "red", "DNA built with red bases: ")
    _assert_dominant(blue, "blue", "DNA built with blue bases: ")


@pytest.mark.live
@pytest.mark.visual
def test_membrane_head_tail_and_surface_colours_reach_the_render(blender):
    """The membrane builder's three colours must survive into the viewport.

    ``color_head`` and ``color_tail`` are read at build time; ``color_surface``
    additionally has an ``update=`` callback that writes through to the active
    membrane. All three are set together and the bilayer is built twice, so a
    builder that consults none of them renders the same membrane both times.

    Only the colour axis is asserted here - shape, size, lipid packing and hole
    handling belong to the membrane module's own coverage.
    """
    _material_shading(blender)

    def build(colour):
        return blender.call("""
H.reset_scene()
props = bpy.context.scene.membrane_builder_props
for key in ("color_head", "color_tail", "color_surface"):
    setattr(props, key, colour)
with R.view3d_override():
    created = H.build_membrane(shape="FLAT", width=20, height=20)
bpy.context.view_layer.update()
return created
""", colour=list(colour))

    created = build(RED)
    assert created, "the membrane builder created no objects"
    blender.call("return R.frame_all()")
    red = _capture(blender, "membrane-red")

    build(GREEN)
    blender.call("return R.frame_all()")
    green = _capture(blender, "membrane-green")

    assert red["covered"] > 0 and green["covered"] > 0, (
        f"the membrane rendered nothing (red={red['covered']}, "
        f"green={green['covered']})")

    _assert_dominant(red, "red", "membrane built with red lipids: ")
    _assert_dominant(green, "green", "membrane built with green lipids: ")
