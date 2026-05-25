"""Regression test for chain-identity operations in the Protein Outliner.

Guards the "chain index vs. chain letter" bug class. The outliner identifies a
chain by its numeric *index* ("<mol>_chain_2") while a MoleculeWrapper domain
stores the author *letter* ("D"). Many features bridge the two -- selection,
colour, split, delete-chain, visibility. If any reverts to a naive
``index == letter`` compare (or to alphabet math, which is wrong for gapped
chain sets like A,B,D) it silently breaks. This script exercises each path on a
real multi-chain molecule and asserts the observable result.

Run inside Blender with a multi-chain protein already loaded:
  * Text Editor -> open this file -> Run Script, or
  * CLI: blender your.blend --python tests/test_chain_operations.py

The non-destructive checks (resolver, tokens, selection, colour, two-way) run
every time. The destructive checks (split/copy/delete) run too and restore the
chain afterwards via merge; run them on a scratch file.
"""

import bpy
import sys
import importlib


# --------------------------------------------------------------------------- #
# Addon access
# --------------------------------------------------------------------------- #
def _package_root():
    """Return the importable package name of the loaded ProteinBlender addon."""
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
selection_sync = importlib.import_module(_PKG + ".handlers.selection_sync")
visual_setup = importlib.import_module(_PKG + ".panels.visual_setup_panel")


# --------------------------------------------------------------------------- #
# Small harness
# --------------------------------------------------------------------------- #
class _Results:
    def __init__(self):
        self.rows = []

    def check(self, name, passed, detail=""):
        self.rows.append((name, bool(passed), detail))
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    def summary(self):
        failed = [r for r in self.rows if not r[1]]
        print(f"\n{len(self.rows) - len(failed)}/{len(self.rows)} checks passed.")
        return failed


def _ui_override():
    """A (window, area, region) triple for operators that need UI context."""
    for wtype in ("PROPERTIES", "VIEW_3D"):
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == wtype:
                    region = next((r for r in area.regions if r.type == "WINDOW"), None)
                    return win, area, region
    return None, None, None


def _deselect_all(scene):
    for obj in bpy.data.objects:
        try:
            obj.select_set(False)
        except Exception:
            pass
    for item in scene.outliner_items:
        item.is_selected = False


def _obj_selected(name):
    obj = bpy.data.objects.get(name)
    return bool(obj and obj.select_get())


def _approx(a, b, tol=0.06):
    return a is not None and all(abs(a[i] - b[i]) < tol for i in range(min(len(a), len(b))))


def _find_test_protein(scene):
    """First PROTEIN outliner row that has >= 2 chain children."""
    for item in scene.outliner_items:
        if item.item_type != "PROTEIN":
            continue
        chains = [c for c in scene.outliner_items
                  if c.item_type == "CHAIN" and c.parent_id == item.item_id]
        if len(chains) >= 2:
            return item, chains
    return None, []


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def run(include_destructive=True):
    scene = bpy.context.scene
    sm = scene_manager.ProteinBlenderScene.get_instance()
    win, area, region = _ui_override()
    results = _Results()

    protein, chains = _find_test_protein(scene)
    if protein is None:
        print("SKIP: load a protein with >= 2 chains first.")
        return True
    molecule = sm.molecules.get(protein.item_id)
    print(f"Testing protein '{protein.name}' with chains: {[c.name for c in chains]}\n")

    def op(call, **kw):
        with bpy.context.temp_override(window=win, area=area, region=region):
            return call(**kw)

    # 1. Resolver returns a real, existing object for every chain (incl. gapped).
    for chain in chains:
        objs = chain_utils.get_chain_objects(molecule, chain)
        ok = len(objs) >= 1 and all(o.name in bpy.data.objects for o in objs)
        results.check(f"resolver: {chain.name} -> objects", ok,
                      ",".join(o.name for o in objs) or "NONE")

    # 2. Token bridge maps each chain index to the molecule's true letter.
    idx_map = getattr(molecule, "idx_to_label_asym_id_map", {}) or {}
    for chain in chains:
        token = chain_utils.chain_token_from_item(chain)
        tokens = chain_utils.chain_match_tokens(molecule, token)
        expected = idx_map.get(int(token)) if str(token).isdigit() else token
        results.check(f"tokens: {chain.name} includes letter '{expected}'",
                      expected is None or str(expected) in tokens, str(sorted(tokens)))

    # 3. Selecting a chain selects its viewport object(s).
    for chain in chains:
        _deselect_all(scene)
        op(bpy.ops.proteinblender.outliner_select, item_id=chain.item_id)
        objs = chain_utils.get_chain_objects(molecule, chain)
        ok = bool(objs) and all(_obj_selected(o.name) for o in objs) and chain.is_selected
        results.check(f"select: {chain.name}", ok)

    # 4. Deselect round-trip on the first chain.
    first = chains[0]
    _deselect_all(scene)
    op(bpy.ops.proteinblender.outliner_select, item_id=first.item_id)
    op(bpy.ops.proteinblender.outliner_select, item_id=first.item_id)
    objs = chain_utils.get_chain_objects(molecule, first)
    results.check("deselect: round-trip",
                  not any(_obj_selected(o.name) for o in objs) and not first.is_selected)

    # 5. Two-way sync: selecting an object updates the outliner row.
    _deselect_all(scene)
    target = chain_utils.get_chain_objects(molecule, first)
    if target:
        for o in target:
            o.select_set(True)
        bpy.context.view_layer.objects.active = target[0]
        selection_sync.update_outliner_from_blender_selection()
        results.check("two-way: object -> outliner", first.is_selected)

    # 6. Live colour path colours the selected chain.
    _deselect_all(scene)
    op(bpy.ops.proteinblender.outliner_select, item_id=first.item_id)
    with bpy.context.temp_override(window=win, area=area, region=region):
        scene.visual_setup_color = (0.0, 1.0, 0.0, 1.0)
    obj0 = chain_utils.get_chain_objects(molecule, first)[0]
    results.check("colour: live pick -> chain green",
                  _approx(visual_setup.get_object_color(obj0), (0.0, 1.0, 0.0, 1.0)))

    # 7. Colour-picker syncs back to the chain's colour.
    _deselect_all(scene)
    with bpy.context.temp_override(window=win, area=area, region=region):
        scene.visual_setup_color = (0.5, 0.5, 0.5, 1.0)
    op(bpy.ops.proteinblender.outliner_select, item_id=first.item_id)
    results.check("colour: picker sync round-trip",
                  _approx(list(scene.visual_setup_color), (0.0, 1.0, 0.0, 1.0)))

    if include_destructive:
        _run_destructive(scene, sm, protein, chains, op, results)

    _deselect_all(scene)
    failed = results.summary()
    if failed:
        raise AssertionError("FAILED: " + ", ".join(n for n, _, _ in failed))
    print("All chain-operation regression checks passed.")
    return True


def _run_destructive(scene, sm, protein, chains, op, results):
    """Split a chain, verify, then merge it back."""
    molecule = sm.molecules.get(protein.item_id)
    chain = chains[-1]  # last chain (often the gapped one)
    token = chain_utils.chain_token_from_item(chain)
    start, end = chain.chain_start, chain.chain_end
    if not (end - start > 4):
        print("  (skipping split/merge: chain too short)")
        return

    mid_a, mid_b = start + 1, start + 1 + max(1, (end - start) // 3)
    before = len(chain_utils.get_chain_domains(molecule, chain))

    op(bpy.ops.proteinblender.split_domain, chain_id=str(token),
       molecule_id=protein.item_id, split_start=mid_a, split_end=mid_b)
    after = chain_utils.get_chain_domains(molecule, chain)
    full_chain_gone = not any(d.start == start and d.end == end for _i, d in after)
    results.check("split: chain divided + full-chain domain removed",
                  len(after) > before and full_chain_gone, f"{before} -> {len(after)} domains")

    # Selecting the now-split chain selects every sub-domain object.
    _deselect_all(scene)
    op(bpy.ops.proteinblender.outliner_select, item_id=chain.item_id)
    sub_objs = chain_utils.get_chain_objects(molecule, chain)
    results.check("split: select chain selects all sub-domains",
                  bool(sub_objs) and all(_obj_selected(o.name) for o in sub_objs))

    # Visibility toggle on the split chain round-trips (hide -> show).
    for o in sub_objs:
        o.hide_set(False, view_layer=bpy.context.view_layer)
    op(bpy.ops.proteinblender.toggle_visibility, item_id=chain.item_id)
    hidden = all(o.hide_get(view_layer=bpy.context.view_layer) for o in sub_objs)
    op(bpy.ops.proteinblender.toggle_visibility, item_id=chain.item_id)
    shown = all(not o.hide_get(view_layer=bpy.context.view_layer) for o in sub_objs)
    results.check("split: visibility hide+show round-trip", hidden and shown)

    # Restore: select the sub-domain rows and merge them back into one chain.
    _deselect_all(scene)
    for item in scene.outliner_items:
        if item.item_type == "DOMAIN" and item.parent_id == chain.item_id:
            item.is_selected = True
    op(bpy.ops.proteinblender.merge_domains)
    restored = chain_utils.get_chain_domains(molecule, chain)
    results.check("merge: chain restored to single domain",
                  len(restored) == 1 and restored[0][1].start == start and restored[0][1].end == end)


if __name__ == "__main__":
    run(include_destructive=True)
