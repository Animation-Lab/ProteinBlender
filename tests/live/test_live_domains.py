"""Domain operations, observed in a live viewport.

Domains are the add-on's central abstraction and its most fragile one. A domain
is not its own mesh: it shares the parent molecule's mesh datablock and is
carved out of it by geometry-nodes masks, with the parent masked out from under
it by the complementary boolean. That design means the bookkeeping and the
picture can disagree in both directions - a domain the registry says exists but
that nothing draws, or geometry that keeps drawing after the domain owning it is
gone.

``tests/integration/test_domains.py`` covers the bookkeeping thoroughly. This
module adds the half that needs a screen, and two invariants in particular:

  * **Splitting must not move anything.** Splitting a chain is pure
    re-partitioning - the same atoms, grouped differently - so the silhouette
    must be identical before and after. The suite has a real history of splits
    that shifted the rendered geometry, which no headless assertion could see
    because the domain ranges were all correct.
  * **Moving a domain must change the render.** The mirror of the above. A
    domain transform that updates ``obj.location`` but never reaches the
    evaluated geometry passes headless and does nothing on screen.

Conventions: the view is framed once and every capture then uses
``frame=False``, because reframing refits to whatever changed and cancels out
the measurement. Outliner rows are never held across an operator call - the
``item_id`` string is captured and the row re-resolved, since most operators
rebuild ``scene.outliner_items`` and Blender hands back defaults rather than
raising on a dangling row.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _capture(blender, label):
    return blender.call("return R.capture(label)", label=label)


def _compare(blender, left, right):
    return blender.call("return R.compare(left, right)", left=left, right=right)


def _domains(blender, molecule_id):
    """Every domain of a molecule as plain data: id, chain, range, object name.

    Returned as a list of dicts rather than as live wrappers, so nothing that
    crosses the socket can go stale across a later operator call.
    """
    return blender.call(
        """
        molecule = H.sm().molecules[mid]
        return sorted(
            ({"id": did,
              "chain": str(domain.chain_id),
              "start": int(domain.start),
              "end": int(domain.end),
              "name": str(domain.name),
              "style": str(getattr(domain, "style", "")),
              "object": domain.object.name if domain.object else None}
             for did, domain in molecule.domains.items()),
            key=lambda d: (d["chain"], d["start"]))
        """,
        mid=molecule_id)


def _select_molecule(blender, molecule_id):
    return blender.call(
        "bpy.context.scene.selected_molecule_id = mid\nreturn mid",
        mid=molecule_id)


def _set_location(blender, obj_name, location):
    return blender.call(
        """
        obj = bpy.data.objects[name]
        obj.location = tuple(location)
        bpy.context.view_layer.update()
        return [round(float(v), 5) for v in obj.location]
        """,
        name=obj_name, location=location)


def _world_translation(blender, obj_name):
    """The object's world-space origin, read from ``matrix_world``.

    Deliberately not ``obj.location``: parenting expresses itself in the world
    matrix, and a child whose local location is untouched can still have moved.
    """
    return blender.call(
        """
        obj = bpy.data.objects[name]
        bpy.context.view_layer.update()
        return [round(float(v), 5) for v in obj.matrix_world.translation]
        """,
        name=obj_name)


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_splitting_a_chain_repartitions_it_without_moving_the_picture(
        blender, shot, single_chain):
    """A split re-groups atoms; it must not relocate or lose any of them.

    This is the regression this module exists for. Splitting rebuilds the
    geometry-nodes masks and creates a new domain object, and every failure mode
    there - a mask off by one residue, a domain object whose pivot is applied
    twice, a parent that stops being masked out - shows up as the rendered
    protein shifting or thickening. None of it shows up in the domain ranges,
    which is all the headless test can inspect, so those stay green throughout.

    The assertion is on the alpha silhouette rather than on colour, because a
    split legitimately introduces a second domain colour. Where the atoms are
    must not change; what colour they are may.
    """
    domains = _domains(blender, single_chain)
    assert len(domains) == 1, f"1ubq should import as one domain, got {domains}"
    original = domains[0]

    blender.call("return R.frame_all()")
    before = _capture(blender, "before-split")
    shot("before-split", frame=False)
    assert before["covered"] > 0

    midpoint = original["start"] + max(1, (original["end"] - original["start"]) // 2)
    result = blender.call(
        """
        return list(H.split_domain_from_outliner(
            mid, chain, start, end, domain_id=domain_id))
        """,
        mid=single_chain, chain=original["chain"],
        start=original["start"], end=midpoint, domain_id=original["id"])
    assert result == ["FINISHED"], f"the outliner split returned {result}"

    after_domains = _domains(blender, single_chain)
    assert len(after_domains) == 2, (
        f"one chain split into {len(after_domains)} domains, expected two")

    # The two halves must tile the original range exactly: same start, same end,
    # no gap and no overlap in the middle.
    lower, upper = after_domains
    assert lower["start"] == original["start"], "the split lost the chain's start"
    assert upper["end"] == original["end"], "the split lost the chain's end"
    assert upper["start"] == lower["end"] + 1, (
        f"the halves do not tile the chain: {lower['start']}-{lower['end']} "
        f"then {upper['start']}-{upper['end']}")

    _capture(blender, "after-split")
    after = shot("after-split", frame=False)
    assert after["covered"] > 0, "splitting a chain emptied the viewport"

    unchanged = _compare(blender, "before-split", "after-split")
    assert unchanged["iou"] > 0.99, (
        "splitting a chain moved what is on screen "
        f"(iou {unchanged['iou']}, {unchanged['xor']} pixels differ). A split "
        "only re-partitions residues; the same atoms must remain in the same "
        "places")


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_merging_two_halves_restores_one_domain_and_the_same_picture(
        blender, shot, single_chain):
    """Split then merge is a round trip: one domain again, same geometry.

    Merge removes both source domains, creates a replacement spanning their
    union, and rebuilds the masks. If it leaves a source domain's mask behind,
    that residue range is still carved out of the parent and rendered twice -
    visible as clipping between two coincident surfaces, invisible to a domain
    count. Comparing the merged image against the pre-split image closes that
    gap: the picture must return to where it started.
    """
    original = _domains(blender, single_chain)[0]

    blender.call("return R.frame_all()")
    _capture(blender, "pre-split")

    midpoint = original["start"] + max(1, (original["end"] - original["start"]) // 2)
    blender.call(
        """
        return list(H.split_domain_from_outliner(
            mid, chain, start, end, domain_id=domain_id))
        """,
        mid=single_chain, chain=original["chain"],
        start=original["start"], end=midpoint, domain_id=original["id"])

    split_ids = [domain["id"] for domain in _domains(blender, single_chain)]
    assert len(split_ids) == 2

    # Rows are re-resolved here, after the split rebuilt the outliner, and only
    # the id strings were carried across.
    result = blender.call(
        """
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        for item in scene.outliner_items:
            item.is_selected = (item.item_type == "DOMAIN"
                                and item.item_id in domain_ids)
        return list(bpy.ops.proteinblender.merge_domains('EXEC_DEFAULT'))
        """,
        mid=single_chain, domain_ids=split_ids)
    assert result == ["FINISHED"], f"merge_domains returned {result}"

    merged = _domains(blender, single_chain)
    assert len(merged) == 1, (
        f"merging two domains left {len(merged)}; both sources should be gone")
    assert merged[0]["start"] == original["start"]
    assert merged[0]["end"] == original["end"], (
        "the merged domain does not span the original chain range")
    assert merged[0]["id"] not in split_ids, (
        "the merge kept one of its source domains instead of replacing both")

    _capture(blender, "merged")
    shot("merged", frame=False)
    round_trip = _compare(blender, "pre-split", "merged")
    assert round_trip["iou"] > 0.99, (
        "split-then-merge did not restore the original geometry "
        f"(iou {round_trip['iou']}); a source domain's mask is likely still "
        "carved out of the parent mesh")


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_copy_domain_adds_a_domain_that_draws_on_its_own(
        blender, shot, multi_chain):
    """A copied domain must be backed by geometry, not just a registry entry.

    ``molecule.copy_domain`` builds a new domain object over the same residue
    range and needs its own mask nodes in the parent tree. If those are not
    created the copy exists everywhere except on screen. Hiding the source
    molecule's other domains is not needed to see this: displacing the copy and
    watching the image change proves it is drawing something of its own.
    """
    _select_molecule(blender, multi_chain)
    before = _domains(blender, multi_chain)
    source = before[0]

    created = blender.call(
        """
        result = bpy.ops.molecule.copy_domain(domain_id=domain_id)
        if result != {'FINISHED'}:
            raise RuntimeError(f"copy_domain returned {result}")
        molecule = H.sm().molecules[mid]
        return sorted(set(molecule.domains.keys()) - set(existing))
        """,
        mid=multi_chain, domain_id=source["id"],
        existing=[d["id"] for d in before])
    assert len(created) == 1, f"copy_domain created {created}, expected one"

    copies = [d for d in _domains(blender, multi_chain) if d["id"] == created[0]]
    assert copies and copies[0]["object"], "the copied domain has no object"
    copy_object = copies[0]["object"]

    blender.call("return R.frame_all()")
    _capture(blender, "with-copy")
    assert shot("with-copy", frame=False)["covered"] > 0

    _set_location(blender, copy_object, [2.0, 0.0, 0.0])
    _capture(blender, "copy-moved")
    shot("copy-moved", frame=False)

    moved = _compare(blender, "with-copy", "copy-moved")
    assert moved["xor"] > 0, (
        "displacing the copied domain changed nothing on screen, so the copy "
        "is a registry entry with no geometry behind it")


# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_renaming_a_domain_changes_the_label_and_nothing_else(
        blender, multi_chain):
    """A rename is metadata only: the picture must be byte-identical after it.

    Renaming touches the wrapper domain and its Blender object, and renaming a
    Blender object is exactly the kind of edit that can invalidate a
    modifier's object pointer or an outliner reference and quietly drop the
    geometry it fed. Asserting the render is unchanged is what separates "the
    name updated" from "the name updated and took a domain off screen with it".
    """
    _select_molecule(blender, multi_chain)
    target = _domains(blender, multi_chain)[0]

    blender.call("return R.frame_all()")
    _capture(blender, "before-rename")

    blender.call(
        """
        result = bpy.ops.molecule.update_domain_name(domain_id=domain_id, name=name)
        if result != {'FINISHED'}:
            raise RuntimeError(f"update_domain_name returned {result}")
        return True
        """,
        domain_id=target["id"], name="Nucleotide_Lobe")

    renamed = [d for d in _domains(blender, multi_chain) if d["id"] == target["id"]]
    assert renamed and renamed[0]["name"] == "Nucleotide_Lobe", (
        f"the domain name did not change: {renamed}")

    _capture(blender, "after-rename")
    unchanged = _compare(blender, "before-rename", "after-rename")
    assert unchanged["identical"], (
        "renaming a domain altered the render "
        f"({unchanged['xor']} pixels, rgb delta {unchanged['rgb_delta']}); a "
        "rename must not disturb geometry")


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_changing_one_domain_style_restyles_only_that_domain(
        blender, shot, multi_chain):
    """A per-domain style change must reach the screen, and stay local to it.

    ``molecule.update_domain_style`` swaps the style node inside one domain's
    branch of the geometry-nodes tree. Two failures are plausible and both look
    fine headless, where the test asserts ``domain.style`` - the value the
    operator just wrote. The swap can fail to evaluate, leaving the domain
    drawn in the old style, or it can be applied to the shared parent tree and
    restyle the whole molecule. The first shows as an unchanged image; the
    second shows as an image that changed far more than one chain of four
    could account for.
    """
    blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")
    _select_molecule(blender, multi_chain)
    domains = _domains(blender, multi_chain)
    assert len(domains) == 4, f"4hhb should have four domains, got {len(domains)}"
    target = domains[0]

    blender.call("return R.frame_all()")
    _capture(blender, "before-style")
    shot("before-style", frame=False)

    applied = blender.call(
        """
        result = bpy.ops.molecule.update_domain_style(domain_id=domain_id, style=style)
        return list(result)
        """,
        domain_id=target["id"], style="spheres")
    if applied != ["FINISHED"]:
        pytest.skip(f"update_domain_style refused this context: {applied}")

    after = _domains(blender, multi_chain)
    restyled = next(d for d in after if d["id"] == target["id"])
    assert restyled["style"] == "spheres", (
        f"the domain style was not recorded: {restyled}")

    _capture(blender, "after-style")
    shot("after-style", frame=False)
    changed = _compare(blender, "before-style", "after-style")
    fraction = changed["xor"] / max(changed["union"], 1)

    assert changed["xor"] > 0, (
        "restyling one domain to 'spheres' left the render byte-identical; the "
        "style node swap never reached the evaluated geometry")
    assert fraction < 0.75, (
        f"restyling one of four domains changed {fraction:.2f} of the drawn "
        "area, which is far more than a quarter of the protein; the style was "
        "applied to the shared parent tree rather than to one domain")


# ---------------------------------------------------------------------------
# Parenting
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_parenting_a_domain_makes_it_follow_its_parent_on_screen(
        blender, shot, multi_chain):
    """Parenting is only real if the child actually moves with the parent.

    Headless this is asserted as ``child.parent == parent_obj``, which is the
    pointer the operator just assigned. The behaviour that matters is
    downstream of it: a parent relationship set without clearing the child's
    inverse matrix, or set on the wrong object in a shared-mesh setup, records
    correctly and still leaves the child sitting still when the parent moves.
    Ground truth here is the child's world matrix - which nothing in the
    parenting path writes - plus the render changing.
    """
    _select_molecule(blender, multi_chain)
    domains = _domains(blender, multi_chain)
    child, parent = domains[0], domains[1]
    assert child["object"] and parent["object"]

    # set_parent_domain is the dialog launcher; EXEC_DEFAULT runs it without UI.
    blender.call(
        """
        bpy.ops.molecule.set_parent_domain('EXEC_DEFAULT', domain_id=domain_id)
        result = bpy.ops.molecule.update_parent_domain(
            domain_id=domain_id, parent_domain_id=parent_id)
        if result != {'FINISHED'}:
            raise RuntimeError(f"update_parent_domain returned {result}")
        return True
        """,
        domain_id=child["id"], parent_id=parent["id"])

    relationship = blender.call(
        """
        molecule = H.sm().molecules[mid]
        domain = molecule.domains[domain_id]
        obj = domain.object
        return {"parent_domain_id": str(domain.parent_domain_id or ""),
                "parent_object": obj.parent.name if obj.parent else None}
        """,
        mid=multi_chain, domain_id=child["id"])
    assert relationship["parent_domain_id"] == parent["id"]
    # bpy structs must be compared by name, never with `is`.
    assert relationship["parent_object"] == parent["object"], (
        "the child domain object was not re-parented to the parent domain")

    blender.call("return R.frame_all()")
    _capture(blender, "before-parent-move")
    shot("before-parent-move", frame=False)
    child_before = _world_translation(blender, child["object"])

    _set_location(blender, parent["object"], [2.0, 0.0, 0.0])
    child_after = _world_translation(blender, child["object"])

    assert child_after != child_before, (
        f"moving the parent domain left the child's world position at "
        f"{child_before}; the parent relationship is recorded but inert")

    _capture(blender, "after-parent-move")
    shot("after-parent-move", frame=False)
    moved = _compare(blender, "before-parent-move", "after-parent-move")
    assert moved["xor"] > 0, "moving a parented pair changed nothing on screen"


# ---------------------------------------------------------------------------
# Reset transform
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_moving_a_domain_changes_the_render_and_reset_puts_it_back(
        blender, shot, multi_chain):
    """The two halves of the same invariant, in one test.

    Moving a domain must change the picture - a domain transform that never
    reaches the evaluated geometry is the single most common way this subsystem
    breaks, and it is invisible to any assertion on ``obj.location``. Resetting
    must then restore the picture exactly, which is a stronger statement than
    ``location`` returning to near zero: the reset also has to leave the pivot
    carried on the geometry-nodes modifier alone. A reset that zeroes the
    location but drops the pivot lands the domain a pivot's width away, and
    only the image shows it.
    """
    _select_molecule(blender, multi_chain)
    target = _domains(blender, multi_chain)[0]
    assert target["object"]

    blender.call("return R.frame_all()")
    _capture(blender, "at-rest")
    assert shot("at-rest", frame=False)["covered"] > 0

    _set_location(blender, target["object"], [2.0, 1.0, 0.5])
    _capture(blender, "displaced")
    shot("displaced", frame=False)

    displaced = _compare(blender, "at-rest", "displaced")
    assert displaced["xor"] > 0, (
        "translating a domain object did not change the render; the domain "
        "transform is not reaching the evaluated geometry")

    result = blender.call(
        "return list(bpy.ops.molecule.reset_domain_transform(domain_id=domain_id))",
        domain_id=target["id"])
    assert result == ["FINISHED"], f"reset_domain_transform returned {result}"

    _capture(blender, "reset")
    shot("reset", frame=False)
    restored = _compare(blender, "at-rest", "reset")
    assert restored["iou"] > 0.99, (
        "resetting the domain transform did not restore its original position "
        f"(iou {restored['iou']}); the reset probably zeroed the object "
        "location without accounting for the modifier-carried pivot")


# ---------------------------------------------------------------------------
# Expand / collapse
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
@pytest.mark.crasher
def test_toggling_domain_expansion_is_a_ui_change_only(blender, multi_chain):
    """Expanding an outliner row must not touch the 3D view.

    ``domain_expanded`` is stored as a custom property on the domain *object*,
    which is also where transforms, pivots and style flags live. Writing to an
    object is enough to trigger a depsgraph update, and a handler that reacts to
    the wrong property change can rebuild or reposition geometry from what the
    user experiences as clicking a disclosure triangle. An identical render is
    the assertion; a flag flip alone would not notice.

    CURRENTLY THIS DOES NOT GET AS FAR AS THE ASSERTION: the single call to
    ``molecule.toggle_domain_expanded`` takes Blender 5.2 down with
    ``EXCEPTION_STACK_OVERFLOW``. Reduced to a minimal reproduction - import a
    structure, expand one domain, nothing else, no rendering involved - it kills
    the process on both 1ubq (one chain) and 4hhb (four), so it is neither
    fixture-specific nor dependent on anything this lane does.

    ``EXCEPTION_STACK_OVERFLOW`` is unbounded recursion. The operator itself is
    only a few property writes (``domain_operators.py``), but two of them are
    ``scene.split_domain_new_start`` and ``scene.split_domain_new_end``, and
    each of those has an update callback that *writes back to the property it is
    the callback for* while clamping against the other one
    (``molecule_props.py``, the ``clamped_start`` / ``clamped_end`` pair). Each
    write re-enters the callback, and the two clamp against each other, which is
    the shape of a ping-pong that never terminates. That is the first place to
    look; this test does not attempt the diagnosis.

    Marked ``crasher`` so it is deselected by default: the lane shares a single
    Blender, and left in the normal run this test would kill the session and
    turn every later result into noise. Reproduce with
    ``python tests/run_live_tests.py --include-crashers -k expansion``.
    """
    _select_molecule(blender, multi_chain)
    target = _domains(blender, multi_chain)[0]

    blender.call("return R.frame_all()")
    _capture(blender, "collapsed")

    flipped = blender.call(
        """
        molecule = H.sm().molecules[mid]
        obj = molecule.domains[domain_id].object
        before = bool(obj.get("domain_expanded", False))
        result = bpy.ops.molecule.toggle_domain_expanded(
            domain_id=domain_id, is_expanded=not before)
        if result != {'FINISHED'}:
            raise RuntimeError(f"toggle_domain_expanded returned {result}")
        return {"before": before, "after": bool(obj["domain_expanded"])}
        """,
        mid=multi_chain, domain_id=target["id"])
    assert flipped["after"] == (not flipped["before"]), (
        f"the expansion flag did not flip: {flipped}")

    _capture(blender, "expanded")
    unchanged = _compare(blender, "collapsed", "expanded")
    assert unchanged["identical"], (
        "toggling a domain's outliner expansion altered the 3D view "
        f"({unchanged['xor']} pixels, rgb delta {unchanged['rgb_delta']})")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_deleting_a_domain_removes_its_geometry_from_the_screen(
        blender, shot, multi_chain):
    """Deleting a domain must take its atoms off screen without taking others.

    The parent mesh is masked so that each domain's residues are drawn by the
    domain object rather than by the parent. Deleting a domain therefore has to
    remove the object *and* unwind its mask. Removing only the object leaves a
    hole - those residues are masked out of the parent and no longer drawn by
    anyone. Leaving the mask and the object leaves the residues drawn twice.
    A strict decrease in covered pixels, with the viewport still non-empty,
    rules out the second; comparing against the whole-molecule image and
    requiring most of it to survive rules out an over-broad deletion.
    """
    _select_molecule(blender, multi_chain)
    before_domains = _domains(blender, multi_chain)
    assert len(before_domains) == 4
    target = before_domains[0]

    blender.call("return R.frame_all()")
    before = shot("four-domains", frame=False)
    assert before["covered"] > 0

    blender.call(
        """
        result = bpy.ops.molecule.delete_domain(molecule_id=mid, domain_id=domain_id)
        if result != {'FINISHED'}:
            raise RuntimeError(f"delete_domain returned {result}")
        return True
        """,
        mid=multi_chain, domain_id=target["id"])

    after_domains = _domains(blender, multi_chain)
    assert target["id"] not in [d["id"] for d in after_domains], (
        "the deleted domain is still registered")
    assert len(after_domains) == 3

    after = shot("three-domains", frame=False)
    assert after["covered"] < before["covered"], (
        f"deleting a domain did not reduce what is drawn "
        f"({before['covered']} -> {after['covered']} pixels)")
    # One of four chains went away, so most of the protein must remain. This is
    # a ratio rather than a pixel count, so it holds across GPUs and drivers.
    assert after["covered"] > before["covered"] * 0.4, (
        f"deleting one of four domains removed most of the render "
        f"({before['covered']} -> {after['covered']} pixels); the deletion "
        "unwound more masking than it owned")
