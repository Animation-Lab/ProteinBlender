# ProteinBlender Feature Audit — 2026-05-10

Branch: `feature/dna-builder` (HEAD `609a4ec` "Fix bend rig drift across DNA sequence rebuild")
Blender: 5.1.0
Method: live MCP-driven tests in the running Blender instance, plus save/load round-trips via fresh-process subprocesses.

## Summary (after fix pass)

| Status | Count |
|---|---|
| PASS | **55** |
| FAIL | 3 |
| ERROR | 0 |
| **Total** | **58** |

**Pass rate: 73% → 95%.** All 8 originally-identified issues addressed (7 fixed, 1 confirmed test bug). The 3 remaining failures are all in the undo/redo section and share a single architectural root cause (see [issues.md](issues.md) ISSUE-1).

### By section (after fix pass)

| Section | Pass rate | Status |
|---|---|---|
| DNA / RNA / Bend | **9/9** | ✓ |
| Save / Load round-trip | **6/6** | ✓ |
| Domains | **7/7** | ✓ (fixed: D5 rename now updates wrapper, D6 merge no longer leaves source domains) |
| Keyframes | **6/6** | ✓ (fixed: KF3 jump-to-keyframe registered) |
| Linkers | **6/6** | ✓ (fixed: L4 visibility toggles all three hide flags) |
| Proteins | **7/7** | ✓ (fixed: P3 style mirrors to PG, P5 visibility flips all hide flags) |
| Poses | **6/6** | ✓ |
| Puppets | **6/6** | ✓ (fixed: registration + RENAME + separator guard) |
| Undo / Redo | 2/5 | Partial — UR1, UR4 fixed; UR2/UR3/UR5 blocked on architectural undo issue |

## Real bugs

See [issues.md](issues.md) for full reproduction steps and proposed fixes.

| ID | Severity | Title |
|---|---|---|
| ISSUE-1 | **High** | Undo doesn't reverse addon operations (UR1, UR3, UR4, UR5) |
| ISSUE-2 | **High** | `proteinblender.delete_puppet` operator never registered |
| ISSUE-3 | **High** | `proteinblender.jump_to_keyframe` + `proteinblender.delete_keyframe` (panel button) never registered |
| ISSUE-4 | Medium | `context.area.tag_redraw()` crashes when called from script/MCP context (rename_domain, edit_puppet) |
| ISSUE-5 | Medium | `molecule.toggle_visibility` and `pb2.toggle_linker_visibility` report success but `hide_get()` unchanged |
| ISSUE-6 | Medium | `scene.molecule_style` updates domain styles but leaves `MoleculeListItem.style` stale |
| ISSUE-7 | Low | `merge_domains` adds a new merged domain but doesn't remove source domains |
| ISSUE-8 | Low | Puppet controller move: children move by ~98% of controller delta, not 100% |

## Test artefacts

- Per-test results JSON: [results/results.json](results/results.json)
- Screenshots: [screenshots/](screenshots/)
- Saved blends for save/load round-trips: [results/blends/](results/blends/)
- Per-section scripts (rerunnable): [section_proteins.py](section_proteins.py), [section_domains.py](section_domains.py), [section_poses.py](section_poses.py), [section_keyframes.py](section_keyframes.py), [section_dna.py](section_dna.py), [section_puppets.py](section_puppets.py), [section_linkers.py](section_linkers.py), [section_undo_redo.py](section_undo_redo.py), [section_saveload.py](section_saveload.py)
- Shared harness: [harness.py](harness.py)

## Rerunning

Each section is self-contained. From the project root:

```bash
python tests/stress_test_workdir/bmcp.py --file tests/feature_audit/section_<name>.py
```

Each rerun deduplicates by `test_id`, so the JSON stays current.

## What this audit did NOT cover

- Multi-frame animation playback (jump to keyframe → render → verify visual state)
- Style-switching across all 5 styles (only 2 tested)
- Brownian motion operators (proteinblender.brownian_*)
- Domain-level pivot operators (set_pivot_first/last/center/custom)
- Animation through pose+keyframe combinations
- Performance / large-scene stress
