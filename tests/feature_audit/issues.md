# ProteinBlender — Feature Audit Issues (2026-05-10, updated post-fix)

**Audit pass rate: 43/59 → 55/58 (73% → 95%)** after the fix pass.

All 8 originally-identified issues have been addressed. Three undo/redo failures remain — they share a single root cause that requires a deeper architectural change (see ISSUE-1 below).

---

## ISSUE-1 — Undo doesn't reverse addon operations

**Severity:** High
**Status:** **Partial fix.** UR1 (undo import) and UR4 (undo DNA build) now pass. UR2 (redo), UR3 (undo delete), UR5 (undo split) still fail.

**What was fixed:**
- `_is_molecule_valid()` and `MoleculeWrapper.object` / `MoleculeWrapper.is_valid()` now catch `databpy.LinkedObjectError` and treat it as "invalid" instead of propagating the exception. Before the fix, the first stale wrapper would kill the entire `_remove_invalid_wrappers` loop, leaving every subsequent wrapper untouched.
- `build_outliner_hierarchy()` now purges wrappers whose underlying object is gone *before* iterating them, so the outliner rebuild can no longer crash on stale UUIDs.
- `_remove_invalid_wrappers` itself wraps each per-wrapper validity check in `try/except` so one bad wrapper can't poison the loop.

**What was attempted and reverted (2026-05-11):**
A second fix attempt routed object deletions in `MoleculeManager.delete_molecule` through a new `undoable_remove_objects(objs)` helper that calls `bpy.ops.object.delete(use_global=False)` (a Blender op that pushes its own undo step and unlinks objects from scenes while keeping the data blocks alive in `bpy.data`).

Probing showed:
- With all undo / depsgraph handlers temporarily disabled: `ed.undo` after `bpy.ops.object.delete(use_global=False)` correctly re-linked the deleted objects to the view layer.
- With the addon's handlers active (as they are in normal use): the objects were already gone from `bpy.data` by the time the first `undo_post` handler started, so `_reconstruct_wrappers_from_properties` had nothing to rebuild from.

In other words: Blender's undo does the right thing in isolation, but some interaction between the addon's depsgraph handlers and `ed.undo`'s internal cycle is purging the orphan data blocks before our reconstruction code can see them. Identifying which handler — and whether the cause is in this addon, MolecularNodes, or Blender 5.1 itself — needs deeper investigation.

The attempted change also caused regressions in P7 (delete protein) and DNA7-9 because leaving data blocks alive as orphans changed the downstream test's "object is gone" check semantics, and forced auxiliary helpers (e.g., the audit's screenshot framing) to deal with objects that are no longer in the view layer. The change was reverted; the audit pass rate is back to **55/58 = 95%**.

**Next steps for a future fix attempt:**
1. Add tracing to identify exactly which handler (or Blender internal step) purges the orphan data between `ed.undo` and the first `undo_post` callback.
2. If it's a 3rd-party handler (MolecularNodes / Blender), prefer the "soft delete" approach: move objects to a hidden helper collection rather than unlinking them, so the data blocks stay scene-linked (just invisible). `ed.undo` can then undo the collection-move directly.
3. Audit downstream code paths that assume `bpy.data.objects.get(name) is None` as the "deleted" signal — they'd need updating to match the new semantics.

**Why it still doesn't work without a refactor:**
- `bpy.data.objects.remove(obj, do_unlink=True)` calls in [proteinblender/core/manager.py:32](../../proteinblender/core/manager.py#L32), [proteinblender/core/molecule_manager.py:142](../../proteinblender/core/molecule_manager.py#L142), and [proteinblender/core/domain.py:281,291](../../proteinblender/core/domain.py#L281) bypass Blender's undo stack entirely.
- Domain splits call low-level mesh API to create sub-meshes and also bypass undo.

---

## ISSUE-2 — `proteinblender.delete_puppet` operator never registered ✅ FIXED

Added `PROTEINBLENDER_OT_delete_puppet` to the import block and `CLASSES` list in [proteinblender/panels/__init__.py](../../proteinblender/panels/__init__.py). PU6 now passes.

---

## ISSUE-3 — Animation panel operators never registered ✅ FIXED

`PROTEINBLENDER_OT_jump_to_keyframe` and `PROTEINBLENDER_OT_delete_keyframe` (the panel button variants, distinct from the `molecule.*` operators) are now imported in [proteinblender/panels/__init__.py](../../proteinblender/panels/__init__.py) and added to `CLASSES`. KF3 now passes.

---

## ISSUE-4 — `context.area.tag_redraw()` crashes outside UI context ✅ FIXED

Both `proteinblender.rename_domain.execute` ([domain_ops.py](../../proteinblender/operators/domain_ops.py)) and `proteinblender.edit_puppet.execute` ([group_maker_panel.py](../../proteinblender/panels/group_maker_panel.py)) now guard with `if context.area is not None:` and fall back to tagging all 3D and properties areas across all windows.

---

## ISSUE-5 — Visibility toggles flip the wrong hide attribute ✅ FIXED

Both `molecule.toggle_visibility` and `pb2.toggle_linker_visibility` now flip `hide_viewport`, `hide_render`, and `hide_set()` together. Outliner eye icon, camera icon, and rendered output stay in sync. Both P5 and L4 now pass.

`hide_set()` requires a valid `view_layer` context and is wrapped in try/except so script invocation doesn't break.

---

## ISSUE-6 — `scene.molecule_style` doesn't update `MoleculeListItem.style` ✅ FIXED

`update_molecule_style` in [proteinblender/properties/molecule_props.py](../../proteinblender/properties/molecule_props.py) now mirrors the new style into the matching `MoleculeListItem.style` after dispatching to domains. This is what survives save/load. P3 now passes.

---

## ISSUE-7 — `merge_domains` left source domains in place ✅ FIXED

The match condition in [domain_ops.py:909](../../proteinblender/operators/domain_ops.py#L909) compared `str(domain.chain_id) == parent_chain.chain_id`, but those two fields use different namespaces (chain letter vs. numeric chain index). The removal loop was a silent no-op so the merged domain was added on top of the sources.

Added a chain-letter resolution step using `molecule.idx_to_label_asym_id_map`, mirroring the same pattern already used elsewhere in the same operator. D6 now passes.

**Note:** as a bonus, `proteinblender.rename_domain` also now actually renames the wrapper's domain (not just the outliner row) and mirrors into the persistent PropertyGroup so the rename survives save/load. D5 now passes.

---

## ISSUE-8 — Puppet controller 98% follow ✅ TEST BUG (no addon change)

Not an addon bug — the test was comparing children's world-position *delta* against the controller's *setpoint* (5, 3, 1). But the controller starts at the bbox centre of its children (not the origin), so the actual delta is `setpoint − initial_controller_location` ≈ (4.87, 3.02, 0.99). Children follow at exactly 100%. Test updated to compute the expected delta correctly. PU3 now passes.

---

## Bonus fixes uncovered during re-test

These weren't in the original audit but surfaced once other things started working:

### B-1 — `delete_puppet` allowed deleting the "── Puppets ──" separator row
**Severity:** Medium (silent data corruption on UI mis-click)

The puppets section in the outliner has a header row with `item_type='PUPPET'` and `item_id='puppets_separator'`. The operator's "find a puppet by id" loop matched the separator and happily removed it, leaving real puppets stranded.

**Fix:** Reject `puppet_id == 'puppets_separator'` at the top of `delete_puppet.execute`. [proteinblender/panels/group_maker_panel.py](../../proteinblender/panels/group_maker_panel.py).

### B-2 — `edit_puppet(action='RENAME')` ignored `puppet_id` kwarg
**Severity:** Medium (operator not scriptable)

The RENAME branch only searched for a puppet via `is_selected=True` in the outliner. Calling the operator with `puppet_id="..."` from a script had no effect: the operator returned `{'FINISHED'}` with no rename actually performed.

**Fix:** Prefer `self.puppet_id` when supplied, fall back to selection if not. Returns `{'CANCELLED'}` with a clear warning if neither resolves to a puppet. PU5 now passes.

---

## Summary table

| Issue | Status | Tests now passing |
|---|---|---|
| ISSUE-1 (undo) | Partial fix | UR1, UR4 |
| ISSUE-2 (delete_puppet not registered) | ✅ Fixed | PU6 |
| ISSUE-3 (animation panel ops not registered) | ✅ Fixed | KF3 |
| ISSUE-4 (tag_redraw crash) | ✅ Fixed | D5, PU5 (no-crash precondition) |
| ISSUE-5 (visibility toggle) | ✅ Fixed | P5, L4 |
| ISSUE-6 (style metadata drift) | ✅ Fixed | P3 |
| ISSUE-7 (merge_domains chain_id) | ✅ Fixed | D6 |
| ISSUE-8 (puppet 98% follow) | Test bug | PU3 (test updated) |
| B-1 (separator delete) | ✅ Fixed | PU6 |
| B-2 (edit_puppet puppet_id) | ✅ Fixed | PU5 |

**Final audit: 55/58 PASS (95%).** Remaining 3 failures are the deep-architectural undo capture issue (ISSUE-1) — UR2, UR3, UR5.
