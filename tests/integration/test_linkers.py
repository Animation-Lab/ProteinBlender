"""Integration tests for the LINKER subsystem.

Linkers connect two chains *within a single puppet* (same-puppet only). Each is
a ``PB2_LinkerDefinition`` in ``scene.pb2_linkers`` backed by a Blender curve
object (``curve_object_name``). The ``pb2.add_linker`` operator drives the whole
flow; its two endpoint enums use ``A_``/``B_`` prefixed identifiers so the same
outliner item_id can appear in both dropdowns without colliding — the prefix is
stripped to the real item_id inside ``execute``.

These drive the addon's own operators (``pb2.add_linker`` / ``update_linker`` /
``toggle_linker_visibility`` / ``edit_linker`` / ``remove_linker``) and the
cascade cleanup handlers, then assert observable scene state. Ported and
expanded from the retired hand-run linker audit.
"""

from typing import NamedTuple

import pytest
import bpy
import helpers as H


# --------------------------------------------------------------------------
# Setup helpers
# --------------------------------------------------------------------------

class _Row(NamedTuple):
    """An immutable snapshot of one ``scene.outliner_items`` row.

    Most PB operators finish by calling ``build_outliner_hierarchy``, which
    clears and refills that CollectionProperty. Any live row object held across
    such a call is left dangling: once Blender reuses the slot, reads return
    defaults (``item_id == ""``) rather than raising. Holding rows across
    ``create_puppet`` made these tests fail intermittently, depending on whether
    the freed slot had been reused yet.

    Snapshot what the assertions need, and re-resolve by id when live state is
    required.
    """
    item_id: str
    name: str
    chain_id: str
    chain_start: int
    chain_end: int


def _snap(item) -> _Row:
    return _Row(
        item_id=item.item_id,
        name=item.name,
        chain_id=getattr(item, "chain_id", ""),
        chain_start=getattr(item, "chain_start", 0),
        chain_end=getattr(item, "chain_end", 0),
    )


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _puppets():
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "PUPPET" and it.item_id != "puppets_separator"]


def _setup_puppet_two_chains(name="LinkerPuppet"):
    """Import 4hhb, puppet its first two chains. Returns (mid, puppet, [c0, c1]).

    The puppet and chains come back as _Row snapshots taken *after*
    create_puppet has rebuilt the outliner, so callers never hold a stale row.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    chain_ids = [it.item_id for it in _chain_items(mid)[:2]]
    assert len(chain_ids) == 2
    wanted = set(chain_ids)
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in wanted
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=name)

    # Re-resolve from the rebuilt collection; the rows gathered above are gone.
    puppet = next((p for p in _puppets() if p.name == name), None)
    assert puppet is not None, "puppet setup failed"
    by_id = {it.item_id: it for it in bpy.context.scene.outliner_items}
    chains = []
    for cid in chain_ids:
        assert cid in by_id, f"chain row {cid} vanished from the rebuilt outliner"
        chains.append(_snap(by_id[cid]))
    return mid, _snap(puppet), chains


def _mid_residue(chain_item):
    """A residue guaranteed to exist within a chain's range."""
    start = chain_item.chain_start or 1
    end = chain_item.chain_end or start
    return max(start, (start + end) // 2)


def _add_linker(puppet, chain_a, chain_b, **overrides):
    """Add a linker between chain_a and chain_b; return the new linker def."""
    scene = bpy.context.scene
    n_before = len(scene.pb2_linkers)
    kwargs = dict(
        puppet_selector=puppet.item_id,
        endpoint_a_item=f"A_{chain_a.item_id}",
        endpoint_a_residue=_mid_residue(chain_a),
        endpoint_b_item=f"B_{chain_b.item_id}",
        endpoint_b_residue=_mid_residue(chain_b),
        linker_name="TestLinker",
        length_residues=30,
        style="TUBE",
        rendering_mode="QUICK",
    )
    kwargs.update(overrides)
    # EXEC_DEFAULT bypasses the props dialog; execute() reads the props as passed.
    bpy.ops.pb2.add_linker('EXEC_DEFAULT', **kwargs)
    assert len(scene.pb2_linkers) == n_before + 1, "linker definition was not added"
    return scene.pb2_linkers[-1]


def _curve_signature(linker):
    """Deterministic signature of a linker curve's control points."""
    obj = bpy.data.objects.get(linker.curve_object_name)
    if not obj or not obj.data or not obj.data.splines:
        return None
    pts = obj.data.splines[0].bezier_points
    return tuple(round(c, 4) for bp in pts for c in bp.co)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_add_linker_creates_definition_and_curve(scene):
    """add_linker adds a definition, a backing curve object, and is_valid True."""
    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1], linker_name="L_Quick")

    # Definition wired up correctly.
    assert linker.puppet_id == puppet.item_id
    assert linker.endpoint_a_item_id == chains[0].item_id
    assert linker.endpoint_b_item_id == chains[1].item_id
    assert linker.is_valid is True

    # Backing curve object exists in the scene.
    assert linker.curve_object_name
    curve_obj = bpy.data.objects.get(linker.curve_object_name)
    assert curve_obj is not None
    assert curve_obj.type == "CURVE"

    # ...and it actually carries curve geometry. A CURVE object with no splines
    # or no control points is visually nothing — asserting only the object's
    # existence and type would pass for an empty curve (a facade). Require real
    # control points, which is what the linker is for.
    assert _curve_signature(linker) is not None, (
        "linker curve object exists but has no control points")


@pytest.mark.integration
def test_add_linker_rejects_same_chain(scene):
    """Both endpoints on the same chain is rejected (no definition added)."""
    mid, puppet, chains = _setup_puppet_two_chains()
    n_before = len(scene.pb2_linkers)

    raised = False
    res = None
    try:
        res = bpy.ops.pb2.add_linker(
            'EXEC_DEFAULT',
            puppet_selector=puppet.item_id,
            endpoint_a_item=f"A_{chains[0].item_id}",
            endpoint_a_residue=_mid_residue(chains[0]),
            endpoint_b_item=f"B_{chains[0].item_id}",  # same chain
            endpoint_b_residue=_mid_residue(chains[0]),
            linker_name="SelfLink",
        )
    except RuntimeError:
        raised = True

    assert raised or res == {'CANCELLED'}
    assert len(scene.pb2_linkers) == n_before


@pytest.mark.integration
def test_update_linker_rebuilds_geometry(scene):
    """Changing length then update_linker recomputes the curve geometry."""
    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1])

    sig_before = _curve_signature(linker)
    assert sig_before is not None

    # Add substantial slack; more length -> more droop -> different control pts.
    linker.length_residues = min(100, linker.length_residues + 40)
    res = bpy.ops.pb2.update_linker('EXEC_DEFAULT', linker_uid=linker.uid)
    assert res == {'FINISHED'}

    sig_after = _curve_signature(linker)
    assert sig_after is not None
    assert sig_after != sig_before, "curve geometry should change when length changes"


@pytest.mark.integration
def test_update_all_and_select_linker_object(scene):
    """Bulk refresh and viewport selection are both public panel actions."""
    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1])
    curve_obj = bpy.data.objects.get(linker.curve_object_name)
    assert curve_obj is not None

    assert bpy.ops.pb2.update_all_linkers() == {"FINISHED"}
    assert bpy.ops.pb2.select_linker_object(linker_uid=linker.uid) == {"FINISHED"}
    assert bpy.context.active_object == curve_obj
    assert curve_obj.select_get()


@pytest.mark.integration
def test_toggle_linker_visibility(scene):
    """toggle_linker_visibility flips the curve hide flags and is_visible."""
    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1])
    curve_obj = bpy.data.objects.get(linker.curve_object_name)
    assert curve_obj is not None

    before_hide = curve_obj.hide_viewport
    before_flag = linker.is_visible

    bpy.ops.pb2.toggle_linker_visibility('EXEC_DEFAULT', linker_uid=linker.uid)

    assert curve_obj.hide_viewport != before_hide, "curve hide_viewport should flip"
    assert linker.is_visible != before_flag, "is_visible flag should flip"

    # Toggling back restores the original state.
    bpy.ops.pb2.toggle_linker_visibility('EXEC_DEFAULT', linker_uid=linker.uid)
    assert curve_obj.hide_viewport == before_hide
    assert linker.is_visible == before_flag


@pytest.mark.integration
def test_edit_linker_updates_properties(scene):
    """edit_linker rewrites name/length and rebuilds the linker in place."""
    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1], linker_name="Before")
    uid = linker.uid
    new_length = min(100, linker.length_residues + 25)

    # edit_linker.execute validates puppet + both endpoints, so they must be
    # supplied (prefixed) even for a rename. Driven via EXEC_DEFAULT (no dialog).
    res = bpy.ops.pb2.edit_linker(
        'EXEC_DEFAULT',
        linker_uid=uid,
        puppet_selector=puppet.item_id,
        endpoint_a_item=f"A_{chains[0].item_id}",
        endpoint_a_residue=_mid_residue(chains[0]),
        endpoint_b_item=f"B_{chains[1].item_id}",
        endpoint_b_residue=_mid_residue(chains[1]),
        linker_name="After",
        length_residues=new_length,
        style="TUBE",
        rendering_mode="QUICK",
        behavior="GRAVITY",
    )
    assert res == {'FINISHED'}

    edited = next((l for l in scene.pb2_linkers if l.uid == uid), None)
    assert edited is not None
    assert edited.name == "After"
    assert edited.length_residues == new_length
    # Still backed by a live curve object after the in-place rebuild.
    assert bpy.data.objects.get(edited.curve_object_name) is not None


@pytest.mark.integration
def test_remove_linker_deletes_definition_and_curve(scene):
    """remove_linker deletes the definition and its curve object."""
    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1])
    uid = linker.uid
    curve_name = linker.curve_object_name
    n_before = len(scene.pb2_linkers)

    bpy.ops.pb2.remove_linker('EXEC_DEFAULT', linker_uid=uid)

    assert len(scene.pb2_linkers) == n_before - 1
    assert not any(l.uid == uid for l in scene.pb2_linkers)
    assert bpy.data.objects.get(curve_name) is None, "curve object should be removed"


@pytest.mark.integration
def test_cascade_delete_on_puppet_deletion(scene):
    """Deleting the puppet cascades to remove its linkers (on_puppet_deleted)."""
    mid, puppet, chains = _setup_puppet_two_chains()
    _add_linker(puppet, chains[0], chains[1])
    assert len(scene.pb2_linkers) == 1

    bpy.ops.proteinblender.delete_puppet('EXEC_DEFAULT', puppet_id=puppet.item_id)

    assert len(scene.pb2_linkers) == 0, "puppet deletion should remove its linkers"


@pytest.mark.integration
def test_cascade_delete_on_chain_deletion(scene):
    """Deleting an endpoint chain prunes the dangling linker."""
    mid, puppet, chains = _setup_puppet_two_chains()
    _add_linker(puppet, chains[0], chains[1])
    assert len(scene.pb2_linkers) == 1

    # molecule.delete_chain takes the chain *index* (chain_id) + molecule_id.
    # invoke uses invoke_confirm; EXEC_DEFAULT bypasses it to execute().
    bpy.ops.molecule.delete_chain('EXEC_DEFAULT',
                                  chain_id=chains[0].chain_id,
                                  molecule_id=mid)

    assert len(scene.pb2_linkers) == 0, \
        "deleting an endpoint chain should prune the dangling linker"


@pytest.mark.integration
def test_cascade_delete_on_protein_deletion(scene):
    """Deleting the whole protein removes linkers referencing it."""
    mid, puppet, chains = _setup_puppet_two_chains()
    _add_linker(puppet, chains[0], chains[1])
    assert len(scene.pb2_linkers) == 1

    bpy.ops.molecule.delete('EXEC_DEFAULT', molecule_id=mid)

    assert len(scene.pb2_linkers) == 0, \
        "deleting the protein should remove its dependent linkers"


@pytest.mark.integration
def test_update_linker_curve_is_a_noop_when_nothing_changed(scene):
    """Re-running the live update path must reproduce the same curve.

    update_linker_curve is what frame_change_post and depsgraph_update_post
    drive, so it runs constantly. It resolved backbone direction WITHOUT passing
    numeric_chain_id, while the three other call sites (add_linker, edit_linker,
    linker_handlers) all pass it. On a multi-chain object that fallback can
    resolve against the wrong chain, so the binding zones - which are built from
    those directions - come out different from what add_linker just created.

    4hhb is 4 chains, and a non-zero binding zone is what makes the direction
    reach the geometry, so a drift shows up as moved control points.
    """
    from proteinblender.linkers.linker_geometry import update_linker_curve

    mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1],
                         linker_name="L_Idempotent", binding_zone_residues=4)

    curve_obj = bpy.data.objects.get(linker.curve_object_name)
    assert curve_obj is not None
    before = [tuple(bp.co) for bp in curve_obj.data.splines[0].bezier_points]
    assert before, "expected control points on the created curve"

    assert update_linker_curve(linker) is not False

    after = [tuple(bp.co) for bp in curve_obj.data.splines[0].bezier_points]
    assert len(after) == len(before), "update changed the control point count"
    for i, (b, a) in enumerate(zip(before, after)):
        for axis in range(3):
            assert abs(b[axis] - a[axis]) < 1e-4, (
                f"control point {i} moved on axis {axis} ({b[axis]} -> {a[axis]}) "
                "with no input change - update resolved a different backbone direction"
            )
