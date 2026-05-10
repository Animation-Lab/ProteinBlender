"""Inner test runner — runs inside a Blender 5.1 process.

Dispatches to a scenario by name and phase. Phase 'setup' creates a fresh
factory-startup scene, exercises the addon, saves a .blend, and writes the
expected-state JSON. Phase 'verify' opens that .blend, runs the molecule
list reconstruction, and checks the actual state against expectations.

Args after `--`:
  worktree_root  output_json_path  blend_path  expected_json_path  scenario  phase
"""

import sys
import os
import json
import traceback


# ----------------------------------------------------------------------------
# Boot: register the worktree's proteinblender package
# ----------------------------------------------------------------------------

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) < 6:
    print("Usage: inner_runner.py -- <worktree> <result_json> <blend> <expected_json> <scenario> <phase>")
    sys.exit(2)

WORKTREE = argv[0]
RESULT_JSON = argv[1]
BLEND_PATH = argv[2]
EXPECTED_JSON = argv[3]
SCENARIO = argv[4]
PHASE = argv[5]


def boot_addon():
    """Wipe any installed extension version, register the worktree's package."""
    import bpy

    for mod in list(sys.modules):
        if mod.startswith("bl_ext.") and mod.endswith(".proteinblender"):
            try:
                bpy.ops.preferences.addon_disable(module=mod)
            except Exception:
                pass

    for mod in list(sys.modules):
        if mod == "proteinblender" or mod.startswith("proteinblender."):
            del sys.modules[mod]

    if WORKTREE not in sys.path:
        sys.path.insert(0, WORKTREE)

    import proteinblender
    proteinblender.register()
    return proteinblender


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def import_pdb(pdb_id, fmt="pdb"):
    """Import a protein via the public operator path. Returns the unique id."""
    import bpy
    scene = bpy.context.scene
    scene.protein_props.import_method = "PDB"
    scene.protein_props.pdb_id = pdb_id
    scene.protein_props.remote_format = fmt

    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    before = set(sm.molecules.keys())
    bpy.ops.molecule.import_protein()
    after = set(sm.molecules.keys())
    new = sorted(after - before)
    if not new:
        raise RuntimeError(f"import_protein did not produce a new molecule for {pdb_id}")
    return new[-1]


def reconstruct_after_load():
    """Mimic what panel draw does: rebuild wrappers from PropertyGroups."""
    from proteinblender.utils.scene_manager import sync_molecule_list_after_undo
    sync_molecule_list_after_undo()


def molecule_summary(mol_id):
    """Capture the state we want to round-trip-check for one molecule."""
    import bpy
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    mol = sm.molecules.get(mol_id)
    item = next((it for it in bpy.context.scene.molecule_list_items if it.identifier == mol_id), None)

    summary = {
        "id": mol_id,
        "wrapper_present": mol is not None,
        "list_item_present": item is not None,
    }
    if item is not None:
        summary["style"] = item.style
        summary["object_name"] = item.object_name
        summary["chain_mapping"] = item.get_chain_mapping()
        summary["chain_residue_ranges"] = {
            k: list(v) for k, v in item.get_chain_residue_ranges().items()
        }
        summary["domain_count"] = len(item.domains)
        summary["domains"] = [
            {
                "domain_id": d.domain_id,
                "name": d.name,
                "chain_id": d.chain_id,
                "start": d.start,
                "end": d.end,
                "color": list(d.color) if hasattr(d, "color") else None,
                "object_name": d.object_name if hasattr(d, "object_name") else None,
                "object_exists": (
                    bpy.data.objects.get(d.object_name) is not None
                    if hasattr(d, "object_name") and d.object_name else False
                ),
            }
            for d in item.domains
        ]
        summary["pose_count"] = len(item.poses)
        summary["poses"] = [
            {
                "name": p.name,
                "domain_transform_count": len(p.domain_transforms),
                "domain_transforms": [
                    {
                        "domain_id": dt.domain_id,
                        "location": list(dt.location),
                        "rotation": list(dt.rotation),
                        "scale": list(dt.scale),
                    }
                    for dt in p.domain_transforms
                ],
                "has_protein_transform": p.has_protein_transform,
            }
            for p in item.poses
        ]
        summary["keyframe_count"] = len(item.keyframes)
        summary["keyframes"] = [
            {"name": k.name, "frame": k.frame} for k in item.keyframes
        ]
        # Object existence
        obj = bpy.data.objects.get(item.object_name) if item.object_name else None
        summary["object_exists"] = obj is not None
    return summary


def raw_property_snapshot(expected_ids):
    """Pure PropertyGroup snapshot — doesn't depend on the runtime wrapper
    dict (which is empty until sync_molecule_list_after_undo runs)."""
    import bpy
    scene = bpy.context.scene
    snap = {
        "wrapper_count": -1,  # not applicable pre-sync
        "list_item_count": len(scene.molecule_list_items),
        "wrapper_ids": [],
        "list_item_ids": [it.identifier for it in scene.molecule_list_items],
        "outliner_item_count": len(scene.outliner_items) if hasattr(scene, "outliner_items") else 0,
        "linker_count": len(scene.pb2_linkers) if hasattr(scene, "pb2_linkers") else 0,
        "molecules": [],
    }
    for mid in expected_ids:
        item = next((it for it in scene.molecule_list_items if it.identifier == mid), None)
        if item is None:
            snap["molecules"].append({"id": mid, "list_item_present": False, "wrapper_present": False})
            continue
        m = {
            "id": mid,
            "wrapper_present": False,
            "list_item_present": True,
            "style": item.style,
            "object_name": item.object_name,
            "chain_mapping": item.get_chain_mapping(),
            "chain_residue_ranges": {k: list(v) for k, v in item.get_chain_residue_ranges().items()},
            "domain_count": len(item.domains),
            "domains": [
                {
                    "domain_id": d.domain_id,
                    "name": d.name,
                    "chain_id": d.chain_id,
                    "start": d.start,
                    "end": d.end,
                    "color": list(d.color) if hasattr(d, "color") else None,
                    "object_name": d.object_name if hasattr(d, "object_name") else None,
                    "object_exists": (
                        bpy.data.objects.get(d.object_name) is not None
                        if hasattr(d, "object_name") and d.object_name else False
                    ),
                }
                for d in item.domains
            ],
            "pose_count": len(item.poses),
            "poses": [
                {
                    "name": p.name,
                    "domain_transform_count": len(p.domain_transforms),
                    "domain_transforms": [
                        {
                            "domain_id": dt.domain_id,
                            "location": list(dt.location),
                            "rotation": list(dt.rotation),
                            "scale": list(dt.scale),
                        }
                        for dt in p.domain_transforms
                    ],
                    "has_protein_transform": p.has_protein_transform,
                }
                for p in item.poses
            ],
            "keyframe_count": len(item.keyframes),
            "keyframes": [{"name": k.name, "frame": k.frame} for k in item.keyframes],
            "object_exists": bpy.data.objects.get(item.object_name) is not None if item.object_name else False,
        }
        snap["molecules"].append(m)
    return snap


def scene_snapshot(expected_ids):
    import bpy
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    return {
        "wrapper_count": len(sm.molecules),
        "list_item_count": len(bpy.context.scene.molecule_list_items),
        "wrapper_ids": sorted(sm.molecules.keys()),
        "list_item_ids": [it.identifier for it in bpy.context.scene.molecule_list_items],
        "outliner_item_count": len(bpy.context.scene.outliner_items),
        "linker_count": (
            len(bpy.context.scene.pb2_linkers)
            if hasattr(bpy.context.scene, "pb2_linkers") else 0
        ),
        "molecules": [molecule_summary(mid) for mid in expected_ids if mid],
    }


def save_blend(path):
    import bpy
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)


def open_blend(path):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=path)


def diff_summaries(expected, actual, raw=False):
    """Compare expected vs actual scene snapshot, return list of mismatches.

    If raw=True the comparison is done in 'pre-sync' mode: wrapper_count and
    wrapper_ids are not compared (no wrappers exist yet at that point).
    """
    issues = []
    keys = ("list_item_count", "list_item_ids", "outliner_item_count", "linker_count")
    if not raw:
        keys = ("wrapper_count", "wrapper_ids") + keys
    for k in keys:
        if expected.get(k) != actual.get(k):
            issues.append(f"{k}: expected={expected.get(k)!r} actual={actual.get(k)!r}")

    e_mols = {m["id"]: m for m in expected.get("molecules", [])}
    a_mols = {m["id"]: m for m in actual.get("molecules", [])}
    for mid, em in e_mols.items():
        am = a_mols.get(mid)
        if am is None:
            issues.append(f"molecule {mid}: missing after reload")
            continue
        for k in ("wrapper_present", "list_item_present", "style", "domain_count",
                  "pose_count", "keyframe_count", "object_exists"):
            if em.get(k) != am.get(k):
                issues.append(f"{mid}.{k}: expected={em.get(k)!r} actual={am.get(k)!r}")
        # chain mapping & residue ranges — normalise so JSON-loaded expected
        # (string-keyed dicts) compares equal to runtime actual (int-keyed
        # dicts produced by chain_utils.deserialize_chain_mapping).
        def _norm(d):
            return {str(k): v for k, v in (d or {}).items()}
        if _norm(em.get("chain_mapping")) != _norm(am.get("chain_mapping")):
            issues.append(f"{mid}.chain_mapping mismatch")
        if _norm(em.get("chain_residue_ranges")) != _norm(am.get("chain_residue_ranges")):
            issues.append(f"{mid}.chain_residue_ranges mismatch")
        # domains
        e_doms = {d["domain_id"]: d for d in em.get("domains", [])}
        a_doms = {d["domain_id"]: d for d in am.get("domains", [])}
        for did, ed in e_doms.items():
            ad = a_doms.get(did)
            if ad is None:
                issues.append(f"{mid}: domain {did} missing")
                continue
            for k in ("name", "chain_id", "start", "end", "object_exists"):
                if ed.get(k) != ad.get(k):
                    issues.append(f"{mid}/{did}.{k}: expected={ed.get(k)!r} actual={ad.get(k)!r}")
            if ed.get("color") and ad.get("color"):
                # tolerate float drift
                if any(abs(a - b) > 1e-4 for a, b in zip(ed["color"], ad["color"])):
                    issues.append(f"{mid}/{did}.color: expected={ed['color']} actual={ad['color']}")
        # poses
        e_poses = {p["name"]: p for p in em.get("poses", [])}
        a_poses = {p["name"]: p for p in am.get("poses", [])}
        for pn, ep in e_poses.items():
            ap = a_poses.get(pn)
            if ap is None:
                issues.append(f"{mid}: pose '{pn}' missing")
                continue
            if ep["domain_transform_count"] != ap["domain_transform_count"]:
                issues.append(f"{mid}/pose '{pn}': transform count {ep['domain_transform_count']} -> {ap['domain_transform_count']}")
            # check transform values
            ep_t = {t["domain_id"]: t for t in ep["domain_transforms"]}
            ap_t = {t["domain_id"]: t for t in ap["domain_transforms"]}
            for did, et in ep_t.items():
                at = ap_t.get(did)
                if at is None:
                    issues.append(f"{mid}/pose '{pn}': transform for domain {did} missing")
                    continue
                for axis_field in ("location", "rotation", "scale"):
                    if any(abs(a - b) > 1e-3 for a, b in zip(et[axis_field], at[axis_field])):
                        issues.append(
                            f"{mid}/pose '{pn}'/{did}.{axis_field}: "
                            f"expected={et[axis_field]} actual={at[axis_field]}"
                        )
        # keyframes
        e_kfs = sorted([(k["name"], k["frame"]) for k in em.get("keyframes", [])])
        a_kfs = sorted([(k["name"], k["frame"]) for k in am.get("keyframes", [])])
        if e_kfs != a_kfs:
            issues.append(f"{mid}.keyframes: expected={e_kfs} actual={a_kfs}")
    return issues


# ----------------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------------

def scenario_01_empty_setup():
    return {"expected_ids": []}


def scenario_01_empty_verify(expected):
    return scene_snapshot(expected.get("expected_ids", []))


def scenario_02_single_setup():
    mid = import_pdb("1aki")
    return {"expected_ids": [mid]}


def scenario_02_single_verify(expected):
    return scene_snapshot(expected.get("expected_ids", []))


def scenario_03_multi_setup():
    import bpy
    mid_a = import_pdb("1aki")
    mid_b = import_pdb("4hhb")
    # Change styles via the operator
    bpy.context.scene.selected_molecule_id = mid_a
    bpy.context.scene.molecule_style = "ribbon"
    bpy.context.scene.selected_molecule_id = mid_b
    bpy.context.scene.molecule_style = "spheres"
    # Persist style on the list items (the enum is on Scene; per-item style
    # mirrors are stored in MoleculeListItem.style — write them directly so
    # we capture intent regardless of UI sync timing).
    for it in bpy.context.scene.molecule_list_items:
        if it.identifier == mid_a:
            it.style = "ribbon"
        elif it.identifier == mid_b:
            it.style = "spheres"
    return {"expected_ids": [mid_a, mid_b]}


def scenario_03_multi_verify(expected):
    return scene_snapshot(expected.get("expected_ids", []))


def scenario_04_domains_setup():
    """Import a multi-chain protein. The addon auto-creates one chain-wide
    domain per chain on import. We tint each one a distinct colour so we can
    verify domain colours survive save/load."""
    import bpy
    mid = import_pdb("4hhb")
    bpy.context.scene.selected_molecule_id = mid

    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    mol = sm.molecules[mid]

    # Tint each auto-created chain domain
    for i, (did, d) in enumerate(sorted(mol.domains.items())):
        if d.object:
            d.object.domain_color = (0.15 * (i + 1), 0.5, 0.9, 1.0)
    return {"expected_ids": [mid], "expected_domain_count": len(mol.domains)}


def scenario_04_domains_verify(expected):
    snap = scene_snapshot(expected.get("expected_ids", []))
    snap["_check_domain_count"] = expected.get("expected_domain_count", 0)
    return snap


def _first_chain(mol):
    """Return (chain_idx_str, auth_id, (start, end)). Falls back to chain_residue_ranges
    when chain_mapping is empty (single-chain proteins like 1aki sometimes have
    chain_mapping={} but chain_residue_ranges={'A': (1,N)})."""
    if mol.chain_mapping:
        chain_idx, auth_id = sorted(mol.chain_mapping.items())[0]
        rng = mol.chain_residue_ranges.get(auth_id)
        return str(chain_idx), auth_id, rng
    if mol.chain_residue_ranges:
        auth_id = sorted(mol.chain_residue_ranges.keys())[0]
        rng = mol.chain_residue_ranges[auth_id]
        return "0", auth_id, rng  # single-chain → blender chain index 0
    raise RuntimeError(f"Molecule {mol.identifier} has no chains")


def scenario_05_poses_setup():
    """Use the auto-created chain domains as pose targets. Two chains gives
    two domains; for single-chain proteins we use 4hhb instead."""
    import bpy
    from mathutils import Vector

    mid = import_pdb("4hhb")  # 4 chains → 4 auto-domains
    bpy.context.scene.selected_molecule_id = mid
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    mol = sm.molecules[mid]
    domain_ids = [did for did, _ in sorted(mol.domains.items())[:2]]
    if len(domain_ids) < 2:
        raise RuntimeError(f"4hhb produced only {len(domain_ids)} domains")

    # Capture pose A at default positions
    item = next(it for it in bpy.context.scene.molecule_list_items if it.identifier == mid)
    p_a = item.poses.add()
    p_a.name = "Pose_A"
    for did in domain_ids:
        d = mol.domains[did]
        if d.object:
            t = p_a.domain_transforms.add()
            t.domain_id = did
            t.location = d.object.location.copy()
            t.rotation = d.object.rotation_euler.copy()
            t.scale = d.object.scale.copy()

    # Move domains, capture pose B
    for i, did in enumerate(domain_ids):
        d = mol.domains[did]
        if d.object:
            d.object.location = Vector((1.0 * (i + 1), 2.0, 3.0))
            d.object.rotation_euler = (0.1, 0.2, 0.3 * (i + 1))
            d.object.scale = (1.0 + 0.1 * i, 1.0, 1.0)
    p_b = item.poses.add()
    p_b.name = "Pose_B"
    for did in domain_ids:
        d = mol.domains[did]
        if d.object:
            t = p_b.domain_transforms.add()
            t.domain_id = did
            t.location = d.object.location.copy()
            t.rotation = d.object.rotation_euler.copy()
            t.scale = d.object.scale.copy()

    return {"expected_ids": [mid]}


def scenario_05_poses_verify(expected):
    return scene_snapshot(expected.get("expected_ids", []))


def scenario_06_keyframes_setup():
    """Use the auto-created chain domain on 1aki (single-chain)."""
    import bpy
    from mathutils import Vector

    mid = import_pdb("1aki")
    bpy.context.scene.selected_molecule_id = mid
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    mol = sm.molecules[mid]
    if not mol.domains:
        raise RuntimeError("1aki produced no auto-domains")
    did, d = sorted(mol.domains.items())[0]

    # Insert raw transform keyframes on the domain object at three frames
    if d.object:
        for frame, loc in [(1, (0, 0, 0)), (30, (5, 0, 0)), (60, (5, 5, 0))]:
            d.object.location = Vector(loc)
            d.object.keyframe_insert(data_path="location", frame=frame)

    # Add the addon's metadata keyframe entries too
    item = next(it for it in bpy.context.scene.molecule_list_items if it.identifier == mid)
    for frame, name in [(1, "Start"), (30, "Middle"), (60, "End")]:
        kf = item.keyframes.add()
        kf.frame = frame
        kf.name = name

    return {"expected_ids": [mid]}


def _action_fcurves(action):
    """Compatibility shim: Blender 4.x exposed `Action.fcurves` directly,
    Blender 5.x moves them under `Action.layers[*].strips[*].channelbag(slot).fcurves`.
    Yield every F-curve regardless of which API is in use."""
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        yield from fcurves
        return
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            # Slotted action API
            for slot in getattr(action, "slots", ()):
                cb = strip.channelbag(slot)
                if cb is None:
                    continue
                yield from getattr(cb, "fcurves", ())


def scenario_06_keyframes_verify(expected):
    import bpy
    snap = scene_snapshot(expected.get("expected_ids", []))
    fcurve_keys = {}
    for it in bpy.context.scene.molecule_list_items:
        for d in it.domains:
            obj = bpy.data.objects.get(d.object_name) if d.object_name else None
            if not obj or not obj.animation_data or not obj.animation_data.action:
                continue
            keys = []
            for fc in _action_fcurves(obj.animation_data.action):
                for kp in fc.keyframe_points:
                    keys.append((fc.data_path, fc.array_index, int(kp.co.x)))
            fcurve_keys[d.object_name] = sorted(set(keys))
    snap["_fcurve_keys"] = fcurve_keys
    return snap


def scenario_07_delete_setup():
    import bpy
    a = import_pdb("1aki")
    b = import_pdb("1ubq")  # tiny ubiquitin
    c = import_pdb("4hhb")
    # Delete the middle one through the scene manager (mirrors the operator path)
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    sm = ProteinBlenderScene.get_instance()
    sm.delete_molecule(b)
    return {"expected_ids": [a, c], "deleted_id": b}


def scenario_07_delete_verify(expected):
    snap = scene_snapshot(expected.get("expected_ids", []))
    # also confirm the deleted molecule is gone from list_item_ids
    snap["_deleted_id"] = expected.get("deleted_id")
    return snap


def scenario_08_resave_setup():
    """Resave path: import, save, then add another protein and tweak style,
    save again. Verify phase opens the final .blend in a fresh process — this
    matches the user workflow without crashing Blender 5.1 on register-then-
    open-mainfile (a known bug surfaced by this stress test).
    """
    import bpy
    a = import_pdb("1aki")
    save_blend(BLEND_PATH + ".step1.blend")

    b = import_pdb("1ubq")
    for it in bpy.context.scene.molecule_list_items:
        if it.identifier == a:
            it.style = "ribbon"
    return {"expected_ids": sorted([a, b])}


def scenario_08_resave_verify(expected):
    return scene_snapshot(expected.get("expected_ids", []))


def scenario_09_in_process_reopen_setup():
    """Try save → in-process open_mainfile → continue editing.
    Surfaces the known Blender 5.1 EXCEPTION_STACK_OVERFLOW when the addon is
    already registered when the file is opened. Setup is expected to crash;
    if it returns normally that's actually progress."""
    import bpy
    a = import_pdb("1aki")
    save_blend(BLEND_PATH + ".prep.blend")
    # This call is the bug-surfacing step: stack-overflow expected on 5.1.
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH + ".prep.blend")
    return {"expected_ids": [a], "_expected_crash": True}


def scenario_09_in_process_reopen_verify(expected):
    return scene_snapshot(expected.get("expected_ids", []))


SCENARIOS = {
    "01_empty": (scenario_01_empty_setup, scenario_01_empty_verify),
    "02_single": (scenario_02_single_setup, scenario_02_single_verify),
    "03_multi": (scenario_03_multi_setup, scenario_03_multi_verify),
    "04_domains": (scenario_04_domains_setup, scenario_04_domains_verify),
    "05_poses": (scenario_05_poses_setup, scenario_05_poses_verify),
    "06_keyframes": (scenario_06_keyframes_setup, scenario_06_keyframes_verify),
    "07_delete": (scenario_07_delete_setup, scenario_07_delete_verify),
    "08_resave": (scenario_08_resave_setup, scenario_08_resave_verify),
    "09_in_process_reopen": (scenario_09_in_process_reopen_setup, scenario_09_in_process_reopen_verify),
}


# ----------------------------------------------------------------------------
# Phase entry points
# ----------------------------------------------------------------------------

def run_setup():
    boot_addon()
    setup_fn, _ = SCENARIOS[SCENARIO]
    expected = setup_fn()
    save_blend(BLEND_PATH)
    # Capture the same snapshot during setup so verify can diff against it
    snap = scene_snapshot(expected.get("expected_ids", []))
    expected["snapshot"] = snap
    os.makedirs(os.path.dirname(EXPECTED_JSON), exist_ok=True)
    with open(EXPECTED_JSON, "w") as f:
        json.dump(expected, f, indent=2)
    return {"phase": "setup", "scenario": SCENARIO, "ok": True,
            "blend": BLEND_PATH, "expected_ids": expected.get("expected_ids", []),
            "snapshot": snap}


def run_verify():
    # In the verify phase, the .blend is opened by Blender BEFORE this script
    # runs (passed on the command line) — register-then-open-mainfile triggers
    # an EXCEPTION_STACK_OVERFLOW in Blender 5.1, so we must register only
    # AFTER the file is already loaded.
    boot_addon()

    with open(EXPECTED_JSON) as f:
        expected = json.load(f)

    # Phase 2a: capture the raw on-disk state before any reconstruction logic
    # runs. This isolates which fields the .blend file actually preserved vs
    # which fields are clobbered by sync.
    raw_snapshot = raw_property_snapshot(expected.get("expected_ids", []))

    # Phase 2b: drive the same reconstruction the UI panel does on first draw.
    reconstruct_after_load()

    _, verify_fn = SCENARIOS[SCENARIO]
    post_sync_snapshot = verify_fn(expected)

    raw_issues = diff_summaries(expected.get("snapshot", {}), raw_snapshot, raw=True)
    sync_issues = diff_summaries(expected.get("snapshot", {}), post_sync_snapshot)

    return {
        "phase": "verify",
        "scenario": SCENARIO,
        "ok": len(sync_issues) == 0,
        "raw_ok": len(raw_issues) == 0,
        "issues": sync_issues,
        "raw_issues": raw_issues,
        "expected_snapshot": expected.get("snapshot", {}),
        "raw_snapshot": raw_snapshot,
        "actual_snapshot": post_sync_snapshot,
    }


def main():
    try:
        if PHASE == "setup":
            result = run_setup()
        elif PHASE == "verify":
            result = run_verify()
        else:
            raise ValueError(f"Unknown phase {PHASE}")
    except Exception as e:
        result = {
            "phase": PHASE,
            "scenario": SCENARIO,
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

    os.makedirs(os.path.dirname(RESULT_JSON), exist_ok=True)
    with open(RESULT_JSON, "w") as f:
        json.dump(result, f, indent=2, default=str)


main()
