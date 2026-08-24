"""Scene builders for the save/load round-trip lane - one per subsystem.

Each builder populates the scene through the add-on's *public operators* (the
same ones the panels drive) and then **asserts that it actually created the
state it claims to**. That assertion is not decoration: a builder that quietly
fails leaves an empty scene, and an empty scene round-trips perfectly. Every
vacuous pass in the old lane came from exactly that - `pose_count` and
`linker_count` were compared as `0 == 0` in all five cases because no builder
ever made a pose or a linker.

Builders run only in-process (before the save). The snapshot that follows is
generic, so a builder never has to describe what it made - it only has to make
it, and prove it.
"""

from __future__ import annotations

import json

import bpy

import helpers as H


# ---------------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------------

def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_rows(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _select_rows(item_ids):
    wanted = set(item_ids)
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in wanted


def _make_puppet(mid, name, n_chains=2, chain_indices=None):
    """Create a puppet from *n_chains* chains (or the given indices). Returns
    (puppet_id, controller, [chain_item_ids]).

    create_puppet rebuilds scene.outliner_items, so every row captured
    beforehand is dangling afterwards - ids are collected first and the rows
    re-resolved from the rebuilt collection.
    """
    _build_outliner()
    rows = _chain_rows(mid)
    if chain_indices is None:
        chain_indices = range(n_chains)
    chain_ids = [rows[i].item_id for i in chain_indices if i < len(rows)]
    assert len(chain_ids) == len(list(chain_indices)), (
        f"need chains {list(chain_indices)} to build a puppet, found {len(rows)}")
    _select_rows(chain_ids)
    assert bpy.ops.proteinblender.create_puppet(
        'EXEC_DEFAULT', puppet_name=name) == {'FINISHED'}

    puppet = next((it for it in bpy.context.scene.outliner_items
                   if it.item_type == "PUPPET" and it.name == name
                   and it.controller_object_name), None)
    assert puppet is not None, f"puppet row {name!r} was not created"
    controller = bpy.data.objects.get(puppet.controller_object_name)
    assert controller is not None, "puppet controller Empty was not created"
    return puppet.item_id, controller, chain_ids


def _mid_residue(row):
    start = row.chain_start or 1
    end = row.chain_end or start
    return max(start, (start + end) // 2)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_empty():
    """The degenerate case: an add-on-registered scene with no molecules.

    Worth keeping - it is the only case that proves a reopened file does not
    *invent* state (rows, linkers, orphan wrappers) out of nothing.
    """
    assert len(bpy.context.scene.molecule_list_items) == 0


def build_single_protein():
    mid = H.import_local("1ubq.pdb", "1ubq")
    assert H.list_item(mid) is not None
    assert H.sm().molecules[mid].object is not None


def build_multi_chain():
    mid = H.import_local("4hhb.pdb", "4hhb")
    assert len(H.sm().molecules[mid].domains) == 4, "4hhb should auto-domain 4 chains"


def build_domains():
    """Split a chain, rename the pieces, and give every domain a distinct
    colour and style - the state a user spends real time building."""
    mid = H.import_local("4hhb.pdb", "4hhb")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid
    assert H.split_domain_from_outliner(mid, "A", 1, 60) == {"FINISHED"}
    _build_outliner()

    mol = H.sm().molecules[mid]
    assert len(mol.domains) >= 5, (
        f"split should have produced an extra domain, have {len(mol.domains)}")

    styles = ["cartoon", "spheres", "surface", "ribbon"]
    renamed = 0
    for i, (_did, domain) in enumerate(sorted(mol.domains.items())):
        obj = getattr(domain, "object", None)
        if obj is None:
            continue
        obj.domain_color = (0.13 * (i + 1), 0.27 * (i + 1) % 1.0, 0.61, 1.0)
        try:
            obj.domain_style = styles[i % len(styles)]
        except (TypeError, ValueError):
            pass
        renamed += 1
    assert renamed >= 5, "expected to colour at least five domain objects"

    # Rename a real DOMAIN row through the public operator.
    dom_row = next(it for it in scene.outliner_items if it.item_type == "DOMAIN")
    assert bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=dom_row.item_id, item_type='DOMAIN',
        new_name="Catalytic Core") == {'FINISHED'}
    assert mol.domains[dom_row.item_id].name == "Catalytic Core"

    # Expansion state is its own persisted Object property, and the operator
    # that sets it once took Blender down with a stack overflow - a reload that
    # loses it is a small bug, but it is the kind this lane must not be blind to.
    assert bpy.ops.molecule.toggle_domain_expanded(
        'EXEC_DEFAULT', domain_id=dom_row.item_id,
        is_expanded=True) == {'FINISHED'}
    assert any(o.get("domain_expanded") for o in bpy.data.objects), \
        "toggle_domain_expanded left no object expanded"


def build_biological_assembly():
    """Build a deposited biological assembly and expect it to survive a reload.

    The copies live as a geometry-nodes assembly node in every domain object's
    tree, reading a shared transforms data object. Both are ordinary datablocks,
    so a reload should return the assembled structure - which is what lets
    Scene.pb_assembly_id (the transient picker) be excluded from the snapshot.
    """
    from proteinblender.core import assembly as assembly_core

    mid = H.import_local("4ins.pdb", "4ins")
    bpy.context.scene.selected_molecule_id = mid
    molecule = H.sm().molecules[mid]

    assert assembly_core.has_buildable_symmetry(molecule), \
        "4ins should offer a symmetric assembly"
    assert assembly_core.build_assembly(molecule, "3"), "assembly 3 failed to build"
    assert assembly_core.built_assembly_id(molecule) == "3"
    _build_outliner()


def build_chain_rename():
    """A user-renamed chain.

    Chain names have no home on the outliner row (rows are regenerated from
    ``auth_chain_id_map`` on every rebuild); they persist only in the list
    item's ``chain_custom_names`` JSON map. That makes this the narrowest
    possible probe of "is the whole persistent field set carried across a
    reload", which is the bug class this lane exists for.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    rows = _chain_rows(mid)
    assert len(rows) >= 2

    for row_id, new_name in ((rows[0].item_id, "Alpha Globin"),
                             (rows[1].item_id, "Beta Globin")):
        assert bpy.ops.proteinblender.rename_domain(
            'EXEC_DEFAULT', target_item_id=row_id, item_type='CHAIN',
            new_name=new_name) == {'FINISHED'}

    stored = json.loads(H.list_item(mid).chain_custom_names or "{}")
    assert sorted(stored.values()) == ["Alpha Globin", "Beta Globin"], (
        f"chain renames were not stored before saving: {stored}")


def build_chain_copy():
    """A copy of a chain that has been split into domains.

    A chain copy is not an object property: it is a set of domains tied
    together by ``copy_group_id``, and the outliner reads that to decide
    whether they are a chain of their own or ordinary domains of the chain
    they were copied from. Lose it on reload and the copy does not merely look
    wrong - it folds back into its source chain, which then reports twice the
    domains it has.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid
    assert H.split_domain_from_outliner(mid, "A", 1, 60) == {"FINISHED"}
    _build_outliner()

    from proteinblender.utils.chain_utils import chain_token_from_item

    row = next(r for r in _chain_rows(mid) if r.name == "Chain A")
    assert bpy.ops.molecule.copy_chain(
        'EXEC_DEFAULT', molecule_id=mid,
        chain_id=chain_token_from_item(row)) == {'FINISHED'}

    mol = H.sm().molecules[mid]
    copies = [d for d in mol.domains.values()
              if getattr(d, "copy_group_id", "")]
    assert len(copies) == 2, (
        f"copying a split chain should copy both domains, copied {len(copies)}")
    assert len({d.copy_group_id for d in copies}) == 1, \
        "the copied domains did not end up in one chain copy"

    _build_outliner()
    copy_rows = [r for r in _chain_rows(mid) if r.has_domains and r.name.endswith(" 1")]
    assert len(copy_rows) == 1, "the chain copy has no chain row of its own"


def build_pivots():
    """Non-default pivots on several domains.

    A pivot is not mesh data and not an object transform - it lives as a value
    on the geometry-nodes modifier, which is exactly the kind of state a naive
    round trip drops. Setting First on one domain and Last on another makes the
    two distinguishable, so a reload that resets both to the origin cannot pass
    by symmetry.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid
    _build_outliner()

    # The pivot operators target CHAIN rows whose object carries the
    # alpha-carbon attributes MolecularNodes stamps on protein meshes; a row
    # with no object (a split chain) or a non-protein chain is not a valid
    # target and the operator cancels. Pick qualifying rows the same way the
    # pivot integration tests do.
    targets = []
    for row in _chain_rows(mid):
        obj = bpy.data.objects.get(row.object_name) if row.object_name else None
        mesh = getattr(obj, "data", None)
        if mesh is not None and "is_alpha_carbon" in mesh.attributes:
            targets.append(row.item_id)
    assert len(targets) >= 2, (
        f"4hhb should offer at least two pivotable chains, found {len(targets)}")

    _select_rows([targets[0]])
    assert bpy.ops.proteinblender.set_pivot_first() == {'FINISHED'}
    _select_rows([targets[1]])
    assert bpy.ops.proteinblender.set_pivot_last() == {'FINISHED'}

    # Prove the pivots really are distinct and non-zero before saving, reading
    # the modifier directly rather than through the product's accessor.
    from _snapshot import _gn_input_value, _gn_socket_identifiers
    seen = []
    for domain in H.sm().molecules[mid].domains.values():
        obj = getattr(domain, "object", None)
        if obj is None:
            continue
        for mod in obj.modifiers:
            group = getattr(mod, "node_group", None)
            if group is None:
                continue
            for identifier in _gn_socket_identifiers(group):
                value = _gn_input_value(mod, identifier)
                if hasattr(value, "__len__") and len(value) == 3:
                    vec = [round(float(v), 5) for v in value]
                    if any(vec):
                        seen.append(tuple(vec))
    assert len(set(seen)) >= 2, (
        f"expected at least two distinct non-zero pivots before saving, got {seen}")


def build_keyframes():
    """Molecule keyframe metadata AND the real F-curves behind it.

    The two are separate stores and fail separately: the Animate panel lists
    frames from ``item.keyframes`` while the motion lives in an Action. A
    reload can keep the list and lose the curves, which reads to a user as
    "my keyframes are there but nothing moves".
    """
    from mathutils import Vector

    mid = H.import_local("1aki.pdb", "1aki")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid
    mol = H.sm().molecules[mid]
    assert mol.domains, "1aki should auto-create a domain"

    _did, domain = sorted(mol.domains.items())[0]
    obj = domain.object
    assert obj is not None
    for frame, loc in [(1, (0.0, 0.0, 0.0)), (24, (3.0, 0.0, 1.5)),
                       (48, (3.0, 3.0, -2.25))]:
        obj.location = Vector(loc)
        obj.keyframe_insert(data_path="location", frame=frame)

    item = H.list_item(mid)
    for frame, name in [(1, "Start"), (24, "Middle"), (48, "End")]:
        kf = item.keyframes.add()
        kf.frame = frame
        kf.name = name

    assert obj.animation_data and obj.animation_data.action, "no action created"
    assert len(item.keyframes) == 3
    scene.frame_set(24)


def build_poses():
    """Molecule poses that capture genuinely different arrangements.

    Two poses of an unmoved molecule are identical, so a reload that collapses
    every pose to the same transform would pass. Moving a domain between
    captures makes the poses distinguishable and the comparison meaningful.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid
    mol = H.sm().molecules[mid]

    first_id = sorted(mol.domains)[0]
    obj = mol.domains[first_id].object
    assert obj is not None

    assert bpy.ops.molecule.create_pose(
        'EXEC_DEFAULT', pose_name="Open") == {'FINISHED'}
    obj.location = (2.5, -1.25, 0.75)
    obj.rotation_euler = (0.3, 0.0, 1.1)
    assert bpy.ops.molecule.create_pose(
        'EXEC_DEFAULT', pose_name="Closed") == {'FINISHED'}

    item = H.list_item(mid)
    assert [p.name for p in item.poses] == ["Open", "Closed"]
    open_tf = {t.domain_id: tuple(t.location) for t in item.poses[0].domain_transforms}
    closed_tf = {t.domain_id: tuple(t.location) for t in item.poses[1].domain_transforms}
    assert open_tf != closed_tf, (
        "the two poses captured identical transforms - the round trip would "
        "be unable to distinguish them")


def build_pose_library():
    """The puppet-based pose LIBRARY (``scene.pose_library``).

    Its capture operator is a modal dialog with per-instance Python state and
    is unreachable headless (see COVERAGE.md), so the rows are written
    directly. That is legitimate here: this lane tests whether the *data*
    survives a .blend round trip, not how it was produced.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _puppet_id, controller, _chains = _make_puppet(mid, "LibPuppet")
    controller.location = (1.5, 0.5, -0.5)

    scene = bpy.context.scene
    pose = scene.pose_library.add()
    pose.name = "Docked"
    pose.puppet_names = "LibPuppet"

    entry = pose.transforms.add()
    entry.puppet_name = "LibPuppet"
    entry.object_name = controller.name
    entry.is_controller = True
    entry.location = (1.5, 0.5, -0.5)
    entry.rotation_euler = (0.0, 0.25, 0.5)
    entry.color = (0.4, 0.7, 0.2, 1.0)
    entry.has_color = True

    assert len(scene.pose_library) == 1
    assert len(scene.pose_library[0].transforms) == 1
    assert scene.pose_library[0].name == "Docked"


def build_puppets():
    """Two puppets with moved controllers and distinct membership."""
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    # Collect all four chain ids up front. Once a puppet exists its member
    # chains re-parent under the PUPPET row, so re-querying `_chain_rows`
    # (which filters on parent_id == molecule) afterwards returns a different,
    # shorter list and indexing into it selects the wrong rows.
    chain_ids = [c.item_id for c in _chain_rows(mid)]
    assert len(chain_ids) >= 4, f"4hhb should have four chains, got {len(chain_ids)}"

    def puppet_rows():
        # The outliner inserts a "--- Puppets ---" separator that also carries
        # item_type == "PUPPET"; a real puppet is the one owning a controller.
        return [it for it in bpy.context.scene.outliner_items
                if it.item_type == "PUPPET" and it.controller_object_name]

    for index, (name, members) in enumerate(
            (("Alpha_Dimer", chain_ids[:2]), ("Beta_Dimer", chain_ids[2:4])),
            start=1):
        _select_rows(members)
        assert bpy.ops.proteinblender.create_puppet(
            'EXEC_DEFAULT', puppet_name=name) == {'FINISHED'}
        # Assert after each creation so a miscount names the call that caused
        # it rather than surfacing as a total at the end.
        rows = puppet_rows()
        assert len(rows) == index, (
            f"creating {name!r} from {len(members)} chains left "
            f"{len(rows)} puppets ({[r.name for r in rows]}), expected {index}")

    puppets = puppet_rows()
    assert len(puppets) == 2, f"expected two puppets, got {len(puppets)}"

    # Move each controller somewhere distinct so the parenting relationship is
    # observable after reload rather than implied.
    for offset, puppet in enumerate(puppets, start=1):
        controller = bpy.data.objects.get(puppet.controller_object_name)
        assert controller is not None
        controller.location = (offset * 2.0, offset * -1.0, offset * 0.5)
    bpy.context.view_layer.update()


def build_linkers():
    """A linker with every appearance parameter moved off its default.

    26 persisted fields per linker had no coverage at all; defaults would let a
    reload that reset them look identical to one that preserved them.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    puppet_id, _controller, chain_ids = _make_puppet(mid, "LinkerPuppet")
    _build_outliner()

    by_id = {it.item_id: it for it in bpy.context.scene.outliner_items}
    chain_a, chain_b = by_id[chain_ids[0]], by_id[chain_ids[1]]

    scene = bpy.context.scene
    assert bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT',
        puppet_selector=puppet_id,
        endpoint_a_item=f"A_{chain_a.item_id}",
        endpoint_a_residue=_mid_residue(chain_a),
        endpoint_b_item=f"B_{chain_b.item_id}",
        endpoint_b_residue=_mid_residue(chain_b),
        linker_name="Hinge",
        length_residues=42,
        style="BEADS",
        rendering_mode="QUICK",
    ) == {'FINISHED'}
    assert len(scene.pb2_linkers) == 1, "linker definition was not added"

    linker = scene.pb2_linkers[0]
    linker.color = (0.9, 0.2, 0.35, 1.0)
    linker.tube_radius = 0.037
    linker.bead_radius = 0.028
    linker.bead_overlap = 0.42
    linker.bead_jitter = 0.13
    linker.coil_width = 0.081
    linker.binding_zone_residues = 4
    linker.is_expanded = True

    assert linker.uid, "linker has no uid to match across the round trip"
    assert linker.curve_object_name, "linker created no curve object"
    assert bpy.data.objects.get(linker.curve_object_name) is not None


def build_dna():
    """A DNA strand plus its bend rig (curve + control Empties + F-curves)."""
    obj = H.build_dna(seq="ATCGATCGATCGATCG", name_prefix="RoundTripDNA",
                      ds=True, style="cartoon")
    H.select_only(obj)
    assert bpy.ops.proteinblender.dna_add_bend() == {'FINISHED'}

    from proteinblender.dna_builder import bender
    curve_name = obj.get(bender.BEND_CURVE_PROP)
    assert curve_name, "bend curve property was not set"
    curve = bpy.data.objects.get(curve_name)
    assert curve is not None and curve.type == "CURVE"

    nodes = bender.get_bend_nodes(obj)
    assert nodes, "bend rig created no control nodes"
    # Drag a node and key it, so the rig carries animation across the reload.
    node = nodes[len(nodes) // 2]
    node.location = (0.15, 0.0, node.location.z)
    node.keyframe_insert(data_path="location", frame=1)
    node.location = (0.35, 0.1, node.location.z)
    node.keyframe_insert(data_path="location", frame=30)
    assert node.animation_data and node.animation_data.action

    props = bpy.context.scene.dna_builder_props
    assert props.sequence, "DNA builder props lost the sequence"


def build_membrane():
    """A membrane with a hole and a resized footprint."""
    created = H.build_membrane(shape="FLAT", width=8.0, height=8.0)
    root = next((bpy.data.objects[n] for n in created
                 if bpy.data.objects.get(n) is not None
                 and bpy.data.objects[n].get("pb_is_membrane", False)), None)
    assert root is not None, f"no pb_is_membrane root among {created}"

    H.select_only(root)
    assert bpy.ops.proteinblender.membrane_add_hole() == {'FINISHED'}
    holes = [c for c in root.children if c.get("pb_is_membrane_hole", False)]
    assert len(holes) == 1, f"expected one hole, got {len(holes)}"
    holes[0].location = (1.2, -0.8, 0.0)

    assert root.data.vertices, "membrane base mesh has no vertices"


def build_force_fields():
    """A protein force field acting on a membrane.

    Force-field state spans two stores that must both survive: the per-object
    ``pb_force_field_*`` RNA properties, and the membrane modifier's geometry-
    nodes inputs that the deferred re-apply pass rebuilds from them.
    """
    created = H.build_membrane(shape="FLAT", width=10.0, height=10.0)
    root = next((bpy.data.objects[n] for n in created
                 if bpy.data.objects.get(n) is not None
                 and bpy.data.objects[n].get("pb_is_membrane", False)), None)
    assert root is not None

    mid = H.import_local("1ubq.pdb", "1ubq")
    _build_outliner()
    mol = H.sm().molecules[mid]
    obj = mol.object
    assert obj is not None

    obj.pb_force_field_enabled = True
    obj.pb_force_field_spacing = 1.75
    for domain in mol.domains.values():
        dom_obj = getattr(domain, "object", None)
        if dom_obj is not None:
            dom_obj.pb_force_field_enabled = True
            dom_obj.pb_force_field_spacing = 1.75

    enabled = [o.name for o in bpy.data.objects
               if getattr(o, "pb_force_field_enabled", False)]
    assert enabled, "no object ended up with a force field enabled"


def build_brownian():
    """Baked Brownian motion: JITTER keyframes plus the metadata that rebuilds
    them. Seeded so the bake is deterministic."""
    mid = H.import_local("4hhb.pdb", "4hhb")
    puppet_id, controller, _chains = _make_puppet(mid, "BrownianPuppet")

    from proteinblender.utils.animation import ensure_quaternion_mode
    ensure_quaternion_mode(controller)
    controller.keyframe_insert(data_path="location", frame=1)
    controller.keyframe_insert(data_path="rotation_quaternion", frame=1)

    assert bpy.ops.proteinblender.brownian_settings(
        "EXEC_DEFAULT",
        controller_object_name=controller.name,
        puppet_id=puppet_id,
        puppet_name="BrownianPuppet",
        frame_number=12,
        jitter_interval=3,
        jitter_max_distance=1.0,
        jitter_max_rotation=30.0,
        use_random_seed=False,
        seed=42,
    ) == {'FINISHED'}

    assert "pb_brownian_metadata" in controller, "Brownian metadata not written"
    metadata = json.loads(controller["pb_brownian_metadata"])
    assert metadata, "Brownian metadata is empty"

    action = controller.animation_data.action
    jitter = 0
    from _snapshot import _action_fcurves
    for fcurve in _action_fcurves(action, controller.animation_data).values():
        jitter += sum(1 for kp in fcurve.keyframe_points if kp.type == "JITTER")
    assert jitter > 0, "no JITTER keyframes were baked"


def build_visual_style():
    """Molecule-level style and colour, which write through to node trees and
    materials rather than to a property the outliner shows."""
    mid = H.import_local("1ubq.pdb", "1ubq")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid

    # Both are FloatVector/Enum properties whose ``update=`` callback does the
    # work, which is the path a user's click takes. Blender fires the callback
    # only on an actual value change, so step through a sentinel first.
    scene.visual_setup_color = (0.85, 0.15, 0.45, 1.0)
    scene.molecule_style = "cartoon"
    scene.molecule_style = "spheres"

    item = H.list_item(mid)
    assert item.style == "spheres", f"style did not stick: {item.style}"
    assert [round(c, 3) for c in scene.visual_setup_color] == [0.85, 0.15, 0.45, 1.0]


def build_kitchen_sink():
    """Everything at once, in one file.

    Subsystems are not independent on reload - they share the outliner, the
    molecule registry, the object graph and the deferred rebuild passes. A file
    holding one of each is the only case that can catch a reload where two
    subsystems individually survive but interfere (a linker rebuilt against a
    membrane-shifted depsgraph, a puppet whose members a DNA cleanup unparented).
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid

    assert H.split_domain_from_outliner(mid, "A", 1, 60) == {"FINISHED"}
    _build_outliner()

    rows = _chain_rows(mid)
    assert bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=rows[-1].item_id, item_type='CHAIN',
        new_name="Renamed Chain") == {'FINISHED'}

    for i, domain in enumerate(sorted(H.sm().molecules[mid].domains.values(),
                                      key=lambda d: getattr(d, "name", ""))):
        obj = getattr(domain, "object", None)
        if obj is not None:
            obj.domain_color = (0.2, 0.11 * (i + 1) % 1.0, 0.7, 1.0)

    # Puppet chains B and C, leaving the split chain A alone: once a chain is
    # split, the linker endpoint list offers its DOMAIN rows rather than the
    # chain itself (guarded by test_linker_split_domains.py). Keeping the two
    # features side by side rather than nested is what this case is for.
    puppet_id, controller, chain_ids = _make_puppet(
        mid, "SinkPuppet", chain_indices=(1, 2))
    controller.location = (1.0, 2.0, 3.0)
    controller.keyframe_insert(data_path="location", frame=1)
    controller.location = (4.0, 2.0, 3.0)
    controller.keyframe_insert(data_path="location", frame=40)

    _build_outliner()
    by_id = {it.item_id: it for it in scene.outliner_items}
    chain_a, chain_b = by_id[chain_ids[0]], by_id[chain_ids[1]]
    assert bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT',
        puppet_selector=puppet_id,
        endpoint_a_item=f"A_{chain_a.item_id}",
        endpoint_a_residue=_mid_residue(chain_a),
        endpoint_b_item=f"B_{chain_b.item_id}",
        endpoint_b_residue=_mid_residue(chain_b),
        linker_name="SinkLinker",
        length_residues=25,
        style="TUBE",
        rendering_mode="QUICK",
    ) == {'FINISHED'}

    assert bpy.ops.molecule.create_pose(
        'EXEC_DEFAULT', pose_name="SinkPose") == {'FINISHED'}

    dna = H.build_dna(seq="ATCGATCGATCG", name_prefix="SinkDNA", ds=True,
                      style="ball_and_stick")
    H.select_only(dna)

    created = H.build_membrane(shape="FLAT", width=12.0, height=12.0)
    root = next((bpy.data.objects[n] for n in created
                 if bpy.data.objects.get(n) is not None
                 and bpy.data.objects[n].get("pb_is_membrane", False)), None)
    assert root is not None, "kitchen sink built no membrane"

    # Non-vacuity: every subsystem must actually be present in the file. The
    # DNA strand is itself a MolecularNodes molecule and gets its own list
    # row, so the protein is asserted by identity rather than by count.
    assert H.list_item(mid) is not None
    assert len(scene.pb2_linkers) == 1
    assert len(H.list_item(mid).poses) == 1
    assert any(it.item_type == "PUPPET" and it.controller_object_name
               for it in scene.outliner_items)
    assert any(o.get("pb_is_nucleic_acid") for o in bpy.data.objects)
    assert any(o.get("pb_is_membrane") for o in bpy.data.objects)


# ---------------------------------------------------------------------------
# Registry
#
# Order is the order they run in. Keep the cheap structural cases first so a
# systemic breakage reports against the simplest file that shows it.
# ---------------------------------------------------------------------------

BUILDERS = {
    "empty": build_empty,
    "single_protein": build_single_protein,
    "multi_chain": build_multi_chain,
    "biological_assembly": build_biological_assembly,
    "domains": build_domains,
    "chain_rename": build_chain_rename,
    "chain_copy": build_chain_copy,
    "pivots": build_pivots,
    "keyframes": build_keyframes,
    "poses": build_poses,
    "pose_library": build_pose_library,
    "puppets": build_puppets,
    "linkers": build_linkers,
    "dna": build_dna,
    "membrane": build_membrane,
    "force_fields": build_force_fields,
    "brownian": build_brownian,
    "visual_style": build_visual_style,
    "kitchen_sink": build_kitchen_sink,
}

# Subsystems each builder is the round-trip guard for. Asserted by
# test_persistence_contract.py against the add-on's registered feature
# packages, so adding a subsystem without adding a builder fails the suite.
BUILDER_SUBSYSTEMS = {
    "empty": (),
    "single_protein": ("core",),
    "multi_chain": ("core",),
    "biological_assembly": ("core", "operators", "panels"),
    "domains": ("core", "operators", "panels", "addon"),
    "chain_rename": ("core", "panels"),
    "chain_copy": ("core", "operators", "utils"),
    "pivots": ("core",),
    "keyframes": ("operators", "utils"),
    "poses": ("properties", "operators"),
    "pose_library": ("properties",),
    "puppets": ("operators", "layout"),
    "linkers": ("linkers",),
    "dna": ("dna_builder",),
    "membrane": ("membrane_builder",),
    "force_fields": ("membrane_builder",),
    "brownian": ("utils", "operators"),
    "visual_style": ("panels",),
    "kitchen_sink": ("core", "linkers", "dna_builder", "membrane_builder",
                     "operators", "properties", "panels"),
}
