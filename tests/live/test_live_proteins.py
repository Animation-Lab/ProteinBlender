"""Protein lifecycle, observed in a live viewport.

``tests/integration/test_proteins.py`` already proves that importing,
duplicating, hiding, centring and deleting a protein move the add-on's own
bookkeeping - the scene-manager registry, the ``MoleculeListItem`` rows, the
``hide_viewport`` flag. It cannot prove that any of it reached the screen,
because ``--background`` has no screen.

That gap is not academic. "Hide" is only meaningful if the pixels go away;
"centre" is only meaningful if the subject moves back to where the user is
looking; "delete" is only meaningful if nothing is left drawn. Each of those is
a flag assertion headless and a pixel assertion here, and the two can disagree.

Conventions in this module:

  * The view is framed **once**, then every capture is taken with
    ``frame=False``. Reframing between captures would re-fit the view to
    whatever geometry survives, which silently cancels out exactly the change
    each test is trying to measure.
  * Comparisons are metamorphic - "this differs from that", "this came back to
    that" - never a coverage number copied off the current build.
"""

from __future__ import annotations

import pytest

# The six user-facing styles. ``STYLE_ITEMS`` also carries preset_1..4, which
# are composites of these and are not what the Style dropdown offers as the
# primary choices.
STYLES = ["spheres", "cartoon", "surface", "ribbon", "sticks", "ball_and_stick"]

# Offline fixtures under tests/data, with the chain count each one really has.
# The count is never trusted from this table: every test that uses it re-derives
# the chains by parsing the PDB with biotite (see ``_chains_from_pdb``), which is
# ground truth the add-on's import path never touches.
FIXTURES = [
    ("1ubq.pdb", "1ubq"),
    ("1aki.pdb", "1aki"),
    ("4hhb.pdb", "4hhb"),
    ("1atn.pdb", "1atn"),
]


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _chains_from_pdb(blender, filename):
    """The chain IDs in a fixture, read straight out of the PDB text.

    Independent ground truth for "one domain per chain": it parses the source
    file by column position and never consults the molecule wrapper, so an
    import that invented or dropped a chain cannot drag the expectation along
    with it.

    The predicate is *every chain that has atoms*, excluding only solvent. An
    earlier version of this helper counted amino-acid chains and was wrong: 1ATN
    chain B is a three-residue glycan (NAG-NAG-BMA) attached to DNase I, so it
    carries no amino acids yet is a real chain the add-on is right to show. The
    two predicates agree on 1ubq, 1aki and 4hhb and disagree only there, which
    is exactly the sort of single-fixture disagreement that turns into a false
    bug report.
    """
    return blender.call(
        """
        chains = set()
        with open(H.data_path(filename)) as handle:
            for line in handle:
                if not line.startswith(("ATOM", "HETATM")):
                    continue
                if line[17:20].strip() == "HOH":
                    continue
                chain = line[21:22].strip()
                if chain:
                    chains.add(chain)
        return sorted(chains)
        """,
        filename=filename,
    )


def _capture(blender, label):
    """Render the viewport, retain it under ``label``, return its metrics."""
    return blender.call("return R.capture(label)", label=label)


def _compare(blender, left, right):
    return blender.call("return R.compare(left, right)", left=left, right=right)


def _molecule_object(blender, molecule_id):
    return blender.call(
        "return H.sm().molecules[mid].object.name", mid=molecule_id)


def _set_location(blender, obj_name, location):
    return blender.call(
        """
        obj = bpy.data.objects[name]
        obj.location = tuple(location)
        bpy.context.view_layer.update()
        return [round(float(v), 5) for v in obj.location]
        """,
        name=obj_name, location=location,
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.parametrize("filename,identifier", FIXTURES)
def test_offline_import_registers_everywhere_the_ui_reads_from(
        blender, snapshot_state, filename, identifier):
    """An import must land in all three places the UI reads, not just one.

    The panel stack has three independent views of "what is loaded": the
    runtime ``ProteinBlenderScene.molecules`` registry, the persisted
    ``molecule_list_items`` rows that survive save/load, and the Protein
    Outliner hierarchy. They are populated by different code, so a molecule can
    reach one and miss another - which the user sees as a protein that renders
    but has no row, or a row that cannot be selected.
    """
    returned = blender.call(
        "return H.import_local(filename, identifier)",
        filename=filename, identifier=identifier)
    assert returned == identifier

    state = snapshot_state()
    assert identifier in state["molecules"], "not in the runtime registry"
    assert identifier in state["molecule_rows"], "no persistent list row"

    chains = _chains_from_pdb(blender, filename)
    outliner_chains = [item for item in state["outliner"]
                       if item["type"] == "CHAIN"]
    assert len(outliner_chains) == len(chains), (
        f"{identifier} has {len(chains)} amino-acid chains in the PDB "
        f"({chains}) but the outliner shows {len(outliner_chains)}")


@pytest.mark.live
@pytest.mark.parametrize("filename,identifier", FIXTURES)
def test_import_auto_creates_exactly_one_domain_per_chain(
        blender, filename, identifier):
    """Import seeds one full-chain domain per chain - no more, no fewer.

    A missing domain leaves that chain unselectable and unanimatable. A spurious
    extra one (historically a degenerate 0-0 range) renders as a phantom row the
    user cannot explain. The expected count comes from parsing the PDB, not from
    the wrapper, so neither failure can move the expectation with it.
    """
    blender.call("return H.import_local(filename, identifier)",
                 filename=filename, identifier=identifier)
    chains = _chains_from_pdb(blender, filename)

    domain_chains = blender.call(
        """
        molecule = H.sm().molecules[mid]
        return sorted(str(domain.chain_id) for domain in molecule.domains.values())
        """,
        mid=identifier)

    assert sorted(domain_chains) == sorted(chains), (
        f"auto-created domains cover {domain_chains}, but {identifier}'s "
        f"amino-acid chains are {chains}")


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize("filename,identifier", FIXTURES)
def test_every_fixture_actually_renders_something(
        blender, shot, filename, identifier):
    """Each bundled structure must put geometry on screen after import.

    The headless lane's equivalent stops at "the wrapper has an object". An
    object with a broken modifier stack, an unbound style node or an empty
    evaluated mesh satisfies that and still renders an empty frame - the
    symptom users report as "I imported it and nothing happened".
    """
    blender.call("return H.import_local(filename, identifier)",
                 filename=filename, identifier=identifier)

    metrics = shot(f"imported-{identifier}")
    assert metrics["covered"] > 0, (
        f"{identifier} imported without error but rendered an empty viewport")


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_duplicate_produces_independently_renderable_geometry(
        blender, shot, single_chain):
    """The copy must be real geometry of its own, not a second row pointing at
    the original's object.

    Duplication has a history of sharing datablocks with its source (the
    MolecularNodes tree, domain masks). The sharpest live proof that the copy
    stands alone is to hide the *original* and check something is still drawn:
    if the copy were only a registry entry aimed at the source's object, the
    viewport would go empty.
    """
    before = blender.call("return sorted(H.sm().molecules.keys())")

    created = blender.call(
        """
        result = bpy.ops.molecule.duplicate_protein(molecule_id=mid)
        if result != {'FINISHED'}:
            raise RuntimeError(f"duplicate_protein returned {result}")
        return sorted(set(H.sm().molecules.keys()) - set(before))
        """,
        mid=single_chain, before=before)
    assert len(created) == 1, f"duplicate registered {created}, expected one"
    copy_id = created[0]

    blender.call("return R.frame_all()")
    both = shot("original-and-copy", frame=False)
    assert both["covered"] > 0, "neither the original nor the copy rendered"

    blender.call("return bpy.ops.molecule.toggle_visibility(molecule_id=mid)",
                 mid=single_chain)
    copy_only = shot("copy-only", frame=False)

    assert copy_only["covered"] > 0, (
        "hiding the original emptied the viewport, so the duplicate is not "
        "backed by geometry of its own")
    assert copy_id in blender.call("return sorted(H.sm().molecules.keys())")


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_toggle_visibility_empties_the_viewport_and_restores_it(
        blender, shot, single_chain):
    """Hiding must remove the pixels, and unhiding must bring back the same
    picture.

    This is the assertion only this lane can make. Headless, "hidden" is the
    value of ``hide_viewport``; the operator sets that flag on the molecule and
    on every domain object, and a miss on the domains leaves the protein still
    fully drawn while the flag reports it hidden. Coverage going to exactly zero
    is unfalsifiable-proof it went away, and the calibration for that zero is
    ``test_live_harness.test_empty_scene_renders_nothing``.

    The restore half matters just as much: a toggle that returns a *different*
    image has lost something on the way back.
    """
    blender.call("return R.frame_all()")
    visible = _capture(blender, "visible")
    assert visible["covered"] > 0, "the molecule was not on screen to begin with"

    blender.call("return bpy.ops.molecule.toggle_visibility(molecule_id=mid)",
                 mid=single_chain)
    hidden = shot("hidden", frame=False)
    assert hidden["covered"] == 0, (
        f"a hidden molecule still rendered {hidden['covered']} pixels; the "
        "hide did not reach every object the molecule draws through")

    blender.call("return bpy.ops.molecule.toggle_visibility(molecule_id=mid)",
                 mid=single_chain)
    _capture(blender, "restored")
    restored = shot("restored", frame=False)
    assert restored["covered"] > 0, "unhiding left the viewport empty"

    round_trip = _compare(blender, "visible", "restored")
    assert round_trip["iou"] > 0.99, (
        "hide/unhide did not restore the original image "
        f"(iou {round_trip['iou']}); something was lost in the round trip")


# ---------------------------------------------------------------------------
# Centre
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_center_protein_brings_a_displaced_molecule_back_to_where_it_was(
        blender, shot, single_chain):
    """Centring must be observable as motion in the viewport, and repeatable.

    Headless this reads ``obj.location`` afterwards, which the operator itself
    sets - close to asserting that an assignment happened. Here the ground truth
    is the rendered centroid under a fixed view: centring once, displacing, and
    centring again must return the subject to the same place on screen. A
    centring that computed the wrong centre of mass would land somewhere else
    and the two images would not overlay.
    """
    obj_name = _molecule_object(blender, single_chain)

    blender.call("return bpy.ops.molecule.center_protein(molecule_id=mid)",
                 mid=single_chain)
    blender.call("return R.frame_all()")
    centred_first = _capture(blender, "centred-first")
    assert centred_first["covered"] > 0

    # Displace by a fraction of the molecule's own size. A fixed distance in
    # Blender units is not portable here: MolecularNodes scales Angstroms by
    # 0.01 at import, so 1ubq spans about 0.3 units and a 1.5 unit shift throws
    # it clean out of the framed view, which reads as "nothing rendered" rather
    # than "it moved".
    # Measured from the raw mesh, not the evaluated one. The default Spheres
    # style emits a point cloud, so an evaluated molecule reports zero vertices
    # even when it is perfectly healthy (COVERAGE.md records the same trap
    # catching an earlier attempt at a geometry check).
    extent = blender.call(
        """
        import numpy as np

        mesh = bpy.data.objects[name].data
        count = len(mesh.vertices)
        assert count, "molecule mesh has no vertices to size from"
        coords = np.empty(count * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", coords)
        coords = coords.reshape(-1, 3)
        return float((coords.max(axis=0) - coords.min(axis=0)).max())
        """,
        name=obj_name)
    _set_location(blender, obj_name, [extent * 0.3, 0.0, 0.0])
    displaced = shot("displaced", frame=False)
    assert displaced["covered"] > 0, "the displaced molecule left the view"
    assert displaced["centroid"] != centred_first["centroid"], (
        "moving the object did not move anything on screen")

    blender.call("return bpy.ops.molecule.center_protein(molecule_id=mid)",
                 mid=single_chain)
    _capture(blender, "centred-again")
    shot("centred-again", frame=False)

    recentred = _compare(blender, "centred-first", "centred-again")
    assert recentred["iou"] > 0.98, (
        "centring a displaced molecule did not return it to the position the "
        f"first centring produced (iou {recentred['iou']})")


# ---------------------------------------------------------------------------
# Delete chain
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_delete_chain_removes_that_chain_from_the_scene_and_the_screen(
        blender, shot, multi_chain):
    """Deleting one chain of haemoglobin drops its domain and its pixels.

    Two things can go wrong independently. The bookkeeping can drop the domain
    while the geometry stays drawn (the parent mesh is masked per-domain, so a
    stale mask leaves the chain visible), or the geometry can go while the row
    survives. Asserting the domain count *and* a strict decrease in covered
    pixels under a fixed view catches either.
    """
    chain = blender.call(
        """
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        molecule = H.sm().molecules[mid]
        row = next(item for item in scene.outliner_items
                   if item.item_type == "CHAIN" and item.parent_id == mid)
        index = row.chain_id
        key = int(index) if str(index).isdigit() else index
        return {"chain_id": str(index),
                "author": str(molecule.chain_mapping.get(key, index)),
                "domains": len(molecule.domains)}
        """,
        mid=multi_chain)
    assert chain["domains"] == 4, (
        f"4hhb should import with four chain domains, got {chain['domains']}")

    blender.call("return R.frame_all()")
    before = shot("four-chains", frame=False)
    assert before["covered"] > 0

    # The outliner row was re-resolved above and is not held across this call;
    # only the plain chain-id string crosses back.
    blender.call(
        """
        result = bpy.ops.molecule.delete_chain(chain_id=chain_id, molecule_id=mid)
        if result != {'FINISHED'}:
            raise RuntimeError(f"delete_chain returned {result}")
        return result == {'FINISHED'}
        """,
        chain_id=chain["chain_id"], mid=multi_chain)

    remaining = blender.call(
        """
        molecule = H.sm().molecules[mid]
        return sorted(str(domain.chain_id) for domain in molecule.domains.values())
        """,
        mid=multi_chain)
    assert len(remaining) == 3, f"expected three surviving domains, got {remaining}"
    assert chain["author"] not in remaining, (
        f"chain {chain['author']} still has a domain after being deleted")

    after = shot("three-chains", frame=False)
    assert after["covered"] < before["covered"], (
        f"deleting a quarter of the protein did not reduce what is drawn "
        f"({before['covered']} -> {after['covered']} pixels); the deleted "
        "chain is still rendering out of the parent mesh")
    assert after["covered"] > 0, "deleting one chain emptied the whole viewport"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_delete_protein_leaves_nothing_registered_or_drawn(
        blender, shot, snapshot_state, single_chain):
    """Deletion must clear the registry, the row, the objects and the screen.

    A delete that unregisters the molecule but orphans its objects looks correct
    in every headless assertion - the wrapper is gone, the list item is gone -
    while the user still sees the protein and has no row left to remove it with.
    Zero covered pixels is the only statement of "it is gone" that cannot be
    satisfied by leftover geometry.
    """
    obj_name = _molecule_object(blender, single_chain)
    blender.call("return R.frame_all()")
    assert shot("before-delete", frame=False)["covered"] > 0

    blender.call(
        """
        result = bpy.ops.molecule.delete(molecule_id=mid)
        if result != {'FINISHED'}:
            raise RuntimeError(f"molecule.delete returned {result}")
        return True
        """,
        mid=single_chain)

    state = snapshot_state()
    assert single_chain not in state["molecules"], "wrapper survived deletion"
    assert single_chain not in state["molecule_rows"], "list row survived deletion"
    assert obj_name not in state["objects"], (
        f"{obj_name} is still in bpy.data.objects after deletion")

    after = shot("after-delete", frame=False)
    assert after["covered"] == 0, (
        f"a deleted protein still rendered {after['covered']} pixels")


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
@pytest.mark.slow
def test_each_style_renders_and_no_two_look_the_same_as_sticks(
        blender, shot, single_chain):
    """Every style must draw something, and must draw something *different*.

    There is no change-style operator: the Style dropdown writes
    ``scene.molecule_style`` and an update callback swaps the style node. That
    makes the whole feature one property assignment, and the headless test for
    it asserts the value was mirrored onto the list item - which is true whether
    or not the node swap reached the geometry. A style that silently fails to
    apply, or one that falls back to the previous node tree, is invisible there
    and obvious here.

    Sticks is the comparison baseline because it is the sparsest style: thin
    bonds with no atom volume. Every other style adds surface, ribbon or sphere
    geometry, so all five must differ from it by a substantial fraction of the
    drawn area. The assertion is a ratio of the union, not a pixel count, so it
    does not move with GPU or driver.

    The view is framed once, on the bulkiest style, and held. Reframing per
    style would refit to each silhouette and mask the very differences being
    measured.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")

    def apply_style(style):
        return blender.call(
            """
            scene = bpy.context.scene
            scene.selected_molecule_id = mid
            # Blender fires an EnumProperty update only on an actual change, so
            # step through a sentinel to guarantee a transition into `style`.
            sentinel = "cartoon" if style != "cartoon" else "spheres"
            scene.molecule_style = sentinel
            scene.molecule_style = style
            return scene.molecule_style
            """,
            mid=single_chain, style=style)

    # Frame on surface, the largest silhouette, so no later style is clipped.
    assert apply_style("surface") == "surface"
    blender.call("return R.frame_all()")

    metrics = {}
    for style in STYLES:
        assert apply_style(style) == style, f"{style} did not stick on the scene"
        metrics[style] = _capture(blender, style)
        shot(f"style-{style}", frame=False)
        assert metrics[style]["covered"] > 0, (
            f"style {style!r} rendered an empty viewport")

    for style in STYLES:
        if style == "sticks":
            continue
        difference = _compare(blender, "sticks", style)
        changed = difference["xor"] / max(difference["union"], 1)
        assert changed > 0.02, (
            f"style {style!r} is pixel-indistinguishable from 'sticks' "
            f"({changed:.4f} of the union differs); the style node swap did "
            "not reach the geometry")


@pytest.mark.live
@pytest.mark.visual
def test_style_changes_are_reversible(blender, single_chain):
    """Returning to a style must return to its picture.

    A style swap that leaks - leaving the previous style's nodes wired in
    alongside the new one - still renders "something different" and would pass
    the test above. It shows up as a round trip that does not close: spheres,
    then cartoon, then spheres again gives a heavier image than the first
    spheres. Comparing the two spheres captures is what catches accumulation.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")

    def apply_style(style):
        blender.call(
            """
            scene = bpy.context.scene
            scene.selected_molecule_id = mid
            sentinel = "cartoon" if style != "cartoon" else "spheres"
            scene.molecule_style = sentinel
            scene.molecule_style = style
            """,
            mid=single_chain, style=style)

    apply_style("spheres")
    blender.call("return R.frame_all()")
    _capture(blender, "spheres-first")

    apply_style("cartoon")
    _capture(blender, "cartoon")
    changed = _compare(blender, "spheres-first", "cartoon")
    assert changed["xor"] > 0, "switching spheres -> cartoon changed nothing"

    apply_style("spheres")
    _capture(blender, "spheres-again")

    round_trip = _compare(blender, "spheres-first", "spheres-again")
    assert round_trip["iou"] > 0.99, (
        "returning to 'spheres' did not reproduce the original spheres image "
        f"(iou {round_trip['iou']}); the intermediate style left geometry "
        "behind")
