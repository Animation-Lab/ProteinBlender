# Test coverage map

What the suite exercises, per subsystem, and the known gaps. Regenerate the
numbers by running `python tests/run_tests.py -q`.

Current status (Blender 5.2, offline lane): **218 passing, 9 skipped,
1 xfailed** across 228 collected tests. The single xfail is intentional (a
modal-dialog operator unreachable headless - see below), not a bug. The suite
was previously verified on Blender 5.0 and 5.1; the membrane Random Value fix
addresses sockets by identity so it stays compatible with those versions, though
the count above was re-run only on 5.2.

## Lanes

| lane | dir | what it proves |
|------|-----|----------------|
| unit | `tests/unit/` | pure logic (chain maths, DNA sequence, base geometry, catenary physics) with no scene |
| integration | `tests/integration/` | every registered subsystem operator, driven headless against a real scene |
| roundtrip | `tests/roundtrip/` | save → reopen (fresh Blender) → state preserved |
| smoke | `tests/test_harness_smoke.py` | the harness itself (register, reset isolation, import) |

## Unit lane

| module | targets |
|--------|---------|
| `test_chain_utils.py` | `get_chain_mapping_from_string`, `chain_mapping_to_string`, serialize/deserialize chain mappings + residue ranges — incl. the gapped-chain (A,B,D) index-vs-letter gotcha |
| `test_dna_sequence.py` | `get_complement` (DNA/RNA), `validate_sequence`, `calculate_helix_info`, `make_wound_mask`, `_cumulative_twist`, `build_nucleic_acid` |
| `test_canonical_geometry.py` | `build_canonical_template`, `get_canonical_templates`, purine/pyrimidine ring builders (atom counts, finite coords) |
| `test_linker_geometry.py` | `compute_catenary_points`, `compute_zero_g_points`, `_arc_length`, `compute_random_coil_points`, `_solve_catenary_parameter`, `apply_rigid_binding_zones` |

## Integration lane (subsystem → operators covered)

| module | operators / behaviour |
|--------|-----------------------|
| `test_proteins.py` | `molecule.import_protein` (network) / offline import, `change_style` across all styles, duplicate, toggle_visibility, center_protein, delete, delete_chain, auto-domain count |
| `test_domains.py` | `create_domain`, `update_domain_name`, `rename_domain`, `update_domain_color/style`, `copy_domain`, `split_domain` (both idnames), `merge_domains`, set/update parent, `reset_domain_transform`, `snap_pivot_to_residue`, `toggle_domain_expanded` |
| `test_poses.py` | `molecule.create_pose/apply_pose/update_pose/rename_pose/delete_pose/apply_pose_and_keyframe`; pose-library `apply_pose/delete_pose` |
| `test_keyframes.py` | `molecule.keyframe_protein/select_keyframe/edit_keyframe/delete_keyframe`, `jump_to_keyframe` — asserts real F-curves (4.x/5.x shim) |
| `test_animation.py` | keyframe-selection filter (`get_keyframe_targets`/`get_filtered_keyframe_targets`), `keyframe_select_all/none_puppets` |
| `test_puppets.py` | `create_puppet`, `edit_puppet` (RENAME + EDIT membership change), `delete_puppet`, controller parenting + move, exclusive membership, un-parent on delete |
| `test_linkers.py` | `add_linker`, `update_linker`, `toggle_linker_visibility`, `edit_linker`, `remove_linker`, cascade-delete on puppet/chain/protein removal |
| `test_dna.py` | `build_dna` (ds/ss/RNA, all styles), `randomize_sequence`, `swap_to_complement`, `update_dna_colors/style`, bend `add/set_resolution/toggle/remove` |
| `test_pivot.py` | `set_pivot_first/last/center` (distinct, sensible origins) |
| `test_domain_geometry_invariants.py` | invariants spanning the domain mesh-sharing refactor: setting a pivot never moves atoms, never disturbs siblings, lands on the requested residue, and domains rotate about their pivot; plus alpha-carbon world-position snapshot and the mesh-sharing assertion |
| `test_brownian.py` | `brownian_settings/rebuild/disable/clear_all` (metadata + jitter F-curve keys) |
| `test_membrane.py` | `build_membrane` (all shapes), `resize_membrane`, hole `add/select/remove`, `reset_deform`, `delete_membrane`, per-protein force field |
| `test_outliner.py` | `outliner_select`, `toggle_expand`, `toggle_visibility`, `outliner_item_info`, `toggle_force_fields` |
| `test_panels.py` | all 9 Panels + 2 UILists registered; `poll()` safety |
| `test_split_domain_regression.py` | crash regression: split a domain after duplicate+delete (see below) |

## Behaviour regressions (guard against reintroduction)

- **Duplicating a protein aliased the source's GN tree, so deleting the copy
  broke the original.** `MOLECULE_PB_OT_duplicate_protein` rebuilt modifiers by
  assigning every non-readonly RNA property, and `node_group` is a *pointer* —
  the copy's MolecularNodes modifier ended up aimed at the source's tree. That
  tree is per-molecule state (it holds `Domain_Boolean_Join` / `Domain_Final_Not`
  and a mask pair per domain), so both molecules shared one set of masking nodes.
  Deleting the copy ran `MoleculeWrapper.cleanup()`, which tore the Join/NOT out
  of the tree the original still rendered through, leaving the original's parent
  mesh unmasked and drawn on top of its own domain objects — reported as "the
  copy didn't get deleted, and lots of clipping". Fixed by giving the copy a
  private `node_group.copy()`, and stripping the source's per-domain mask nodes
  from it (the duplicate re-creates every domain against the new molecule, so the
  inherited masks are never reused, keep masking after their domain is deleted,
  and burn join input slots). Guarded by `test_proteins.py::`
  `test_duplicate_gives_copy_its_own_node_group`,
  `test_duplicate_does_not_inherit_source_domain_masks` and
  `test_delete_copy_leaves_original_domain_masking_intact` (all verified to fail
  on the pre-fix code). Note `molecule_wrapper._create_domain_mask_nodes` carries
  a self-heal that rebuilds missing infrastructure — it was a workaround for this
  aliasing, and can be revisited now the root cause is gone.

- **Outliner chain-range fallback raised NameError.** `build_outliner_hierarchy`
  resolves a chain's residue range from `idx_to_label_asym_id_map` first and
  `auth_chain_id_map` second, but the second branch tested a bare `chain_mapping`
  that was never bound in the function, so reaching it raised `NameError`. Every
  caller wraps the rebuild in a broad `except`, so the outliner silently failed to
  build instead of surfacing the error. Fixed to read `molecule.auth_chain_id_map`,
  which is what the branch's own comment says. Guarded by
  `test_outliner.py::test_outliner_chain_range_falls_back_to_auth_chain_id_map`
  (verified to fail on the pre-fix code).

- **Failed domain merge crashed with UnboundLocalError.** In
  `PROTEINBLENDER_OT_merge_domains`, `covers_entire_chain` was bound only inside
  `if created_domain_ids:`; the `else` branch reported "Failed to create merged
  domain" and then fell through to `if affected_groups and covers_entire_chain:`.
  Any failed merge whose domains belonged to a puppet raised `UnboundLocalError`.
  Fixed to report and return `{'CANCELLED'}`. Guarded by
  `test_domains.py::test_merge_domains_cancels_cleanly_when_creation_fails`
  (verified to fail on the pre-fix code — note the assertion inspects the printed
  traceback, because Blender surfaces `report({'ERROR'})` as `RuntimeError` either
  way and the message alone cannot distinguish a clean refusal from a crash).

- **Save/load wiped every persisted field but keyframes and poses.**
  `scene_manager._refresh_molecule_ui` preserved only `keyframes` and `poses`,
  then cleared `scene.molecule_list_items` and rebuilt each row writing just
  `identifier` and `object_ptr`. Everything else was reset: `object_name` to
  `""`, both JSON blobs to `"{}"`, `style` back to `cartoon`, the `domains`
  collection and the outliner's chain rows dropped entirely. A panel draw
  triggered the sync, so merely looking at the addon after loading degraded the
  molecule; the next save then persisted the cleared values. Fixed by snapshotting
  and restoring the full persistent field set. Guarded by
  `roundtrip/test_saveload.py::test_saveload_roundtrip`.

- **Domains never reached the .blend.** `_create_domain_with_params` added the
  domain to the runtime `MoleculeWrapper.domains` dict but never mirrored it into
  `MoleculeListItem.domains`, the CollectionProperty Blender actually saves. The
  panel showed domains the file did not contain, so on reload every custom
  colour, name, residue range, split and copy was rebuilt from raw chain
  attributes and lost. Fixed by `_mirror_domains_to_property_group`, called at the
  end of each domain CRUD operation. Guarded by
  `roundtrip/test_saveload.py::test_saveload_roundtrip`.

- **Duplicate fabricated a spurious 0-0 domain.** Copying a freshly imported
  protein via the PB Outliner produced a copy whose first chain gained an extra
  degenerate `0-0` domain (read as "Chain A split into two"), because the
  duplicate path copied each domain through `create_domain`
  (`auto_fill_chain=True`) instead of replicating it verbatim. Fixed to call
  `_create_domain_with_params(..., auto_fill_chain=False)`. Guarded by
  `test_proteins.py::test_duplicate_preserves_domain_structure` (verified to
  fail on the pre-fix code).

- **Membrane build crashed on Blender 5.2 (Random Value socket order).** The
  membrane GN builder addressed the Random Value node's float/int Min/Max/Value
  sockets by positional index (`inputs[2]`/`[3]`, `inputs[4]`/`[5]`,
  `outputs[1]`/`[2]`). Blender 5.2 reordered them (a `NodeSocketInt` now sits at
  index 2), so building any membrane raised
  `TypeError: NodeSocketInt.default_value expected an int type, not float` and
  every membrane operation failed. Fixed by addressing those sockets by
  identity (name + `.type`) via `_socket_by_type`, which is stable across all of
  Blender 5.x. Guarded by all of `test_membrane.py` (10 tests build a membrane;
  verified to fail on the pre-fix code on 5.2 and pass after).

- **`molecule.create_domain` crashed on a partial chain range.**
  `MoleculeWrapper.create_domain` returns a **list** of ids (the requested
  domain plus any auto-filled fillers), but the operator treated it as a single
  id — `if domain_id in molecule.domains:` hashed the list and raised
  `TypeError` on any partial-range domain. Fixed in `domain_operators.py` by
  normalizing the return and focusing the first (requested) id. Guarded by
  `test_domains.py::test_create_custom_range_domain`.

- **`molecule.update_domain_color` crashed, then dropped the colour.** It read
  `scene.domain_color`, which is never registered (only `scene.temp_domain_color`
  is), raising `AttributeError`; and it stored the live operator RNA-property
  array, which reverts to the operator default once `execute()` returns. Fixed
  in `domain_operators.py` to read `scene.temp_domain_color` and snapshot the
  colour to a plain tuple before applying it. Guarded by
  `test_domains.py::test_update_domain_color_operator_applies_color`.

## Crash regressions (guard against reintroduction)

- **Split domain after duplicate → delete → crash.** Splitting a domain after
  duplicating a molecule and deleting the copy dereferenced stale cached node
  pointers in `molecule_wrapper._create_domain_mask_nodes` — a hard native
  crash on Blender 5.1, a `KeyError: "Result" not found` on 5.0. Fixed by
  re-resolving the domain-mask infrastructure nodes by name at use time
  (`_refresh_domain_node_refs`) and rebuilding the infrastructure if the copy's
  deletion tore it out of the shared node group. Guarded by
  `test_split_domain_regression.py` (both the real workflow and a deterministic
  stale-pointer trigger). Verified to fail on the pre-fix code on both 5.0/5.1.

## Bugs this suite surfaced (now fixed - see Behaviour regressions above)

None outstanding. The two `create_domain` / `update_domain_color` bugs this
suite originally surfaced as xfails are fixed and are now normal passing tests,
documented under "Behaviour regressions (guard against reintroduction)".

## Modal-dialog operators driven via their execute() path

These operators are modal `invoke_props_dialog`s, but `invoke()` only fills a
settable operator property that `execute()` reads, so they are driven headless
by passing that state directly (no dialog needed):

- `proteinblender.create_keyframe` — `invoke()` fills the `puppet_items`
  `CollectionProperty`; the test passes those rows via `bpy.ops` and asserts the
  puppet controller is keyframed (`test_keyframes.py::test_create_keyframe_keys_puppet_controller`).
- `edit_puppet` (EDIT membership) — `invoke()` fills the `item_selections` dialog
  collection; for scripted use `execute()` now also accepts a `member_ids`
  string, so the test drives a membership change directly
  (`test_puppets.py::test_edit_puppet_membership_change_via_member_ids`).

## Intentional xfails (design, not bugs)

- `proteinblender.create_pose` — modal dialog whose selection state is *plain
  Python* built in `invoke()` (`self.available_puppets` / `self.selected_puppets`),
  so `bpy.ops` can't set it and the wrapper can't be `execute()`-driven without a
  refactor. Its pose-creation logic is already fully covered by
  `molecule.create_pose`, so no refactor is warranted.

## Not reachable headless (skipped)

- `set_pivot_custom` — spawns an interactive gizmo Empty and finalizes through a
  user-driven depsgraph deselection handler; needs a human, not just a screen.
  (Its stated `context.screen.areas is None` reason is stale — screen is present
  headless on 5.2 — but it remains genuinely interactive.)
- Panel `poll()` — 8 of 9 panels define no `poll` of their own (nothing to
  test); `PROTEINBLENDER_PT_domain_maker`'s poll is exercised.
- Edit-mode operators (`dna_edit_bend`/`dna_finish_bend_edit`,
  `membrane_edit_deform`/`membrane_finish_deform`) degrade to a skip if
  headless mode-switching fails; their non-edit siblings are asserted.
- `draw()` for panels — no window/screen exists in `--background`, so panels
  are checked via registration + `poll`, not rendering.

## Deliberately not covered

- **Undo/redo** — the prior audit (ISSUE-1) established addon operations don't
  fully reverse through Blender's undo stack; driving it from a script is
  unreliable. Confirm interactively in a fresh session.
- **Visual/pixel regression** — the `geo_snapshot` fixture + `snapshot_ext.py`
  are wired for syrupy geometry snapshots, but no image-diff baselines are
  committed yet. Add per-feature geometry snapshots as styles stabilize.
