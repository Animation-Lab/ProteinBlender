"""Integration tests for the PUPPET (group) subsystem.

Puppets are ``scene.outliner_items`` with ``item_type='PUPPET'``. Membership is
tracked via each item's ``puppet_memberships`` (comma-separated item_ids) and is
EXCLUSIVE — a chain/domain may belong to only one puppet. The controller is an
Empty (referenced by ``controller_object_name``) that every member domain object
is parented to, so moving the controller moves the whole puppet.

These drive the addon's own operators (``proteinblender.create_puppet`` /
``edit_puppet`` / ``delete_puppet``) exactly as the Protein Outliner would, then
assert observable scene state. Ported and expanded from
the retired hand-run puppet audit.
"""

import pytest
import bpy
import helpers as H


# --------------------------------------------------------------------------
# Setup helpers
# --------------------------------------------------------------------------

def _build_outliner():
    """(Re)build the outliner hierarchy so CHAIN rows exist after an import."""
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _import_4hhb():
    """Import the 4-chain 4hhb (offline) and build the outliner. Returns id."""
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    return mid


def _chain_items(mid):
    """CHAIN outliner rows belonging to molecule *mid*, in outliner order."""
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _puppets():
    """Real puppet rows (excludes the 'puppets_separator' header row)."""
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "PUPPET" and it.item_id != "puppets_separator"]


def _select_only_items(item_ids):
    """Set ``is_selected`` True on exactly the given outliner item_ids."""
    wanted = set(item_ids)
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in wanted


def _member_objects(puppet_item):
    """Blender objects for a puppet's recorded members (via object_name)."""
    ids = [m for m in (puppet_item.puppet_memberships or "").split(",") if m]
    objs = []
    for mid in ids:
        for it in bpy.context.scene.outliner_items:
            if it.item_id == mid and it.object_name:
                obj = bpy.data.objects.get(it.object_name)
                if obj:
                    objs.append(obj)
                break
    return objs


def _make_puppet(mid, name="Puppet_AB", n_chains=2):
    """Create a puppet from the first *n_chains* chains of *mid*. Returns row.

    create_puppet rebuilds scene.outliner_items, which invalidates every row
    gathered beforehand - a stale row reads back "" instead of raising. Collect
    the ids first, then re-resolve the rows from the rebuilt collection.
    """
    chain_ids = [c.item_id for c in _chain_items(mid)[:n_chains]]
    assert len(chain_ids) >= n_chains, "need enough chains to build the puppet"
    _select_only_items(chain_ids)
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=name)
    by_id = {it.item_id: it for it in bpy.context.scene.outliner_items}
    chains = [by_id[cid] for cid in chain_ids if cid in by_id]
    assert len(chains) == len(chain_ids), "chain rows vanished from the rebuilt outliner"
    return next((p for p in _puppets() if p.name == name), None), chains


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_create_puppet_from_two_chains(scene):
    """Creating a puppet yields a PUPPET row, a controller Empty and members."""
    mid = _import_4hhb()
    puppet, chains = _make_puppet(mid, "Puppet_AB", 2)

    assert puppet is not None, "PUPPET outliner item should appear"

    # Controller Empty exists and is an EMPTY.
    controller = bpy.data.objects.get(puppet.controller_object_name)
    assert controller is not None, "controller Empty should exist"
    assert controller.type == "EMPTY"

    # Both chains recorded as members, and each chain now knows its puppet.
    members = [m for m in (puppet.puppet_memberships or "").split(",") if m]
    for c in chains:
        assert c.item_id in members
        assert puppet.item_id in (c.puppet_memberships or "").split(",")


@pytest.mark.integration
def test_puppet_controller_parents_member_objects(scene):
    """Every member's domain object is parented to the controller Empty."""
    mid = _import_4hhb()
    puppet, chains = _make_puppet(mid, "Puppet_AB", 2)
    controller = bpy.data.objects.get(puppet.controller_object_name)
    assert controller is not None

    children = [o for o in bpy.data.objects if o.parent is controller]
    assert len(children) >= 2, f"controller should parent >=2 objects, got {len(children)}"

    # The recorded members are exactly the parented objects.
    member_objs = _member_objects(puppet)
    assert member_objs, "members should resolve to objects"
    for obj in member_objs:
        assert obj.parent is controller


@pytest.mark.integration
def test_move_controller_moves_members(scene):
    """Moving the controller moves member objects by the matching delta.

    The controller spawns at the bbox centre of its members (not the origin),
    so the expected child delta is (setpoint - old_controller_location).
    """
    mid = _import_4hhb()
    puppet, _chains = _make_puppet(mid, "Puppet_AB", 2)
    controller = bpy.data.objects.get(puppet.controller_object_name)
    children = [o for o in bpy.data.objects if o.parent is controller]
    assert controller is not None and children

    before_ctrl = tuple(controller.location)
    before = {c.name: tuple(c.matrix_world.translation) for c in children}

    controller.location = (5.0, 3.0, 1.0)
    bpy.context.view_layer.update()

    after = {c.name: tuple(c.matrix_world.translation) for c in children}
    expected = (5.0 - before_ctrl[0], 3.0 - before_ctrl[1], 1.0 - before_ctrl[2])
    for name in before:
        delta = tuple(after[name][i] - before[name][i] for i in range(3))
        for i in range(3):
            assert abs(delta[i] - expected[i]) < 0.01, \
                f"{name} moved {delta}, expected {expected}"


@pytest.mark.integration
def test_edit_puppet_rename(scene):
    """edit_puppet(action='RENAME', puppet_id=...) renames the puppet row."""
    mid = _import_4hhb()
    puppet, _chains = _make_puppet(mid, "Puppet_AB", 2)
    pid = puppet.item_id

    bpy.ops.proteinblender.edit_puppet(
        'EXEC_DEFAULT', action='RENAME', puppet_id=pid, new_name="Renamed_Puppet")

    updated = next((it for it in scene.outliner_items if it.item_id == pid), None)
    assert updated is not None and updated.name == "Renamed_Puppet"


@pytest.mark.integration
def test_exclusive_membership_rejected(scene):
    """A chain already in a puppet cannot seed a second puppet (exclusivity)."""
    mid = _import_4hhb()
    puppet, chains = _make_puppet(mid, "Puppet_AB", 2)
    assert puppet is not None

    n_before = len(_puppets())

    # Select a chain that's already puppeted and try to create another puppet.
    _select_only_items([chains[0].item_id])
    raised = False
    res = None
    try:
        # EXEC_DEFAULT: execute() reports {'ERROR'} + returns CANCELLED, which
        # bpy.ops surfaces as a RuntimeError.
        res = bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT',
                                                   puppet_name="Conflicting")
    except RuntimeError:
        raised = True

    assert raised or res == {'CANCELLED'}, "duplicate-membership create should be rejected"
    assert len(_puppets()) == n_before, "no new puppet should have been created"


@pytest.mark.integration
def test_delete_puppet_unparents_and_removes_controller(scene):
    """delete_puppet removes the row + controller and restores member objects."""
    mid = _import_4hhb()
    puppet, chains = _make_puppet(mid, "Puppet_AB", 2)
    pid = puppet.item_id
    controller_name = puppet.controller_object_name

    # Capture member world positions before deletion (should be preserved).
    members = _member_objects(puppet)
    assert members
    before_world = {o.name: tuple(o.matrix_world.translation) for o in members}
    member_names = list(before_world.keys())

    # invoke uses invoke_confirm; EXEC_DEFAULT bypasses it straight to execute.
    bpy.ops.proteinblender.delete_puppet('EXEC_DEFAULT', puppet_id=pid)

    # Puppet row gone.
    assert not any(it.item_id == pid for it in scene.outliner_items)
    # Controller Empty gone.
    assert bpy.data.objects.get(controller_name) is None

    # Member objects survive, un-parented, at their original world positions.
    for name in member_names:
        obj = bpy.data.objects.get(name)
        assert obj is not None, f"member {name} should still exist"
        assert obj.parent is None, f"member {name} should be un-parented"
        after = tuple(obj.matrix_world.translation)
        for i in range(3):
            assert abs(after[i] - before_world[name][i]) < 0.01

    # Membership stripped from the chain rows.
    for c in _chain_items(mid):
        assert pid not in (c.puppet_memberships or "").split(",")


@pytest.mark.integration
def test_edit_puppet_membership_change_via_member_ids(scene):
    """edit_puppet(action='EDIT') recomputes membership from the dialog's
    ``item_selections`` collection; run without the dialog it takes the new
    membership from the scriptable ``member_ids`` string instead. Start with a
    two-chain puppet, then EDIT to keep only the first chain.
    """
    mid = _import_4hhb()
    puppet, chains = _make_puppet(mid, "EP", 2)
    pid = puppet.item_id
    keep, drop = chains[0], chains[1]

    # Sanity: both chains are members before the edit.
    before = set((puppet.puppet_memberships or "").split(","))
    assert {keep.item_id, drop.item_id} <= before

    bpy.ops.proteinblender.edit_puppet(
        'EXEC_DEFAULT', action='EDIT', puppet_id=pid, new_name=puppet.name,
        member_ids=keep.item_id)

    updated = next(it for it in scene.outliner_items if it.item_id == pid)
    members = [m for m in (updated.puppet_memberships or "").split(",") if m]
    assert keep.item_id in members, "kept chain should remain a member"
    assert drop.item_id not in members, "unticked chain should be removed"
    # The dropped chain's row no longer references this puppet.
    drop_row = next(it for it in scene.outliner_items if it.item_id == drop.item_id)
    assert pid not in (drop_row.puppet_memberships or "").split(",")
