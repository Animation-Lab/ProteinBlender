# Test coverage map

What the suite exercises, per subsystem, and the known gaps. Regenerate the
numbers by running `python tests/run_tests.py -q`.

Current status (Blender 5.2, offline lane): **269 passing, 9 skipped,
1 xfailed**, no failures. The single xfail is intentional (a
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
| live | `tests/live/` | a real, open, windowed Blender observed through its 3D viewport, over the BlenderMCP socket |

## Live lane (`tests/live/`)

The only lane that runs *outside* Blender: system Python attaches to a Blender
the developer already has open and drives it over the BlenderMCP socket. Run it
with `python tests/run_live_tests.py`; it skips when nothing is listening, and
`PB_LIVE_REQUIRED=1` turns that skip into a failure. Full guide in
[live/README.md](live/README.md).

It exists for the three things `--background` structurally cannot do:

- **See the viewport.** Captures are OpenGL renders of the actual 3D view in the
  user's shading mode, not a Cycles render through a camera the test invented.
- **See colour.** Every pixel assertion elsewhere in the suite reduces a render
  to an alpha mask (`px[:, 3] > 0.01`) and discards RGB, so a domain drawn in the
  wrong colour, or every domain drawn identically, is invisible to it.
- **Exercise the deployed add-on** in a normal Blender profile, which is the
  configuration CLAUDE.md requires a change to be proven in.

| module | what it observes |
|--------|------------------|
| `test_live_harness.py` | the lane itself: connection, remote tracebacks, scene isolation, and the calibration that an *empty* scene captures zero covered pixels |
| `test_live_proteins.py` | import across all four fixtures, one domain per chain (ground truth parsed from the PDB text), duplicate, hide/restore, centre, delete chain, delete, all six styles distinct and reversible |
| `test_live_domains.py` | split / merge / copy / rename / restyle / reparent / reset-transform / delete, each checked against the render as well as the state |
| `test_live_pivots.py` | the invariant with real bug history: setting a pivot must not change what is rendered, while rotation about it must |
| `test_live_visual_color.py` | the colour lane: `visual_setup_color` reaching the render, selection scoping, several colours coexisting, per-style distinctness |
| `test_live_dna.py` | DNA/RNA build, both windings, all five styles, sequence ops, per-base colours, bend rig |
| `test_live_membrane.py` | all shapes and render styles, resize, density/thickness, holes, deform reset, delete, colours, force fields |
| `test_live_puppets_poses.py` | puppet structure and membership, pose round trips that must re-converge on screen |
| `test_live_animation.py` | keyframes and real F-curves, frame scrubbing that must visibly change the viewport, Brownian bake/reproducibility |
| `test_live_linkers.py` | linker geometry, styles, behaviours, visibility, cascade deletes, and that a linker renders at all |
| `test_live_outliner_ui.py` | outliner hierarchy and selection, visibility reaching the renderer, and all nine panels registered with `poll()` accepting a real window |

Caveat: DNA, membranes, linkers and puppet controllers are never rendered
anywhere in the headless suite, so their appearance was entirely unasserted
before this lane.

### What the lane found on its first run

119 passed, 34 failed. The failures were not 34 independent defects; they
clustered into a few causes. Fixed since, each guarded by the test that caught
it:

- **Membranes rendered nothing, then rendered wrongly (20 failures).** Three
  separate Blender-5.2 defects, written up below.
- **`molecule.toggle_domain_expanded` hard-crashed Blender** with
  `EXCEPTION_STACK_OVERFLOW`. A clamp callback wrote a value the property's own
  `min=1` forbade, so it re-fired forever. Expanding a domain row in the
  outliner took the whole application down.

Still open, with red tests in the tree:

- **Domain visual updates do not reach the render.**
  `molecule.update_domain_color` and `molecule.update_domain_style` both leave
  the image byte-identical while updating their model state. The molecule-level
  equivalents (`scene.visual_setup_color`, `scene.molecule_style`) work, which
  is what makes the domain-level pair look like one shared defect.
- **Membrane holes and force fields** (`test_a_hole_removes_covered_geometry`,
  `test_a_bigger_hole_removes_more_lipids`,
  `test_a_protein_force_field_parts_the_lipids_around_it`). These paths write GN
  inputs that never once succeeded on 5.2 before the `gn_compat` fix, so they
  have effectively never run on this Blender version. Untriaged.
- **Brownian bake and frame scrubbing, two pivot snap operators, puppet and pose
  round trips, the "Multiple" style sentinel, delete-domain coverage.**
  Untriaged; several assert the same "a change must reach the render" shape as
  the confirmed defects above and may share a cause.

#### Membrane: three separate defects, all fixed

Membranes rendered nothing on Blender 5.2 while working on 5.1, and once they
rendered they were not bilayers. Three distinct causes, all found by looking at
the viewport rather than at state.

**1. No lipids at all.** Blender 5.2 removed IDProperty support from
`NodesModifier`, so `mod["Socket_2"] = value` raises `TypeError`. Both membrane
call sites wrapped that write in a bare `except: pass`, so every modifier input
write failed silently: `Lipid Collection` never bound, Collection Info fed
Instance on Points an empty collection, and the build reported success while
producing no bilayer. 5.1 and earlier still accept the IDProperty form, which is
exactly why the bug was version-specific. Fixed by `membrane_builder/gn_compat.py`,
which writes through `mod.properties.inputs[id]["value"]` on 5.2, falls back to
`mod[id]` for 4.2-5.1, and **raises rather than swallowing** - silent failure is
what let this ship.

Note the trap inside the trap: `mod.properties.inputs[id]` is an
`IDPropertyGroup` for *every* socket type, datablock sockets included. Assigning
a Collection onto the mapping instead of into `["value"]` reads back convincingly
as the collection and then hangs the process on the next depsgraph evaluation.

**2. Every lipid mis-oriented.** `Capture Attribute` gained a `Selection` socket
at index 1 in 5.2, and the normal capture was addressed positionally. The surface
Normal was therefore written into `Selection` and `Selection` was read back as
the normal - a boolean, which Blender broadcasts into a vector as `(1, 1, 1)`.
Every lipid aligned to that diagonal at exactly `arccos(1/sqrt(3))` = 54.7356
degrees with zero variance, and the half-thickness offset scaled along the same
diagonal, shearing the leaflets sideways and opening a void. Fixed by addressing
the socket by the name the code itself assigns (`captured_normal`);
`GN_TREE_VERSION` bumped to 32 so saved membranes rebuild.

This is the third positional-socket-index bug in this file (Random Value, the
modifier interface, now Capture Attribute). **Address geometry-node sockets by
name or identity, never by index.**

**3. A visible seam down the midplane.** The thickness slider was redefined from
origin-to-origin to outer-to-outer and defaulted to 5.0 nm, but the SURFACE lipid
mesh runs ~0.80 nm above its origin and only 1.25-1.65 nm below, so two leaflets
cannot span 5.0 nm with their tails still touching. Measured across the range:
4.8 nm leaves a 0.08 nm gap (solid hydrophobic core), 5.0 nm opens it to 0.28 nm
and reads as a seam. Default changed to 4.8, which also reproduces the 1.6 nm
half-offset the builder used before the redefinition.

Guarded by `test_live_membrane.py`: lipids perpendicular to the plane (naming the
54.7 degree signature), leaflets opposing each other, leaflets stacked rather than
laterally sheared, thickness matching the slider with the midplane closed, and
colour reaching rendered pixels. Gap assertions use the **median** tail tip, not
the extreme - the variants differ in length, so a global min/max reported 0.06 nm
on a membrane whose typical gap was 0.28 nm.

- **Remaining failures are untriaged** (Brownian bake and frame scrubbing,
  two pivot snap operators, puppet controller and pose round trips, the
  "Multiple" style sentinel, delete-domain coverage). Several assert the same
  "a change must reach the render" shape as the confirmed bugs above, so they
  may share a cause; others may be first-run calibration. Only the protein and
  domain modules have been calibrated against a real run.

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
| `test_proteins.py` | `molecule.import_protein` (network) / offline import, `change_style` across all styles, duplicate, toggle_visibility, center_protein, delete, delete_chain, auto-domain count, critical-attribute import abort + non-critical degrade |
| `test_domains.py` | `create_domain`, `update_domain_name`, `rename_domain`, `update_domain_color/style`, `copy_domain`, `split_domain` (both idnames), `merge_domains`, set/update parent, `reset_domain_transform`, `snap_pivot_to_residue`, `toggle_domain_expanded` |
| `test_poses.py` | `molecule.create_pose/apply_pose/update_pose/rename_pose/delete_pose/apply_pose_and_keyframe`; pose-library `apply_pose/delete_pose` |
| `test_keyframes.py` | `molecule.keyframe_protein/select_keyframe/edit_keyframe/delete_keyframe`, `jump_to_keyframe` — asserts real F-curves (4.x/5.x shim) |
| `test_animation.py` | keyframe-selection filter (`get_keyframe_targets`/`get_filtered_keyframe_targets`), `keyframe_select_all/none_puppets` |
| `test_puppets.py` | `create_puppet`, `edit_puppet` (RENAME + EDIT membership change), `delete_puppet`, controller parenting + move, exclusive membership, un-parent on delete |
| `test_linkers.py` | `add_linker`, `update_linker`, `toggle_linker_visibility`, `edit_linker`, `remove_linker`, cascade-delete on puppet/chain/protein removal |
| `test_dna.py` | `build_dna` (ds/ss/RNA, all styles), `randomize_sequence`, `swap_to_complement`, `update_dna_colors/style`, bend `add/set_resolution/toggle/remove` |
| `test_pivot.py` | `set_pivot_first/last/center` (distinct, sensible origins); a full-chain domain's default pivot is its centre of mass; First/Center/Last move the origin and land on the selected chain's N-term/centroid/C-term |
| `test_rendering.py` | that an imported molecule actually draws: the geometry path from Group Input to Group Output survives import, pivot changes and style swaps (style-independent), plus a real Cycles render asserting non-zero pixel coverage |
| `test_domain_geometry_invariants.py` | invariants spanning the domain mesh-sharing refactor: setting a pivot never moves what is rendered (pixel render) and never writes to mesh data, First/Center/Last land on PDB-derived residues (biotite ground truth), the pivot input matches the raw first-residue coordinate, domains rotate about a fixed origin, rendered coverage stays in-band, and the mesh-sharing assertion. Ground truth is kept independent of the pivot code under test |
| `test_brownian.py` | `brownian_settings/rebuild/disable/clear_all` (metadata + jitter F-curve keys) |
| `test_membrane.py` | `build_membrane` (all shapes), `resize_membrane`, hole `add/select/remove`, `reset_deform`, `delete_membrane`, per-protein force field |
| `test_outliner.py` | `outliner_select`, `toggle_expand`, `toggle_visibility`, `outliner_item_info`, `toggle_force_fields` |
| `test_panels.py` | all 9 Panels + 2 UILists registered; `poll()` safety |
| `test_split_domain_regression.py` | crash regression: split a domain after duplicate+delete (see below) |

## Behaviour regressions (guard against reintroduction)

- **"Set Pivot Last" landed in the centre of the chain, not the C-terminus.**
  A bound metal ion whose atom name is "CA" (a calcium ion - element Ca, e.g.
  the Ca(2+) in actin, 1ATN chain A res 373) was flagged `is_alpha_carbon`,
  because the (locally modified) MolecularNodes `att_is_alpha` matched any atom
  named "CA". The ion sits in the centre of the protein and carries the highest
  res_id in its chain, so "Set Pivot Last" (max-res_id alpha carbon) landed on
  it - dead centre - instead of the real C-terminus (res 372, out at the
  periphery). It also spliced the ion into the cartoon/backbone spline. Fixed in
  `att_is_alpha`: require `struc.filter_amino_acids(array)` as well as the name,
  which drops ions and ligands while keeping modified residues (1ATN's HIC at
  res 73 stays). This is a vendored-MolecularNodes edit; note it for the
  4.2.10 -> 4.5.x sync. Guarded by
  `test_pivot.py::test_calcium_ion_is_not_counted_as_an_alpha_carbon` (reads the
  mesh attributes directly) and
  `::test_set_pivot_last_lands_on_the_terminus_not_the_center` (asserts Last is
  off-centre) - both verified red pre-fix, using ground truth independent of the
  pivot operators' own helpers.

- **A full chain's default pivot landed on its first residue, so "Set Pivot
  First" looked like a no-op.** Select a chain, click Set Pivot First - nothing
  moves, because the pivot is already there. Two independent causes in the
  initial-pivot setup (`molecule_wrapper._create_domain_with_params`): (1) an
  off-by-one - `chain_residue_ranges` can report a chain min of 0, but auto-
  created domains are normalised to start at 1, so the `is_full_chain` test
  failed for such chains and they were pivoted at the start residue instead of
  the centre of mass; (2) `_calculate_center_of_mass` never actually filtered by
  chain - it compared the mesh's integer `chain_id` attribute against a chain
  *letter*, never matched, and fell back to the bounding-box centre of the shared
  full mesh (the same wrong point for every chain). It only appeared to work
  before because it read the *evaluated* mesh, which is masked to one chain, so
  the bbox happened to bound the right atoms. Fixed by normalising the chain min
  the same way domain creation does, and by resolving the chain letter to its
  integer index via `obj["chain_ids"]`; `_calculate_center_of_mass` now reads the
  *raw* mesh (deterministic, unmasked) and returns the true per-chain centroid.
  Guarded by `test_pivot.py::test_full_chain_domain_default_pivot_is_center_of_mass`
  and `::test_first_center_last_move_the_pivot_and_land_correctly` (both verified
  red pre-fix). The alpha-carbon world-position snapshot was re-baselined once:
  import centring now uses the true atom centroid rather than the centroid of the
  style spheres, a small rigid shift of the whole molecule (geometry, overlap and
  rendering are unchanged - the other 19 geometry/render tests still pass).

- **Duplicating a protein and then splitting a chain on the copy moved that
  chain.** The two proteins overlapped perfectly until a chain was split on the
  copy, at which point the split chain jumped (~0.39 units on 1ATN). Two causes,
  both in the copy's *parent* pivot, which is masked out of the render and so was
  invisible until a split created a domain that inherited it: (1) the pivot lives
  as a geometry-nodes modifier input value, which the duplicate operator's
  RNA-property copy loop does not carry, so the copy's parent defaulted to a zero
  pivot; (2) the duplicate then re-centred the copy via `center_protein` *after*
  its domains existed, and `center_protein` moves only the parent, desyncing it
  from the already-placed domains. Fixed by copying the source parent's pivot
  onto the copy (`domain_space.copy_pivot`) and removing the redundant, harmful
  re-center - a duplicate is an exact overlay of the source and needs no
  re-centring. Import is unaffected because it centres the parent *before*
  creating domains, so they are born consistent. Guarded by
  `test_split_domain_regression.py::test_split_on_a_copy_does_not_move_the_split_chain`
  and `::test_parent_pivot_matches_its_domains` (both verified red pre-fix). The
  latter asserts the general invariant - a molecule's parent and its domains must
  render the same atom at the same world position - so the class is caught at its
  source, not only via this one workflow.

- **Every imported molecule rendered nothing.** The pivot's Transform node was
  wired to its own geometry input, so the atoms never entered the tree:
  `Group Input.Atoms` fed nothing and the viewport stayed empty while the
  molecule appeared normally in the PB Outliner. Reported against 1ATN; it
  affected *every* structure and every style. Root cause: `ensure_pivot_input`
  decided which links to move behind the Transform with
  `if link.to_node is not transform`. **Blender returns a fresh `bpy_struct`
  wrapper on every attribute access, so `is` compares Python wrapper identity,
  not node identity** - it was always True, so on any tree where the pivot was
  already wired the Transform's own input was collected as "downstream" and
  relinked to the Transform's own output, clobbering the real source. Fixed by
  comparing node *names* (`bpy_struct` implements `__eq__` for data identity;
  `is` does not). **Never use `is`/`is not` to compare bpy structs.** Guarded by
  the new `test_rendering.py` lane, verified to fail on the pre-fix code (6 of 7
  red).

  **Why 234 passing tests missed it:** every test asserted on raw mesh
  coordinates, pivot maths and world positions - none checked that a node tree
  emits geometry. The obvious check does not work either:
  `bpy.data.meshes.new_from_object` and evaluated `dimensions` both report zero
  for a *healthy* molecule, because the default Style Spheres emits a point
  cloud rather than a mesh. Measuring either way looked identical before and
  after the break. `test_rendering.py` therefore asserts on tree topology (the
  geometry path from Group Input to Group Output, style-independent) plus a real
  Cycles render at 96x96/1 sample counting covered pixels - which cleanly
  separated broken (0 px) from known-good (48 px).

- **Every domain deep-copied the whole molecule's mesh.** `core/domain.py` did
  `self.object.data = parent_obj.data.copy()`, so a domain covering 5% of a
  protein still stored 100% of the atoms - even though it masks itself down to a
  residue range inside geometry nodes, which is what actually makes it render.
  Import auto-creates one domain per chain, so stored atoms scaled as
  `(1 + n_chains) x n_atoms`: measured 5.0x on 4hhb (4558 atoms -> 22798 stored
  across 5 datablocks), and 61x on a 60-chain capsid. The copy existed solely to
  serve pivots: `bpy.ops.object.origin_set` moves an origin by rewriting mesh
  vertices (verified: 100% of 13674 coordinates), which on a shared datablock
  reaches every sharer while only the active object's origin compensates, so the
  siblings jump. Fixed by moving the pivot onto the geometry-nodes modifier
  (`core/domain_space.py`) and then sharing the datablock - now 1.0x. Guarded by
  `test_domain_geometry_invariants.py`, in particular
  `test_setting_a_pivot_never_writes_to_mesh_data` (the precondition; verified to
  fail on the pre-fix code) and `test_pivot_does_not_disturb_sibling_domains`
  (the symptom). **If the pivot ever regresses to mutating mesh data, the mesh
  sharing must be reverted with it** - the two are load-bearing for each other.
  Note `obj.matrix_world @ co` is no longer the local->world mapping for molecule
  objects; use `domain_space.local_to_world`. Coordinates read from an
  *evaluated* object already have the pivot applied and must not be re-mapped.

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

- **Split-domain dialog cancellation violated Blender's callback contract.**
  Its `cancel()` returned `{'CANCELLED'}`, which causes an RNA callback error
  when a real user presses Escape. The foreground UI lane reproduced it; the
  callback now returns `None` as Blender requires.
- **Undo left newly created domains in the Python singleton.** Blender restored
  the PropertyGroup rows and objects, but the still-valid molecule wrapper kept
  its pre-undo domain dictionary. The undo handler now refreshes existing
  wrappers from Blender's undo-aware rows, guarded by the foreground domain
  create/undo/redo scenario.
- **The UI runner accepted a failed report.** It searched for any literal
  `"ok": true`, which matched successful individual steps even when the
  top-level result was false. It now parses JSON and checks the root result.
- **Artifact tests inherited the developer profile.** The first implementation
  used a nonexistent umbrella environment override and then discarded enabled
  preferences with `--factory-startup`. It now isolates Blender's actual config,
  scripts, datafiles, and extension directories and preserves the install step's
  enabled state for smoke testing.
- **Protein Blender workspace existed with no visible add-on panels.** Workspace
  creation closed editors through stale Blender 5.2 `Area` handles and aborted
  with `Area not found in screen`; reuse then returned without binding any
  screen or editor references. Workspace activation also selects its screen
  asynchronously, so the Scene context was applied to the previous Layout
  screen. Setup now preserves existing editors, repairs existing workspaces,
  and reapplies Scene context after the real screen switch settles. The
  foreground lane now selects the actual Protein Blender workspace and asserts
  that its own Properties editor is in Scene context before requesting redraw.
- **Split-domain pivots used the whole chain instead of the domain range.** A
  selected 1ATN domain spanning residues 1-50 placed Last on chain residue 372;
  Center was likewise the full-chain centroid. Domain objects share the full
  raw molecule mesh and are visually masked by Geometry Nodes, so chain-only
  filtering was insufficient. Pivot targets now include the outliner domain's
  inclusive start/end bounds, and each selected target receives its own pivot.
  `test_split_domains_first_center_last_respect_domain_residue_ranges` splits
  1ATN exactly this way and validates First, Center, and Last for both resulting
  domains against independently parsed PDB C-alpha coordinates.

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

## Known issues surfaced but not fixed here

- **`pdb_model_num` and `entity_id` fail to write on every PDB import.**
  `_create_object` builds them from `array.pdb_model_num` / `array.entity_id`,
  which a PDB-sourced biotite `AtomArray` simply does not carry, so both raise
  `AttributeError` on every single `.pdb` import. This was invisible until the
  attribute writer stopped swallowing failures - it now logs one WARNING apiece.
  Consequence: MolecularNodes' `Select Entity_` node has no attribute to read for
  PDB-format structures. ProteinBlender does not use entity selection, so nothing
  in the add-on is broken by it today. The real fix belongs upstream (default the
  annotation when the array lacks it) and should be picked up with the
  4.2.10 -> 4.5.x sync rather than patched into the vendored copy.

## Cross-lane coverage outside background pytest

- **Undo/redo** — the foreground event-loop lane creates a partial domain,
  performs undo and redo, drives the add-on reconstruction path, and asserts
  runtime domain state after both transitions. Extend that scenario list for
  every new stateful UI workflow.
- **UI and modal context** — the foreground lane forces all ProteinBlender
  panels through real redraws, invokes and cancels pose/puppet dialogs via
  synthetic window events, finalizes a custom pivot through its deselection
  handler, and enters/exits DNA and membrane edit modes.
- **Installed package** — the artifact lane validates and installs the built
  ZIP in an isolated repository, rejects source imports, checks bundled binary
  dependencies, imports a molecule, and reopens its `.blend` in a second
  process.
- **Visual regression** — Cycles tests assert nonempty pixels and distinct
  masks for cartoon, spheres, and surface styles. This catches blank output and
  ignored style wiring without imposing device-fragile byte-exact PNGs.
