"""Pivot placement, observed in a live viewport.

The headless lane already proves *where* a pivot lands: ``tests/integration/
test_pivot.py`` validates First/Center/Last against coordinates parsed straight
out of the PDB with biotite. What it cannot prove is the other half of the
contract, because ``--background`` has no screen:

**Setting a pivot must not change a single rendered pixel.**

A pivot is an origin, not geometry. Moving it re-parameterises how the object
will rotate; it must leave the atoms exactly where they were. That invariant has
a real failure history in this repo - the pivot's Transform node is spliced into
the geometry path, and a mistake there either shifts the molecule or severs it
from its own node tree. ``tests/integration/test_rendering.py`` catches the
severed case ("did it render *anything*"), but a pivot that silently *translates*
the whole molecule still renders plenty of pixels and sails through.

So each test here does two things in sequence:

1. capture before and after, and require the images to be *identical* - that is
   the invariant a broken pivot violates;
2. rotate the object and capture again, and require First / Last / Center to
   produce *different* rotated images - that is what proves the pivot actually
   moved rather than the operator being a no-op. An assertion that only checks
   "nothing changed" is satisfied by an operator that does nothing at all.

Ground truth for placement is the PDB itself. ``H.pdb_amino_acid_cas`` re-parses
the fixture with biotite (so bound ions such as 1ATN's Ca2+, atom name "CA", are
excluded) and ``H.assert_world_points_match_residues`` compares via pairwise
distances, which are invariant under the unknown rigid+scale transform between
PDB Angstroms and Blender world space. Neither touches ProteinBlender code, so
neither can move together with a bug in it.

Coordinate rule (CLAUDE.md): a molecule/domain's pivot is carried on its
geometry-nodes modifier, not in mesh vertices, so raw mesh coordinates must be
mapped with ``core.domain_space.local_to_world`` and never with
``obj.matrix_world @ co``. Nothing here reads raw mesh coordinates: the tests
assert on ``obj.matrix_world.translation`` (which *is* the pivot's world
position by construction) and on rendered pixels, both of which already have the
pivot applied.
"""

from __future__ import annotations

import math
import time

import pytest


# ---------------------------------------------------------------------------
# Remote snippets
# ---------------------------------------------------------------------------
#
# Blender-side logic lives inline in these strings by design: tests/live/remote.py
# is shared infrastructure and must not grow a helper per test module.

# Resolve exactly one CHAIN outliner row by its author chain letter, and leave it
# as the only selected row.
#
# The chain letter is read from ``obj["chain_ids"]`` - the labels MolecularNodes
# stamps on the object at import - indexed by the numeric suffix of the row's
# item_id. That is deliberately independent of pivot_operators._chain_index_for_item,
# the helper the operators themselves use to answer the same question; deriving
# the target from the code under test is how a facade test gets written.
_SELECT_CHAIN = """
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)

target_id = ""
object_name = ""
for item in scene.outliner_items:
    if item.item_type != 'CHAIN' or not item.object_name:
        continue
    obj = bpy.data.objects.get(item.object_name)
    if obj is None:
        continue
    suffix = item.item_id.rsplit('_chain_', 1)[-1]
    try:
        index = int(suffix)
    except ValueError:
        continue
    labels = list(obj.get('chain_ids') or [])
    if index < len(labels) and labels[index] == letter:
        target_id = item.item_id
        object_name = item.object_name
        break

if not target_id:
    raise AssertionError(
        "no CHAIN row for chain %r; rows=%s"
        % (letter, [(i.item_type, i.item_id) for i in scene.outliner_items]))

# Clear first (a plain flag write, not a user action), then select the target
# through the public outliner operator the checkbox drives.
for item in scene.outliner_items:
    item.is_selected = False
with R.view3d_override():
    bpy.ops.proteinblender.outliner_select(item_id=target_id)

# Never hold a row across an operator call: outliner_select can rebuild
# scene.outliner_items, so re-resolve by id to confirm the selection took.
row = next((i for i in scene.outliner_items if i.item_id == target_id), None)
assert row is not None and row.is_selected, "chain row did not stay selected"
return {"item_id": target_id, "object_name": object_name}
"""

# Run one pivot operator against the current outliner selection and report the
# resulting origin. ``matrix_world.translation`` is Blender's own value and, per
# core/domain_space.py, is exactly the pivot's world position.
_RUN_PIVOT_OP = """
scene = bpy.context.scene
op = getattr(bpy.ops.proteinblender, operator)
with R.view3d_override():
    result = op()
bpy.context.view_layer.update()
obj = bpy.data.objects[object_name]
return {
    "result": sorted(result),
    "origin": [float(v) for v in obj.matrix_world.translation],
}
"""

# Rotate an object about its own origin (which is its pivot) by ``angle`` radians
# around Z, or reset it. Rotating is the only way to make a pivot's position
# observable in pixels: an unrotated object renders identically wherever its
# pivot sits, which is precisely the invariant asserted first.
_SET_ROTATION = """
obj = bpy.data.objects[object_name]
obj.rotation_euler = (0.0, 0.0, angle)
bpy.context.view_layer.update()
return [float(v) for v in obj.rotation_euler]
"""


def _select_chain(blender, letter: str) -> dict:
    return blender.call(_SELECT_CHAIN, letter=letter)


def _run_pivot(blender, operator: str, object_name: str) -> dict:
    return blender.call(_RUN_PIVOT_OP, operator=operator,
                        object_name=object_name)


def _rotate(blender, object_name: str, angle: float):
    return blender.call(_SET_ROTATION, object_name=object_name, angle=angle)


def _capture(blender, label: str) -> dict:
    return blender.call("return R.capture(label=label)", label=label)


def _compare(blender, left: str, right: str) -> dict:
    return blender.call("return R.compare(left, right)", left=left, right=right)


# ---------------------------------------------------------------------------
# The invariant: a pivot change is invisible
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("operator", [
    "set_pivot_first", "set_pivot_center", "set_pivot_last",
])
def test_setting_a_pivot_does_not_change_what_is_rendered(blender, actin,
                                                          operator):
    """Moving an origin must move nothing the user can see.

    The pivot is applied inside geometry nodes as a translate-by-minus-pivot,
    compensated by the object transform. If those two halves ever disagree the
    whole molecule slides across the viewport - visible instantly to a user,
    invisible to every assertion that only asks whether *some* geometry rendered.

    The comparison is deliberately exact on the alpha mask (``xor == 0``): the
    atoms must occupy the identical set of pixels. Color is allowed a hair of
    floating-point slack because the shading path re-evaluates, but nothing
    close to a real recolor.
    """
    chain = _select_chain(blender, "A")
    blender.call("return R.frame_all()")

    before = _capture(blender, "before")
    assert before["covered"] > 0, (
        "the molecule rendered nothing before the pivot change; this test "
        "cannot detect a shift in an already-empty frame")

    ran = _run_pivot(blender, operator, chain["object_name"])
    assert ran["result"] == ["FINISHED"], f"{operator} did not finish"

    # No re-framing between captures: re-framing would silently re-centre a
    # molecule that had genuinely moved and hide the very bug this catches.
    after = _capture(blender, "after")
    diff = _compare(blender, "before", "after")

    assert after["covered"] > 0, (
        f"{operator} blanked the render - the pivot Transform has severed the "
        f"geometry path")
    assert diff["xor"] == 0, (
        f"{operator} moved {diff['xor']} pixels of geometry. Setting a pivot "
        f"must relocate the origin only; the atoms must not move. "
        f"iou={diff['iou']}")
    assert diff["rgb_delta"] < 1e-3, (
        f"{operator} changed the rendered color (rgb_delta={diff['rgb_delta']}); "
        f"a pivot has no business touching shading")


# ---------------------------------------------------------------------------
# Proof that the pivot actually moved
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_rotation_about_first_center_last_produces_three_different_images(
        blender, actin):
    """The pivot is only observable through rotation - so rotate.

    "Nothing changed" is satisfied by an operator that does nothing, which is
    why the invisibility test above cannot stand alone. Here the same chain is
    rotated 90 degrees about each of the three pivots in turn. Because First,
    Center and Last are three genuinely different points on a real protein, the
    three rotated images must differ from each other. If any pair matches, that
    pair of pivots landed on the same place and one of the operators is a no-op.

    Ground truth is the geometry of rotation itself, not any value read out of
    the add-on: a rigid rotation about two distinct centres cannot produce the
    same image.
    """
    chain = _select_chain(blender, "A")
    name = chain["object_name"]
    blender.call("return R.frame_all()")

    metrics = {}
    for operator in ("set_pivot_first", "set_pivot_center", "set_pivot_last"):
        ran = _run_pivot(blender, operator, name)
        assert ran["result"] == ["FINISHED"], f"{operator} did not finish"

        _rotate(blender, name, math.pi / 2)
        metrics[operator] = _capture(blender, operator)
        _rotate(blender, name, 0.0)

        assert metrics[operator]["covered"] > 0, (
            f"rotating about the {operator} pivot rendered nothing")

    pairs = [
        ("set_pivot_first", "set_pivot_center"),
        ("set_pivot_center", "set_pivot_last"),
        ("set_pivot_first", "set_pivot_last"),
    ]
    for left, right in pairs:
        diff = _compare(blender, left, right)
        assert diff["xor"] > 0, (
            f"rotating about {left} and about {right} produced identical "
            f"images (iou={diff['iou']}). Those two pivots are at the same "
            f"point, so at least one of the operators did not move it.")


@pytest.mark.live
def test_first_center_last_land_on_the_residues_the_pdb_says_they_should(
        blender, actin):
    """Placement, re-checked in the live/deployed add-on.

    The headless lane owns this assertion, but the live Blender runs the
    *deployed* add-on from a normal Blender profile rather than the repo, which
    CLAUDE.md requires a change to be proven in. A packaging mistake that ships
    a stale pivot module would pass the headless suite and fail only here.

    Truth comes from biotite parsing 1atn.pdb, compared through pairwise
    distances so it is invariant to the scale and re-centring MolecularNodes
    applies at import. 1ATN is the right fixture because chain A binds a Ca2+
    ion whose atom name is literally "CA": a naive alpha-carbon filter picks it
    up, it holds the highest res_id in the chain, and "Last" then lands in the
    middle of the protein instead of at the C-terminus. biotite's
    filter_amino_acids excludes it, so this comparison fails loudly if the
    add-on ever reintroduces that confusion.

    The comparison runs inside Blender (that is where both the origins and
    biotite live) but its verdict is returned as a message and asserted here, so
    a failure reads as a test failure rather than a transport error.
    """
    chain = _select_chain(blender, "A")
    name = chain["object_name"]

    origins = {}
    for label, operator in (("first", "set_pivot_first"),
                            ("center", "set_pivot_center"),
                            ("last", "set_pivot_last")):
        ran = _run_pivot(blender, operator, name)
        assert ran["result"] == ["FINISHED"]
        origins[label] = ran["origin"]

    verdict = blender.call("""
import numpy as np

cas = H.pdb_amino_acid_cas("1atn.pdb", "A")
residues = sorted(cas)
truth = {
    "first": cas[residues[0]],
    "center": tuple(np.mean([cas[r] for r in residues], axis=0)),
    "last": cas[residues[-1]],
}
try:
    H.assert_world_points_match_residues(origins, truth)
except AssertionError as exc:
    return str(exc)
return ""
""", origins=origins)

    assert verdict == "", verdict

    # Distinctness, so a degenerate "all three returned the same point" cannot
    # satisfy the distance comparison by collapsing every pair to zero.
    def gap(a, b):
        return math.dist(origins[a], origins[b])

    assert gap("first", "last") > 1e-3, "First and Last coincide"
    assert gap("center", "first") > 1e-3, "Center and First coincide"
    assert gap("center", "last") > 1e-3, "Center and Last coincide"


@pytest.mark.live
def test_pivot_operators_refuse_when_nothing_is_selected(blender, actin):
    """The operators read their targets from the outliner selection.

    With nothing selected they must cancel, not silently move the last thing
    they touched.
    """
    result = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
for item in scene.outliner_items:
    item.is_selected = False
with R.view3d_override():
    return {
        "first": sorted(bpy.ops.proteinblender.set_pivot_first()),
        "center": sorted(bpy.ops.proteinblender.set_pivot_center()),
        "last": sorted(bpy.ops.proteinblender.set_pivot_last()),
    }
""")
    assert result == {"first": ["CANCELLED"], "center": ["CANCELLED"],
                      "last": ["CANCELLED"]}


# ---------------------------------------------------------------------------
# The domain-level pivot operators (Domain panel, not the outliner buttons)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_snap_pivot_to_residue_moves_the_origin_without_moving_the_atoms(
        blender, actin):
    """``molecule.snap_pivot_to_residue`` START vs END.

    A different code path from the outliner's First/Last: it addresses a domain
    by id and resolves the alpha carbon through the molecule wrapper rather than
    through ``_collect_chain_filtered_alphas``. It therefore needs its own proof
    of the same two properties - the render must not move, and START and END
    must reach two different places.

    The START/END separation is asserted against chain A's residue span read
    out of ``1atn.pdb`` with biotite, which no add-on code touches: a chain
    spanning many residues cannot have its first and last alpha carbons at the
    same point. (It used to be read off a DOMAIN outliner row, but an unsplit
    chain has no such row - it draws as a CHAIN - so that lookup found nothing
    and the test died before it asserted anything.)
    """
    setup = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
manager = H.sm()
molecule = manager.molecules["1atn"]
scene.selected_molecule_id = "1atn"

domain_id, domain = next(
    (did, d) for did, d in molecule.domains.items() if d.chain_id == "A")
residues = sorted(H.pdb_amino_acid_cas("1atn.pdb", "A"))
return {
    "domain_id": domain_id,
    "object_name": domain.object.name,
    "span": [residues[0], residues[-1]],
}
""")
    assert setup["span"][1] > setup["span"][0] + 10, (
        "fixture changed: chain A no longer spans enough residues for START "
        "and END to be meaningfully different")

    blender.call("return R.frame_all()")
    before = _capture(blender, "before")
    assert before["covered"] > 0

    origins = {}
    for target in ("START", "END"):
        origins[target] = blender.call("""
scene = bpy.context.scene
with R.view3d_override():
    result = bpy.ops.molecule.snap_pivot_to_residue(
        domain_id=domain_id, target_residue=target)
bpy.context.view_layer.update()
obj = bpy.data.objects[object_name]
return {
    "result": sorted(result),
    "origin": [float(v) for v in obj.matrix_world.translation],
}
""", domain_id=setup["domain_id"], target=target,
             object_name=setup["object_name"])
        assert origins[target]["result"] == ["FINISHED"], (
            f"snap_pivot_to_residue({target}) did not finish")

    after = _capture(blender, "after")
    diff = _compare(blender, "before", "after")
    assert after["covered"] > 0, "snapping the pivot blanked the render"
    assert diff["xor"] == 0, (
        f"snap_pivot_to_residue moved {diff['xor']} pixels of geometry; a "
        f"pivot change must be invisible")

    separation = math.dist(origins["START"]["origin"], origins["END"]["origin"])
    assert separation > 1e-3, (
        f"START and END snapped to the same point ({separation:.6f} apart) "
        f"across residues {setup['span'][0]}-{setup['span'][1]}; the target "
        f"argument is being ignored")


@pytest.mark.live
@pytest.mark.visual
def test_snap_protein_pivot_center_is_invisible_and_lands_inside_the_molecule(
        blender, single_chain):
    """``molecule.snap_protein_pivot_center`` moves the whole protein's origin.

    Ground truth is what Blender itself evaluated and drew: the atoms come back
    as point-cloud instances off the depsgraph, mapped by each instance's own
    ``matrix_world``. A "centre" that falls outside the geometry it is meant to
    be the centre of is wrong regardless of how it was computed, and nothing in
    that reading goes through the add-on's coordinate helpers.

    It has to be read that way. ``helpers.eval_positions`` (``to_mesh()``)
    returns *zero* vertices for a molecule or domain object - MolecularNodes
    emits a point cloud, not a mesh - and the molecule object itself evaluates
    to an empty one: the atoms are drawn by its chain domains. Measuring the
    parent alone therefore measured nothing at all.
    """
    blender.call("return R.frame_all()")
    before = _capture(blender, "before")
    assert before["covered"] > 0

    result = blender.call("""
molecule = H.sm().molecules["1ubq"]
obj = molecule.object
with R.view3d_override():
    outcome = bpy.ops.molecule.snap_protein_pivot_center(molecule_id="1ubq")
bpy.context.view_layer.update()

# Every object the protein draws through: the molecule object and its domains.
drawn = [obj] + [d.object for d in molecule.domains.values() if d.object]
world = H.evaluated_atom_positions(drawn)
if not len(world):
    raise AssertionError(
        "the protein evaluated to no drawable atoms, so there is nothing to "
        "measure the pivot against")
return {
    "result": sorted(outcome),
    "atoms": int(len(world)),
    "origin": [float(v) for v in obj.matrix_world.translation],
    "bbox_min": [float(v) for v in world.min(axis=0)],
    "bbox_max": [float(v) for v in world.max(axis=0)],
}
""")
    assert result["atoms"] > 0
    assert result["result"] == ["FINISHED"]

    after = _capture(blender, "after")
    diff = _compare(blender, "before", "after")
    assert after["covered"] > 0, "snapping the protein pivot blanked the render"
    assert diff["xor"] == 0, (
        f"snap_protein_pivot_center moved {diff['xor']} pixels of geometry")

    for axis, (low, high, value) in enumerate(zip(
            result["bbox_min"], result["bbox_max"], result["origin"])):
        assert low <= value <= high, (
            f"the 'centre' pivot fell outside the molecule on axis {axis}: "
            f"{value} is not within [{low}, {high}]")


# ---------------------------------------------------------------------------
# Interactive pivot modes - reachable only in a real window
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_toggle_pivot_edit_enters_edit_mode_in_a_real_window(blender, actin):
    """``molecule.toggle_pivot_edit`` opens Edit Pivot in a real window.

    The session itself is driveable headless now (the offline lane runs the
    whole open/drag/apply cycle), but the parts that need a window are not:
    reading ``context.workspace.tools.from_space_view3d_mode`` and iterating
    ``context.screen.areas`` to force the Move tool. This lane is the only
    place those run. The assertion is that it completes and leaves the helper
    Empty it promises - the object a user then drags.
    """
    result = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
scene.selected_molecule_id = "1atn"
molecule = H.sm().molecules["1atn"]
domain_id = next(did for did, d in molecule.domains.items()
                 if d.chain_id == "A")

before = {o.name for o in bpy.data.objects}
with R.view3d_override():
    outcome = bpy.ops.molecule.toggle_pivot_edit(domain_id=domain_id)
after = {o.name for o in bpy.data.objects}
return {"result": sorted(outcome), "created": sorted(after - before)}
""")
    assert result["result"] == ["FINISHED"], (
        "toggle_pivot_edit failed in a real window - this operator is "
        "unreachable headless, so this lane is its only coverage")
    assert result["created"], (
        "toggle_pivot_edit reported success but created no helper object; "
        "the user has nothing to drag")


@pytest.mark.live
def test_toggle_protein_pivot_edit_enters_edit_mode_in_a_real_window(
        blender, single_chain):
    """The protein-level twin of the above, exercising the same window-only path.

    It builds an ARROWS Empty at the protein origin and switches the workspace
    tool; the tool switch is what only a real window can do.
    """
    result = blender.call("""
before = {o.name for o in bpy.data.objects}
with R.view3d_override():
    outcome = bpy.ops.molecule.toggle_protein_pivot_edit(molecule_id="1ubq")
after = {o.name for o in bpy.data.objects}
return {"result": sorted(outcome), "created": sorted(after - before)}
""")
    assert result["result"] == ["FINISHED"], (
        "toggle_protein_pivot_edit failed in a real window")
    assert any("PivotHelper" in name for name in result["created"]), (
        f"expected a PB_PivotHelper Empty at the protein origin; "
        f"created={result['created']}")


@pytest.mark.live
def test_set_pivot_custom_round_trips_in_a_real_window(blender, actin):
    """The row button's Edit Pivot: open, drag the helper, apply.

    A remote-code lane cannot synthesise a mouse drag, but it does not have
    to any more: the mode is a plain two-click toggle around a helper Empty
    the caller can move directly, which is exactly what a drag amounts to.
    What this lane adds over the offline one is a real window - the Move tool
    switch and the gizmo flags only exist here.
    """
    result = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
scene.selected_molecule_id = "1atn"
from mathutils import Vector
from proteinblender.operators.pivot_operators import PIVOT_HELPER, pivot_edit_key

row = next(r for r in scene.outliner_items
           if r.item_type == "CHAIN" and r.object_name)
obj = bpy.data.objects[row.object_name]

with R.view3d_override():
    opened = bpy.ops.proteinblender.set_pivot_custom(item_id=row.item_id)
    helper = bpy.data.objects.get(PIVOT_HELPER)
    tool = bpy.context.workspace.tools.from_space_view3d_mode(
        "OBJECT", create=False).idname
    helper.location = helper.location + Vector((2.0, 0.0, 1.0))
    bpy.context.view_layer.update()
    dropped = list(helper.matrix_world.translation)
    applied = bpy.ops.proteinblender.set_pivot_custom(item_id=row.item_id)

bpy.context.view_layer.update()
return {
    "opened": sorted(opened),
    "applied": sorted(applied),
    "tool": tool,
    "helper_gone": bpy.data.objects.get(PIVOT_HELPER) is None,
    "session_closed": pivot_edit_key(scene) == "",
    "dropped": dropped,
    "origin": list(obj.matrix_world.translation),
}
""")
    assert result["opened"] == ["FINISHED"]
    assert result["applied"] == ["FINISHED"]
    assert result["tool"] == "builtin.move", (
        f"Edit Pivot left the active tool at {result['tool']!r}; the user has "
        f"no translate gizmo to drag the helper with")
    assert result["helper_gone"], "the helper survived the second click"
    assert result["session_closed"], "the session stayed open"

    offset = max(abs(a - b) for a, b in zip(result["dropped"], result["origin"]))
    assert offset < 1e-4, (
        f"the pivot landed {offset} from where the helper was dropped: "
        f"helper={result['dropped']} origin={result['origin']}")


@pytest.mark.live
def test_clicking_away_from_the_helper_applies_the_pivot(blender, single_chain):
    """Click anywhere but the helper and the mode ends, applying the placement.

    Two things make this lane the one that can prove it. The click goes through
    ``view3d.select`` - the operator Blender's own keymap runs on a left click,
    with its own picking - rather than a scripted deselect standing in for one.
    And the close is done by the add-on's real ``bpy.app.timers`` watcher on its
    own schedule, so this measures the wall-clock behaviour a user gets, not a
    hand-pumped callback.

    The helper is dragged clear first and the click aimed at the far edge, so it
    cannot land on the helper. Where it lands otherwise does not matter: the
    mode makes every other object unselectable, so empty space and the molecule
    are the same answer.
    """
    opened = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
from proteinblender.operators import pivot_operators as P

row = next(r for r in scene.outliner_items if r.item_type == 'PROTEIN')
with R.view3d_override():
    bpy.ops.wm.tool_set_by_id(name="builtin.rotate")
    bpy.ops.proteinblender.set_pivot_custom(item_id=row.item_id)

helper = bpy.data.objects[P.PIVOT_HELPER]
helper.location.x += 1.5
bpy.context.view_layer.update()
return {
    "row": row.item_id,
    "session": P.pivot_edit_key(scene),
    "watching": bpy.app.timers.is_registered(P.click_away_watcher),
    "dropped": [float(v) for v in helper.matrix_world.translation],
}
""")
    assert opened["session"], "Edit Pivot did not open a session to click away from"
    assert opened["watching"], (
        "no click-away watcher is running, so no click could ever end the mode")

    # Still open after a full second of NOT clicking: dragging the gizmo must
    # not be mistaken for letting go of it.
    time.sleep(1.0)
    assert blender.call("""
from proteinblender.operators import pivot_operators as P
return P.pivot_edit_key(bpy.context.scene)
"""), "the session closed on its own without any click"

    clicked = blender.call("""
from proteinblender.operators import pivot_operators as P
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(area=area, region=region):
    bpy.ops.view3d.select(deselect_all=True, location=(8, region.height // 2))
helper = bpy.data.objects.get(P.PIVOT_HELPER)
return {"helper_selected": helper.select_get() if helper else None,
        "session": P.pivot_edit_key(bpy.context.scene)}
""")
    assert clicked["helper_selected"] is False, (
        "the click did not reach the helper's selection, so this test is not "
        "measuring a click away")
    assert clicked["session"], (
        "the session closed inside the click itself; this test would then pass "
        "without the watcher it is meant to exercise")

    time.sleep(1.0)
    result = blender.call("""
from proteinblender.operators import pivot_operators as P
scene = bpy.context.scene
row = next(r for r in scene.outliner_items if r.item_id == row_id)
tool = bpy.context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
bpy.context.view_layer.update()
return {
    "session": P.pivot_edit_key(scene),
    "helper_gone": bpy.data.objects.get(P.PIVOT_HELPER) is None,
    "watching": bpy.app.timers.is_registered(P.click_away_watcher),
    "tool": tool.idname if tool else None,
    "locked": sorted(o.name for o in bpy.context.view_layer.objects
                     if o.hide_select),
    "origins": [[float(v) for v in o.matrix_world.translation]
                for o in P.row_pivot_objects(bpy.context, row)],
}
""", row_id=opened["row"])

    assert result["session"] == "", "clicking away left the session open"
    assert result["helper_gone"], "clicking away left the helper in the scene"
    assert not result["watching"], "the watcher kept polling after the mode ended"
    assert result["locked"] == [], (
        f"clicking away left {result['locked']} unselectable")
    assert result["tool"] == "builtin.rotate", (
        f"clicking away left the active tool at {result['tool']}")
    assert result["origins"], "the row resolved to no objects"
    for origin in result["origins"]:
        offset = max(abs(a - b) for a, b in zip(origin, opened["dropped"]))
        assert offset < 1e-4, (
            f"the pivot landed {offset} from where the helper was left: "
            f"helper={opened['dropped']} origin={origin}")
