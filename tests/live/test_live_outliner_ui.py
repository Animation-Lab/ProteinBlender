"""The PB Outliner and the panel shell, observed in a real Blender window.

The headless lane covers the outliner operators' *state*: ``tests/integration/
test_outliner.py`` asserts that ``outliner_select`` flips ``is_selected``, that
``toggle_expand`` flips ``is_expanded``, and that ``toggle_visibility`` flips
``obj.hide_render``. All true, all necessary, and none of it answers the
question a user actually asks, which is whether the thing disappeared from the
screen.

Two things are only provable here.

**Visibility must reach the renderer.** ``hide_render`` is a flag; the viewport
is the truth. The outliner's eye toggle has three separate paths (a PROTEIN row
cascades to its domains, a split CHAIN row aggregates across domain objects, a
DOMAIN row acts on one object), and a flag can be set correctly on the wrong
object without anything on screen changing.

**A panel must accept the live context.** Headless Blender cannot draw a panel
at all, so a panel that registers cleanly and then refuses to appear - a poll()
that returns False for the state a user is actually in - is invisible to every
other lane. ``R.ui_state()`` evaluates each panel's poll against the real
window's context, which is as close to "would this be on screen" as an
assertion can get without reading pixels of UI chrome.

Row-handling rule (see tests/live/README.md): outliner rows are rebuilt by most
operators, and Blender returns defaults from a dangling row rather than raising.
Every snippet below re-resolves by ``item_id`` after any operator call.
"""

from __future__ import annotations

import pytest


# The panels ``R.ui_state()`` can see. Its filter matches idnames beginning
# PROTEINBLENDER_PT / PB2_PT / MOLECULE_PT, which excludes the importer panel
# (``PROTEIN_PB_PT_import_protein`` - the PB is in the middle). That one is
# checked separately below rather than by widening the shared remote helper.
PANELS_VIA_UI_STATE = [
    "PROTEINBLENDER_PT_outliner",
    "PROTEINBLENDER_PT_visual_setup",
    "PROTEINBLENDER_PT_builders",
    "PROTEINBLENDER_PT_puppet_maker",
    "PROTEINBLENDER_PT_pose_library",
    "PB2_PT_linkers",
    "PROTEINBLENDER_PT_animation",
]

IMPORT_PANEL = "PROTEIN_PB_PT_import_protein"


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_multi_chain_protein_builds_a_protein_chain_hierarchy(blender,
                                                              multi_chain):
    """4HHB is a haemoglobin tetramer: one protein, four chains.

    Ground truth for the chain count is the structure, not the outliner: 4HHB
    has chains A, B, C and D, a fact about the PDB entry that no amount of
    add-on breakage can change. Asserting "the outliner has as many chains as
    the outliner says it has" would pass with the hierarchy flattened entirely.

    The parent links matter as much as the counts. A chain row whose
    ``parent_id`` does not point at its protein still draws, but every operator
    that resolves a molecule through the hierarchy - visibility cascades, pivot
    chain-index lookup, colour application - silently targets nothing.
    """
    state = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return [
    {"type": i.item_type, "id": i.item_id, "parent": i.parent_id,
     "indent": int(i.indent_level), "object": i.object_name}
    for i in scene.outliner_items
]
""")

    proteins = [row for row in state if row["type"] == "PROTEIN"]
    chains = [row for row in state if row["type"] == "CHAIN"]

    assert [row["id"] for row in proteins] == ["4hhb"], (
        f"expected exactly one PROTEIN row for 4hhb, got {proteins}")
    assert len(chains) == 4, (
        f"4HHB is a tetramer with chains A/B/C/D, but the outliner built "
        f"{len(chains)} chain rows: {[c['id'] for c in chains]}")

    for chain in chains:
        assert chain["parent"] == "4hhb", (
            f"chain row {chain['id']} is parented to {chain['parent']!r}, not "
            f"to its protein; hierarchy lookups will resolve to nothing")
        assert chain["indent"] > proteins[0]["indent"], (
            f"chain row {chain['id']} is not indented below its protein")


@pytest.mark.live
def test_splitting_a_chain_adds_domain_rows_under_that_chain(blender, actin):
    """PROTEIN > CHAIN > DOMAIN, the third level.

    Splitting chain A at residues 1-50 must produce exactly two domains, 1-50
    and 51-end, both parented to the chain row that was split. The residue
    bounds are the independent truth here: they were chosen by the caller, so a
    domain row reporting a different span has lost the split range regardless of
    how many rows appeared.
    """
    result = blender.call("""
scene = bpy.context.scene
manager = H.sm()
molecule = manager.molecules["1atn"]
scene.selected_molecule_id = "1atn"

original_id = next(did for did, d in molecule.domains.items()
                   if d.chain_id == "A")
outcome = H.split_domain_from_outliner("1atn", "A", 1, 50,
                                       domain_id=original_id)
H.scene_manager_module().build_outliner_hierarchy(bpy.context)

chains = {i.item_id: i for i in scene.outliner_items if i.item_type == 'CHAIN'}
domains = [i for i in scene.outliner_items if i.item_type == 'DOMAIN']
return {
    "split": sorted(outcome),
    "domains": sorted(
        [{"id": d.item_id, "parent": d.parent_id,
          "span": [int(d.domain_start), int(d.domain_end)]}
         for d in domains],
        key=lambda d: d["span"]),
    "chain_ids": sorted(chains),
}
""")

    assert result["split"] == ["FINISHED"], "the split operator did not finish"

    on_chain_a = [d for d in result["domains"] if d["span"][0] == 1]
    assert on_chain_a, f"no 1-50 domain among {result['domains']}"
    assert on_chain_a[0]["span"] == [1, 50], (
        f"the split domain spans {on_chain_a[0]['span']}, not the 1-50 range "
        f"that was requested")

    parent = on_chain_a[0]["parent"]
    assert parent in result["chain_ids"], (
        f"domain row is parented to {parent!r}, which is not a CHAIN row "
        f"({result['chain_ids']}); the third hierarchy level is detached")

    siblings = [d for d in result["domains"] if d["parent"] == parent]
    assert len(siblings) == 2, (
        f"splitting one chain once must leave two domains on it, found "
        f"{len(siblings)}: {siblings}")


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_outliner_select_toggles_and_cascades_to_chains(blender, multi_chain):
    """Clicking a PROTEIN checkbox selects its chains; clicking again clears.

    The cascade is the behaviour the Visual Set-up panel depends on - it applies
    colour and style to whatever the selection resolves to - so a protein whose
    click does not reach its chains makes the colour picker look broken.

    Re-resolution matters here: ``outliner_select`` syncs Blender's own object
    selection and can rebuild rows, so the second read fetches rows fresh by id
    rather than reusing the objects from the first.
    """
    def select(item_id):
        return blender.call("""
scene = bpy.context.scene
with R.view3d_override():
    bpy.ops.proteinblender.outliner_select(item_id=item_id)
return {i.item_id: bool(i.is_selected) for i in scene.outliner_items}
""", item_id=item_id)

    rows = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return {
    "protein": next(i.item_id for i in scene.outliner_items
                    if i.item_type == 'PROTEIN'),
    "chains": [i.item_id for i in scene.outliner_items
               if i.item_type == 'CHAIN'],
}
""")

    after_click = select(rows["protein"])
    assert after_click[rows["protein"]] is True, (
        "clicking the protein checkbox did not select it")
    unselected = [cid for cid in rows["chains"] if not after_click.get(cid)]
    assert not unselected, (
        f"selecting the protein left chains {unselected} unselected; the "
        f"cascade the Visual Set-up panel relies on did not run")

    after_second = select(rows["protein"])
    assert after_second[rows["protein"]] is False, (
        "clicking a selected protein checkbox did not deselect it")
    still_on = [cid for cid in rows["chains"] if after_second.get(cid)]
    assert not still_on, (
        f"deselecting the protein left chains {still_on} selected; the next "
        f"colour or style change will hit them by surprise")


@pytest.mark.live
def test_toggle_expand_flips_a_chain_row(blender, actin):
    """Expanding a CHAIN rebuilds the hierarchy, so the row must be re-fetched.

    This is the exact trap the lane's README warns about: ``toggle_expand`` on a
    CHAIN calls ``build_outliner_hierarchy``, which replaces every element of
    ``scene.outliner_items``. A test holding the old row reads a default and
    passes or fails for reasons unconnected to the operator.
    """
    result = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
chain_id = next(i.item_id for i in scene.outliner_items
                if i.item_type == 'CHAIN')
before = next(bool(i.is_expanded) for i in scene.outliner_items
              if i.item_id == chain_id)

with R.view3d_override():
    outcome = bpy.ops.proteinblender.toggle_expand(item_id=chain_id)

# Re-resolve: the rows above are dangling after the rebuild.
row = next((i for i in scene.outliner_items if i.item_id == chain_id), None)
return {
    "result": sorted(outcome),
    "before": before,
    "after": None if row is None else bool(row.is_expanded),
}
""")
    assert result["result"] == ["FINISHED"]
    assert result["after"] is not None, (
        "the chain row vanished from the outliner after toggling expand")
    assert result["after"] is (not result["before"]), (
        f"toggle_expand left is_expanded at {result['after']}")


@pytest.mark.live
def test_outliner_item_info_is_harmless(blender, single_chain):
    """The tooltip operator exists to carry a dynamic description.

    It must complete without side effects; it is wired to every labelled row, so
    an exception here makes the outliner unusable rather than merely untooltipped.
    """
    result = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
item_id = next(i.item_id for i in scene.outliner_items
               if i.item_type == 'PROTEIN')
before = len(scene.outliner_items)
with R.view3d_override():
    outcome = bpy.ops.proteinblender.outliner_item_info(item_id=item_id)
return {"result": sorted(outcome), "before": before,
        "after": len(scene.outliner_items)}
""")
    assert result["result"] == ["FINISHED"]
    assert result["before"] == result["after"], (
        "the tooltip operator changed the outliner contents")


# ---------------------------------------------------------------------------
# Visibility - the assertion only this lane can make
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_hiding_a_protein_removes_it_from_the_render(blender, single_chain):
    """The eye toggle must empty the viewport, and un-toggling must restore it.

    ``hide_render`` flipping is not the same claim. The outliner resolves a
    PROTEIN row to the molecule object *and* every domain object, and a
    molecule's atoms are drawn by its domains: setting the flag on the parent
    alone leaves the protein fully visible while every state assertion passes.
    Only a render can tell those two apart.

    Restoring is asserted against the original capture, exactly (``xor == 0``).
    A toggle that hides and then brings back something subtly different - one
    domain left hidden, say - is a real regression and would survive a mere
    "coverage went back up" check.
    """
    blender.call("return R.frame_all()")
    visible = blender.call('return R.capture(label="visible")')
    assert visible["covered"] > 0, (
        "nothing was on screen before hiding, so this test cannot observe "
        "anything being hidden")

    item_id = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return next(i.item_id for i in scene.outliner_items if i.item_type == 'PROTEIN')
""")

    def toggle():
        return blender.call("""
with R.view3d_override():
    outcome = bpy.ops.proteinblender.toggle_visibility(item_id=item_id)
bpy.context.view_layer.update()
return sorted(outcome)
""", item_id=item_id)

    assert toggle() == ["FINISHED"]
    hidden = blender.call('return R.capture(label="hidden")')
    assert hidden["covered"] == 0, (
        f"hiding the protein left {hidden['covered']} pixels on screen "
        f"(was {visible['covered']}). The hide flag was set on some object, "
        f"but not on the ones that draw the atoms.")

    assert toggle() == ["FINISHED"]
    blender.call('return R.capture(label="restored")')
    diff = blender.call('return R.compare("visible", "restored")')
    assert diff["xor"] == 0, (
        f"un-hiding the protein did not restore the original image "
        f"({diff['xor']} pixels differ, iou={diff['iou']}); something stayed "
        f"hidden")


@pytest.mark.live
@pytest.mark.visual
def test_hiding_one_chain_of_four_leaves_the_others_on_screen(blender,
                                                              multi_chain):
    """A CHAIN row must hide its chain and nothing else.

    The chain path is the one with the index-versus-letter translation in it:
    outliner rows carry a numeric chain index while domains store the author
    chain letter, and a mistranslation makes the toggle either a no-op or a
    scene-wide blackout. Both extremes are excluded here by requiring the
    coverage to land strictly between zero and unchanged - the shape of the
    correct answer, not a number copied off a current build.
    """
    blender.call("return R.frame_all()")
    everything = blender.call('return R.capture(label="everything")')
    assert everything["covered"] > 0

    item_id = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
return next(i.item_id for i in scene.outliner_items if i.item_type == 'CHAIN')
""")

    outcome = blender.call("""
with R.view3d_override():
    result = bpy.ops.proteinblender.toggle_visibility(item_id=item_id)
bpy.context.view_layer.update()
return sorted(result)
""", item_id=item_id)
    assert outcome == ["FINISHED"]

    partial = blender.call('return R.capture(label="partial")')
    assert partial["covered"] < everything["covered"], (
        "hiding one of four chains changed nothing on screen; the chain row's "
        "index-to-letter translation resolved to no objects")
    assert partial["covered"] > 0, (
        "hiding one of four chains emptied the whole viewport; the toggle "
        "reached objects belonging to the other chains")


# ---------------------------------------------------------------------------
# Panels, in a window that can actually draw them
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_every_proteinblender_panel_is_registered_and_polls_in_a_live_window(
        blender, single_chain):
    """All eight panels must exist and accept the real context.

    Headless can confirm registration and can call ``poll`` against an empty
    background context. It cannot confirm that poll returns True for a context
    that has a window, a screen, a Properties editor and a loaded molecule -
    which is the only context that matters, because it is the one the user is
    in. A panel that polls False here is a panel the user never sees.
    """
    state = blender.call("""
scene = bpy.context.scene
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
protein = next(i.item_id for i in scene.outliner_items
               if i.item_type == 'PROTEIN')
with R.view3d_override():
    bpy.ops.proteinblender.outliner_select(item_id=protein)
return R.ui_state()
""")
    panels = {panel["idname"]: panel for panel in state["panels"]}

    missing = [name for name in PANELS_VIA_UI_STATE if name not in panels]
    assert not missing, (
        f"panels absent from the live Blender: {missing}. The deployed add-on "
        f"in this Blender profile is not registering everything the repo does.")

    for name in PANELS_VIA_UI_STATE:
        panel = panels[name]
        assert panel["registered"], f"{name} reports itself unregistered"
        assert panel["space"] == "PROPERTIES", (
            f"{name} is placed in {panel['space']!r}; the add-on's UI lives in "
            f"the Properties editor and it will not appear where users look")
        assert panel["poll"] is True, (
            f"{name}.poll() returned {panel['poll']!r} against a live window "
            f"with a molecule loaded and selected, so the panel is invisible "
            f"to the user")


@pytest.mark.live
def test_the_importer_panel_is_registered(blender):
    """``PROTEIN_PB_PT_import_protein`` is the one panel ``R.ui_state`` misses.

    Its idname spells the prefix differently (PROTEIN_PB_PT, not
    PROTEINBLENDER_PT), so the remote helper's filter skips it. Rather than
    widening that shared filter - remote.py is infrastructure for the whole
    lane - it is resolved directly here. It is the panel a user meets first, so
    it cannot go uncovered.
    """
    panel = blender.call("""
cls = getattr(bpy.types, name, None)
if cls is None:
    return None
try:
    polled = bool(cls.poll(bpy.context)) if hasattr(cls, "poll") else True
except Exception as exc:
    polled = "error: %s" % exc
return {"space": getattr(cls, "bl_space_type", ""),
        "registered": bool(getattr(cls, "is_registered", False)),
        "poll": polled}
""", name=IMPORT_PANEL)

    assert panel is not None, f"{IMPORT_PANEL} is not registered in live Blender"
    assert panel["registered"], f"{IMPORT_PANEL} reports itself unregistered"
    assert panel["space"] == "PROPERTIES"
    assert panel["poll"] is True, (
        f"{IMPORT_PANEL}.poll() returned {panel['poll']!r}; the import panel "
        f"is the add-on's entry point and must always be visible")


# ---------------------------------------------------------------------------
# The workspace and the window itself
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_the_protein_blender_workspace_exists(blender):
    """The add-on builds a named workspace with its Properties editor laid out.

    ``ProteinWorkspaceManager`` needs a window to build into, so this cannot be
    verified anywhere but here. Without the workspace the panels are all
    registered, all polling True, and all somewhere the user has to go hunting
    for.
    """
    workspaces = blender.environment["workspaces"]
    assert "Protein Blender" in workspaces, (
        f"the 'Protein Blender' workspace was not created in this session; "
        f"workspaces are {workspaces}. The panels exist but the add-on's own "
        f"layout does not.")


@pytest.mark.live
@pytest.mark.visual
def test_the_real_window_screenshot_is_not_blank(blender, single_chain,
                                                 tmp_path):
    """A screenshot of the literal Blender window, chrome and all.

    Distinct from every other capture in the lane, which renders the 3D viewport
    in isolation. This one observes what is genuinely on the user's screen, and
    the assertion is deliberately weak - a valid PNG of non-trivial size - since
    the point is to leave behind a reviewable artifact of the actual UI rather
    than to pin down its pixels. A blank or truncated image means the window
    never drew.
    """
    path = tmp_path / "window.png"
    raw = blender.screenshot(path)

    assert raw[:8] == b"\x89PNG\r\n\x1a\n", (
        "the screenshot is not a valid PNG; the window capture path is broken")
    assert len(raw) > 10_000, (
        f"the window screenshot is only {len(raw)} bytes - a real Blender "
        f"window full of panels does not compress that far, so the window is "
        f"blank or was never drawn")
