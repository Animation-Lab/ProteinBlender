"""Common test harness — loaded once via MCP exec, then individual test
modules call into it. Records results progressively to disk so partial
runs don't lose data."""
import bpy
import sys
import json
import traceback
from pathlib import Path
from mathutils import Vector

ADDON = "bl_ext.vscode_development.proteinblender"
ROOT = Path(r"c:/Users/dlee1/BlenderProjects/ProteinBlender")
AUDIT = ROOT / "tests" / "feature_audit"
SHOTS = AUDIT / "screenshots"
RESULTS = AUDIT / "results"
RESULTS_JSON = RESULTS / "results.json"


def sm():
    return sys.modules[ADDON + ".utils.scene_manager"].ProteinBlenderScene.get_instance()


def sm_module():
    return sys.modules[ADDON + ".utils.scene_manager"]


def bender_mod():
    return sys.modules[ADDON + ".dna_builder.bender"]


# --------------------------------------------------------------------------
# Result storage
# --------------------------------------------------------------------------

_RESULTS = []


def _save_results():
    RESULTS_JSON.write_text(json.dumps(_RESULTS, indent=2, default=str))


def record(test_id, name, status, error=None, notes="", repro=None, screenshot=None):
    entry = {
        "test_id": test_id,
        "name": name,
        "status": status,
        "error": error,
        "notes": notes,
        "repro": repro or {},
        "screenshot": str(screenshot) if screenshot else None,
    }
    # Replace any prior entry with the same test_id (re-running a section
    # should overwrite, not append).
    for i, prior in enumerate(_RESULTS):
        if prior.get("test_id") == test_id:
            _RESULTS[i] = entry
            break
    else:
        _RESULTS.append(entry)
    print(f"[{status:4s}] {test_id} — {name}")
    if error:
        print(f"       error: {error}")
    if notes:
        print(f"       notes: {notes}")
    _save_results()
    return entry


def load_existing_results():
    global _RESULTS
    if RESULTS_JSON.exists():
        try:
            _RESULTS = json.loads(RESULTS_JSON.read_text())
            print(f"loaded {len(_RESULTS)} prior results")
        except Exception:
            _RESULTS = []


# --------------------------------------------------------------------------
# Scene reset + screenshot
# --------------------------------------------------------------------------

def reset_scene():
    """Tear down everything addon-managed. Manager first, then orphan objs."""
    mgr = sm()
    for ident in list(mgr.molecules.keys()):
        try:
            mgr.delete_molecule(ident)
        except Exception:
            try: del mgr.molecules[ident]
            except Exception: pass
    scene = bpy.context.scene
    while len(scene.molecule_list_items) > 0:
        scene.molecule_list_items.remove(0)
    while len(scene.outliner_items) > 0:
        scene.outliner_items.remove(0)
    if hasattr(scene, "pb2_linkers"):
        while len(scene.pb2_linkers) > 0:
            scene.pb2_linkers.remove(0)
    for obj in list(bpy.data.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    for blockset in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                     bpy.data.node_groups, bpy.data.collections):
        for blk in list(blockset):
            try:
                blockset.remove(blk)
            except Exception:
                pass


def screenshot(name):
    out = SHOTS / f"{name}.png"
    # Frame current selection / all addon objects
    bpy.ops.object.select_all(action='DESELECT')
    framed = False
    for o in bpy.data.objects:
        if (o.get("pb_is_nucleic_acid") or
                o.modifiers and any(m.type == "NODES" for m in o.modifiers) or
                "Bend" in o.name or "Linker" in o.name or "Puppet" in o.name or "Controller" in o.name):
            o.select_set(True)
            framed = True
    if not framed:
        for o in bpy.data.objects:
            o.select_set(True)
    for area in bpy.context.window.screen.areas:
        if area.type == "VIEW_3D":
            for region in area.regions:
                if region.type == "WINDOW":
                    try:
                        with bpy.context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_selected()
                    except Exception:
                        pass
            break
    bpy.context.scene.render.filepath = str(out)
    bpy.context.scene.render.resolution_x = 800
    bpy.context.scene.render.resolution_y = 1000
    try:
        bpy.ops.render.opengl(write_still=True)
    except Exception as e:
        print(f"screenshot failed: {e}")
        return None
    return out


# --------------------------------------------------------------------------
# Convenience builders
# --------------------------------------------------------------------------

def import_pdb(pdb_id):
    scene = bpy.context.scene
    scene.protein_props.import_method = "PDB"
    scene.protein_props.pdb_id = pdb_id
    scene.protein_props.remote_format = "pdb"
    before = set(sm().molecules.keys())
    bpy.ops.molecule.import_protein()
    new = sorted(set(sm().molecules.keys()) - before)
    if not new:
        raise RuntimeError(f"import failed for {pdb_id}")
    return new[-1]


def build_dna(seq="ATCGATCGATCG", name_prefix="DNA", nt="DNA", ds=True, style="ball_and_stick"):
    props = bpy.context.scene.dna_builder_props
    props.nucleic_type = nt
    props.sequence = seq
    props.double_stranded = ds
    props.style = style
    props.name_prefix = name_prefix
    bpy.ops.proteinblender.build_dna()
    for o in bpy.data.objects:
        if o.get("pb_is_nucleic_acid") and o.name.startswith(name_prefix):
            return o
    raise RuntimeError(f"build_dna({name_prefix}) failed — no nucleic object found")


def select_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def select_outliner_items(item_ids):
    """Set is_selected on outliner items matching given ids."""
    for it in bpy.context.scene.outliner_items:
        it.is_selected = (it.item_id in item_ids)


# --------------------------------------------------------------------------
# Boot
# --------------------------------------------------------------------------

print("=" * 60)
print("Feature audit harness loaded")
print(f"Addon: {ADDON}")
print(f"Results: {RESULTS_JSON}")
print(f"Screenshots: {SHOTS}")
print("=" * 60)
