"""End-to-end regression suite for ProteinBlender, driven through the addon's
OWN operators (never Blender-native fallbacks).

Design goal it protects: ProteinBlender must stay a self-contained UI. Every
capability a user needs (select, colour, style, puppet, pose, DNA, keyframe)
is exercised here via ``proteinblender.*`` / ``molecule.*`` operators and the
PB outliner — NOT via bpy.ops.object.* or Blender's native outliner/timeline.
If a capability can only be reached through Blender-native UI, that's drift,
and these tests are where it should surface.

Run inside Blender with a multi-chain protein already loaded (e.g. 1atn):
  * Text Editor -> open -> Run Script, or
  * CLI: blender your.blend --python tests/test_full_suite.py

Each subsystem builds and cleans up its own fixtures (puppets, poses, DNA),
so the suite is repeatable and leaves the scene as it found it (aside from
chain colour/style, which are visual-only).

Scope notes (read before trusting a green run):
  * Save/load and undo/redo are NOT exercised here. They depend on file IO and
    Blender's undo stack, which are unreliable to drive from a script and must
    be confirmed interactively in a FRESH Blender session. See
    ``MANUAL_CHECKS`` at the bottom.
  * Keyframe navigation/deletion via the PB panel is currently not wired
    (placeholder operators) — see the animation test's notes.
"""

import bpy
import sys
import importlib
from mathutils import Matrix


# --------------------------------------------------------------------------- #
# Addon access + harness
# --------------------------------------------------------------------------- #
def _package_root():
    for name in sys.modules:
        if name.split(".")[-1] == "proteinblender":
            try:
                importlib.import_module(name + ".utils.chain_utils")
                return name
            except Exception:
                continue
    raise RuntimeError("ProteinBlender addon is not loaded / enabled")


_PKG = _package_root()
chain_utils = importlib.import_module(_PKG + ".utils.chain_utils")
scene_manager = importlib.import_module(_PKG + ".utils.scene_manager")
visual_setup = importlib.import_module(_PKG + ".panels.visual_setup_panel")


class Results:
    def __init__(self):
        self.rows = []

    def check(self, name, passed, detail=""):
        self.rows.append((name, bool(passed), detail))
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    def note(self, text):
        print(f"  [NOTE] {text}")

    def failed(self):
        return [r for r in self.rows if not r[1]]


def _ui():
    for wtype in ("PROPERTIES", "VIEW_3D"):
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == wtype:
                    region = next((r for r in area.regions if r.type == "WINDOW"), None)
                    return win, area, region
    return None, None, None


_WIN, _AREA, _REGION = _ui()


def op(call, ctx=None, **kw):
    """Run a PB operator under a UI override; return (status_str, error_or_None)."""
    try:
        with bpy.context.temp_override(window=_WIN, area=_AREA, region=_REGION):
            return (str(call(ctx, **kw) if ctx else call(**kw)), None)
    except Exception:
        import traceback
        return (None, traceback.format_exc().strip().splitlines()[-1])


def sm():
    return scene_manager.ProteinBlenderScene.get_instance()


def deselect_all():
    scene = bpy.context.scene
    for o in bpy.data.objects:
        try:
            o.select_set(False)
        except Exception:
            pass
    for it in scene.outliner_items:
        it.is_selected = False


def items_of(t):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == t and it.item_id != "puppets_separator"]


def obj_selected(name):
    o = bpy.data.objects.get(name)
    return bool(o and o.select_get())


def approx(a, b, tol=0.06):
    return a is not None and all(abs(a[i] - b[i]) < tol for i in range(min(len(a), len(b))))


def find_protein():
    for it in bpy.context.scene.outliner_items:
        if it.item_type == "PROTEIN":
            chains = [c for c in bpy.context.scene.outliner_items
                      if c.item_type == "CHAIN" and c.parent_id == it.item_id]
            if len(chains) >= 2:
                return it, chains
    return None, []


# --------------------------------------------------------------------------- #
# Subsystem tests
# --------------------------------------------------------------------------- #
def test_proteins(R, protein):
    mol = sm().molecules[protein.item_id]
    obj = mol.object
    # center_protein
    obj.matrix_world = obj.matrix_world @ Matrix.Translation((10, 0, 0))
    bpy.context.view_layer.update()
    _, err = op(bpy.ops.molecule.center_protein, molecule_id=protein.item_id)
    bpy.context.view_layer.update()
    R.check("protein: center_protein returns to origin",
            err is None and abs(obj.matrix_world.translation.x) < 2.0)
    # duplicate + delete
    before = set(sm().molecules)
    _, err = op(bpy.ops.molecule.duplicate_protein, molecule_id=protein.item_id)
    dup = list(set(sm().molecules) - before)
    ok = bool(dup) and len(sm().molecules[dup[0]].domains) >= len(mol.domains)
    if dup:
        op(bpy.ops.molecule.delete, molecule_id=dup[0])
    R.check("protein: duplicate creates full copy + delete cleans up",
            err is None and ok and (not dup or dup[0] not in sm().molecules))


def test_styles(R, protein, chains):
    chain = chains[0]
    objs = chain_utils.get_chain_objects(sm().molecules[protein.item_id], chain)
    if not objs:
        R.check("style: resolve chain object", False)
        return
    obj = objs[0]
    deselect_all()
    op(bpy.ops.proteinblender.outliner_select, item_id=chain.item_id)
    before = visual_setup.get_object_style(obj)
    target = "spheres" if before != "spheres" else "cartoon"
    with bpy.context.temp_override(window=_WIN, area=_AREA, region=_REGION):
        bpy.context.scene.visual_setup_style = target
    R.check(f"style: live picker sets chain to '{target}' (PB UI)",
            visual_setup.get_object_style(obj) == target)


def test_selection(R, protein, chains):
    mol = sm().molecules[protein.item_id]
    # select each chain via PB outliner -> its object(s) selected
    all_ok = True
    for chain in chains:
        deselect_all()
        op(bpy.ops.proteinblender.outliner_select, item_id=chain.item_id)
        objs = chain_utils.get_chain_objects(mol, chain)
        all_ok = all_ok and bool(objs) and all(obj_selected(o.name) for o in objs)
    R.check("selection: every chain selects its object via PB outliner", all_ok)
    # two-way: viewport selection -> outliner checkbox
    deselect_all()
    objs = chain_utils.get_chain_objects(mol, chains[0])
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    importlib.import_module(_PKG + ".handlers.selection_sync").update_outliner_from_blender_selection()
    R.check("selection: viewport -> outliner two-way sync", chains[0].is_selected)


def test_puppets(R, chains):
    deselect_all()
    for c in chains[:2]:
        c.is_selected = True
    op(bpy.ops.proteinblender.create_puppet, puppet_name="SuitedPuppet")
    pup = next((p for p in items_of("PUPPET") if p.name == "SuitedPuppet"), None)
    if not pup:
        R.check("puppet: create", False)
        return None
    ctrl = bpy.data.objects.get(pup.controller_object_name)
    members = (pup.puppet_memberships or "").split(",")
    objA = chain_utils.get_chain_objects(sm().molecules[chains[0].parent_id], chains[0])
    parented = bool(objA) and all(o.parent == ctrl for o in objA)
    R.check("puppet: controller Empty + membership + parenting",
            ctrl is not None and ctrl.type == "EMPTY"
            and chains[0].item_id in members and chains[1].item_id in members and parented)
    # selection via PB outliner -> controller selected
    deselect_all()
    op(bpy.ops.proteinblender.outliner_select, item_id=pup.item_id)
    R.check("puppet: PB-outliner selection drives controller",
            bool(ctrl and ctrl.select_get()))
    return pup


def test_poses(R, chains, pup):
    if not pup:
        R.check("pose: (no puppet)", False)
        return
    scene = bpy.context.scene
    objA = chain_utils.get_chain_objects(sm().molecules[chains[0].parent_id], chains[0])[0]
    n_before = len(scene.pose_library)
    pose = scene.pose_library.add()
    pose.name = "SuitePose"
    pose.puppet_ids = pup.item_id
    pose.puppet_names = pup.name
    idx = len(scene.pose_library) - 1
    M = objA.matrix_world.copy()
    _, err = op(bpy.ops.proteinblender.capture_pose, pose_index=idx)
    R.check("pose: capture stores transforms", err is None and len(pose.transforms) >= 1)
    objA.matrix_world = M @ Matrix.Translation((0, 0, 3))
    bpy.context.view_layer.update()
    _, err = op(bpy.ops.proteinblender.apply_pose, pose_index=idx)
    bpy.context.view_layer.update()
    R.check("pose: apply restores captured transform",
            err is None and (objA.matrix_world.translation - M.translation).length < 0.05)
    _, err = op(bpy.ops.proteinblender.delete_pose, pose_index=idx)
    R.check("pose: delete removes entry", err is None and len(scene.pose_library) == n_before)


def test_dna(R):
    props = bpy.context.scene.dna_builder_props
    props.nucleic_type = "DNA"
    props.sequence = "ATCG"
    op(bpy.ops.proteinblender.swap_to_complement)
    R.check("dna: swap_to_complement (ATCG -> CGAT reverse-complement)",
            props.sequence == "CGAT")
    props.sequence = "ATCGAATTCCGG"
    before = set(sm().molecules)
    op(bpy.ops.proteinblender.build_dna, ctx="EXEC_DEFAULT")
    did = next(iter(set(sm().molecules) - before), None)
    obj = sm().molecules[did].object if did else None
    R.check("dna: build registers molecule with stored sequence",
            did is not None and obj is not None and obj.get("pb_sequence") == "ATCGAATTCCGG")
    if obj:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        _, err = op(bpy.ops.proteinblender.update_dna_colors, ctx="EXEC_DEFAULT")
        R.check("dna: update_dna_colors", err is None)
    if did:
        op(bpy.ops.molecule.delete, molecule_id=did)
        R.check("dna: delete cleans up", did not in sm().molecules)
    R.note("DNA strands are NOT individual outliner rows (a DNA molecule is one "
           "selectable row) -- confirm this is the intended UX.")


def test_animation(R, chains):
    deselect_all()
    for c in chains[:2]:
        c.is_selected = True
    op(bpy.ops.proteinblender.create_puppet, puppet_name="SuiteAnim")
    pup = next((p for p in items_of("PUPPET") if p.name == "SuiteAnim"), None)
    if not pup:
        R.check("animation: (no puppet)", False)
        return
    ctrl = bpy.data.objects.get(pup.controller_object_name)
    scene = bpy.context.scene

    def puppet_items():
        # bpy.ops collection conversion requires EVERY PropertyGroup field present.
        return [{"name": pup.item_id, "puppet_id": pup.item_id, "puppet_name": pup.name,
                 "controller_object_name": pup.controller_object_name, "use_puppet": True,
                 "keyframe_location": True, "keyframe_rotation": True, "keyframe_scale": True,
                 "keyframe_color": True, "keyframe_pose": True, "brownian_enabled": False}]

    scene.frame_set(1)
    _, e1 = op(bpy.ops.proteinblender.create_keyframe, frame_number=1, puppet_items=puppet_items())
    scene.frame_set(30)
    ctrl.matrix_world = ctrl.matrix_world @ Matrix.Translation((0, 0, 6))
    bpy.context.view_layer.update()
    _, e2 = op(bpy.ops.proteinblender.create_keyframe, frame_number=30, puppet_items=puppet_items())
    R.check("animation: create_keyframe at f1 and f30 (PB UI)",
            e1 is None and e2 is None and bool(ctrl.animation_data and ctrl.animation_data.action))
    # The animation actually drives the controller (interpolates between keys).
    scene.frame_set(1); bpy.context.view_layer.update(); z1 = ctrl.matrix_world.translation.z
    scene.frame_set(15); bpy.context.view_layer.update(); z15 = ctrl.matrix_world.translation.z
    scene.frame_set(30); bpy.context.view_layer.update(); z30 = ctrl.matrix_world.translation.z
    R.check("animation: keyframes drive the controller (interpolated)",
            z1 < z15 < z30 and (z30 - z1) > 1.0)
    scene.frame_set(1)
    op(bpy.ops.proteinblender.delete_puppet, puppet_id=pup.item_id)
    R.note("Keyframe NAVIGATION/DELETE are not exposed in the Animate panel "
           "(proteinblender.jump_to_keyframe / delete_keyframe are placeholders "
           "bound to a legacy data model). Today, editing/removing keyframes "
           "requires Blender's native timeline -- this is UI drift to address.")


# --------------------------------------------------------------------------- #
# Things that need a FRESH Blender session / interactive verification
# --------------------------------------------------------------------------- #
MANUAL_CHECKS = """
NOT covered by this script -- verify in a fresh Blender session, interactively:
  * Save/Load: load a .blend with proteins+puppets+poses+keyframes; confirm the
    outliner, molecule registry, puppets, poses and animation all return intact.
  * Undo/Redo: create/copy/delete a domain, split a chain, create a puppet;
    Ctrl-Z / Ctrl-Shift-Z and confirm the outliner + registry stay consistent.
  (Both are unreliable to drive from a script and were inconclusive when run in
   a hot-reloaded session.)
"""


def run():
    scene = bpy.context.scene
    R = Results()
    protein, chains = find_protein()
    if protein is None:
        print("SKIP: load a protein with >= 2 chains first.")
        return True
    print(f"Suite target: '{protein.name}' chains {[c.name for c in chains]}\n")

    print("PROTEINS");   test_proteins(R, protein)
    print("STYLES");     test_styles(R, protein, chains)
    print("SELECTION");  test_selection(R, protein, chains)
    print("PUPPETS");    pup = test_puppets(R, chains)
    print("POSES");      test_poses(R, chains, pup)
    if pup:
        op(bpy.ops.proteinblender.delete_puppet, puppet_id=pup.item_id)
    print("DNA");        test_dna(R)
    print("ANIMATION");  test_animation(R, chains)

    deselect_all()
    failed = R.failed()
    print(f"\n{len(R.rows) - len(failed)}/{len(R.rows)} checks passed.")
    print(MANUAL_CHECKS)
    if failed:
        raise AssertionError("FAILED: " + ", ".join(n for n, _, _ in failed))
    print("All automated subsystem checks passed.")
    return True


if __name__ == "__main__":
    run()
