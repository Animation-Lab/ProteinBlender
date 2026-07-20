"""The membrane builder, observed on screen.

Membranes are never rendered anywhere else in the suite. The headless lane
(``tests/integration/test_membrane.py``) says so itself: the geometry-nodes tree
emits *instances*, so an evaluated ``to_mesh`` contains zero vertices and every
assertion there falls back to the root's flat base patch. That patch is created
before a single lipid is placed. It survives a lipid collection that never
loads, a render style that never binds, a colour that never reaches a material,
a hole that carves nothing, and a force field that pushes nothing aside.

This module measures the lipids themselves, two ways, both independent of the
add-on's own reporting:

  * **Instances, straight from the depsgraph.** ``LIPID_STATS`` walks
    ``depsgraph.object_instances`` and counts the lipids Blender actually
    evaluated, with their world positions. That is Blender's answer to "what is
    in this scene", not ProteinBlender's.
  * **Pixels.** Renders of the viewport, compared against each other.

Assertions are relational and monotonic - more density means more lipids, a
thicker bilayer spans more Z, a hole removes lipids and a bigger hole removes
more - so they hold on any GPU and cannot be satisfied by a number copied from
today's build.
"""

from __future__ import annotations

import itertools

import pytest


# Values of MembraneBuilderProperties.shape (membrane_props.py).
SHAPES = ["FLAT", "SPHERE", "HEMISPHERE"]

# lipid_assets.RENDER_STYLE_ITEMS. SURFACE is DEFAULT_STYLE.
RENDER_STYLES = ["SURFACE", "STYLIZED", "BALL_AND_STICK"]

# membrane_geometry.MAX_HOLES, restated here rather than imported so the cap
# test measures the documented contract instead of whatever the constant
# happens to say.
MAX_HOLES = 8

RED = [0.95, 0.05, 0.05, 1.0]
BLUE = [0.05, 0.05, 0.95, 1.0]
DARK_GREY = [0.15, 0.15, 0.15, 1.0]


# ---------------------------------------------------------------------------
# Blender-side snippets
#
# Anything that drives an operator runs under ``R.view3d_override()``: calls
# arrive on a timer callback with no editor area, while building a membrane
# appends node groups and lipid collections, which needs a real VIEW_3D context
# just as a click on the panel button would have.
# ---------------------------------------------------------------------------

BUILD = """
with R.view3d_override():
    names = H.build_membrane(**overrides)
root = None
for candidate in names:
    obj = bpy.data.objects.get(candidate)
    if obj is not None and obj.get("pb_is_membrane", False):
        root = obj
        break
if root is None:
    raise RuntimeError("build_membrane created no pb_is_membrane root: %r" % (names,))
return {
    "root": root.name,
    "created": names,
    "children": sorted(c.name for c in root.children),
    "child_types": sorted({c.type for c in root.children}),
    "shape": root.get("pb_mem_shape"),
    "render_style": root.get("pb_mem_render_style"),
    "base_verts": len(root.data.vertices),
    "modifiers": [m.name for m in root.modifiers if m.type == "NODES"],
}
"""

# What Blender evaluated, not what the add-on says it built.
#
# The membrane's lipids exist only as geometry-nodes instances, so this is the
# only honest count of them. ``origin`` is optional: pass a world point to also
# get the distance from it to the nearest lipid, which is how "the membrane
# parts around this protein" becomes measurable.
LIPID_STATS = """
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
xs, ys, zs = [], [], []
for inst in deps.object_instances:
    if not inst.is_instance:
        continue
    parent = inst.parent
    if parent is None or parent.original.name != name:
        continue
    translation = inst.matrix_world.translation
    xs.append(translation.x)
    ys.append(translation.y)
    zs.append(translation.z)
stats = {"count": len(xs)}
if xs:
    stats["x_extent"] = max(xs) - min(xs)
    stats["y_extent"] = max(ys) - min(ys)
    stats["z_extent"] = max(zs) - min(zs)
    if origin:
        ox, oy, oz = origin
        stats["min_distance"] = min(
            ((x - ox) ** 2 + (y - oy) ** 2 + (z - oz) ** 2) ** 0.5
            for x, y, z in zip(xs, ys, zs))

    # Clearance around the first hole, in nm. A hole pushes lipids radially
    # outwards rather than deleting them, so "did the hole work" is a question
    # about where the lipids are, not how many there are.
    root_obj = bpy.data.objects.get(name)
    holes = [child for child in (root_obj.children if root_obj else [])
             if child.get("pb_is_membrane_hole")]
    # Measured about the hole when there is one, and about the membrane's own
    # origin when there is not - which is where a new hole spawns. That keeps
    # the before and after readings comparable; measuring only when a hole
    # exists leaves nothing to compare the "solid" state against.
    if holes:
        centre = holes[0].matrix_world.translation
        radius_nm = float(holes[0].scale.x) * 10.0
    else:
        centre = root_obj.matrix_world.translation if root_obj else None
        radius_nm = 0.0
    if centre is not None:
        radial = [(((x - centre.x) ** 2 + (y - centre.y) ** 2) ** 0.5) * 10.0
                  for x, y in zip(xs, ys)]
        stats["clearance_nm"] = min(radial)
        stats["hole_radius_nm"] = radius_nm
        stats["inside_hole"] = sum(1 for d in radial if d < radius_nm * 0.8)
return stats
"""

SETTLE = """
# Let the depsgraph and the FF refresh timers catch up after a transform
# change, the way an interactive redraw would. A membrane refresh repositions
# the FF anchors and re-reads them in Object Info; without a settle the
# evaluated geometry can lag a frame behind the move.
with R.view3d_override():
    import bpy
    for _ in range(3):
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
bpy.context.view_layer.update()
return True
"""

NEAR_XY = """
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
ox, oy = origin[0], origin[1]
within = 0
for inst in deps.object_instances:
    if not inst.is_instance:
        continue
    parent = inst.parent
    if parent is None or parent.original.name != name:
        continue
    t = inst.matrix_world.translation
    d_nm = ((t.x - ox) ** 2 + (t.y - oy) ** 2) ** 0.5 * 10.0
    if d_nm < radius_nm:
        within += 1
return {"within": within}
"""

SET_PROPS = """
props = bpy.context.scene.membrane_builder_props
with R.view3d_override():
    for key, value in settings.items():
        setattr(props, key, value)
return {key: str(getattr(props, key)) for key in settings}
"""

# An orthographic view straight down the Z axis. A flat bilayer seen from above
# is the one framing in which "a hole removes covered geometry" means what it
# says: the gap has nothing behind it to fill in.
TOP_VIEW = """
window, area, region = R.find_view3d()
region_3d = area.spaces.active.region_3d
previous = {"perspective": region_3d.view_perspective,
            "rotation": list(region_3d.view_rotation)}
region_3d.view_perspective = "ORTHO"
region_3d.view_rotation = (1.0, 0.0, 0.0, 0.0)
return previous
"""

# The live Blender is a long-lived session shared by the whole lane, so a test
# that changes the user's view puts it back.
RESTORE_VIEW = """
window, area, region = R.find_view3d()
region_3d = area.spaces.active.region_3d
region_3d.view_perspective = previous["perspective"]
region_3d.view_rotation = previous["rotation"]
return previous["perspective"]
"""

HOLE_NAMES = """
root = bpy.data.objects[name]
return sorted(c.name for c in root.children
              if c.get("pb_is_membrane_hole", False))
"""

ACTIVATE = """
with R.view3d_override():
    H.select_only(bpy.data.objects[name])
return bpy.context.view_layer.objects.active.name
"""


def build_membrane(blender, **overrides):
    """Build one membrane through the public operator; return its facts dict."""
    overrides.setdefault("shape", "FLAT")
    overrides.setdefault("width", 20.0)
    overrides.setdefault("height", 20.0)
    return blender.call(BUILD, overrides=overrides)


def lipid_stats(blender, root, origin=None):
    """Depsgraph-evaluated lipid instances for one membrane root."""
    return blender.call(LIPID_STATS, name=root, origin=origin)


def delete_membrane(blender, root):
    return blender.call("""
        with R.view3d_override():
            return sorted(bpy.ops.proteinblender.delete_membrane(
                membrane_name=name))
    """, name=root)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_a_built_membrane_is_visible_and_carries_lipids(blender, shot):
    """The baseline: a membrane must render, and must render lipids.

    Both halves matter. The headless lane can prove the base patch exists; only
    a render can prove anything was drawn, and only the instance count can prove
    the thing drawn was a bilayer rather than a bare grid.
    """
    facts = build_membrane(blender)
    assert facts["base_verts"] > 0, "membrane base mesh has no vertices"
    assert facts["modifiers"], "membrane has no geometry-nodes modifier"
    assert "LATTICE" in facts["child_types"], (
        f"no lattice deformer child; children are {facts['children']}")

    stats = lipid_stats(blender, facts["root"])
    assert stats["count"] > 0, (
        "the membrane evaluated zero lipid instances; the base patch exists "
        "but no bilayer was built on it")

    metrics = shot("built")
    assert metrics["covered"] > 0, "a built membrane rendered nothing"


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("shape", SHAPES)
def test_every_shape_renders_lipids(blender, shot, shape):
    """Sheet, vesicle and bowl each have their own base-mesh generator."""
    facts = build_membrane(blender, shape=shape, radius=15.0)
    assert facts["shape"] == shape

    stats = lipid_stats(blender, facts["root"])
    assert stats["count"] > 0, f"shape {shape!r} placed no lipids"

    metrics = shot(shape)
    assert metrics["covered"] > 0, f"shape {shape!r} rendered nothing"


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.slow
def test_the_three_shapes_are_visually_distinct(blender):
    """A sheet, a sphere and a bowl cannot look the same.

    Each membrane is deleted before the next is built, and the view is framed
    once and then left alone, so the only variable between the three captures is
    the shape. A shape enum that is recorded but never reaches the base-mesh
    generator produces three identical pictures and is caught here; the headless
    lane checks ``pb_mem_shape`` and would stay green.
    """
    first = build_membrane(blender, shape=SHAPES[0], radius=15.0)
    blender.call("return R.frame_all()")
    blender.call("return R.capture(label=shape)", shape=SHAPES[0])
    delete_membrane(blender, first["root"])

    for shape in SHAPES[1:]:
        facts = build_membrane(blender, shape=shape, radius=15.0)
        metrics = blender.call("return R.capture(label=shape)", shape=shape)
        assert metrics["covered"] > 0, f"shape {shape!r} rendered nothing"
        delete_membrane(blender, facts["root"])

    for left, right in itertools.combinations(SHAPES, 2):
        diff = blender.call("return R.compare(left, right)",
                            left=left, right=right)
        assert not diff["identical"], (
            f"shapes {left!r} and {right!r} rendered identical images")


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("render_style", RENDER_STYLES)
def test_every_render_style_renders_lipids(blender, shot, render_style):
    """Each style feeds the modifier from a different lipid collection.

    A style whose collection fails to append leaves the modifier with an empty
    Lipid Collection input: the base patch is untouched, the operator reports
    success, and nothing is drawn. That is invisible to a vertex count and
    obvious in a render.
    """
    facts = build_membrane(blender, render_style=render_style)
    assert facts["render_style"] == render_style

    stats = lipid_stats(blender, facts["root"])
    assert stats["count"] > 0, (
        f"render style {render_style!r} placed no lipid instances")

    metrics = shot(render_style)
    assert metrics["covered"] > 0, (
        f"render style {render_style!r} rendered nothing")


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.slow
def test_render_styles_are_visually_distinct(blender):
    """Surface, stylized and ball-and-stick draw the same lipid three ways.

    Same shape, same size, same framing throughout, so identical captures can
    only mean the style never changed which collection was instanced.
    """
    first = build_membrane(blender, render_style=RENDER_STYLES[0])
    blender.call("return R.frame_all()")
    blender.call("return R.capture(label=style)", style=RENDER_STYLES[0])
    delete_membrane(blender, first["root"])

    for style in RENDER_STYLES[1:]:
        facts = build_membrane(blender, render_style=style)
        metrics = blender.call("return R.capture(label=style)", style=style)
        assert metrics["covered"] > 0, f"style {style!r} rendered nothing"
        delete_membrane(blender, facts["root"])

    for left, right in itertools.combinations(RENDER_STYLES, 2):
        diff = blender.call("return R.compare(left, right)",
                            left=left, right=right)
        assert not diff["identical"], (
            f"render styles {left!r} and {right!r} rendered identical images")


# ---------------------------------------------------------------------------
# Size, density, thickness
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_resize_widens_the_evaluated_membrane(blender):
    """Widening the patch must move lipids, not just the invisible base grid.

    The headless lane measures the base mesh, which the resize operator rebuilds
    directly. Measuring the evaluated lipid instances instead means the
    assertion only passes if the change propagated all the way through the
    geometry-nodes tree to the things a user can see, and the render has to move
    with it.
    """
    facts = build_membrane(blender, width=20.0, height=20.0)
    root = facts["root"]
    before = lipid_stats(blender, root)
    assert before["count"] > 0
    blender.call("return R.frame_all()")
    blender.call('return R.capture("narrow")')

    resized = blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.context.scene.membrane_builder_props.width = 40.0
            return sorted(bpy.ops.proteinblender.resize_membrane())
    """, name=root)
    assert resized == ["FINISHED"], f"resize_membrane returned {resized}"

    after = lipid_stats(blender, root)
    assert after["x_extent"] > before["x_extent"] * 1.5, (
        f"doubling the width moved the lipid field from {before['x_extent']:.3f} "
        f"to {after['x_extent']:.3f} BU; the resize did not reach the lipids")
    assert after["y_extent"] == pytest.approx(before["y_extent"], rel=0.15), (
        f"the height was left alone but the lipid field's Y extent moved from "
        f"{before['y_extent']:.3f} to {after['y_extent']:.3f}")

    blender.call('return R.capture("wide")')
    diff = blender.call('return R.compare("narrow", "wide")')
    assert not diff["identical"], "resizing the membrane did not change the render"


@pytest.mark.live
def test_higher_density_packs_in_more_lipids(blender):
    """Density is lipids per nm squared, so raising it must add lipids.

    Monotonicity is the whole claim, and it is a property of the physical
    quantity the slider names. No absolute count is asserted, because the exact
    number depends on the point-distribution seed.
    """
    facts = build_membrane(blender, density=0.5)
    root = facts["root"]
    sparse = lipid_stats(blender, root)
    assert sparse["count"] > 0

    blender.call(ACTIVATE, name=root)
    blender.call(SET_PROPS, settings={"density": 2.5})
    dense = lipid_stats(blender, root)

    assert dense["count"] > sparse["count"], (
        f"raising density from 0.5 to 2.5 lipids/nm^2 changed the instance "
        f"count from {sparse['count']} to {dense['count']}; the slider is not "
        "reaching the distribution")


@pytest.mark.live
def test_a_thicker_bilayer_spans_more_z(blender):
    """Thickness is measured head-group to head-group, so it is a Z span.

    The two leaflets are what separate, so the invariant is the Z extent of the
    lipid field. A thickness value that is stored but never fed to the leaflet
    offset leaves the span unchanged.
    """
    facts = build_membrane(blender, bilayer_thickness=3.0)
    root = facts["root"]
    thin = lipid_stats(blender, root)
    assert thin["count"] > 0

    blender.call(ACTIVATE, name=root)
    blender.call(SET_PROPS, settings={"bilayer_thickness": 9.0})
    thick = lipid_stats(blender, root)

    assert thick["z_extent"] > thin["z_extent"], (
        f"tripling the bilayer thickness left the lipid field spanning "
        f"{thick['z_extent']:.4f} BU against {thin['z_extent']:.4f} before; "
        "the slider is not separating the leaflets")


# ---------------------------------------------------------------------------
# Holes
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_a_hole_removes_covered_geometry(blender):
    """A hole must take lipids out of the membrane, and out of the picture.

    Framed orthographically from straight above, a flat bilayer covers a solid
    block of pixels and a hole is a genuine gap with nothing behind it, so
    covered pixels have to fall. The lipid instance count has to fall with them:
    a hole that only hides lipids from one viewing angle would satisfy the pixel
    check alone.

    This is the assertion the headless lane cannot make at all. Holes are carved
    inside the geometry-nodes tree, so the base mesh it measures is byte
    identical before and after.
    """
    facts = build_membrane(blender, shape="FLAT", width=20.0, height=20.0)
    root = facts["root"]
    previous_view = blender.call(TOP_VIEW)
    try:
        blender.call("return R.frame_all()")

        solid_pixels = blender.call('return R.capture("solid")')
        solid = lipid_stats(blender, root)
        assert solid_pixels["covered"] > 0 and solid["count"] > 0

        added = blender.call("""
            with R.view3d_override():
                H.select_only(bpy.data.objects[name])
                return sorted(bpy.ops.proteinblender.membrane_add_hole())
        """, name=root)
        assert added == ["FINISHED"], f"membrane_add_hole returned {added}"
        assert len(blender.call(HOLE_NAMES, name=root)) == 1

        holed_pixels = blender.call('return R.capture("holed")')
        holed = lipid_stats(blender, root)
    finally:
        blender.call(RESTORE_VIEW, previous=previous_view)

    # A hole does NOT delete lipids, it pushes them radially outwards - see
    # the GN tree version log, "holes redistribute lipids (radial push)
    # instead of deleting them". So the count is expected to be unchanged and
    # asserting on it tests the opposite of the design. What must change is
    # where the lipids are: the hole has to be empty.
    assert holed["count"] == solid["count"], (
        f"the lipid count changed from {solid['count']} to {holed['count']}; "
        "a hole should displace lipids, not delete them")
    assert holed["clearance_nm"] > solid["clearance_nm"] + 1.0, (
        f"the nearest lipid to the hole centre only moved from "
        f"{solid['clearance_nm']:.2f} nm to {holed['clearance_nm']:.2f} nm; "
        "the hole is not pushing lipids aside")
    assert holed["inside_hole"] == 0, (
        f"{holed['inside_hole']} lipids are still standing inside the hole")
    assert holed_pixels["covered"] < solid_pixels["covered"], (
        f"seen from directly above, the membrane still covers "
        f"{holed_pixels['covered']} pixels against {solid_pixels['covered']} "
        "before the hole; the hole is not visible")


@pytest.mark.live
def test_a_bigger_hole_clears_a_wider_patch(blender):
    """The panel's per-hole radius slider drives the empty's scale.

    Growing the radius must clear a wider patch. A radius stored on the empty
    but never read by the geometry-nodes tree leaves the clearing the same size,
    which no state-based assertion would notice.

    Measured as the distance from the hole centre to the nearest surviving
    lipid, because the lipid *count* is deliberately constant: the tree pushes
    lipids out of the hole rather than deleting them.
    """
    facts = build_membrane(blender, shape="FLAT", width=20.0, height=20.0)
    root = facts["root"]
    blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            bpy.ops.proteinblender.membrane_add_hole()
    """, name=root)
    small = lipid_stats(blender, root)

    blender.call("""
        hole = bpy.data.objects[name]
        radius = hole.scale.x * 1.8
        hole.scale = (radius, radius, radius)
        bpy.context.view_layer.update()
        return radius
    """, name=blender.call(HOLE_NAMES, name=root)[0])

    big = lipid_stats(blender, root)
    assert big["clearance_nm"] > small["clearance_nm"] * 1.3, (
        f"widening the hole moved the nearest lipid from "
        f"{small['clearance_nm']:.2f} nm to only {big['clearance_nm']:.2f} nm; "
        "the radius is not reaching the geometry")
    assert big["count"] == small["count"], (
        "widening the hole changed the lipid count; it should only move them")


@pytest.mark.live
def test_holes_can_be_added_selected_and_removed(blender):
    """The full hole lifecycle, ending where it started.

    Removing the hole must restore the lipid field exactly: the distribution is
    seeded rather than random, so a leftover difference means the removal left
    the hole's slot still carving.
    """
    facts = build_membrane(blender, shape="FLAT", width=20.0, height=20.0)
    root = facts["root"]
    pristine = lipid_stats(blender, root)

    for _ in range(2):
        blender.call("""
            with R.view3d_override():
                H.select_only(bpy.data.objects[owner])
                bpy.ops.proteinblender.membrane_add_hole()
        """, owner=root)
    holes = blender.call(HOLE_NAMES, name=root)
    assert len(holes) == 2, f"expected two holes, got {holes}"

    # Never hold an object across an operator call: names are captured, the
    # operator runs, and the state is re-read afterwards.
    active = blender.call("""
        with R.view3d_override():
            bpy.ops.proteinblender.membrane_select_hole(hole_name=hole)
            obj = bpy.context.view_layer.objects.active
            return {"active": obj.name if obj else "",
                    "selected": obj.select_get() if obj else False}
    """, hole=holes[0])
    assert active["active"] == holes[0], (
        f"selecting hole {holes[0]!r} made {active['active']!r} active instead")
    assert active["selected"] is True

    for hole in holes:
        blender.call("""
            with R.view3d_override():
                H.select_only(bpy.data.objects[owner])
                bpy.ops.proteinblender.membrane_remove_hole(hole_name=hole)
        """, owner=root, hole=hole)

    assert blender.call(HOLE_NAMES, name=root) == []
    restored = lipid_stats(blender, root)
    assert restored["count"] == pristine["count"], (
        f"after removing both holes the membrane has {restored['count']} "
        f"lipids against {pristine['count']} before they were added; a removed "
        "hole is still carving")


@pytest.mark.live
@pytest.mark.slow
def test_the_hole_cap_is_enforced(blender):
    """Eight holes fit; the ninth must be refused, not silently dropped.

    The geometry-nodes tree has a fixed number of hole slots, so a ninth hole
    that appeared to be created would be a controller carving nothing - worse
    than a refusal, because the panel would count it.
    """
    facts = build_membrane(blender, shape="FLAT", width=30.0, height=30.0)
    root = facts["root"]

    results = []
    for _ in range(MAX_HOLES + 1):
        results.append(blender.call("""
            with R.view3d_override():
                H.select_only(bpy.data.objects[owner])
                return sorted(bpy.ops.proteinblender.membrane_add_hole())
        """, owner=root))

    assert results[:MAX_HOLES] == [["FINISHED"]] * MAX_HOLES, (
        f"the first {MAX_HOLES} holes were not all accepted: {results}")
    assert results[MAX_HOLES] == ["CANCELLED"], (
        f"hole number {MAX_HOLES + 1} returned {results[MAX_HOLES]} instead of "
        "being refused")
    assert len(blender.call(HOLE_NAMES, name=root)) == MAX_HOLES


# ---------------------------------------------------------------------------
# Deformation reset
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_reset_deform_returns_the_membrane_to_its_rest_shape(blender):
    """Reset must undo a lattice deformation all the way to the pixels.

    The lattice point is displaced directly, which is what grabbing it in
    lattice edit mode does. The proof that reset worked is that the render
    matches the pre-deformation capture again, not that ``co_deform`` was
    reassigned - a reset that fixed the lattice data while leaving the modifier
    stale would pass the data check and still look wrong.

    The deformed capture in the middle is what stops this being vacuous: if the
    lattice never bent the membrane in the first place, there was nothing to
    reset and the two matching captures would prove nothing.
    """
    facts = build_membrane(blender, shape="FLAT", width=20.0, height=20.0)
    root = facts["root"]
    blender.call("return R.frame_all()")
    blender.call('return R.capture("rest")')

    blender.call("""
        root = bpy.data.objects[name]
        lattice = next(c for c in root.children if c.type == "LATTICE")
        point = lattice.data.points[0]
        point.co_deform = (point.co[0], point.co[1], point.co[2] + 2.0)
        bpy.context.view_layer.update()
        return lattice.name
    """, name=root)
    blender.call('return R.capture("deformed")')

    bent = blender.call('return R.compare("rest", "deformed")')
    assert not bent["identical"], (
        "displacing a lattice point did not change the render, so this test "
        "cannot show that reset undid anything")

    result = blender.call("""
        with R.view3d_override():
            H.select_only(bpy.data.objects[name])
            return sorted(bpy.ops.proteinblender.membrane_reset_deform())
    """, name=root)
    assert result == ["FINISHED"]

    at_rest = blender.call("""
        root = bpy.data.objects[name]
        lattice = next(c for c in root.children if c.type == "LATTICE")
        return max(max(abs(d - c) for d, c in zip(p.co_deform, p.co))
                   for p in lattice.data.points)
    """, name=root)
    assert at_rest == pytest.approx(0.0, abs=1e-5), (
        f"a lattice point is still {at_rest} from its rest position after reset")

    blender.call('return R.capture("restored")')
    restored = blender.call('return R.compare("rest", "restored")')
    assert restored["iou"] > 0.999 and restored["rgb_delta"] < 0.01, (
        f"after reset the membrane does not render as it did at rest "
        f"(iou {restored['iou']}, rgb delta {restored['rgb_delta']})")


# ---------------------------------------------------------------------------
# Colour
#
# The headless lane cannot check any of this: it reduces every render to an
# alpha mask and throws the RGB channels away.
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_the_lipid_surface_colour_reaches_the_render(blender):
    """A red membrane must read redder than a blue one.

    Two membranes built in turn at the same place with the same framing, so the
    only difference is the colour that was asked for. Only the ordering of the
    channels is asserted, never their values, so viewport lighting cannot make
    or break it.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")

    facts = build_membrane(blender, render_style="SURFACE", color_surface=RED)
    blender.call("return R.frame_all()")
    red = blender.call('return R.capture("red")')
    delete_membrane(blender, facts["root"])

    build_membrane(blender, render_style="SURFACE", color_surface=BLUE)
    blue = blender.call('return R.capture("blue")')

    assert red["covered"] > 0 and blue["covered"] > 0
    assert red["mean_rgb"][0] > red["mean_rgb"][2], (
        f"a membrane asked to be red rendered mean RGB {red['mean_rgb']}")
    assert blue["mean_rgb"][2] > blue["mean_rgb"][0], (
        f"a membrane asked to be blue rendered mean RGB {blue['mean_rgb']}")

    diff = blender.call('return R.compare("red", "blue")')
    assert diff["rgb_delta"] > 0.0, (
        "the lipid colour never reached the rendered membrane")


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.slow
def test_head_and_tail_colours_each_reach_the_render(blender):
    """Head and tail are separately coloured in the stylized style.

    Each swatch is varied on its own against a dark constant for the other, so a
    head colour wired to the tail material, or to nothing, cannot hide behind
    the other swatch changing at the same time.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")

    for index, (label, settings) in enumerate([
        ("head-red", {"color_head": RED, "color_tail": DARK_GREY}),
        ("head-blue", {"color_head": BLUE, "color_tail": DARK_GREY}),
        ("tail-red", {"color_head": DARK_GREY, "color_tail": RED}),
        ("tail-blue", {"color_head": DARK_GREY, "color_tail": BLUE}),
    ]):
        facts = build_membrane(blender, render_style="STYLIZED", **settings)
        if index == 0:
            blender.call("return R.frame_all()")
        metrics = blender.call("return R.capture(label=label)", label=label)
        assert metrics["covered"] > 0, f"{label} rendered nothing"
        delete_membrane(blender, facts["root"])

    for part in ("head", "tail"):
        diff = blender.call("return R.compare(left, right)",
                            left=f"{part}-red", right=f"{part}-blue")
        assert diff["rgb_delta"] > 0.0, (
            f"changing only the lipid {part} colour from red to blue left the "
            "render unchanged; that swatch is not connected to a material")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_deleting_a_membrane_clears_it_from_the_scene_and_the_screen(blender,
                                                                     shot):
    """Delete must take the root, its children and every pixel with it.

    An empty scene renders zero covered pixels - that is the calibration
    ``test_live_harness`` establishes - so returning to zero is a complete
    statement that nothing was left behind, including instanced lipids that
    never appear in ``bpy.data.objects`` at all.
    """
    facts = build_membrane(blender)
    root, children = facts["root"], facts["children"]
    assert children, "membrane had no children to check the cascade against"
    assert shot("built")["covered"] > 0

    result = delete_membrane(blender, root)
    assert result == ["FINISHED"], f"delete_membrane returned {result}"

    survivors = blender.call("""
        return [n for n in [root] + children if bpy.data.objects.get(n) is not None]
    """, root=root, children=children)
    assert survivors == [], f"these objects survived the delete: {survivors}"

    empty = shot("deleted", frame=False)
    assert empty["covered"] == 0, (
        f"after deleting the membrane the viewport still shows "
        f"{empty['covered']} covered pixels")


# ---------------------------------------------------------------------------
# Per-protein force fields
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_a_protein_force_field_parts_the_lipids_around_it(blender, single_chain):
    """The claim the feature makes: the bilayer parts around the protein.

    Measured as the distance from the force-field anchor to the nearest lipid
    Blender actually evaluated. With the field on that distance must be larger
    than with it off, which is what "parts around it" means and what neither the
    ``pb_force_field_enabled`` flag nor the anchor's existence can tell you.

    The anchor's world position is read once, while the field is on, and reused
    as the reference point for both measurements, so the two numbers are
    distances to the same place.

    The protein is first dragged onto the bilayer midplane, the way a user
    would, by offsetting its location so the anchor lands at the world origin.
    An imported structure sits wherever its PDB coordinates put it, which may be
    clear of the membrane entirely, and a force field that never overlaps any
    lipid would leave nothing to measure.
    """
    facts = build_membrane(blender, shape="FLAT", width=20.0, height=20.0)
    root = facts["root"]

    enabled = blender.call("""
        scene = bpy.context.scene
        for item in scene.outliner_items:
            item.is_selected = (item.item_type == "PROTEIN"
                                and item.item_id == molecule_id)
        with R.view3d_override():
            result = bpy.ops.proteinblender.toggle_force_fields(target_state="on")
        obj = H.sm().molecules[molecule_id].object
        anchor = bpy.data.objects.get(obj.name + ".ff_anchor")
        if anchor is not None:
            obj.location = obj.location - anchor.matrix_world.translation
            bpy.context.view_layer.update()
        # The anchor is deliberately NOT parented: parenting a molecule failed
        # to carry the owner's Z to the child, so the anchor is repositioned to
        # the owner's world centre on every FF apply / membrane refresh instead.
        return {
            "result": sorted(result),
            "object": obj.name,
            "flag": bool(obj.pb_force_field_enabled),
            "anchor": list(anchor.matrix_world.translation) if anchor else None,
        }
    """, molecule_id=single_chain)

    assert enabled["result"] == ["FINISHED"]
    assert enabled["flag"] is True, "the force-field flag did not turn on"
    assert enabled["anchor"] is not None, "no force-field anchor Empty was created"

    anchor_point = enabled["anchor"]
    with_field = lipid_stats(blender, root, origin=anchor_point)

    disabled = blender.call("""
        scene = bpy.context.scene
        for item in scene.outliner_items:
            item.is_selected = (item.item_type == "PROTEIN"
                                and item.item_id == molecule_id)
        with R.view3d_override():
            result = bpy.ops.proteinblender.toggle_force_fields(target_state="off")
        obj = H.sm().molecules[molecule_id].object
        return {
            "result": sorted(result),
            "flag": bool(obj.pb_force_field_enabled),
            "anchor_left": bpy.data.objects.get(obj.name + ".ff_anchor") is not None,
        }
    """, molecule_id=single_chain)

    assert disabled["result"] == ["FINISHED"]
    assert disabled["flag"] is False, "the force-field flag did not turn off"
    assert disabled["anchor_left"] is False, (
        "the anchor Empty survived after the force field was disabled")

    without_field = lipid_stats(blender, root, origin=anchor_point)

    assert with_field["min_distance"] > without_field["min_distance"], (
        f"with the force field on the nearest lipid sits "
        f"{with_field['min_distance']:.4f} BU from the protein, against "
        f"{without_field['min_distance']:.4f} BU with it off; the membrane is "
        "not parting around the protein")


@pytest.mark.live
@pytest.mark.visual
def test_a_force_field_only_parts_the_membrane_when_it_is_near_it(blender,
                                                                  single_chain):
    """A protein far above or below the sheet must leave the lipids alone.

    A force field is a 3D body: it parts the bilayer when the protein is
    embedded in it and lets it close as the protein floats away. The FLAT
    pusher shrinks each hole by the sphere's cross-section at the leaflet's
    height (radius = sqrt(R**2 - dz**2)), so a protein lifted more than its own
    radius off the sheet should carve nothing - but only if the force-field
    anchor carries the protein's Z. It did not: the anchor was never given a
    height (a molecule renders as a point cloud, so the centroid helper that
    was meant to place it measured no vertices and left it at the origin), so a
    protein 200 nm up still bored a hole straight down.

    Observed through a fixed top-down render, not instance matrices: the
    membrane's evaluated geometry is what the renderer sees, and reading it back
    as raw instance transforms over the socket does not reliably reflect a
    just-moved anchor, while a render forces a full evaluation. The protein is
    hidden so only the membrane, and any hole in it, is measured.
    """
    build_membrane(blender, shape="FLAT", width=20.0, height=20.0)

    blender.call("""
        obj = H.sm().molecules[molecule_id].object
        obj.hide_viewport = True
        obj.hide_render = True
        obj.pb_force_field_enabled = True
        obj.pb_force_field_spacing = 2.0
        import sys
        ff = sys.modules["proteinblender.membrane_builder.force_fields"]
        ff.apply_to_all_membranes(bpy.context.scene)
        # Drop the protein so its force field sits over the membrane centre.
        anchor = bpy.data.objects.get(obj.name + ".ff_anchor")
        if anchor is not None:
            obj.location = obj.location - anchor.matrix_world.translation
        bpy.context.view_layer.update()
        return True
    """, molecule_id=single_chain)

    # Fix a top-down orthographic view once, so both captures share framing.
    blender.call("""
        from mathutils import Euler
        window, area, region = R.find_view3d()
        region_3d = area.spaces.active.region_3d
        with R.view3d_override():
            bpy.ops.view3d.view_all()
        region_3d.view_perspective = "ORTHO"
        region_3d.view_rotation = Euler((0, 0, 0), "XYZ").to_quaternion()
        return True
    """)

    def coverage_at_height(z_bu, label):
        blender.call("""
            obj = H.sm().molecules[molecule_id].object
            obj.location = (0.0, 0.0, z_bu)
            bpy.context.view_layer.update()
            import sys
            ff = sys.modules["proteinblender.membrane_builder.force_fields"]
            ff.apply_to_all_membranes(bpy.context.scene)
            for _ in range(4):
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            return True
        """, molecule_id=single_chain, z_bu=z_bu)
        return blender.call("return R.capture(label, resolution=420)",
                            label=label)

    embedded = coverage_at_height(0.0, "ff-embedded")
    lifted = coverage_at_height(20.0, "ff-lifted")  # 200 nm above

    # Embedded, the field bores a hole, so fewer lipids are on screen. Lifted
    # far clear, the hole closes and coverage returns. A hole in a 20 nm sheet
    # is a small fraction of the frame, so the margin is modest but consistent.
    assert lifted["covered"] > embedded["covered"], (
        f"a protein 200 nm above the membrane still carved it: coverage "
        f"{lifted['covered']} lifted vs {embedded['covered']} embedded - the "
        "hole did not close, so the force field is ignoring Z and acting as an "
        "infinite vertical column.")


def test_wider_force_field_spacing_opens_a_wider_gap(blender, single_chain):
    """Spacing is extra clearance in nm beyond the protein's own radius.

    More clearance must push the nearest lipid further away. Both measurements
    are taken against the same anchor point with the field on throughout, so the
    only variable is the slider.
    """
    facts = build_membrane(blender, shape="FLAT", width=20.0, height=20.0)
    root = facts["root"]

    anchor_point = blender.call("""
        scene = bpy.context.scene
        for item in scene.outliner_items:
            item.is_selected = (item.item_type == "PROTEIN"
                                and item.item_id == molecule_id)
        with R.view3d_override():
            bpy.ops.proteinblender.toggle_force_fields(target_state="on")
        obj = H.sm().molecules[molecule_id].object
        obj.pb_force_field_spacing = 1.0
        anchor = bpy.data.objects.get(obj.name + ".ff_anchor")
        if anchor is None:
            return None
        # Drag the protein onto the bilayer midplane so the field has lipids
        # to act on, exactly as a user positions a membrane protein.
        obj.location = obj.location - anchor.matrix_world.translation
        bpy.context.view_layer.update()
        return list(anchor.matrix_world.translation)
    """, molecule_id=single_chain)
    assert anchor_point is not None, "no force-field anchor to measure against"

    narrow = lipid_stats(blender, root, origin=anchor_point)

    blender.call("""
        obj = H.sm().molecules[molecule_id].object
        obj.pb_force_field_spacing = 6.0
        bpy.context.view_layer.update()
        return obj.pb_force_field_spacing
    """, molecule_id=single_chain)

    wide = lipid_stats(blender, root, origin=anchor_point)

    assert wide["min_distance"] > narrow["min_distance"], (
        f"raising the force-field spacing from 1 nm to 6 nm left the nearest "
        f"lipid at {wide['min_distance']:.4f} BU against "
        f"{narrow['min_distance']:.4f} BU before; the spacing slider is not "
        "reaching the membrane")


# ---------------------------------------------------------------------------
# Lipid orientation
#
# These exist because the suite once had 16 of 18 membrane tests green over
# geometry that was obviously wrong to the eye. Every assertion above this point
# asks whether lipids *exist*, whether shapes *differ*, whether colour *reaches*
# the render. None of them asked which way a lipid points, so a bilayer whose
# every lipid lay on the (1,1,1) diagonal, with the two leaflets sheared apart
# and no membrane to speak of, passed them all.
#
# Ground truth here is independent of the add-on: a FLAT membrane lies in the XY
# plane, so its surface normal is world Z by construction. Nothing below reads
# the normal the product computed.
# ---------------------------------------------------------------------------

ORIENTATION = """
import numpy as np

deps = bpy.context.evaluated_depsgraph_get()
axes, origins = [], []
for inst in deps.object_instances:
    if not inst.is_instance:
        continue
    matrix = np.array(inst.matrix_world).reshape(4, 4)
    axis = matrix[:3, 2]
    length = float(np.linalg.norm(axis))
    if length == 0.0:
        continue
    axes.append(axis / length)
    origins.append(float(matrix[2, 3]))

if not axes:
    raise AssertionError("the membrane evaluated no lipid instances at all")

axes = np.array(axes)
origins = np.array(origins)
# Angle away from vertical, ignoring which end is up: a lower-leaflet lipid is
# the mirror of an upper-leaflet one, and both are correctly oriented.
tilt = np.degrees(np.arccos(np.clip(np.abs(axes[:, 2]), 0.0, 1.0)))
return {
    "count": int(len(axes)),
    "tilt_mean": float(tilt.mean()),
    "tilt_max": float(tilt.max()),
    "tilt_spread": float(tilt.max() - tilt.min()),
    "pointing_up": float((axes[:, 2] > 0).mean()),
    "origin_above": float((origins > 0).mean()),
}
"""


@pytest.mark.live
def test_lipids_stand_perpendicular_to_the_membrane_plane(blender):
    """Every lipid must point along the surface normal, not some fixed diagonal.

    A flat membrane lies in XY, so each lipid's long axis should be world Z to
    within a few degrees. This is the assertion the suite was missing: the
    Capture Attribute normal was being read out of the wrong socket on Blender
    5.2, which handed the aligner a boolean broadcast into a vector as (1, 1, 1)
    and tilted every lipid to exactly arccos(1/sqrt(3)) = 54.7356 degrees.

    54.7 degrees is called out by name below because a *constant* tilt is the
    real symptom. Randomly scattered lipids would be a different bug; a whole
    membrane agreeing on one wrong angle to seven significant figures is a
    mis-wired socket.
    """
    blender.call(BUILD, overrides={"shape": "FLAT", "width": 15, "height": 15})
    stats = blender.call(ORIENTATION)

    assert stats["count"] > 0
    assert stats["tilt_max"] < 5.0, (
        f"lipids are not standing up: worst tilt {stats['tilt_max']:.1f} deg "
        f"from the surface normal (mean {stats['tilt_mean']:.1f}). "
        "A constant 54.7 deg means the aligner received (1, 1, 1) instead of "
        "the captured normal - check the Capture Attribute socket lookup."
    )
    assert stats["tilt_spread"] < 5.0, (
        "lipid tilt varies wildly across the sheet "
        f"(spread {stats['tilt_spread']:.1f} deg)")


@pytest.mark.live
def test_the_two_leaflets_point_away_from_each_other(blender):
    """A bilayer is two opposed leaflets, not two copies of one.

    Roughly half the lipids must sit above the midplane and half below, and the
    two halves must point in opposite directions. If the lower leaflet were
    never negated it would render as a second upward-facing sheet, which looks
    almost right in a thumbnail and is not a membrane.
    """
    blender.call(BUILD, overrides={"shape": "FLAT", "width": 15, "height": 15})
    stats = blender.call(ORIENTATION)

    assert 0.35 < stats["origin_above"] < 0.65, (
        "the leaflets are not evenly populated: "
        f"{stats['origin_above']:.0%} of lipids sit above the midplane")
    assert 0.35 < stats["pointing_up"] < 0.65, (
        "the two leaflets do not oppose each other: "
        f"{stats['pointing_up']:.0%} of lipids point the same way")


@pytest.mark.live
def test_the_two_leaflets_sit_directly_above_each_other(blender):
    """The leaflets must be stacked, not sheared sideways.

    When the half-thickness offset was scaled along a broken (1, 1, 1) normal
    it displaced each leaflet diagonally, so the upper sheet slid sideways
    relative to the lower one by as much as it rose. From directly overhead
    that is invisible; edge-on it reads as two staggered mats. Comparing the
    two leaflets' XY centroids catches it without needing a particular view.
    """
    blender.call(BUILD, overrides={"shape": "FLAT", "width": 15, "height": 15})
    offset = blender.call("""
import numpy as np

deps = bpy.context.evaluated_depsgraph_get()
upper, lower = [], []
for inst in deps.object_instances:
    if not inst.is_instance:
        continue
    matrix = np.array(inst.matrix_world).reshape(4, 4)
    (upper if matrix[2, 3] > 0 else lower).append(matrix[:2, 3])

upper = np.array(upper)
lower = np.array(lower)
NM_PER_BU = 10.0
return {"dx_nm": float(abs(upper[:, 0].mean() - lower[:, 0].mean()) * NM_PER_BU),
        "dy_nm": float(abs(upper[:, 1].mean() - lower[:, 1].mean()) * NM_PER_BU),
        "half_width_nm": float(np.abs(upper[:, 0]).max() * NM_PER_BU)}
""")
    # Both leaflets sample the same patch, so their centroids coincide to
    # within sampling noise. The broken offset shifted them by the full
    # half-thickness, over a nanometre.
    assert offset["dx_nm"] < 0.3 and offset["dy_nm"] < 0.3, (
        "the leaflets are laterally offset from each other by "
        f"({offset['dx_nm']:.2f}, {offset['dy_nm']:.2f}) nm; they should be "
        "stacked directly on top of one another")


@pytest.mark.live
@pytest.mark.parametrize("requested", [4.0, 4.8])
def test_the_bilayer_is_as_thick_as_the_slider_says(blender, requested):
    """Rendered thickness must match the slider, with the tails still meeting.

    Both halves matter. Thickness alone passes even when the leaflets are
    sheared apart, and a closed midplane alone passes even when the sheet is
    the wrong size.

    The gap is measured from the *median* tail tip of each leaflet, not the
    extreme. The lipid variants differ in length (1.25 to 1.65 nm below their
    origin), so a global min/max is set by whichever single variant reaches
    furthest and reported a 0.06 nm gap on a membrane whose typical gap was
    0.28 nm and plainly showed a seam.
    """
    blender.call(BUILD, overrides={"shape": "FLAT", "width": 15, "height": 15,
                                   "bilayer_thickness": requested})
    span = blender.call("""
import numpy as np

deps = bpy.context.evaluated_depsgraph_get()
upper_lo, upper_hi, lower_lo, lower_hi = [], [], [], []
for inst in deps.object_instances:
    if not inst.is_instance:
        continue
    source = inst.object
    if source is None or source.type != "MESH" or not len(source.data.vertices):
        continue
    coords = np.empty(len(source.data.vertices) * 3, dtype=np.float64)
    source.data.vertices.foreach_get("co", coords)
    matrix = np.array(inst.matrix_world).reshape(4, 4)
    world_z = (coords.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])[:, 2]
    if matrix[2, 3] > 0:
        upper_lo.append(world_z.min()); upper_hi.append(world_z.max())
    else:
        lower_lo.append(world_z.min()); lower_hi.append(world_z.max())

NM_PER_BU = 10.0
return {"visible_nm": float((np.median(upper_hi) - np.median(lower_lo))
                            * NM_PER_BU),
        "gap_nm": float((np.median(upper_lo) - np.median(lower_hi))
                        * NM_PER_BU)}
""")

    assert abs(span["visible_nm"] - requested) < 0.4, (
        f"asked for a {requested} nm bilayer, rendered "
        f"{span['visible_nm']:.2f} nm")
    assert span["gap_nm"] < 0.15, (
        f"the leaflets leave a {span['gap_nm']:.2f} nm void down the midplane "
        "at the default thickness; their tails should meet so the hydrophobic "
        "core reads as solid")


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_the_surface_style_renders_close_to_its_configured_near_white(blender):
    """SURFACE is one near-white colour for the whole lipid, and must stay so.

    The default is a deliberate off-white (0.92): light enough to read as a
    pale membrane behind a coloured protein. A style that silently fell back to
    an unlit grey, or to the pink head colour, would still render and still
    pass every other test in this module.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")
    blender.call(BUILD, overrides={"shape": "FLAT", "width": 12, "height": 12,
                                   "render_style": "SURFACE"})
    blender.call("return R.frame_all()")
    metrics = blender.call("return R.viewport_metrics(resolution=300)")

    red, green, blue = metrics["mean_rgb"]
    assert min(red, green, blue) > 0.75, (
        f"the SURFACE lipids rendered at {metrics['mean_rgb']}, darker than "
        "the near-white this style configures")
    assert max(red, green, blue) - min(red, green, blue) < 0.12, (
        f"the SURFACE lipids rendered tinted ({metrics['mean_rgb']}); this "
        "style is a single neutral colour")


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("style", ["STYLIZED", "BALL_AND_STICK"])
def test_head_and_tail_colours_reach_the_render(blender, style):
    """Changing the head colour must change what is on screen, in that channel.

    The two-material styles are the only place head and tail can be told apart,
    and the property write reaching the material is not the same thing as the
    material reaching a pixel. This is the assertion the domain-colour bug
    taught us to write: drive the user-facing property, then look.

    The tail is pinned to a dark neutral both times so the head colour is the
    only thing that moves between the two builds.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")

    def build_and_measure(head_colour):
        blender.call(BUILD, overrides={"shape": "FLAT", "width": 12,
                                       "height": 12, "render_style": style,
                                       "color_head": head_colour,
                                       "color_tail": DARK_GREY})
        blender.call("return R.frame_all()")
        return blender.call("return R.viewport_metrics(resolution=300)")

    red = build_and_measure(RED)
    blue = build_and_measure(BLUE)

    assert red["dominant_channel"] == 0, (
        f"{style} with a red head rendered dominant channel "
        f"{red['dominant_channel']} ({red['mean_rgb']})")
    assert blue["dominant_channel"] == 2, (
        f"{style} with a blue head rendered dominant channel "
        f"{blue['dominant_channel']} ({blue['mean_rgb']})")
    assert red["mean_rgb"][0] > blue["mean_rgb"][0], (
        "making the head blue did not reduce red in the render")
