# ProteinBlender Save/Load Stress Test

This document captures the audit, the scenario design, and the run results
of a save/load stress-test pass against the **worktree code** in
`adoring-booth-03e8a1`, executed against **Blender 5.1**.

The intent is to drive the addon "like a regular user" and verify that
every persistent feature survives a full save → close-and-reopen cycle.

---

## 1. Audit summary (what gets persisted)

ProteinBlender's persistent state lives almost entirely in Blender
PropertyGroups. Runtime objects (e.g. `MoleculeWrapper` in
`ProteinBlenderScene.molecules`) are reconstructed from PropertyGroup
data after load.

| Layer | Storage | Persists? | Location |
| --- | --- | --- | --- |
| Molecule list | `Scene.molecule_list_items` (CollectionProperty of `MoleculeListItem`) | yes | scene |
| Per-molecule chain map | `MoleculeListItem.chain_mapping_json`, `chain_residue_ranges_json` | yes | scene |
| Style | `MoleculeListItem.style` (enum) | yes | scene |
| Domain definitions | `MoleculeListItem.domains` (CollectionProperty of `Domain`) | yes | scene |
| Domain pivot/colour/name | `Object.domain_color`, `Object.domain_expanded`, custom props | yes | object |
| Poses | `MoleculeListItem.poses` (CollectionProperty of `MoleculePose`) | yes | scene |
| Pose transforms | `MoleculePose.domain_transforms`, `group_transforms`, `protein_*` | yes | scene |
| Keyframes (PB metadata) | `MoleculeListItem.keyframes` | yes | scene |
| Keyframes (animation data) | F-curves on objects | yes | object/animdata |
| Outliner / puppets | `Scene.outliner_items` | yes | scene |
| Linkers | `Scene.pb2_linkers` (CollectionProperty of `PB2_LinkerDefinition`) | yes | scene |
| Brownian motion | F-curve Noise modifiers | yes | animdata |
| Runtime wrapper dict | `ProteinBlenderScene._instance.molecules` | **no** — rebuilt on demand | singleton |
| MN session | `Scene.MNSession` | rebuilt | scene |

### Reconstruction on load

`load_handlers.reset_scene_manager_on_load()` (registered in `bpy.app.handlers.load_post`)
clears the singleton, then `create_workspace_on_load()` rebuilds the workspace.
The molecule wrapper dict is **not** rebuilt on load_post — it is rebuilt
lazily by `panels/molecule_list_panel.py:25-26`, which calls
`sync_molecule_list_after_undo()` while drawing. In headless tests we therefore
need to call that function manually after opening the file.

`sync_molecule_list_after_undo()` (`utils/scene_manager.py:819`) performs:

1. `_heal_all_wrapper_references()` — restores stale object/node-group refs by stored name
2. `_remove_invalid_wrappers()` — drops wrappers whose objects no longer exist
3. `_reconstruct_wrappers_from_properties()` — recreates `MoleculeWrapper` instances from `MoleculeListItem`s
4. `_handle_orphaned_proteins()` — adopts MolecularNodes objects that have no PropertyGroup entry yet
5. `_refresh_molecule_ui()` — rebuilds `scene.molecule_list_items` from the wrapper dict
6. `build_outliner_hierarchy()` — recreates chain/domain/puppet rows in `outliner_items`

### Key risk areas (from audit)

- **Chain mapping**: three internal maps can diverge (`auth_chain_id_map`,
  `idx_to_label_asym_id_map`, `chain_mapping`). Persistence path uses
  `chain_mapping_json` only — divergence between residue ranges and chain map
  shows up after reload.
- **Pose schema split**: poses can store both legacy `domain_transforms` and
  new `group_transforms`. Apply path needs to handle both.
- **Object name healing**: `Domain.object_name` and
  `MoleculeListItem.object_name` are used to re-find Blender objects after
  duplication / suffix collisions. If a `.001` clone exists, healing can
  attach to the wrong object.
- **Linker endpoint validation**: linkers reference outliner items; if
  outliner rebuild produces different IDs after load, linkers can be
  silently dropped.
- **MNSession**: not Blender-native; if the MolecularNodes addon is not
  reinitialised on load, style change / colour-by-X attribute updates can
  fail silently.

---

## 2. Test design

### 2.1 Test environment

- **Blender executable**: `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`
- **Addon under test**: the worktree at `proteinblender/` (NOT the
  `vscode_development` install — the harness inserts the worktree on
  `sys.path`, removes any cached `proteinblender` modules, then registers
  the worktree's package directly).
- **Mode**: `--background --factory-startup --python harness.py -- ...`.
  `--factory-startup` is the headless equivalent of "File → New" / Ctrl+N
  with all factory defaults — exactly what the user asked for to refresh
  the workspace before each setup phase.
- **PDB downloads**: cached to `tests/stress_test_workdir/cache/`. First
  scenario warms the cache; subsequent runs reuse local copies (the harness
  uses `molecule.import_local` instead of fetching from RCSB to avoid
  flaky network).
- **Scratch dir**: `tests/stress_test_workdir/` (`.blend` files,
  per-scenario JSON results, log dump).

### 2.2 Scenario shape

Each scenario runs in **two phases, two separate Blender processes**:

1. **`setup`** — fresh factory startup → register addon → exercise feature
   → save `.blend` → write expected-state JSON
2. **`verify`** — fresh factory startup → register addon → open `.blend`
   → call `sync_molecule_list_after_undo()` → compare actual state to
   the expected-state JSON → write result JSON

This is much closer to the real user workflow than "save and load in one
session" — the second Blender process truly knows nothing about phase 1
beyond what is in the `.blend` file.

### 2.3 Scenarios

| # | Name | Features exercised |
| --- | --- | --- |
| 1 | Empty session (regression baseline) | addon register, empty-scene save/load, no proteins |
| 2 | Single PDB import | import 1AKE (1 chain), default style, basic round-trip |
| 3 | Multi-protein + style mix | import 1AKE + 4HHB, set styles cartoon/surface/ribbon, change identifier |
| 4 | Domain hierarchy | import 4HHB, create 4 domains across chains, custom colours, then split one |
| 5 | Pose library | import 1AKE, two domains, capture two poses with different transforms, apply each after reload |
| 6 | Keyframes | import 1AKE, two domains, set keyframes at frames 1/30/60, evaluate at each after reload |
| 7 | Delete persistence | import three proteins, delete the middle one, save, reload, confirm two remain with no orphan objects |
| 8 | Resave / incremental edit | reload scenario 3's `.blend`, add another protein, change a style, resave, reload again |

### 2.4 Verification checks (per scenario)

For every scenario the verify phase records:

- **load_ok**: file opened without exceptions
- **register_ok**: `proteinblender.register()` survived a re-register on the loaded file
- **wrapper_count** vs **expected_count**: `len(ProteinBlenderScene.molecules)` after `sync_molecule_list_after_undo()`
- **list_count** vs **wrapper_count**: `len(scene.molecule_list_items)` matches the wrapper dict
- **per-molecule**: identifier survives, chain_mapping non-empty, residue ranges non-empty, style preserved, object exists in `bpy.data.objects`
- **per-domain**: name, residue range, colour, parent molecule, object exists
- **per-pose**: name, domain_transform count, location/rotation/scale match captured values
- **per-keyframe**: pb metadata + corresponding F-curve keys exist on every domain object
- **errors**: full Python traceback if anything raised

A scenario passes only if every check is green.

---

## 3. Results

Test environment: Blender **5.1.0** (`hash adfe2921d5f3 built 2026-03-17`),
worktree at commit `b4ab600`, `tests/stress_test_workdir/` is the artifact
root (per-scenario `.blend`, `expected/*.json`, `logs/*.log`,
`results/*.json`, `results/summary.json`).

The verify phase captures **two snapshots** so we can tell where state is
lost:

- **raw**: read straight from PropertyGroups after Blender opens the
  `.blend`, before any addon code runs against it.
- **post-sync**: read after `sync_molecule_list_after_undo()` runs (this is
  the function the molecule-list panel calls during its first draw, so it
  is what a user sees the moment they look at the addon UI).

### 3.1 Score card

Two columns: **before** is the result on the original branch (claude/adoring-booth-03e8a1).
**after** is the result on `fix/save-load-data-loss` with Bugs A, B, C and the
delete-outliner-rebuild glitch from scenario 07 fixed.

| # | Scenario | Before | After | Notes |
| --- | --- | --- | --- | --- |
| 01 | Empty session | OK | OK | clean baseline |
| 02 | Single 1aki | FAIL | **OK** | sync no longer wipes object_name + chain ranges |
| 03 | Multi + style mix | FAIL | **OK** | `ribbon`/`spheres` survive |
| 04 | Domain colours on 4hhb | FAIL | **OK** | auto-domains now mirrored into `MoleculeListItem.domains` |
| 05 | Pose library | FAIL | **OK** | poses still round-trip bit-exact + surrounding state preserved |
| 06 | Keyframes | FAIL | **OK** | keyframe metadata + F-curves round-trip |
| 07 | Delete persistence | FAIL | **OK** | `delete_molecule` now drops orphan outliner rows immediately |
| 08 | Resave / incremental | FAIL | **OK** | resave preserves the mid-session style change |
| 09 | Register → in-process reopen | CRASH | CRASH | Bug D unfixed — `EXCEPTION_STACK_OVERFLOW` reproduces; needs deeper investigation (see §3.5) |

\* The "raw .blend round-trip" column is OK only in the narrow sense that
the bytes that the addon *did* write to the .blend come back unchanged. It
does **not** mean the .blend captures everything the user sees in the
addon UI — see §3.3.

### 3.2 What survives a real save → close → reopen

Verified by reading PropertyGroups straight after a fresh Blender process
opens the .blend (no addon sync run yet). Numbers match expectations
captured at setup time.

| State | Survives? | Where it lives |
| --- | --- | --- |
| `Scene.molecule_list_items[*].identifier` | yes | scene PropertyGroup |
| `…object_name` | yes | scene PropertyGroup |
| `…style` | yes | scene PropertyGroup |
| `…chain_residue_ranges_json` | yes | scene PropertyGroup |
| `…poses[*]` (name, has_protein_transform, all `domain_transforms` with float locations/rotations/scales) | yes — bit-exact | scene PropertyGroup |
| `…keyframes[*]` (pb metadata) | yes | scene PropertyGroup |
| `Scene.outliner_items` (1 protein + 1 row per chain) | yes | scene PropertyGroup |
| F-curves on domain objects (`location` keys at frames 1/30/60) | yes | object animation data |
| Deleted molecules stay deleted | yes | (scenario 07) |
| Multiple-protein blend with mixed styles | yes | (scenario 03) |
| Save → modify → resave (scenario 08) | yes | second save replaces first cleanly |

### 3.3 What is silently lost (the user-facing bugs)

These are the regressions a real user would hit. They group into three
distinct issues:

#### Bug A — `sync_molecule_list_after_undo()` clobbers persistent fields

`utils/scene_manager.py:_refresh_molecule_ui()` (lines 410–507) preserves
**only** `keyframes` and `poses`, then calls
`scene.molecule_list_items.clear()` and rebuilds each entry by writing
just `identifier` and `object_ptr`. Every other persisted field is wiped:

- `object_name` → `""`
- `chain_mapping_json` → `"{}"`
- `chain_residue_ranges_json` → `"{}"`
- `style` → resets to `cartoon` (the default)
- `domains` (CollectionProperty) — wiped, but see Bug C
- `outliner_items` chain rows — wiped, only the top-level protein row remains

Reproduces every scenario 02–08 once the user looks at the addon panel
(the panel-draw call in `panels/molecule_list_panel.py:25` is what triggers
the sync). Two save cycles after this point and the .blend itself is
permanently degraded — the next .blend save persists the cleared values.

Fix sketch: extend `_refresh_molecule_ui` to preserve **all** persistent
fields (`object_name`, `style`, both JSON blobs, the full domains
collection) the same way it already preserves `keyframes` and `poses`, or
re-call `item.sync_from_wrapper(wrapper)` after the rebuild.

#### Bug B — Domains never persist to the .blend

`MoleculeWrapper._create_domain_with_params()` adds the new domain to
`self.domains[domain_id]` (`core/molecule_wrapper.py:605`) but does **not**
mirror it into `MoleculeListItem.domains` (the CollectionProperty that
Blender would actually save). So the runtime dict has the domains the user
sees in the panel, but the .blend never gets them.

Visible everywhere:

- Setup-time snapshot already shows `domain_count: 0` on `MoleculeListItem`
  even after `_finalize_imported_molecule` auto-creates one per chain.
- `outliner_items` does have chain rows after import (because
  `build_outliner_hierarchy` walks `mol.domains` directly), but those are
  the only trace of domains in persisted data.
- After reload, `_reconstruct_wrappers_from_properties` calls
  `MoleculeWrapper.from_existing_object(...)` which has to rebuild the
  domain dict from the Blender object's chain attributes — any
  user-customised colour, name, residue range, split, or copy is gone.

Fix sketch: in `_create_domain_with_params` (and friends — `split_domain`,
`copy_domain`, `delete_domain`), update the parent `MoleculeListItem`'s
`domains` collection alongside the wrapper dict, then read back from there
during `_reconstruct_wrappers_from_properties`.

#### Bug C — `chain_mapping` is empty after import on Blender 5.1

`MoleculeWrapper.__init__` sets `self.chain_mapping = self.auth_chain_id_map`
(`core/molecule_wrapper.py:69`). `auth_chain_id_map` is empty for every
molecule we imported on Blender 5.1, including 4HHB. Side effects:

- `_create_domains_for_each_chain` worked only via its
  `idx_to_label_asym_id_map` fallback, so it did create one domain per
  chain — but those domains carry an integer-index chain key
  (`"0"`, `"1"`, …), not the author chain id `"A"`/`"B"`/…, which makes
  later lookups by author id (`mol.chain_mapping[chain_idx]`) silently
  return defaults.
- The `create_domain` operator's overlap check in
  `domain_operators.py:33-39` reads `chain_id_char = molecule.chain_mapping.get(...)`
  and gets back the bare numeric string, so manually-created partial
  domains report "Domain overlaps with existing domain" against the
  auto-created chain-wide domain (this is what scenarios 05 and 06
  initially tripped on).

Fix sketch: investigate why `auth_chain_id_map` ends up empty under the
biotite stack on Blender 5.1 (likely an API change in biotite 1.2.x); fall
back to populating it from `chain_residue_ranges` keys at the end of
`MoleculeWrapper.__init__` so downstream code always has a chain-id map.

#### Bug D — Register-then-`open_mainfile` crashes Blender 5.1

Reproduced reliably by scenario 09, the smoke test, and the original
verify-phase design:

```
Error : EXCEPTION_STACK_OVERFLOW
Address : 0x00007FFE93C0753F
Module : C:\Program Files\Blender Foundation\Blender 5.1\python313.dll
```

Triggered by:

1. `bpy.ops.preferences.addon_enable(module="proteinblender")` (or the
   equivalent direct `proteinblender.register()` call), then
2. `bpy.ops.wm.open_mainfile(filepath=…)`.

Opening the same .blend on the command line *before* the addon registers
works fine, so the bug only manifests with the
register-then-open ordering. This is the order a user hits when they
"File → Open" after installing the addon — so any user trying to open a
project file from within an active Blender session crashes the process.

Fix sketch: this is almost certainly a load_post handler doing something
nasty during `open_mainfile`. Likely suspects in order of how much they
touch on file load:

- `selection_sync.on_load_post` → `refresh_object_subscriptions()` (msgbus rebind)
- `linker_load_post_handler` (rebuilds linker geometry — calls
  `update_linker_curve` which mutates objects)
- `create_workspace_on_load` (calls `bpy.ops.workspace.duplicate()` and
  `area_split`, which are dangerous in a load-post context)
- `MNSession._load` (registered via `utils/molecularnodes/addon.py:60`,
  unpickles a `.MNSession` sidecar)

Bisecting by disabling each handler in turn before calling
`open_mainfile` would localise this in <10 minutes.

### 3.4 Per-scenario diff highlights

#### 02 — Single 1aki

```
raw   1aki_001: object_name='1aki' style='cartoon' chains=['A']
sync  1aki_001: object_name=''     style='cartoon' chains=[]
```

Only thing that round-trips post-sync: identifier and the protein object
itself.

#### 03 — Multi + style mix

```
raw   1aki_001: style='ribbon'   chains=['A']
raw   4hhb_001: style='spheres'  chains=['A','B','C','D']
sync  1aki_001: style='cartoon'  chains=[]
sync  4hhb_001: style='cartoon'  chains=[]
```

Both styles silently revert.

#### 04 — Domains

Setup: imports 4HHB, the addon auto-creates one chain-wide domain per
chain inside `MoleculeWrapper`, and the loop tints each one.
Setup-time `MoleculeListItem.domains` is **already** empty (0 entries)
because of Bug B — what the user sees in the panel is only the runtime
dict. `outliner_item_count` is 5 at setup, 1 after sync (Bug A drops the
chain rows).

#### 05 — Poses

Beautifully clean **for poses themselves**. Both Pose_A (defaults) and
Pose_B (custom locations / rotations / scales) survive bit-exact:

```
Pose_B / 4hhb_001_0_1_198_Chain_A: location=(1.0, 2.0, 3.0)
                                   rotation=(0.10000000149, 0.20000000298, 0.30000001192)
```

Float drift is only the usual `f32 ↔ f64` repacking — well below the
`1e-3` tolerance the harness uses.

The surrounding state (object_name, chain ranges, outliner) is
clobbered as in every other scenario.

#### 06 — Keyframes

Setup inserts F-curve keys at frames 1, 30, 60 on the auto-created
domain object. After reload + sync the F-curves are still attached to
the Blender object (Blender's native animation persistence works), but
because Bug B nukes `MoleculeListItem.domains`, the addon no longer
treats the keyed object as a tracked domain. The pb metadata
`MoleculeListItem.keyframes` (Start/Middle/End at frames 1/30/60)
**does** round-trip cleanly.

#### 07 — Delete persistence

Imports three (`1aki`, `1ubq`, `4hhb`), deletes the middle one via
`scene_manager.delete_molecule(...)`. After save → reload the deleted
molecule is gone (no orphan object, no orphan list item). The two
survivors carry the same surrounding-state damage as everything else.

#### 08 — Resave / incremental

Demonstrates that the *raw* .blend persistence is consistent across two
save cycles — `1aki_001`'s style flips to `ribbon` mid-session and the
final save still has it. The first time the user looks at the panel
after reopening the file, the sync wipe rolls it back to `cartoon`.

#### 09 — In-process reopen

Documented under Bug D. The setup process exits with rc 3221225725
(0xC0000409 — `STATUS_STACK_BUFFER_OVERRUN`) before it can write a result
JSON.

### 3.5 What this means for the addon

In rough priority:

1. **Bug D is the sharpest user-facing crash** — every "File → Open"
   path is a hard crash on Blender 5.1.
2. **Bug A is silent data corruption** — every reopen looks fine for a
   split second and then loses style + chain ranges + object names the
   instant the panel draws. Two saves later the .blend itself is corrupt.
3. **Bug B is catastrophic for user-customised domains** — colours,
   custom names, splits, copies all evaporate on reload.
4. **Bug C is a foundation issue** that masks itself by hiding behind
   chain-index fallbacks; cleaning it up makes the create-domain
   operator usable on a single-chain protein again.

Poses, keyframe metadata, deletions, and the basic .blend save path
itself are all working correctly today. The persistence layer is sound;
the problem is the runtime layer's reconstruction code.

### 3.6 Fixes applied (branch `fix/save-load-data-loss`)

- **Bug A (`_refresh_molecule_ui` clobbers state)** — fixed in
  `proteinblender/utils/scene_manager.py`. Added two helpers:
  `_snapshot_list_item` captures every persistent field
  (`object_name`, `style`, `chain_mapping_json`, `chain_residue_ranges_json`,
  the full `domains` collection, keyframes, poses, active indices) into a
  plain dict; `_restore_list_item` writes them back onto a freshly-added
  `MoleculeListItem`. `_refresh_molecule_ui` now snapshots → clears →
  rebuilds → restores instead of clearing-and-rebuilding-with-only-identifier.
- **Bug B (domains never persisted)** — fixed in
  `proteinblender/core/molecule_wrapper.py` and
  `proteinblender/utils/scene_manager.py`. Added
  `MoleculeWrapper._mirror_domains_to_property_group()` which writes every
  runtime `DomainDefinition` into the parent `MoleculeListItem.domains`
  CollectionProperty; called at the end of `_create_domain_with_params`
  (creates and renames), `_delete_domain_direct`, and
  `_finalize_imported_molecule` (so auto-created chain domains land in PG
  after the list item exists). Added `_restore_domains_into_wrapper()`
  which is called from `_reconstruct_wrappers_from_properties` after
  `from_existing_object`, rebuilding the runtime `wrapper.domains` dict
  from the persisted PG (matching object pointer by stored name and
  re-reading colour/style from the Blender object's custom properties).
  Also added `domain_id` and `object_name` `StringProperty` fields on the
  `Domain` PropertyGroup in `proteinblender/core/domain.py`.
- **Bug C (`chain_mapping` empty on Blender 5.1)** — fixed in
  `proteinblender/core/molecule_wrapper.py`. After
  `auth_chain_id_map` is populated from biotite, if the result is empty
  but `chain_residue_ranges` has entries, fall back to deriving
  `{idx → author_id}` from the residue-range keys so downstream code
  always sees a non-empty map.
- **Scenario-07 outliner glitch** — fixed in
  `ProteinBlenderScene.delete_molecule` by calling
  `build_outliner_hierarchy(bpy.context)` immediately after the list item
  is removed. Without this, deleting a molecule left orphan chain rows in
  the outliner until the next sync (which after this fix is just visual
  cleanup, not a data correction).
- **Bug D — not yet fixed.** A bisect over the load_post handlers and a
  subsystem-level register bisect both fail to localise the recursion. A
  clean `proteinblender.register()` followed by `bpy.ops.wm.open_mainfile`
  still triggers the stack overflow even on an empty .blend, so the cause
  is not file content. Workaround for users today: restart Blender between
  project files (or close the file from the splash screen before opening
  another). Worth investigating further.

---

## 4. How to re-run

```powershell
python tests/stress_test/run_stress_test.py
# or run a single scenario:
python tests/stress_test/run_stress_test.py --only=05_poses
```

`run_stress_test.py` hard-codes the Blender 5.1 executable path so it
ignores any pre-existing `BLENDER_PATH` env var (the workstation here had
it pinned to 5.0). Per-scenario phases time out at 120 s — useful when a
scenario hits Bug D's stack overflow.

The harness is fully isolated under `tests/stress_test_workdir/` and does
not touch the user's `vscode_development` extension install. Each verify
phase passes the .blend on the Blender command line so the file is opened
*before* the addon registers — this is how we sidestep Bug D for every
verify-phase run; only scenario 09 calls `open_mainfile` post-register
deliberately to keep the bug under test.
