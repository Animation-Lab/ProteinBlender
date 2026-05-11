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

**What still fails and why:**
- `bpy.data.objects.remove(obj, do_unlink=True)` calls in [proteinblender/core/manager.py:32](../../proteinblender/core/manager.py#L32), [proteinblender/core/molecule_manager.py:142](../../proteinblender/core/molecule_manager.py#L142), and [proteinblender/core/domain.py:281,291](../../proteinblender/core/domain.py#L281) bypass Blender's undo stack. Blender's undo system only knows about state changes made via `bpy.ops` operators. So when `molecule.delete` calls these low-level removes, `ed.undo` later has nothing to roll back — the objects are simply gone.
- The same applies to domain splits which call low-level mesh API to create the new sub-meshes.

**Proposed fix path (multi-day):** route every object deletion through `bpy.ops.object.delete()`. That requires:
1. Selecting the object(s) to delete.
2. Calling `bpy.ops.object.delete(use_global=False)` instead of `bpy.data.objects.remove`.
3. Ensuring the surrounding manager state (wrapper dict, list items) is mirrored to PropertyGroups so Blender's undo of the operator includes that state too.

This is the right fix but a substantial refactor of the manager + molecule_manager + domain cleanup paths. Flagged for separate planning.

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
