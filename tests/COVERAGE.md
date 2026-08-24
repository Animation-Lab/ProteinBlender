# Test coverage map

What the suite exercises, per subsystem, and the known gaps. Regenerate the
numbers by running `python tests/run_tests.py -q`.

Current status (offline lane): **441 passing, 7 skipped, 1 xfailed**, no
failures, re-run on Blender 5.0, 5.1 and 5.2. The single xfail is intentional
(a modal-dialog operator unreachable headless - see below), not a bug. The
foreground UI lane (`python tests/run_ui_tests.py`) is green at 36 scenarios.

## Lanes

| lane | dir | what it proves |
|------|-----|----------------|
| unit | `tests/unit/` | pure logic (chain maths, DNA sequence, base geometry, catenary physics) with no scene |
| integration | `tests/integration/` | every registered subsystem operator, driven headless against a real scene |
| roundtrip | `tests/roundtrip/` | save → reopen (fresh Blender) → **whole scene** identical, plus contracts that keep it exhaustive |
| smoke | `tests/test_harness_smoke.py` | the harness itself (register, reset isolation, import) |
| live | `tests/live/` | a real, open, windowed Blender observed through its 3D viewport, over the BlenderMCP socket |

## Save/load lane (`tests/roundtrip/`)

Save/load is the hardest thing to get useful bug reports about - a tester who
reopens a file and finds their work subtly wrong usually cannot say what
changed. The lane is therefore built to answer three questions on its own:
*did anything change*, *exactly which field*, and *is the check still complete*.

### How it works

| file | role |
|------|------|
| `_snapshot.py` | whole-scene serializer, driven by walking RNA rather than by a list of fields |
| `_diff.py` | path-precise structural diff (`scene.molecule_list_items[4hhb].chain_custom_names: '…' -> ''`) |
| `_builders.py` | one builder per subsystem, each asserting it really created the state |
| `_verify.py` | subprocess that reopens the .blend and runs the **real** file-load lifecycle |
| `test_saveload.py` | the cases: 17 builders x round trip, 3 x second generation, 2 x render |
| `test_persistence_contract.py` | the contracts that keep all of the above exhaustive |

**The comparison is whole-scene and generic.** Every property of every
PropertyGroup, every object transform, custom property, modifier input,
geometry-node link, F-curve keyframe *value*, material node value, mesh/curve/
lattice digest and the runtime molecule registry. Because the serializer walks
`bl_rna.properties` instead of naming fields, a property added to the add-on
next year is covered the day it is added.

**It runs the load path, not the undo path.** The .blend must be opened before
the add-on registers (`wm.open_mainfile` after registration raises
EXCEPTION_STACK_OVERFLOW on 5.0/5.1 and hangs indefinitely on 5.2 - measured,
killed after 9 minutes), so `load_post` never fires on its own. `_verify.py`
runs the whole handler chain by hand and then pumps the deferred bodies those
handlers schedule (`registry_reconstruct`, `linker_rebuild`,
`force_field_reapply`), because `bpy.app.timers` never ticks in `--background`.
The previous implementation instead called `sync_molecule_list_after_undo`,
which is registered on `undo_post`/`redo_post` and *only* there - so the lane
reported on file loading while exercising undo. `create_workspace_on_load` is
the one handler still skipped; it builds UI, terminates only under a real event
loop, and is covered by the foreground-ui lane.

**Nothing is waived silently.** Reviewed tolerances live in
`test_saveload.IGNORED`, snapshot exclusions in `_snapshot.EXCLUSIONS`, skipped
handlers in `_verify.SKIPPED_HANDLERS` - each keyed to a written reason, each
capped in size, all asserted by the contract tests.

### What keeps it exhaustive

`test_persistence_contract.py` fails the build when the lane stops being
complete, rather than when save/load breaks:

- every `bpy.types.Scene` / `bpy.types.Object` property the add-on registers is
  snapshotted or excluded with a reason (parsed from the add-on's own source);
- no covered name refers to a property that no longer exists;
- the RNA walk demonstrably reaches every field of every live PropertyGroup;
- every `bpy.app.timers` body is pumped by the verifier or declared
  not-load-related;
- every package that persists state has a builder that creates some;
- the verifier does not regress to driving the undo path, and importing it does
  not run it.

### Falsifiability

Two checks stop the lane from being decorative:

- `test_the_comparison_detects_a_planted_change` plants six changes (a reset
  scalar, a dropped collection, a moved object, an emptied registry, a rewired
  geometry-node link, a renamed collection member) and requires each to be
  reported, with its path in the message.
- Verified by sabotage: reintroducing the historical
  `_mirror_domains_to_property_group` bug (domains never reaching the .blend)
  turns 5 of the 7 selected cases red, including both second-generation cases.
  Builders assert their own state before the save, so a builder that silently
  fails cannot round-trip an empty scene and report a pass.

### Cases

18 builders: `empty`, `single_protein`, `multi_chain`, `domains`,
`chain_rename`, `chain_copy`, `pivots`, `keyframes`, `poses`, `pose_library`,
`puppets`, `linkers`, `dna`, `membrane`, `force_fields`, `brownian`,
`visual_style`, `kitchen_sink`. Three of them also run a **second generation**
(save → reopen → save → reopen, compared against the original expectation),
which is the only shape that catches the original data-loss bug's real
mechanism: the reload degraded state and the *next save* persisted it. Two run
a **Cycles render after reload**, because state assertions cannot see a node
tree that reloaded subtly rewired.

Whole lane: 34 tests, ~2m30s on Blender 5.2.

### Known gaps

- No corpus of `.blend` files written by *previous releases*, so the migration
  paths (`GN_TREE_VERSION` membrane rebuild, the bend-curve `hide_render`
  backfill) are exercised only against files this version wrote.
- No cross-version round trip (save on 5.0, open on 5.2).
- The deferred load passes are invoked directly rather than by a real timer
  tick; only the live lane can observe them firing on their own.

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
exactly why the bug was version-specific. Fixed by `utils/gn_compat.py`
(originally under `membrane_builder/`; promoted to `utils/` so `core` can share
it - see the pivot regression below),
which writes through `mod.properties.inputs[id]["value"]` on 5.2, falls back to
`mod[id]` for 4.2-5.1, and **raises rather than swallowing** - silent failure is
what let this ship.

#### Pivots: the same version split, the other way round (fixed)

Every pivot / domain-geometry / protein-centering / rendering test that touched
a pivot failed on Blender 5.0 and 5.1 (16 tests) while passing on 5.2 - the
mirror of the membrane bug. `core/domain_space.py` read and wrote the `Pivot`
modifier input through `mod.properties.inputs[...]` **only** (the 5.2 API), which
does not exist on 5.0/5.1, so `set_pivot_local` returned False, the snap-pivot
operators cancelled, and pivots stayed at the origin. Fixed by routing both the
read and the write through the shared `gn_compat` helpers (relocated
`membrane_builder/gn_compat.py` -> `utils/gn_compat.py`, since `core` must not
depend on a feature package). Verified: the 16 failures go green on 5.0 and 5.1
and 5.2 stays green. These tests are the regression guard - they were red on
5.0/5.1 before the fix.

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
| `test_membrane.py` | `build_membrane` (all shapes), `resize_membrane`, hole `add/select/remove`, `reset_deform`, `delete_membrane`, per-protein force field (through the protein's edit dialog) |
| `test_outliner.py` | `outliner_select` (including that it reaches the viewport when there is no UI area to redraw), `toggle_expand`, `toggle_visibility`, `outliner_item_info`, the protein row's force-field toggle, and chain rows listing their domains in residue order rather than creation order |
| `test_visual_edit_dialogs.py` | the per-item Visual Set-up dialogs and Edit Pivot mode: colour and style reaching every object a protein owns, a call that sets one field leaving the others alone, rename+recolour in one pass, a protein's pivot being one shared point that lands on PDB-derived termini, `item_id` not leaking into the selection, and the Edit Pivot session: the helper starting on the current pivot, the second click applying where it was left without moving the atoms, a protein sharing one hand-placed pivot, a preset abandoning an open session, a second row committing the first, a deleted helper ending the session, and the mode owning the viewport while it is open - the helper the only selectable object, a user's own selection lock left alone, and nothing selected in the viewport or ticked in the outliner once it closes; and what a dialog opens *showing*: the seed read across every object that draws the item (never the molecule object, whose untouched carbon grey is on no screen), grey plus a flag when the parts disagree on colour, "Multiple" when they disagree on style, and the real value once they agree |
| `test_panels.py` | all 8 Panels + 2 UILists registered; `poll()` safety |
| `test_delete_last_chain_deletes_protein.py` | deleting the last chain/domain of a protein deletes the protein itself, cascading to its puppets, poses and linkers; it does not fire while any chain or sibling domain survives |
| `test_biological_assembly.py` | BIOMT/mmCIF assembly parsing: both parsers returning the one documented dict contract, PDB transforms matching the fixture's own `REMARK 350` text, a non-identity rotation surviving with its orientation intact, building the assembly end to end from either format, and mmCIF being the download default |
| `test_symmetry_realize_cutaway.py` | realizing copies into real objects (one per extra copy per source, independently selectable, sharing their atom data, landing exactly where their instances were, and the instanced assembly cleared so nothing is drawn twice) with ChimeraX's over-threshold refusal unless forced; and the cutaway (copies in front of the plane removed, the offset moving the plane, the original cut like any other copy, a degenerate normal keeping everything) |
| `test_symmetry_axes.py` | recovering an assembly's symmetry axes from its operators and drawing them: a Cn having one axis whose fold comes from the *smallest* rotation, a Dn having one n-fold plus n perpendicular two-folds (group theory, computed in the test), a tilted axis recovered as asked for, a deposited assembly's three-fold, axis objects being renderable meshes rather than empties and pointing the right way (checked by transforming their own local Z, not by reading back the quaternion set), rebuilds replacing rather than accumulating, and deletion of the protein taking its axes with it |
| `test_symmetry_filtering.py` | trimming an assembly to a legible patch (ChimeraX's `range` / `contact`): which copies of a ring survive a cutoff, checked against `2r sin(k pi/n)` computed in the test; the identity always surviving; both limits behaving as Angstrom rather than Blender units; a filament too spread out to touch anywhere; and the panel's limits reaching a real build |
| `test_symmetry_builder.py` | generative symmetry (Cn, Dn, helical): the operators themselves against trigonometry done in the test, an off-origin centre staying fixed, a tilted axis staying invariant, copies placed on a real ring at `2r sin(pi/n)`, a filament climbing by exactly its rise along whichever axis was asked for, generated copies inheriting the assemble/disassemble factor, either kind of build replacing the other, and the cubic groups being refused rather than guessed |
| `test_assembly_build.py` | building *and animating* a deposited assembly inside ProteinBlender: which assemblies a structure offers, identity-only ones being withheld, the Symmetry panel polling itself away without symmetry, one instance placed per `REMARK 350` operator *on the domain objects* (measured from the depsgraph and from rendered pixels, not the node graph), clear restoring the asymmetric unit exactly, rebuilds not stacking, the build/clear/keyframe operators, and the assemble/disassemble animation: factor 0 returning every copy exactly onto the asymmetric unit, factor 1 reproducing the deposited placement, intermediate factors matching the file's own operator rotated part-way about its own axis, per-copy monotonic travel, stagger putting copies at different stages mid-animation, the factor surviving as keyframes, coexistence with Brownian jitter on a puppet over the same protein, and deleting the protein taking its assembly datablocks with it |
| `test_split_domain_regression.py` | crash regression: split a domain after duplicate+delete (see below) |
| `test_domain_splitter.py` | the Domain Splitter dialog and the `core.domain_layout` reconcile engine: even-split arithmetic, layout validation/coverage gaps, boundary re-tiling, the grid's line numbering (edge lines counted like any other line, and the header's count agreeing with them), the ghost-everything preview's ghost/solid/restore cycle, per-domain colours (live preview and commit, via the dialog rows or `layout_json`'s `color` field), and the identity-preservation invariants a layout edit must hold (see below) |
| `test_copy_chain.py` | `molecule.copy_chain` from the outliner's chain row: a split chain copying every one of its domains (residue coverage against the PDB text, and a Cycles render proving the copy puts as much protein on screen as the chain it copied), the copy appearing as one expandable chain row rather than leaking into its source chain, an unsplit chain still copying as a single domain, copying a copy, and the copy's Delete removing all of it and nothing else |
| `test_outliner_colors.py` | the PB Outliner's row colour swatches: seeding from what each item renders with (node graph as ground truth), the mixed-grey placeholder for a protein whose chains disagree, and a pick on a protein/chain/domain row recolouring exactly what that row covers |

## Behaviour regressions (guard against reintroduction)

- **The PB Outliner listed a chain's domains in creation order.**
  `build_outliner_hierarchy` walked `molecule.domains` (a dict, so insertion
  ordered) and emitted the rows as it found them, so a chain carved up
  back-to-front listed its last domain first and stayed that way. The rows are
  now sorted by start residue, which is the order the chain itself has.
  Guarded by `test_outliner.py::test_chain_domain_rows_are_ordered_by_residue`,
  which submits a deliberately out-of-order layout through the Domain Maker and
  expects the residue numbers written in the test.

- **Copying a split chain copied only its first domain.**
  The outliner's chain row wired Copy to `molecule.copy_domain` with the
  chain's *primary* domain id, so a chain split into 1-99 / 100-198 copied as
  1-99 alone - and, no longer spanning the whole chain, the half-copy was
  auto-parented to the original and listed as an extra domain row *inside* the
  chain it came from. A chain copy is now a group: `molecule.copy_chain`
  duplicates every domain of the chain, each keeping its own range, colour and
  style, tied together by a `copy_group_id` that the outliner reads to show
  them under one expandable chain row (`chain_utils.chain_copy_groups`). The
  same grouping carries Delete, the colour swatch, selection sync and rename,
  and the copy identity is persisted on the `Domain` PropertyGroup - the only
  part of a domain that reaches the .blend - so a reloaded copy stays a copy
  instead of folding back into its source chain.
  Guarded by `test_copy_chain.py` (7 tests) and the `chain_copy` save/load
  builder. Ground truth for "the entire chain" is parsed from `4hhb.pdb`
  directly (chain A spans author residues 1-198), never from
  `chain_residue_ranges`, and the pixel test renders the copy against the
  chain it copied.

- **Edit dialogs opened showing the wrong colour and style.**
  The Visual Set-up block seeded its fields from `objects[0]`, which for a
  protein is the *molecule object*. That object is written to but is no
  witness: it keeps its own untouched Color Common node, whose carbon grey
  (0.202) appears on no screen, and after a per-domain recolour or restyle its
  style is stale too. A freshly imported 4hhb - four chains in four distinct
  colours - therefore opened showing one dark grey, which looked like a correct
  "mixed" answer while being an accident of reading the wrong object. Reading
  the first *domain* instead would have been just as wrong in the other
  direction: one chain's colour presented as if it spoke for all four.
  `appearance_objects_for_row` now returns what actually draws the item (a
  protein's domains, falling back to the molecule object only when it has
  none), and `seed_from_objects` reads across all of them: agreement gives the
  real value, disagreement gives `MIXED_COLOR` grey with a note for colour and
  the existing empty "Multiple" entry for style. Neither placeholder is ever
  applied on the way out, because `commit_visual_edit` only writes fields that
  differ from what they were seeded with.
  Guarded by `test_visual_edit_dialogs.py::test_protein_with_differently_colored_chains_seeds_grey`,
  `::test_protein_seeding_ignores_the_molecule_object`,
  `::test_protein_seeds_the_real_color_once_its_chains_agree`,
  `::test_style_seeds_multiple_only_when_the_parts_disagree` and
  `::test_each_chain_seeds_its_own_color_not_a_siblings`. Ground truth is each
  object's own Color Common **Carbon socket**, read straight off the node -
  not `get_object_color`, which is the reader the seeding goes through and
  would pass whichever object it picked. Verified red by mutating
  `seed_from_objects` back to "first object, never mixed".
  Seeding only happens in `invoke()`, which headless never runs, so the wiring
  from invoke to the live fields is covered in the foreground UI lane
  (`invoke_and_cancel_protein_visuals_dialog` asserts the open dialog's
  `vs_color`, `vs_color_is_mixed` and `vs_style`).

- **Moving a protein's pivot translated the whole protein.**
  Every chain domain is *parented* to its molecule object, and a child's world
  transform is `parent.matrix_world @ matrix_parent_inverse @ basis`. So when
  `domain_space.set_pivot_world` rehomed the molecule object's origin, it
  dragged every domain by the same vector - the pivot moved and the molecule
  followed it across the scene. Reported from the UI: import 1atn, Edit Pivot
  on the protein row, drag X, click again, and the protein has translated
  instead of just its pivot. `set_pivot_world` now captures each direct child's
  world matrix and writes it back after rehoming the parent, which re-derives
  the child's basis and leaves it exactly where it was.
  A second defect sat on top: the protein row wrote its pivot onto every domain
  as well as the molecule object, which was both redundant (the domains are
  parented, so the protein already rotates as one about that origin) and
  destructive (it silently overwrote whatever pivot the user had set on each
  domain from its own row). `row_pivot_objects` now narrows a PROTEIN row to
  the molecule object, while `row_objects` - what colour and style use - still
  covers every domain.
  Guarded by `test_visual_edit_dialogs.py::test_edit_pivot_on_a_protein_moves_the_pivot_not_the_protein`,
  whose ground truth is Blender's *renderer* (`H.render_coverage` pixel
  coverage before vs after), the only witness that cannot move with the bug -
  `matrix_world` and the GN Pivot input are rewritten together, so the add-on's
  own `local_to_world` would report "nothing moved" either way. Verified red at
  93 changed pixels via `git stash push -- proteinblender/core/domain_space.py`.
  The pivot-clobbering half is guarded by
  `::test_protein_pivot_moves_only_the_molecule_object` and
  `::test_edit_pivot_on_a_protein_moves_only_the_molecule_object`, both verified
  red by mutating `row_pivot_objects` back to the wide set.

- **Edit Pivot let the viewport steal the gizmo, and left the outliner ticked.**
  Reported from the UI: while the pivot helper is on screen the Move gizmo
  keeps switching between the pivot and the protein, and after the session the
  molecule is still ticked in the Protein Outliner.
  One omission behind both. The mode deselected everything on the way in but
  never stopped anything being *re*-selected, and the molecule is exactly what
  is sitting under the cursor: a click aimed at the helper lands on the
  protein, Blender moves the selection - and therefore the gizmo - onto it, and
  the next drag slides the whole molecule instead of placing the pivot. The
  same stray click ticks that row via the selection-sync poll, and nothing
  cleared it when the session closed.
  Fixed by making Edit Pivot own the viewport for as long as it is open:
  `_lock_scene_selection` makes the helper the only selectable object (only
  objects it actually locked are unlocked again, so a user's own lock
  survives), and `end_pivot_edit` leaves nothing selected - clearing the
  outliner rows directly rather than waiting on the 0.2 s poll, which does not
  run headless at all.
  The mode was also keeping what it borrowed: it switched the active tool to
  Move and forced `show_gizmo_object_translate` on, and restored neither, so a
  user who entered with the Rotate tool came out with Move and every protein
  they selected afterwards wore a translate gizmo it never had. `_borrow_viewport`
  now records the tool and each viewport's gizmo flags, and `end_pivot_edit`
  hands them back alongside the 3D cursor and transform orientation it already
  restored.
  Guarded by `test_visual_edit_dialogs.py::test_edit_pivot_makes_the_helper_the_only_selectable_object`
  (ground truth is Blender's own `object.select_all(action='SELECT')` - if the
  molecule comes back selected, a user's click would have selected it too),
  `::test_edit_pivot_leaves_the_outliner_deselected`, and
  and `::test_edit_pivot_returns_objects_the_user_had_locked_still_locked`
  (the one test here that cannot be red pre-fix - there was no lock to unlock
  selectively; it exists so a future "unlock everything" shortcut fails). The
  tool and gizmo restore needs a real window, so it is guarded in the
  foreground UI lane (`tests/ui/run_ui_scenarios.py`,
  `edit_pivot_second_click_applies_and_closes`). The other three were verified
  red pre-fix - the outliner one on `['4hhb'] stayed ticked`, the selection one
  on the molecule and all four chain objects coming back selected, and the UI
  one on `left the active tool at builtin.move`.

- **"Snap Protein Pivot to Center" put the centre outside the protein.**
  `snap_protein_pivot_center` averaged `obj.matrix_world @ corner` over
  `obj.bound_box`, with a comment claiming `bound_box` was evaluated geometry
  and therefore already pivot-applied. It is not: it is the *raw* mesh's
  bounds, and a molecule object has no evaluated bounds of its own to borrow -
  it evaluates to an **empty** point cloud, because the atoms are drawn by its
  chain domains. Raw bounds mapped with `matrix_world` are off by exactly the
  pivot (CLAUDE.md's first silent-failure rule), which on 1ubq put the "centre"
  at x = 0.305 for a molecule spanning [-0.150, +0.150] - twice its half-width
  outside itself. Fixed by mapping the corners with
  `domain_space.local_to_world`.
  It survived because the only assertion on it was that the result was
  *finite*. Now guarded by
  `test_operator_surface.py::test_snap_parent_pivot_center_lands_inside_the_molecule`
  and its live twin, both measuring Blender's own evaluated point-cloud atoms
  (`helpers.evaluated_atom_positions`) rather than anything the add-on derives.
  Verified red pre-fix with that exact 0.305-vs-0.150 signature in both lanes.
  The new helper also replaces `eval_positions` for molecular objects, where
  `to_mesh()` returns zero vertices and reductions over the empty array raised
  instead of failing an assertion - which is how the live test that should have
  caught this had been dying before it asserted anything.

- **`outliner_select` never reached the viewport without a UI area.**
  Its redraw tail called `context.area.tag_redraw()` unguarded, and that tail
  sits *before* the `sync_outliner_to_blender_selection` call - so for any
  caller with no area (a script, an MCP session, the headless suite) the
  operator threw halfway through and the row ticked without the object ever
  being selected. The suite had been documenting this as a headless caveat and
  swallowing the `RuntimeError`. Guarded by
  `test_outliner.py::test_outliner_select_reaches_the_viewport_without_an_area`,
  which asserts on `Object.select_get()` rather than the row flag (the flag is
  set before the throw, so it passes with the bug in place). Verified red
  pre-fix via `git stash push -- proteinblender/panels/protein_outliner_panel.py`.

- **A renamed chain was wiped by the first undo.**
  `scene_manager._refresh_molecule_ui` rebuilds `scene.molecule_list_items` by
  snapshotting every persistent field, clearing the collection, and writing the
  snapshot back. `chain_custom_names` was added later, by the chain-rename
  feature, and was never added to `_snapshot_list_item` - so it was reset to
  `""` on every rebuild. That JSON map is the only home a chain name has (chain
  rows are regenerated from `auth_chain_id_map` on every outliner rebuild), so
  the rename was gone the first time the user pressed Ctrl+Z. This is the exact
  shape of the documented "Save/load wiped every persisted field" regression
  below, reintroduced for one field by a later feature.
  Only `sync_molecule_list_after_undo` reaches that function, so **save/load was
  never affected** - a renamed chain survives save and reopen. The bug was found
  while auditing the round-trip lane precisely because the old verifier called
  the undo handler in place of the load path.
  Fixed by carrying `chain_custom_names` through `_snapshot_list_item` /
  `_restore_list_item`. Guarded by
  `test_rename_chain_domain.py::test_rename_chain_survives_the_undo_redo_reconstruction`
  (ground truth is the literal string the test set; verified red pre-fix -
  the stored map came back `{}` and the row reverted to "Chain A").

- **Renaming a chain or domain left its outliner tooltip quoting the old name.**
  `rename_domain` wrote the new label onto every matching row but not onto
  `row.tooltip`, which is pre-rendered and only regenerated by
  `build_outliner_hierarchy`. The row read "Alpha Globin" while hovering it
  still said "Chain: Chain A", until some unrelated action happened to rebuild
  the outliner and it silently corrected itself.
  Found by the save/load round-trip lane: the reopened file (which rebuilds the
  outliner on load) disagreed with the live scene, and the reopened one was
  right. Fixed by rebuilding the outliner at the end of the operator - the
  rename is already persisted to the model at that point, so the rebuild
  re-derives the new name rather than reverting it. Guarded by
  `test_rename_chain_domain.py::test_rename_chain_updates_the_row_tooltip_not_just_its_label`.

- **The save/load lane reported on the file-load path while exercising undo.**
  `roundtrip/_verify.py` reopened the .blend and then called
  `sync_molecule_list_after_undo` to "drive the same reconstruction the panel
  does on first draw after load". That function is registered on `undo_post` and
  `redo_post` and nowhere else; no panel calls it, and it is not a load handler.
  None of the ten `load_post` handlers a real File > Open runs had ever executed
  in a test, and the three that defer their real work to `bpy.app.timers`
  (registry rebuild, linker rebuild, force-field re-apply) were doubly
  unreachable, since timers never tick in `--background`.
  Fixed by `_verify.simulate_file_load`, which runs the real handler chain and
  then pumps the deferred bodies. Guarded by
  `test_persistence_contract.py::test_the_verifier_does_not_drive_the_undo_path_instead_of_the_load_path`
  and `::test_every_deferred_load_pass_is_pumped_by_the_verifier`.
  See the "Save/load lane" section above for the rest of the rebuild.

- **A linker with an endpoint on a split chain was silently never created.**
  Reported: import 1atn, make a domain on chain A, puppet the chain, Create Linker with the chain as an endpoint -> nothing appears (log: `No object found for item ..._chain_0`, then `Could not find residue A:1`).
  Root cause: once a chain is split into domains its CHAIN outliner row owns no object (`object_name == ''`) by design - the residues live in the domain objects. `linker_geometry.get_residue_position_from_item` bailed the moment the chain's own object was missing (no fallback), so `add_linker` reported "Could not find residue" and `return {'CANCELLED'}` before creating anything. Pre-existing on `alpha`.
  Fixed by `_objects_for_item` / `_resolve_residue`: when a CHAIN row has no object, resolve residues via its DOMAIN children's objects. Backbone-direction resolution (`get_backbone_object_for_item`) was routed the same way at all four call sites (add/edit/handler/update) so rigid zones still align.
  Guarded by `test_linkers.py::test_split_chain_endpoint_resolves_residue_via_domain_objects` (chain-row resolution must match the independent domain-row path; verified red - returned `None` pre-fix).

- **The random-coil linker looked like a jagged EKG trace / a regular telephone-cord spiral.**
  The old `compute_random_coil_points` summed a few sine waves and bisected their amplitude to hit the arc length; the result had sharp cusps (turning >70 deg between control points) and an obviously periodic silhouette (tester feedback via Janet: wanted "gently rounding curves, but not regular spirals").
  Rebuilt as a "confused fly" wander: the path leaves the straight chord by two channels of smooth band-limited (low-pass) noise in the perpendicular plane, with a steady handedness precession for coil character; an envelope pins both endpoints and the offset amplitude is solved for the arc length. Fully vectorised (no per-step Python loop) so it still rebuilds every linker every frame in ~0.3 ms.
  `RANDOM_COIL` is now the default behaviour.
  Guarded by `test_linker_geometry.py::test_random_coil_turns_are_gently_rounded_not_jagged` (max turn <45 deg on a moderate-slack linker; the old code cusped at ~75 deg, verified red) plus `_is_three_dimensional_not_a_flat_ribbon`, `_endpoints_exact_and_absorbs_slack`, `_deterministic_for_seed`, and `_taut_is_straight`.

- **The random-coil linker corkscrewed as the endpoints moved.**
  Tester report: moving the two connected chunks closer/further made the coil wind up and unwind, as if the ends were twisting - unnatural. Cause: the loop count was `(L - D) / (2*pi*coil_width)`, i.e. a function of the endpoint distance `D`, and it drove the precession angle, so changing `D` changed the number of turns. Fixed by making the loop count a *fixed* property of the linker (`COIL_REST_SLACK * L / (2*pi*coil_width)`, anchored to a half-slack resting pose); moving the endpoints now only breathes the offset amplitude, like a spring at a fixed turn count.
  Guarded by `test_linker_geometry.py::test_random_coil_winding_is_distance_invariant_no_corkscrew` (total angle swept around the chord axis must match at two endpoint distances; verified red - it scaled ~2x with distance pre-fix).

- **The random-coil linker flipped 180 deg as an endpoint orbited the other.**
  Tester report: swinging one connected chunk around the other (clock-hand motion) made the coil suddenly flip at one position. Cause: the perpendicular frame the coil wraps was built from a fixed world axis (`cross(direction, Z)`), which vanishes and reverses when the chord points along world Z - so a vertical orbit flipped the coil there. A frame field on the sphere must have one singularity (hairy-ball), so it cannot be removed, only relocated. Fixed by capturing the linker's rest chord direction (`rest_direction`, set once at creation) and rotation-transporting a canonical frame from it (`_transport_perp_axes`); the singularity now sits at the pose 180 deg opposite the rest pose, which ordinary animation never reaches.
  Guarded by `test_linker_geometry.py::test_random_coil_frame_does_not_flip_when_endpoints_orbit` (sweeping the chord through +Z, consecutive coils must differ by only the endpoint's small motion; the fixed-axis frame jumped ~12x more, verified red at 0.23 vs 0.02 BU).

- **The DNA/RNA builder (HELIX mode) produced geometrically wrong helices: a torn backbone and mispaired bases.**
  The old builder extracted single residues from one crystal (1BNA), re-centred each on its own C1' (`_extract_one`: `t.coord -= c1_pos` plus a de-rotation by only the C1' azimuth), then stamped them onto an idealised 36°/3.38 Å screw. Re-centring discards each residue's helical-frame Z position and base orientation, so no uniform screw can reconnect the sugar-phosphate backbone. Measured on a 12-mer: O3'(i)->P(i+1) averaged 2.56 Å on strand A and 4.56 Å on strand B (up to 8.68 Å) versus the real 1.60 Å covalent bond, and only 1/12 bases paired with their true Watson-Crick complement (strands collapsed to ~7.5 Å C1'-C1' vs the canonical ~10.5). The prior "Alpha 1.0.6 pairing fix" only held for the palindromic 1BNA sequence, not a general one.
  Fixed by replacing the HELIX path with a canonical **fiber-diffraction / screw-transform** generator (`sequence_builder._build_fiber_helix` + vendored `fiber_data.py`, a BSD-licensed transcription of AmberTools NAB `fd_helix.c`). Each residue is one fiber repeat unit in helix-frame cylindrical coordinates, replicated by a rigid screw (rotate by twist, translate by rise); the antisense strand mirrors phi/z (`hxmul = ∓1`). Backbone continuity and Watson-Crick pairing then hold by construction. B-DNA, A-DNA, and A-RNA supported (`helix_form` prop; RNA is always A-form). LADDER mode (stylised, intentionally non-atomic) is unchanged. Helix axis stays +Z so the bend rig is unaffected.
  Guarded by `tests/unit/test_dna_geometry.py`, which asserts against ground truth independent of the builder: O3'->P = 1.6 ± 0.1 Å on both strands, WC-partner C1'-C1' in [9.5, 11.5] Å, purine-N1/pyrimidine-N3 H-bond < 3.2 Å, measured rise/twist == published fiber constants (B 3.38/36.0, A 2.56/32.7, A-RNA 2.81/32.7), no bond > 2.0 Å, and `struc.filter_nucleotides` all True (MN's cartoon gate). Verified red on the pre-fix builder (O3'->P up to 8.68 Å); port matches reference `fd_helix.c` output to 0.0007 Å, and B-DNA/A-DNA/A-RNA render as proper double helices (cartoon + ball-and-stick) in Blender 5.2.

- **The DNA bend rig floated above the strand: control nodes sat half a helix too high, and dragging one deformed the wrong slice.**
  Reported (manager, playing with the DNA tool): "the deformers aren't aligned with the structure - they're shifted up relative to the DNA structure".
  Cause: `bender` built the rig from raw `mesh.vertices` z values, but a molecule's geometry-nodes pivot is applied inside the MolecularNodes modifier, so the strand renders at `matrix_world @ (co - pivot)` (see `core/domain_space`, and the CLAUDE.md rule this broke).
  On a 16-mer the pivot is the centre of mass, so the curve, its bezier points and every control node were offset by half the helix length; because the Curve modifier runs *after* the node tree, the deformation was misaligned by the same amount and pulling the top node did nothing to the top of the strand.
  Fixed by moving the origin with the pivot instead of rewriting mesh data (`shift_origin_to_bottom` / `restore_origin_to_centre` now call `domain_space.set_pivot_world`) and by measuring the strand in pivot-applied space (`_strand_z_extent` replaces `_mesh_z_extent`).
  Guarded by `test_dna.py::test_dna_bend_nodes_align_with_the_strand`, `::test_dna_bend_deforms_the_half_of_the_strand_its_node_owns` and `::test_dna_bend_nodes_stay_aligned_after_a_sequence_edit`; ground truth is the *evaluated* strand's world-space extent, which no bender code contributes to.
  Verified red pre-fix (bottom node 0.266 BU off a 0.587 BU strand; pulling the top node moved the top by exactly 0).

- **The add-on failed to load on Windows when a bundled wheel was only partially extracted.**
  Blender's extension installer occasionally extracts a bundled wheel WITHOUT its sibling `<pkg>.libs` folder - the OpenBLAS (scipy) / Arrow (pandas/pyarrow) DLLs, which are not listed in the wheel's RECORD.
  The package then imports at top level but its compiled submodules raise `ImportError: DLL load failed` (e.g. `scipy.linalg._fblas`), so scipy / MDAnalysis / starfile break; `_can_import_core_packages()` returns False, the daily cache blocks a pip retry, and even a retry into user-site is shadowed by the broken `.local`, leaving the add-on dead with an unhelpful "Dependencies failed to install".
  Root-caused live on Blender 5.2: the installed alpha extension's `.local` had scipy and pandas each missing only their large `.libs` DLL (a 0-byte leftover `.whl` in site-packages confirmed a partial/interrupted extraction); a direct test of Blender's `wheel_manager` proved it extracts `.libs` correctly when it runs cleanly, so the corruption is an intermittent Windows extraction failure, not a repo/wheel defect (the bundled scipy wheel does carry its 20 MB openblas DLL).
  Fixed by `__init__._repair_partial_wheels` (core `_restore_missing_libs`), which - before importing any compiled dep - re-extracts just the missing `.libs` members from the matching bundled wheel into the site-packages that has the partial install. Offline, deterministic, idempotent (no-op once healthy), and not rate-limited by the dependency cache.
  Guarded by `tests/unit/test_wheel_repair.py` (synthetic wheels as independent ground truth: restores the exact DLL bytes, leaves a healthy install untouched, respects the Python ABI tag, skips uninstalled packages). Verified end-to-end on real Blender 5.2: a broken `.local` that previously failed to load now self-heals and the pivot flow returns FINISHED.

- **Every pivot operator was broken on Blender 5.1 and earlier (5.0, 4.2): all returned `CANCELLED`.**
  Blender 5.2 replaced the long-standing geometry-nodes modifier-input subscript (`modifier[identifier]`) with a typed `modifier.properties.inputs` interface; on 5.1 the subscript is the only API and `modifier.properties` does not exist.
  `core/domain_space.set_pivot_local` / `get_pivot` used only `getattr(mod.properties.inputs, identifier).value`, so on 5.1 `set_pivot_local` raised `AttributeError` (caught -> returned False) and every First/Center/Last/Snap/Center-protein operator cancelled with "Could not find alpha carbons" / "No valid objects".
  Root-caused live on Blender 5.1: alpha carbons were found (76 for 1ubq chain A) but `domain_space.set_pivot_world` returned False because `mod.properties` is absent there; a minimal modifier probe confirmed `mod[identifier]` works on 5.1 and raises "id properties not supported" on 5.2, the mirror image.
  Fixed by routing `domain_space` reads/writes through the shared `utils/gn_compat.py` (the same 5.2-vs-4.2/5.1 split the membrane builder already relied on; it was promoted from `membrane_builder/` to `utils/` so `core` could share it instead of duplicating the version logic).
  This is exactly why the pivot/domain-geometry/rendering suite showed 16 failures on 5.1 and none on 5.2; the headless `source-suite` CI matrix omitted 5.1 (now added: 4.2/5.0/5.1/5.2).
  Guarded by the existing `tests/integration/test_pivot.py`, `test_domain_geometry_invariants.py`, `test_domains.py::test_snap_pivot_to_residue`, `test_operator_surface.py::test_snap_parent_pivot_center_is_finite`, `test_proteins.py::test_center_protein_moves_to_origin`, and `test_rendering.py` pivot cases; verified red on 5.1 pre-fix (16 failed) and green post-fix (276 passed, 0 failed).

- **The Protein Blender workspace loaded a stock "Scene Collection" Outliner above the Protein Outliner.**
  The workspace is built by duplicating Blender's default "Layout", whose right column is an Outliner editor stacked above Properties.
  `set_properties_context` switched Properties to Scene context (where the Protein Outliner panel renders) but nothing removed the Outliner editor, so users saw the stock Scene-Collection tree sitting directly above the Protein Outliner.
  The area-closing loop that used to strip non-viewport editors had been deleted because closing areas from a captured collection crashes on Blender 5.2 ("Area not found in screen" - each `area_close` invalidates the remaining Area handles); the deletion over-corrected and kept *all* editors.
  Fixed by `workspace_setup._close_extra_editors`, which closes every editor outside the canonical set (VIEW_3D / PROPERTIES / DOPESHEET / TIMELINE) one at a time, re-reading `screen.areas` after each close and bounding the loop by the area count, then re-resolving the managed area handles.
  Reproduced identically on Blender 5.0, 5.1 and 5.2 - not version-specific; the sole workspace-layout job ran only on 5.2 and never asserted the Outliner was absent.
  Guarded by `tests/ui/run_ui_scenarios.py::verify_workspace_ui` (asserts no OUTLINER editor and nothing stacked above the panel column), now run by the `foreground-ui` CI job across Blender 5.0/5.1/5.2; verified red pre-fix with "still shows a stock Outliner editor (1 found)".

- **A linker could not connect two domains of a chain when the puppet was made from the chain.**
  Reported workflow: import 1atn, split chain A into domains 1-50 / 51-end, create a puppet from *Chain A* (the natural action, not selecting the two domain rows), then Create Linker.
  The endpoint dropdown is built by `linker_operators._build_chain_items_for_puppet`, which listed one entry per puppet member.
  A chain-with-domains puppet has the chain as its single member, so both endpoints defaulted to it and `add_linker` failed with "Start and end must be different chains".
  Fixed by expanding a chain member into its DOMAIN children when the chain has been split into two or more domains, so the domains become the linkable endpoints (linkers attach to the domain objects).
  An unsplit chain (whose whole-chain auto-domain has no separate DOMAIN row) is unchanged, and puppeting the domain rows directly already worked.
  Guarded by `test_linkers.py::test_split_chain_puppet_exposes_domains_as_linker_endpoints` (endpoint list must equal the two domain ids taken from the molecule model) and `test_add_linker_between_two_domains_of_split_chain_puppet` (the full create flow); both verified red pre-fix.

- **Splitting a chain AFTER it was puppeted left the split pieces behind - only the un-split chain followed the puppet and got saved into poses.**
  Reported workflow (Janet, Blender 5.2): puppet two chains, split one of them, move things, then build poses from the puppet. Only the chain that was NOT split moved/animated; the split pieces stayed put. Splitting the chains BEFORE making the puppet was fine.
  Two independent root causes. (1) The split deletes the chain's single controller-parented object and creates new piece objects parented to the MOLECULE, never re-parenting them to the puppet controller, so moving the puppet moved only the intact chain (`operators/domain_ops.py`). (2) `panels/pose_library_panel.get_puppet_objects` resolved a chain member's split pieces by matching the chain INDEX ("0") against split-domain keys that use the chain LETTER ("A"), matched nothing, and dropped the split chain from the pose entirely.
  Fixed by re-parenting each new split piece to the puppet controller with keep-transform (mirroring `create_puppet`), and by routing `get_puppet_objects` through the canonical `chain_utils.get_puppet_member_objects` (the same split-aware resolver keyframing and selection sync already use).
  Guarded by `test_split_after_puppet_regression.py::test_split_pieces_follow_the_puppet` (moving the controller moves all 3 objects) and `::test_pose_captures_all_split_pieces` (capture_pose stores every controlled object); ground truth is the raw parent graph, independent of the resolver. Both verified red pre-fix (`assert 1 == 3` - the puppet controlled only one object after the split).

- **Deleting a protein left its puppets' poses in the Protein Pose Library.**
  Reported (Janet, Blender 5.2): after deleting the entire model, the Pose Library still listed poses for puppets/proteins that no longer existed. The outliner rebuild dropped the orphaned PUPPET rows but nothing scrubbed `scene.pose_library`.
  Fixed by `scene_manager.ProteinBlenderScene._cleanup_orphaned_puppets`, called from `delete_molecule` BEFORE the outliner rebuild (while the puppet rows still resolve): any puppet with no surviving member object is torn down through the normal `delete_puppet` operator (controller Empty, member linkers, pose transforms), then poses left empty are pruned. Puppets still spanning a surviving molecule are untouched.
  Guarded by `test_delete_molecule_cleanup.py::test_delete_molecule_clears_puppets_and_poses`; verified red pre-fix (pose library still had the orphaned pose).

- **Moving/rotating a chain then splitting it snapped the pieces back to the imported pose.**
  Reported (Janet, Blender 5.2): move and rotate a chain in the Domain Maker, split it, and it jumps back to its original location. Cause: each split piece is a fresh copy of the parent MOLECULE object (`domain.create_object_from_parent` sets `matrix_world = molecule.matrix_world`), so it takes the molecule's transform and drops the chain object's move/rotate.
  Fixed in `operators/domain_ops.py` by carrying the split source's world mapping onto the pieces. Because a domain maps a mesh coord as `matrix_world @ (co - pivot)`, the transfer is computed in that render space: `delta = (src_mw @ T(-src_pivot)) @ (ref_mw @ T(-ref_pivot))^-1`, applied as a rigid premultiply AFTER the pivots are set. Computing it in render space (not from `matrix_world` alone) makes it EXACTLY identity when the source already draws its atoms where a fresh piece would - e.g. an unmoved chain, or a chain on a re-centred copy whose `matrix_world` differs but whose rendered position matches - so it only fires for a genuine user move.
  Guarded by `test_split_domain_regression.py::test_split_preserves_a_moved_and_rotated_chain` (every piece must draw atom 0 where the moved chain drew it, `_render_world` as independent ground truth); verified red pre-fix (piece ~13 units away). The existing `test_split_on_a_copy_does_not_move_the_split_chain` guards the identity case against re-introduction.

- **Re-ranging a domain destroyed its puppet membership, linkers, animation and pivot.**
  A domain's id embeds its residue range (`_create_domain_with_params` builds `{molecule}_{chain}_{start}_{end}_{name}`) and its object name embeds the range too (`DomainDefinition.create_object_from_parent`).
  Every downstream consumer keys off one of those two strings - puppet membership and linker endpoints and saved per-molecule poses store the domain id; the scene pose library stores the object name; pose/colour keyframes and the geometry-nodes pivot live on the object itself.
  The only route to "change this domain's range" was delete-and-recreate (`proteinblender.split_domain`), so every one of those references silently went stale: the outliner rebuild pruned the unknown puppet member and, if that emptied the puppet, deleted its controller Empty and the puppet's animation with it.
  Fixed by making a range edit an in-place mutation. `MoleculeWrapper.update_domain_range` keeps the id and the object, retargets only the domain's own `Select Res ID Range` node and the matching parent mask, and re-mirrors to the persisted collection; it replaces the dead, never-called `update_domain`, which re-derived a *different* id scheme (no name suffix) and renamed the object.
  On top of it, `core/domain_layout.py` reconciles a whole desired layout against the chain's current domains: rows carrying a known domain id are updated in place, rows without one are created, and only domains genuinely absent from the layout are deleted (with puppet-membership strip and linker prune, the prune running *after* the outliner rebuild so it resolves against current rows).
  Guarded by `test_domain_splitter.py`: identity (`::test_reranging_keeps_the_domain_id_and_its_object`), animation (`::test_reranging_preserves_per_domain_animation`, evaluated through Blender's own animation data), puppets (`::test_reranging_preserves_puppet_membership_and_controller`, deliberately built from DOMAIN rows because a chain-row puppet's id never moves and would pass even when broken), linkers (`::test_reranging_preserves_linker_endpoints`), cleanup on genuine deletion (`::test_removing_a_domain_strips_it_from_puppet_membership`), persistence (`::test_layout_edit_is_mirrored_into_the_persisted_collection`) and that the geometry actually follows the new range (`::test_domain_geometry_follows_its_range`, measured as rendered pixel coverage because a MolecularNodes style emits instanced geometry and `to_mesh()` reports zero verts for every molecule and domain object).
  All seven verified red against a delete-and-recreate reconcile.

- **The Domain Splitter edits boundaries, not two independent numbers.**
  A layout tiles the chain end to end, so a domain's start *is* the previous domain's end plus one - the same boundary seen from both sides.
  Moving one therefore moves the other (`domain_layout.retile_after_edit`), instead of leaving the user to keep two numbers in sync by hand and failing validation when they do not.
  Two rules keep it sane: a boundary never drags through the neighbour beyond it (the neighbour keeps at least one residue - removing a domain is what Merge and the row's X are for, not a side effect of dragging), and pulling the first domain's start off the beginning of the chain (or the last domain's end off the end) creates a domain to own the residues that would otherwise belong to none.
  The explicit "Build Domains" button is gone: the domain-count field re-divides the chain as it changes, and OK commits.
  Guarded by `test_domain_splitter.py::test_moving_a_start_moves_the_boundary_with_the_domain_above` and `::test_moving_an_end_moves_the_boundary_with_the_domain_below`, `::test_pulling_the_first_start_off_the_chain_creates_a_domain_above` and `::test_pulling_the_last_end_off_the_chain_creates_a_domain_below`, `::test_a_boundary_cannot_swallow_its_neighbour`, `::test_retiling_clamps_to_the_chain_and_never_inverts_a_domain` and `::test_retiling_a_single_full_chain_domain_is_a_no_op`. Every case also asserts the result still tiles the chain exactly.

- **Domains on one chain were named by three different generators, so they disagreed.**
  Reported: splitting a chain gave a first domain named "Chain A: Residues 1-248" and a second named "Domain 1".
  Three places produced a default name and none of them agreed: `_create_domain_with_params` generated `Chain A: 1-248`, the outliner rebuild re-derived display names as `Chain A: Residues 1-248`, and the Domain Splitter dialog used `Domain N` - which the rebuild's auto-name patterns did not recognise, so it was preserved as though the user had typed it.
  Fixed by moving both rules into `chain_utils`: `default_domain_name(chain_id, start, end)` -> `"Chain A: 1-248"` (the wording the user asked for), and `is_default_domain_name(name)`, which recognises every historical auto form (blank, `Residues N-M`, `Chain X`, `Chain X: N-M`, `Chain X: Residues N-M`, `Domain N`). The create path, the dialog and the outliner rebuild all go through them.
  An auto-generated name is re-derived whenever its range changes - on a boundary drag, a merge, a remove, or a re-divide - so it never advertises a span it no longer covers. A name the user typed is never rewritten, including across a re-divide that changes its range.
  Guarded by `test_domain_splitter.py::test_auto_generated_names_name_the_chain_and_the_range`, `::test_every_historical_auto_name_is_recognised_as_auto`, `::test_a_name_the_user_typed_is_never_treated_as_auto`, `::test_split_domains_are_all_named_for_the_chain_and_their_range` and `::test_the_outliner_keeps_a_name_the_user_typed`, plus the live-dialog assertions in `tests/ui/run_ui_scenarios.py::edit_chain_domains_live_boundary_drag`.
  Note `test_domains.py::test_split_domain_default_name_includes_chain_and_residues` now pins `"Chain A: 1-50"`; the expected string is written out in full rather than built with `default_domain_name`, so it cannot silently follow a change to the generator it exists to pin.

- **Changing the Domain Splitter's domain count raised AttributeError and did nothing.**
  `domain_count`'s update callback called `instance.redistribute()` on the ``self`` RNA hands a property update callback. That wrapper does not expose the operator's own **methods** - the same limitation that makes plain class attributes unreachable there - so re-dividing the chain raised `AttributeError: no attribute 'redistribute'` and silently left the rows alone.
  Fixed by routing through `_active()` (the instance published at invoke/draw time), as the row callbacks already did.
  Only reachable through a live modal dialog, so guarded in `tests/ui/run_ui_scenarios.py::edit_chain_domains_live_boundary_drag`.

- **A Domain Splitter boundary edit did not move the neighbour, and the viewport preview did not follow.**
  Reported: "when I adjust a domain's start/end it just snaps back to where it was", and "it doesn't adjust the res_id on-the-fly in the 3d viewer".
  The re-tile was computed in the row's property update callback but *applied* in the operator's `check()`, on the assumption that Blender calls `check()` after any dialog property edit.
  It does not call it for an edit to a **CollectionProperty element** - only for a property directly on the operator - so the re-tiled layout was computed and then never written: the neighbour stayed put and the layout stopped tiling the chain.
  Fixed by writing the re-tiled values immediately, in the update callback. Only *resizing* the row collection is unsafe there (it reallocates the collection Blender is mid-write on), so only the edge-insert case is still deferred to `check()`, and the edited row's own clamped value is applied immediately even then.
  The preview also now drives the **edited domain's own object** rather than always the chain's first domain, so the user watches that domain grow and shrink where it actually sits; switching rows hands the previous object its range back.
  Guarded by `tests/ui/run_ui_scenarios.py::edit_chain_domains_live_boundary_drag`, which drives a **real modal dialog in a foreground Blender** (background Blender routes `INVOKE_DEFAULT` to `execute()`, so there is no live instance to drive and this cannot be covered in the headless lane) and deliberately never calls `check()`.
  Verified red pre-fix: `AssertionError: neighbour did not follow: rows[0].end=66, expected 78`.

- **Dragging the FIRST domain's Start stalled one residue in and left a 1-1 domain behind.**
  Reported: "the start one just snaps to 2 and creates a new domain from 1-1"; the End field of the same domain was fine, because that is an ordinary middle boundary.
  Raising the first Start orphans the residues below it, and the fix for that was to insert a domain in front - which moves the edited row, and every row after it, down by one. Blender's number widget stays bound to *row 0*, so what the user carried on dragging was the domain just inserted ahead of theirs, and that one is pinned to the start of the chain and cannot move at all. The drag died at the first residue.
  It was also non-deterministic: the insert was parked in `_state["pending_layout"]` for `check()` to apply, and Blender does **not** call `check()` for an edit to a CollectionProperty *element* - which is what every row field is. So it landed at whatever unrelated moment `check()` next fired, or never; committing without it silently left a gap.
  Fixed by never adding a row while the dialog is open. The row list may stop short of either end of the chain, `execute` completes it through the new `domain_layout.complete_layout`, and the orphaned stretch is shown as an **adjuster drawn from operator properties** - a grid line above the first row or below the last, with the boundary editable, the chain's own end greyed out, and an editable name. Operator properties cannot be inserted into, so there is nothing for a drag to trip over.
  A debounced timer was tried first and is the wrong shape: a real drag pauses for longer than any sane debounce, so the row landed mid-drag and reintroduced the identical stall (measured: `STALLED at 1  rows: [(1, 1), (2, 66), ...]`). Reverted in 87fb50f. The lesson generalises - **a CollectionProperty row must never be added ahead of a row the user may be dragging, at any time, however it is timed.**
  Guarded by `test_domain_splitter.py::test_complete_layout_*` for the arithmetic (orphaned head, orphaned tail, both ends at once, an interior hole, an already-tiling layout left alone, the degenerate empty layout, no mutation of the caller's list, and the names it invents), plus two foreground scenarios for the interaction, which is the only lane that can reach it since the headless lane never calls the row-element update path at all. `run_ui_scenarios.py::edit_chain_domains_first_start_drag` drags the first Start and asserts it does not stall, that no row is inserted mid-drag, that the head adjuster appears with the right range and drives the boundary both ways, and that a name typed into it reaches the created domain. `::edit_chain_domains_last_end_drag` is the mirror for the tail. Both commit through the live instance's `execute()` rather than `layout_json`, which is taken literally and would prove nothing about the completion, and each runs on its **own** chain: they are the only committing scenarios and the undo scenarios below assume the first chain's domain ordering.
  Both scenarios read `item_id`/`parent_id` into plain values before committing, because `build_outliner_hierarchy` rebuilds `scene.outliner_items` and every `bpy_struct` into it goes stale - the tail scenario failed with `KeyError: ''` until it did.
  Verified red pre-fix: `AssertionError: the drag stalled: rows[0].start reached 1, expected 13`.

- **Sizing a domain ghosts everything else in the viewport, and the ghosting is always undone.**
  Residue numbers alone are a poor way to choose a domain boundary, so while a range is being edited the geometry-nodes residue range is driven live (the same technique `split_domain_popup` uses) and everything except the domain being sized is ghosted - the rest of the chain, the rest of the protein, and every other visible molecule. Only an object with no Style material to swap falls back to being hidden.
  The chain itself stays whole: the domain under the cursor is drawn solid, in the colour its dialog row carries (its own colour until the user picks one - there used to be a fixed gold `HIGHLIGHT_COLOR`, replaced when the rows grew editable colour swatches); its neighbours are shown at the ranges the pending layout gives them but ghosted. Isolating the one domain alone left it floating with nothing to judge a boundary against; ghosting everything around it gives the boundary something to be a boundary *of*.
  Ghosting swaps a material *pointer* on the Style node rather than dialling alpha down in place: every domain of a molecule shares `MN Default`, so editing alpha on it would ghost the whole scene.
  What is swapped in is a **copy of the domain's own material** with its alpha lowered, not a material of our own. The first attempt built a stand-in from scratch - an Attribute node reading `Color` into a fresh Principled BSDF - which reproduced every domain's colour correctly and so looked right in the node graph and in an F12 render, but rendered **effectively opaque in the Material Preview viewport at any alpha**: MolecularNodes shades through its own group node reading the *instancer*, and the stand-in does not reproduce it. Copying the real material changes exactly one thing.
  The copies are swapped back out and deleted when the preview ends, so nothing survives the dialog.
  **Per-surface alpha compounds, and on this geometry it compounds to nothing.** A space-filling chain stacks ~20 sphere surfaces along any view ray and each one blends again, so a ghost at alpha 0.2 still rendered at 68% of its opaque brightness - visibly flat, but not visibly *behind*, which is what "I still don't see it" meant. `show_transparent_back = False` (draw only the surface nearest the camera) is the load-bearing setting: it alone takes the same chain from 68% to 42%, and 0.1 alpha on top lands at 25%. Percentages are mean per-pixel distance from the viewport background over the opaque render's silhouette, measured in a live Material Preview viewport.
  Judge this effect in a **live viewport**, never an F12 render: the isolation uses `hide_viewport`, which Cycles and EEVEE renders ignore, and a from-scratch ghost that renders translucent under F12 can still render opaque in the viewport.
  **Most rows in this dialog have no object.** A chain imports as a *single* domain, so the ordinary way in - open the splitter on a chain, set the count to 3, drag - leaves one row backed by a real object and two backed by nothing; the domains a layout describes are created on OK, long after the preview must draw them. Previewing only the rows that already had objects meant the common path had nothing to ghost at all. Rows without objects are now given throwaway copies of a real chain object (`PB Splitter Preview N`), deleted on restore.
  A copied node group keeps its *group nodes* pointing at the original's sub-trees, so a stand-in shares its `Color Common` tree with the object it was copied from. That makes the tree shared, which is exactly the case this module refuses to write colour into - costing the highlight on the stand-in **and** on the real domain. The colour tree is copied too.
  Every other test in this file splits the chain up front, which hands the preview a full set of objects and hides all of this; `::test_a_chain_that_was_never_split_still_gets_ghosted_context` is the one that exercises the real entry path.
  This is the only part of the dialog that touches the scene *before* the user confirms, so a leak is highly visible - the user would be left looking at a scene missing most of its contents, or at a molecule the dialog silently repainted. The bookkeeping therefore lives on the scene, not the operator instance, so a preview left behind by a dialog that died without closing can be cleared by the next `invoke`; `execute` and `cancel` both restore.
  Guarded by `test_domain_splitter.py::test_preview_ghosts_the_rest_of_the_scene_and_restores_it_afterwards` (ground truth is the visibility flags, material names and node ranges captured *before* previewing - it imports a second protein so "everything" provably includes other molecules - and it also asserts a second preview call does not re-capture the previewed state as the original), `::test_preview_ghosts_the_chain_and_keeps_the_sized_domain_solid` (materials and colours read straight off the node graph, never through the splitter's own accessors), `::test_preview_paints_row_colors_and_restores_the_real_ones`, `::test_the_ghost_is_a_copy_of_the_domains_own_material` (asserts the ghost's node types and links match the real material's, which is the only assertion that catches the opaque-stand-in failure - one about colour or about which material is assigned passes straight through it), `::test_a_new_row_gets_its_own_stand_in_and_leaves_the_real_domains_alone` and `::test_restoring_a_preview_that_was_never_started_is_harmless`.
  Note for future work here: Blender does **not** expose a plain (non-RNA) class attribute through an operator *instance* inside a property update callback - `instance.suspended` raises AttributeError even with `suspended = False` on the class - so the dialog's re-entrancy guard and deferred-layout state are module-level, not class attributes.

- **Re-ranging a domain silently repainted it with a fresh random colour.**
  `_setup_domain_network` looked its colour node up by tree name `== "Color Common"`, but the first setup renames that tree to `Color Common_<domain_id>` to make it unique - so every later re-range found nothing, added a *second* colour node (name-collided to "Color Common.001", and wired in place of the first), rolled a fresh golden-ratio colour for it, and overwrote `domain.color`. Every boundary nudge in the Domain Splitter recoloured both domains at the boundary. Two same-shaped exact-match bugs rode along: `update_domain_color` and the splitter's `_color_sockets` matched the *node* name `== "Color Common"`, so once the ".001" node existed, colour writes silently did nothing.
  Fixed by matching the tree name and node name by prefix (`startswith("Color Common")`) in all three places.
  Guarded by `test_domain_splitter.py::test_a_layout_without_colors_leaves_the_domains_colors_alone` (colour read through the link that actually feeds Set Color, so it keeps reading truth whatever the node is called); verified red pre-fix with the exact signature - a colour-free boundary nudge changed the Head domain's rendered colour.

- **The Domain Maker panel has been removed.**
  It offered Split, Merge and "Edit Domains...", all of which the Domain Splitter does in one place, reached from the pencil button on any chain row in the Protein Outliner. Keeping a second, weaker route to the same model edits was the source of its own bugs - it once drew an entire unreachable block wired to two operator ids that do not exist anywhere (`proteinblender.update_domain_range`, `proteinblender.delete_domain`), which only never raised in front of a user because the branch could not be reached.
  Removed with it: `panels/domain_maker_panel.py`, its `PROTEINBLENDER_PT_domain_maker` registration, and the write-only `Scene.domain_maker_start` / `domain_maker_end` properties (nothing ever read their value - the Protein Outliner's selection handler wrote them and no one consumed them).
  Deliberately *kept*: `PROTEINBLENDER_OT_split_domain_popup` and `PROTEINBLENDER_OT_merge_domains`. Both lose their only UI caller, but the popup is the split entrypoint the whole suite goes through (mandated by `test_repository_contracts.py`) and both remain scriptable and covered; deleting them would have meant deleting live coverage to justify deleting code.

- **Renaming a domain never survived an outliner rebuild, and chains had no rename at all.**
  `build_outliner_hierarchy` unconditionally reset every non-copy DOMAIN row name to `"Residues N-M"`, clobbering any name set via the (UI-less) `rename_domain` operator - so renaming appeared not to work. Chains were regenerated from `auth_chain_id_map` with no custom-name store.
  Fixed by: preserving a user-set domain name in the rebuild (only auto-generated `Residues N-M` / `Chain X` / blank names are normalised); adding a persistent `MoleculeListItem.chain_custom_names` JSON store consulted during the rebuild; generalising `proteinblender.rename_domain` to rename chains too (explicit `target_item_id` + `item_type`); and exposing a Rename (pencil) button on CHAIN and DOMAIN rows in the Protein Outliner.
  Guarded by `test_rename_chain_domain.py` (chain rename persists across rebuild, blank restores the default, domain rename persists on the wrapper) and the existing `test_domains.py::test_rename_domain_updates_wrapper_and_list_item`.
  Relatedly, a split domain's default outliner name now names both the chain and the range ("Chain A: Residues 1-50") instead of the bare "Residues 1-50". The rebuild normalises any auto-generated form (bare residues, "Chain X", "Chain X: N-M") to this canonical name while still preserving a user rename. Guarded by `test_domains.py::test_split_domain_default_name_includes_chain_and_residues`.

- **Linkers were unmakeable on puppets whose chains had been split (and a domain deleted), and defaulted to a residue that didn't exist.**
  Reported (Janet, Blender 5.2): with a puppet built from chains that were split then had one domain deleted, the Add Linker endpoint dropdown listed the split parent chain (Chain A / Chain B) *and* its domain; picking the chain gave "Valid range 1-999" and every create failed with "Could not find residue". Several coupled causes in `linkers/linker_operators.py`:
    - `_build_chain_items_for_puppet` only expanded a chain into its domains at >= 2 domain children; after deleting a sibling piece a split chain had one child, so it listed the parent chain - whose object the split had deleted, so it resolved to no residues. Fixed to expand on >= 1 domain child (a split chain never lists itself; unsplit chains still list as chains).
    - `get_residue_range_for_item` read res_id off the domain's shared whole-molecule mesh and reported the parent chain's span (1-141) instead of the domain's (51-198). Fixed to read the range from the domain model. `get_chain_letter_for_item` likewise now reads the chain letter from the model (the "Chain A: Residues …" display name parsed to "A:").
    - The endpoint residue defaulted to a hard-coded 1. Fixed with endpoint update callbacks + an invoke that snap the residue to the endpoint's first real residue, plus an execute retry that falls back to it instead of erroring.
  Guarded by `test_linker_split_domains.py` (endpoint list offers domains not split chains; domain range is the domain's own; a linker created with no residues lands on a real residue and is valid).
  Follow-up: the endpoint dropdown also listed each domain twice when a puppet's membership held both a split chain AND its domains (selecting the chain cascades to its domain rows), producing duplicate enum identifiers. `_build_chain_items_for_puppet` now de-duplicates by endpoint id. Guarded by `test_linker_split_domains.py::test_endpoint_list_has_no_duplicate_domains`.

- **Random Coil is now the default linker behaviour, and the Coil Width slider actually works.**
  Reported (Janet): Gravity is irrelevant at this scale; Random Coil is the realistic default, but was too spring-like and its Coil Width slider did nothing. `compute_random_coil_points` accepted `coil_width` but never used it. Fixed by scaling the coil cycle count inversely with `coil_width` (wider loops -> fewer coils), defaulting the behaviour to `RANDOM_COIL` and the width to a looser 0.06 (across the add/edit operators and the linker PG). Aesthetic tuning is deliberately left to the now-live slider.
  Guarded by `test_linker_split_domains.py::test_new_linker_defaults_to_random_coil` and `::test_coil_width_actually_changes_the_coil`.
  Follow-up on the coil shape (three reported defects): the discrete-kink generator that preceded this made every kink the same size (a uniform "EKG" ripple), let the coil erupt at the domain surface when the endpoints were close (its straight lead-in was a *parametric* margin that collapsed to nothing in world space as the chord shrank), and flipped the whole coil abruptly when one domain was orbited around the other (the perpendicular frame was `direction x Z` with a hard branch near vertical - a full 90 deg jump in one update). Replaced with a smooth value-noise meander: independent smoothstep value noise on each of the two perpendicular axes (wanders in full 3D, never a flat repeating wave), interior nodes kept off-axis with varied magnitudes (`COIL_NODE_MIN_MAG`) so every loop is a different size and there are no straight mid-coil runs, a squared-smootherstep window (`COIL_END_TAPER`) that zeroes the offset at both ends regardless of endpoint distance, and loop count from residues x Coil Width only (`WAVES_PER_RESIDUE`/`MIN_WAVES`/`MAX_WAVES`) so it is constant during a drag and the shape morphs instead of popping. The perpendicular frame is now parallel-transported from the previous update via an in-memory per-linker cache (`_coil_frame_cache`, keyed by uid, cleared on delete/unregister), so orbiting swings the coil smoothly through vertical; `compute_random_coil_points` stays deterministic when called without a `frame_key` (the pure/test path). Guarded by `tests/unit/test_linker_geometry.py::test_random_coil_shape_is_smooth_and_taper_bounded`, `::test_random_coil_loops_vary_in_size`, `::test_coil_frame_is_continuous_through_vertical`, and `::test_random_coil_leaves_endpoints_straight` (plus the existing endpoint/arc-length, taut-is-straight, deterministic, and never-doubles-back cases).

- **Guard: editing an invalid linker back to a valid residue re-attaches it.**
  Reported (Janet, Blender 5.2) as a linker that stayed detached after being fixed. On the current code the edit path restores `is_valid` (the coil-width property callback re-runs `update_linker_curve` once endpoints are valid), so the fixed linker follows movement again - this could not be reproduced as a live defect, and the test exists to keep that behaviour from regressing.
  Guarded by `test_linker_edit_reattach_regression.py::test_editing_invalid_linker_reattaches_and_follows_movement` (drive a linker invalid, edit it back keeping every appearance param identical, then assert it re-snaps to a moved endpoint through the real frame-change handler).

- **Keyframing a DNA bend deformer at a frame other than the playhead recorded the pre-drag position.**
  Reported as "moving the deformers works great, but keyframes don't seem to be recorded".
  `create_keyframe.execute` moved the playhead to the dialog's target frame *before* reading the values to key.
  That frame change re-evaluates animation, which wipes any edit with no keyframe behind it - so dragging a bend control node and then typing a later frame into the dialog keyed the node's *old* position, the two keyframes were identical, and the strand never moved.
  Fixed with `utils.animation.capture_unkeyed_edits` / `restore_unkeyed_edits`: any animated value that differs from its own F-curve at the current frame is a pending user edit and is carried across the frame change. Applies to every keyframe target (puppet controllers and members, DNA bend rigs, membrane holes and lattice `co_deform`), not just DNA.
  Guarded by `test_keyframes.py::test_create_keyframe_at_a_later_frame_keeps_the_dragged_deformer` (ground truth is the constant the test drags the node to; verified red pre-fix - frame 60 keyed x=0.0 instead of 0.15).

- **Re-editing a DNA strand silently deleted its bend animation.**
  Same report. The strand's edit dialog rebuilds the molecule on OK, and `reattach_after_rebuild` recreates the control-node Empties from scratch, so every F-curve keyed against the old strand object and old nodes was destroyed.
  The bend *curve* survives the rebuild as the same object and keeps its keys, so `get_keyframe_frames` still listed the frames - the Animate panel showed keyframes that no longer animated anything, which is what made this read as "not recorded" rather than "deleted".
  Fixed with `bender.capture_bend_animation` / `restore_bend_animation`: the strand's and each node's action is held (with a fake user) across the rebuild and re-bound afterwards, matching nodes by bezier-point order and binding the action slot explicitly when the 4.4+ slotted-action auto-bind comes up empty.
  Guarded by `test_keyframes.py::test_re_editing_a_dna_strand_preserves_its_bend_animation` (verified red pre-fix - the rebuilt node had no keyframes at all).

- **Membrane head / tail lipid colours never reached the membrane.**
  Reported (Janet): "changing the lipid colors in the membrane can be buggy (if you change representations, change colors, repeat) especially when trying to change the color of head domains. This doesn't seem to work for me."
  `color_head` and `color_tail` were the only membrane properties declared without an `update=_sync_to_active_membrane` callback, so setting them left the value in the scene props and never touched the membrane or its shared materials.
  Two consequences: no live preview (every other membrane control previews as you drag it), and - because the pick lived nowhere but the props - the object->props msgbus sync that fires on any active-object change replaced it with the membrane's stale stored colour. Every in-dialog button (Add Hole, Edit Deformation, Select Hole) changes the active object, so touching one after picking a colour silently reverted the pick, and OK then re-applied the old value. That is the "change representations, change colors, repeat" path.
  Fixed by giving both props the same `update` callback as the rest.
  Guarded by `test_membrane.py::test_head_and_tail_colors_write_through_to_the_active_membrane` (asserts the Principled BSDF base colour on the shared material, against a colour constant the test picks) and `::test_head_color_survives_an_in_dialog_action` (builds with an explicit baseline colour so the resync has something to clobber, and asserts the setup baseline so the case cannot pass vacuously). Both verified red pre-fix.

- **Nothing could be imported or built while a membrane's deformer was in edit mode.**
  Reported (Janet): "I can't seem to download a protein after creating and editing a membrane."
  `membrane_edit_deform` parks the user in Lattice edit mode by design so they can drag deformation points. MolecularNodes appends its style node groups with `bpy.ops.wm.append` and the builders call `bpy.ops.object.select_all`, neither of which polls outside Object mode, so protein import died with "context is incorrect" and no molecule appeared. The DNA builder and a second membrane build failed identically - the add-on put the user in the one state where its own creation paths could not run.
  Fixed with `utils.blender_utils.ensure_object_mode`, called at the top of `create_molecule_from_id`, `import_molecule_from_file`, `build_dna.execute` and `build_membrane.execute`. Fixing it at the creation sites covers every edit mode, not just the membrane lattice.
  Guarded by `test_membrane.py::test_import_protein_works_after_editing_membrane_deformation` and `::test_builders_work_after_editing_membrane_deformation` (ground truth is the molecule registry plus real Blender objects with vertices). Both verified red pre-fix with the real `bpy.ops.wm.append.poll() failed` signature.

- **The hole operators failed - and half-completed - from Lattice edit mode.**
  The same root cause as the import/builder regression above, in three places that fix missed. `membrane_add_hole`, `membrane_remove_hole` and `membrane_select_hole` all finish by calling `bpy.ops.object.select_all`, which does not poll outside Object mode, while `membrane_edit_deform` parks the user in Lattice edit mode by design. `build_membrane` and the importers got `ensure_object_mode` in the earlier fix; these three did not.
  Add Hole was the worst: it created the hole object, linked it, parented it, resynced the cache and rebuilt the GN hole assignments, and only then hit `select_all` and raised. Measured from edit mode: `holes_before=1`, `RuntimeError`, `holes_after=2`. So the user saw a red error and reasonably concluded nothing happened, while a hole silently existed in the scene - a half-completed operator rather than a clean failure, on the exact path a membrane tutorial walks (shape the deformer, then add a pore).
  Fixed by calling `utils.blender_utils.ensure_object_mode` at the top of all three `execute` methods.
  Guarded by `test_membrane.py::test_hole_operators_work_from_lattice_edit_mode`, which drives all three from `EDIT_LATTICE` and asserts on hole counts it tracks itself plus whether the controller object exists in `bpy.data` - never on the operators' own return values alone. Verified red pre-fix via `git stash push -- membrane_operators.py`, with the real `bpy.ops.object.select_all.poll() failed` signature.

- **The DNA builder's Length field did nothing.**
  Reported (Janet): "using the 'length' feature doesn't seem to work? I tried changing it to 100 and no change, but copying/pasting the random 50 so that there was 100 bp worked."
  `sequence_length` was the only builder field declared without an `update` callback. It was read solely by the randomize-arrows operator, so typing a number into Length left `sequence` - and therefore the built strand - exactly as it was. The control looked like it set the length and silently didn't; the reporter worked around it by pasting the sequence twice, and only later found the arrows.
  Fixed by giving the field an update callback that resizes the sequence in place: grow by appending bases from the type's alphabet, shrink by truncating, so nudging 50 -> 51 does not discard the sequence you already have (the arrows still reroll outright). Guarded to Length (`RANDOM`) mode so it can never rewrite a sequence typed in Sequence mode.
  `input_mode` also gained a callback that points Length at the sequence's real length on switching into Length mode. Without it the field could sit on a stale default (50) beside a 12-base sequence, and typing 50 would be a no-op write that Blender never fires an update for - the same silent failure, reachable a second way.
  Guarded by four tests in `test_dna.py`: `::test_setting_length_resizes_the_sequence`, `::test_length_change_builds_a_strand_of_that_length` (end to end, asserts the built strand's `pb_sequence`), `::test_length_respects_the_rna_alphabet`, and `::test_switching_to_length_mode_shows_the_real_length`. Ground truth is the integer the test asks for, never a length read back from the code that sets it. All four verified red on the pre-fix module via `git stash push -- dna_props.py` (`Length=100 left the sequence at 50 bases`). `::test_length_does_not_clobber_a_typed_sequence` passes both before and after - it guards the fix from over-reaching into Sequence mode.

- **Overlapping membrane force fields carved a phantom hole, ignoring Z.** A
  protein lifted far above the sheet still bored a hole straight down, at any
  height, as long as it overlapped in XY. It was NOT the per-field Z-attenuation
  (a *single* field correctly closes its hole once its centre clears the sheet by
  its radius). The cause was the multi-field combiner in
  `membrane_geometry._compute_sdf_displacement`: it formed the combined
  penetration as `smin_sdf = -ln(Σ w_i)/α` (log-sum-exp), which is biased below
  the true minimum by `ln(N)/α`. N fields stacked at the same XY, each already
  Z-attenuated to radius 0 (so `sdf_i ≈ dist_flat`, and `≈ 0` for lipids right
  under the shared centre), summed to `total_w ≈ N` and produced `ln(N)/α`
  (~0.69 BU for N=4 at α=2) of penetration - a hole conjured from overlap with no
  field actually reaching the membrane. Enabling the force field on a whole
  protein AND each of its chains (the toggle sets the flag on all of them) stacks
  exactly such fields. Fixed by replacing the penetration with the
  softmax-weighted mean `smin_sdf = Σ(w_i·sdf_i)/Σ w_i`, which is bounded by the
  individual sdfs (`min ≤ smin ≤ max`), so out-of-reach fields carve nothing and
  a single field is unchanged (weights cancel). `GN_TREE_VERSION` 34 -> 35.
  Guarded by
  `test_membrane.py::test_stacked_force_fields_do_not_carve_a_hole_from_afar`
  (verified red pre-fix: four fields 50 nm above the sheet carved it completely,
  341 -> 0 lipids), which also asserts the field still carves when embedded.
  Root-caused live over the BlenderMCP socket against the user's actual scene,
  where the field was enabled on the molecule plus all three chains.

- **Morphing a membrane made the lipids flicker violently, so membranes could
  not be animated.** Reported as "it redraws/resets the lipids when the shape
  deforms" - which is exactly right. The Lattice modifier sits *before* the GN
  modifier, so `_build_membrane_gn_tree` fed the already-deformed mesh straight
  into Distribute Points on Faces. Poisson-disk sampling is a function of the
  triangle geometry, so moving a single lattice point re-sampled the entire
  sheet: over a 10-frame lattice bulge the lipid count drifted 1240 -> 1267 and
  each lipid teleported across the membrane every frame (max per-lipid step
  4.70 BU on a 4 BU grid). The lipids weren't flickering, they were being
  replaced. Fixed by scattering on the mesh's REST shape, which is
  frame-invariant: the deformed position and normal are captured on the mesh
  point domain, Set Position flattens the mesh back to `rest_position`,
  Distribute runs on that, and the resulting points are immediately pushed onto
  the live surface with the captured deformed position (Distribute propagates
  anonymous attributes onto the points, barycentrically interpolated). Doing the
  remap right after Distribute means every downstream `Input Position` - the
  half-thickness offset, the hole/force-field SDF pushers, the six wobble
  channels - still reads real deformed coordinates and needed no change. Max
  per-lipid step dropped to 0.027 BU. Two things that are not optional: the
  captured *deformed* normal must replace `dist.outputs["Normal"]` for the tilt
  and bilayer offset (on a domed sheet the rest normal measures 0.0000
  off-vertical against the true 0.4152, so every lipid would stand bolt upright
  on a curve), and the `rest_position` read is wrapped in an Exists switch
  falling back to the live position - without it, a membrane whose object lacks
  `add_rest_position_attribute` collapses to a point and renders ZERO lipids
  (measured). `add_rest_position_attribute` is set per-object by
  `membrane_operators._enable_rest_position`, on build and again in
  `reapply_membrane_settings` so older .blend files pick it up on load; it is a
  native Object property and survives save/load (verified). Consequence by
  design: lipid count is fixed by the rest area, so stretching spreads the
  lipids apart rather than spawning new ones - which is how a bilayer under
  tension behaves, and the only pop-free option. `GN_TREE_VERSION` 35 -> 36.
  Guarded by `test_membrane.py::test_lipids_keep_their_identity_while_the_membrane_morphs`
  (verified red pre-fix with the exact signature above) and
  `::test_morphed_membrane_lipids_follow_the_deformed_surface`, which guards the
  obvious wrong fix - leaving the lipids frozen on the rest shape - and was
  already green pre-fix. Both measure the depsgraph instance list (what actually
  renders) against a dome the test itself authors, so the expected value never
  comes from the node tree. Removing only the object flag reproduces the
  original signature exactly, so each half of the fix is independently covered.
  Green on Blender 5.0, 5.1 and 5.2.

- **Lipids snapped 180 degrees about their own axis while a membrane morphed.**
  Reported as "a superfast flip, almost like they are going from a negative
  angle to a positive and they flip at a specific angle value" - which is
  exactly the shape of the defect. The per-instance rotation came from
  `AlignRotationToVector` with `pivot_axis = "AUTO"`, which derives the azimuth
  frame from its own input vector and swaps to a different pivot as that input
  crosses a critical direction. v9 had already hit this and worked around it by
  feeding the *un-perturbed* normal, so the node's input stopped moving - a fix
  that only held while the surface was rigid. v36 (morphable membranes) put a
  slowly-swinging normal back into it and the flip returned. Measured over a
  20-frame lattice bulge: the lipid's long axis tracked the surface smoothly at
  1.59 deg/frame while its SPIN about that axis jumped 179.91 deg in a single
  frame - the lipid never tumbled, it snapped about its own axis, which is why
  it looked instantaneous and hit only the few lipids whose normal crossed the
  critical direction. Fixed by replacing the node with `AxesToRotation`, which
  takes the azimuth reference as an explicit input instead of guessing one; the
  reference is `normalize(cross(rest_normal, helper))` built from the REST
  normal, so it is constant in time by construction and the only time-varying
  input left is the primary axis. A flip is therefore impossible rather than
  merely unlikely. `helper` picks world X or Y by which is less parallel to the
  rest normal - a branch that is safe precisely because it reads a per-lipid
  constant and so cannot flip mid-animation. Tilt behaviour is untouched (max
  step identical at 1.59 deg before and after). `GN_TREE_VERSION` 36 -> 37.
  Guarded by `test_membrane.py::test_lipids_do_not_flip_about_their_own_axis_during_a_morph`
  (FLAT and SPHERE), which asserts a lipid's total rotation between adjacent
  frames cannot greatly exceed how far its long axis actually tilted - both
  measured from the rendered instance matrices, so neither side comes from the
  node tree - plus a tilt floor so it cannot pass on a frozen scene. Verified
  red by reverting *only* the rotation node while keeping v36 (179.93 deg flat,
  179.22 deg sphere); stashing the whole file instead passes vacuously, because
  without v36 the lipids have no stable identity to compare across frames.

- **The v37 flip fix moved the singularity instead of removing it.**
  Found by driving the live Blender past the gentle domes the v37 tests use.
  v37 fed `AxesToRotation` a secondary axis built from the REST normal, on the
  reasoning that a frame-invariant reference cannot flip. That reasoning is
  incomplete: `AxesToRotation` projects the secondary onto the plane
  perpendicular to the primary, and the projection collapses when the two go
  parallel. The rest normal never moves - but the DEFORMED normal (the primary)
  swings onto it once a lipid tilts ~90 degrees from rest *in the direction of
  the reference*, and the lipid then snaps 180 degrees about its own axis. Same
  user-visible symptom v37 was meant to end, and "a specific angle value" is
  literally 90 degrees from rest. Measured on a flat sheet folded 120 degrees
  about X: 178.98 deg of total rotation in one frame against 19.13 deg of
  actual tilt, with every culprit lipid sitting 80-90 deg from its rest
  orientation. Fixed by carrying the reference onto the deformed surface with
  the minimal (Rodrigues) rotation that takes the rest normal to the deformed
  normal: `ref' = ref cos + (k x ref) sin + k (k . ref)(1 - cos)` for
  `k = normalize(rest_n x def_n)`. That rotation is rigid and `ref` starts
  perpendicular to the rest normal, so `ref'` is perpendicular to the deformed
  normal *by construction* at every frame - parallel is now impossible rather
  than merely unlikely, which is the property v37 claimed but did not have.
  Both endpoints are safe: at `def_n == rest_n` the cross product is zero and
  Blender's NORMALIZE maps zero to zero rather than NaN, so the sin and
  (1-cos) terms vanish and `ref' = ref`; at `def_n == -rest_n` it degrades to
  `ref' = -ref`, still perpendicular to the normal. The only discontinuity left
  is exactly antipodal, where the sheet has folded fully back on itself and the
  azimuth is undefined for any stateless frame. Tilt behaviour is untouched -
  the per-frame tilt steps are bit-identical before and after across the whole
  fold sweep (2.21 / 6.18 / 15.47 / 38.59 / 156.90 deg), only the spurious spin
  is gone, and on the dome sweep total step now equals tilt step exactly where
  it previously carried a small residual (19.00 vs 18.61 at a 16 BU bulge).
  `GN_TREE_VERSION` 37 -> 38. Guarded by
  `test_membrane.py::test_lipids_do_not_flip_when_a_fold_passes_the_azimuth_reference`,
  verified red pre-fix with exactly the signature above. The test folds about
  **X** deliberately: for a flat membrane the azimuth reference is world Y, so a
  fold about Y keeps the normal permanently perpendicular to the reference and
  cannot expose the defect (measured - a Y fold is clean at every angle even on
  the broken code). It also asserts a >90 deg tilt-from-rest floor, because the
  existing dome tests cannot reach the cliff at all: a radially symmetric bulge
  asymptotes at ~88 deg no matter how hard it is driven (87.71 deg at a 32 BU
  bulge, 2.3 deg short of failure). Green on Blender 5.0, 5.1 and 5.2, and
  re-confirmed against the live windowed Blender across the whole fold sweep
  and on FLAT / SPHERE / HEMISPHERE with `animate_bob` left ON (the headless
  morph tests disable it).

- **A membrane vanished entirely if its `_Group` collection was unlinked, and
  could never come back.** Found while hunting the reported "Reset Deformation
  makes everything disappear" (see the open note below - Reset turned out not to
  be the trigger, but this failure mode matches the symptom exactly). Every
  object a membrane owns - root, lattice, holes - lives in one `<name>_Group`
  collection, so unlinking that one collection makes all of them disappear
  together while the objects stay in `bpy.data`. That is an ordinary user
  accident, not file corruption: deleting the group's row in Blender's own
  outliner unlinks the collection without touching the objects.
  `_ensure_membrane_collection` looked the collection up by name and returned it
  as-is, so nothing ever re-attached it and the membrane could not be recovered
  by re-editing it. Building a *new* membrane that resolved to the same group
  name then failed outright, because the builder selects the root it just
  created and Blender refuses: `Object 'Membrane_001' cannot be selected because
  it is not in View Layer 'ViewLayer'`. Fixed by making the helper ensure the
  collection is *in this scene*, not merely that it exists - it re-links when
  the collection is not reachable from `scene.collection.children_recursive`.
  Reachability rather than direct parentage on purpose: a user who filed the
  group away inside another collection still sees the membrane, and re-linking
  to the scene root would yank it out of the place they put it. The repair is
  reachable from any path that builds or re-applies a membrane, so an already
  stranded membrane heals rather than staying lost. Guarded by
  `test_membrane.py::test_a_membrane_survives_its_group_collection_being_unlinked`,
  verified red pre-fix with exactly the RuntimeError above. Ground truth is
  Blender's own scene graph - membership in `scene.objects` and
  `scene.collection.children` - never the helper under test, and the test
  asserts its own setup actually stranded the membrane so it cannot pass
  vacuously.

- **Reset Deformation silently did nothing in the two cases that matter.**
  Found while investigating a reported "reset makes the membrane disappear",
  which did NOT reproduce (see the open note below) - but two real defects in
  the same operator did. (1) It wrote `lattice.data.points[*].co_deform`
  directly, and Blender holds an authoritative edit-mode copy of a lattice that
  overwrites the datablock on exit, so pressing Reset while *in* deformation
  mode had no effect at all, neither immediately nor after leaving - and edit
  mode is exactly where a user reaches for it. Fixed by dropping to Object
  mode, resetting, and restoring edit mode. (2) On a keyframed lattice the
  reset landed and was then re-asserted by the F-curves on the next depsgraph
  evaluation, so the membrane snapped back the instant the frame changed.
  Harmless while lattices were static; a lie once v36 made lattice keyframes
  the way membranes are animated. Fixed by clearing the lattice *data*
  animation as part of the reset (that is where `co_deform` lives), leaving any
  object-level animation on the lattice alone, and reporting what was dropped
  since the operator is undoable. Guarded by
  `test_membrane.py::test_reset_deform_sticks_while_in_edit_mode` and
  `::test_reset_deform_clears_lattice_keyframes`, both verified red pre-fix
  ("did not stick" / "keyframes re-asserted the deformation"); ground truth is
  each point's own rest `co`, which the operator never computes.

- **Deformation mode moved out of the Edit Membrane dialog onto the PB
  Outliner row.** Reported as "when I click Edit Deformation on the popup then
  Okay it doesn't let me edit, it takes me out of that mode" - confirmed:
  `build_membrane.execute()` calls `ensure_object_mode()` (it has to; building
  calls `select_all`, which does not poll in an edit mode), so confirming the
  dialog tore the mode straight back down and the lattice could only be reached
  by *dismissing* the dialog instead. The root cause is a category error rather
  than a bug: deformation is a **mode**, and it was being launched from a
  **transient popup**, which cannot host one. Blender offers no way to pin an
  `invoke_props_dialog` open - it closes on OK, Esc and click-away alike - so
  the entry point became a toggle on the membrane's Outliner row, which stays
  on screen and makes entering and leaving the same control.
  `membrane_toggle_deform` resolves its membrane by name (so it works on a row
  that is not the active object), hands the mode over cleanly when a
  *different* membrane is already being deformed, and invokes `edit_deform`
  with `INVOKE_DEFAULT` so the Esc/Enter modal is actually armed - an EXEC call
  would silently skip it. The Edit Deformation button was removed from the
  dialog rather than left as a trap, and the Deformation section was then
  dropped from it entirely (along with the now-dead `show_deform_section`
  property). Reset Deformation moved to the deform banner instead of being
  orphaned - the same dead-operator trap `finish_deform` used to be in - which
  is also the one surface guaranteed to be on screen while the lattice is being
  shaped, and it works from there because Reset now drops out of edit mode,
  resets, and returns. Guarded by
  `test_membrane.py::test_outliner_toggle_enters_and_leaves_deform_mode` and
  `::test_deform_toggle_is_per_membrane` (two membranes: only the one actually
  open may read as active, and toggling the other hands over rather than
  stacking). The row draw itself is not reachable from background pytest, so it
  was smoke-tested in a real GUI in both states.

- **Esc / Enter now leave membrane deformation mode.** Follow-up to the
  one-way-door fix below: a banner button helped, but the mode is entered from
  a popup and worked on in the viewport, so users still had no keystroke out.
  `membrane_edit_deform` now stays resident as a modal operator and owns the
  exit key itself, rather than registering a global keymap item that would
  hijack Esc for every lattice in the file (the add-on registers no keymaps at
  all, and this is not a good place to start). It falls back to the old
  one-shot behaviour whenever a modal handler cannot be attached (headless, no
  window), so the mode is never entered without *some* way back out. The risky
  half is not the exit key but swallowing keys normal lattice editing needs, so
  the per-event decision lives in `deform_modal_step()` - testable without an
  event loop - and everything except an exit-key PRESS returns "pass". A
  running transform sits above this handler in Blender's modal stack, so Esc
  mid-grab is consumed there and cancelling a grab does not drop the user out
  of the mode. Guarded by
  `test_membrane.py::test_esc_and_enter_leave_deform_mode`, which pins the
  whole decision table: the three exit keys, key releases (must not re-fire),
  the stand-down case outside deform mode, and 16 editing/mouse events that
  must pass through.

- **Membrane deformation mode was a one-way door.** Reported as "once you enter
  deformation, there is not an obvious way to exit it". `membrane_edit_deform`
  drops the user into Lattice edit mode from inside a dialog that then closes,
  and `membrane_finish_deform` was registered but drawn nowhere - so the only
  exit was already knowing to press Tab. Fixed with
  `PROTEINBLENDER_PT_membrane_deform_banner`, a `bl_order = -1` panel that polls
  true only in Lattice edit mode on a membrane deformer, plus a status-bar hint
  set on entry. The banner's poll doubles as the cleanup hook for the status
  text, since Blender's own Tab leaves the mode without going through the Finish
  operator. Guarded by
  `test_membrane.py::test_deform_mode_offers_a_visible_way_out` (banner poll
  false before, true while editing, false after Finish).

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

- **A headless Blender hung forever building the UI workspace.** Every leg of
  the nightly artifact job (ubuntu, windows, macos) printed add-on registration
  and then went silent until the 45-minute job timeout killed it; the lane had
  never once passed in CI.
  Root cause: `ProteinWorkspaceManager` rearranges editors with
  `workspace.duplicate`, `screen.area_close` and `screen.area_split`. Those are
  UI operators that complete via the window event loop, and `blender
  --background` has no event loop, so `bpy.ops.screen.area_close()` in
  `_reduce_to_main_viewport` never returns and spins at 100% CPU. Reached on
  startup through the `create_workspace_on_load` load_post handler, which is why
  Blender wedged before it ever ran the `--python` script - no watchdog inside
  that script could observe it, and Blender's crash handler swallows SIGABRT.
  Located by running the lane against a headless Linux Blender and profiling
  with py-spy: 790 of 798 samples in that one stack. It terminates on Windows,
  which is why local runs never showed it.
  Fixed by no-opping both public entry points of `ProteinWorkspaceManager` when
  `bpy.app.background` is set. Guarded by
  `test_workspace_background.py` (asserts the guard, not the symptom: a hang
  cannot be asserted on without wedging the suite, so the UI entry points are
  replaced with something that raises; verified red pre-fix).

- **`build.py` reported a missing module instead of the real install failure.**
  The nightly's ubuntu leg died in 32s with `ModuleNotFoundError: No module
  named 'tomlkit'`. Root cause: the import-time bootstrap ran `pip install
  tomlkit` into a system Python whose `dist-packages` the CI user cannot write
  (EACCES), and `run_python` called `subprocess.run` without `check=True`, so
  that exit status was discarded and the failed re-import became the visible
  error. Fixed by retrying into the user site directory and failing loudly with
  pip's own output. `check=True` matters beyond the bootstrap: `run_python`
  drives `pip download` for the whole release wheel matrix, so a swallowed
  failure let `update_toml_whls` write a manifest from whatever wheels landed -
  a partial dependency set shipping as a complete release. Guarded by
  `test_build_tooling.py` (verified red pre-fix).

- **Deleting a protein's last chain/domain left an empty protein behind.**
  The trash can on a chain or domain row deleted only that chain's domains, so
  removing the last one left a PROTEIN row with nothing under it - plus its
  wrapper, its Blender object and everything built on it (puppets, poses,
  keyframes, linkers) still holding on to a protein the user had emptied.
  Two older leaks sat behind it. A puppet whose members were all deleted was
  dropped silently by the outliner rebuild rather than through
  `delete_puppet`, so the Protein Pose Library kept listing its poses. And
  `delete_domain` stripped only the *chain* row from puppet memberships -
  never the deleted domain's own id, and via a `"{mol}_chain_{letter}"` string
  that never matched the index-keyed rows anyway - so a puppet built on a
  single domain went stale the same way. Every route now goes through
  `delete_molecule_cascade` / `delete_molecule_if_empty` /
  `prune_emptied_puppets`, the same cascade the protein row's own Delete uses,
  and the confirmation dialog says the whole protein is about to go. The
  Domain Splitter, which empties a chain transiently while re-laying it out,
  deliberately does not go through this. Guarded by
  `test_delete_last_chain_deletes_protein.py` (verified red pre-fix, green on
  Blender 5.0/5.1/5.2).

- **Biological assemblies could not be built from a `.pdb` file at all.**
  Two defects in the embedded MolecularNodes, both on the PDB side only.
  `PDBAssemblyParser.get_transformations` returned `(chain_ids, matrix)`
  tuples while its only consumer, `utils.array_quaternions_from_dict`, indexes
  them as dicts by `chain_ids`/`matrix`/`pdb_model_num`, so building raised
  `TypeError: list indices must be integers or slices, not str`.
  `CIFAssemblyParser` already returned dicts, so the two implementations of
  one abstract interface disagreed about what that interface was - and the
  `AssemblyParser` docstring still documented the tuple neither consumer
  accepted. Behind it sat a worse one: a chain set was sliced up to the start
  of the next one, sweeping in the blank separator line `REMARK 350` writes
  between BIOMOLECULE blocks, and `_parse_transformations` requires exactly
  three lines per transformation - so every assembly except the file's *last*
  raised `Invalid number of transformation vectors`. 4hhb hid this by having
  only one assembly. Both parsers now return the documented dict, the slice
  keeps only `BIOMT` records, and the download default moved to mmCIF (legacy
  PDB cannot express a large assembly: 99,999 atom serials, 62 chain ids).
  Guarded by `test_biological_assembly.py`, whose expected transforms come
  from the fixture's own `REMARK 350` text rather than from the parser
  (verified red pre-fix, green on Blender 5.0/5.1/5.2).

- **An assembly built on the molecule object alone would be invisible.**
  A ProteinBlender import creates one object per domain on top of the molecule
  object, all sharing one mesh, and the molecule object draws only the atoms
  *no* domain covers - which after a normal import is none of them. Rendering
  it in isolation produces zero covered pixels. MolecularNodes' own
  `assembly_insert` targets the molecule object, so reusing it directly would
  have produced a perfectly correct assembly that never appeared on screen,
  and every node-graph assertion about it would still have passed.
  `core.assembly` therefore wires the assembly node into every domain object
  as well. Guarded by `test_assembly_build.py`, which counts the instances the
  depsgraph places per domain object against the operator count in
  `REMARK 350` and separately asserts that rendered coverage increases;
  both were confirmed to fail when the node is wired into the molecule object
  only (green on Blender 5.0/5.1/5.2).

- **A cancelled Realize Copies destroyed the assembly it refused to realize.**
  Reachable from the UI in two clicks: cut an assembly down until only the
  original is left, then press Realize Copies. There was nothing to realize,
  so the operator reported as much and returned CANCELLED - but
  `realize_copies` had already called `clear_assembly` unconditionally on the
  way out, so the build still on screen was silently thrown away. A cancelled
  operator has to leave the scene as it found it. The teardown now happens
  only when copies were actually created. Guarded by
  `test_symmetry_realize_cutaway.py::test_realizing_nothing_leaves_the_assembly_alone`,
  plus an end-to-end test of the cutaway-then-realize sequence that surfaced
  it. Found by driving the panel in a live Blender session; no headless test
  covered the combination.

- **mmCIF assembly matrices carried uninitialised memory.**
  `pdbx._extract_matrices` allocated with `np.empty` and filled only rows 0-2,
  so the homogeneous bottom row was whatever happened to be in that memory -
  a downloaded 1ubq came back with `[1.5e-312, 1.1e-312, 1.5e-312,
  1.1e-312]` instead of `[0, 0, 0, 1]`. Nothing validates that row, and the
  damage surfaced far away: an identity operator no longer compared equal to
  the identity, so a *monomer* reported symmetry and put a Symmetry panel on
  screen whose Build button placed one identity copy and appeared to do
  nothing. Switching the download default to mmCIF made this the primary
  path. Both extractors now start from the identity. Guarded by
  `test_biological_assembly.py::test_mmcif_matrices_do_not_leak_uninitialised_memory`,
  which poisons `np.empty` with NaN to make the defect deterministic - a
  plain assertion on the bottom row is *not* reliably red, because a fresh
  `np.empty` often does come back looking like a valid matrix, which is
  precisely what let this ship. Found by driving the live GUI, not by the
  suite.

- **Assembly copies landed on top of each other instead of forming the assembly.**
  The copies were built with MolecularNodes' assembly node, which splits the
  structure into per-chain *centred* instances before transforming. Centring
  discards where each chain sits relative to the crystallographic origin -
  the exact thing a BIOMT operator is defined against - so the copies rotated
  about each chain's own centroid and piled up on the original: correct in
  number, wrong in space. For 4ins assembly 3, consecutive copies sat 0.0095
  apart where the operators put them 0.303 apart, a factor of 32.
  Neither the copy-count test nor the render-coverage test can see this: both
  pass with the copies stacked. ProteinBlender now applies each operator as a
  placement of the whole structure in the deposited frame, which is what
  ChimeraX's `sym` does. The translation carries a `R @ pivot - pivot`
  correction because the node tree has already shifted geometry by `-pivot`
  before our node sees it. Guarded by
  `test_assembly_build.py::test_copies_land_where_the_operators_put_them`,
  which takes chain A's centroid from the fixture's own ATOM records and
  asserts where the copies' *atoms* land - not where instance origins land,
  which is governed by the mass-weighted pivot and is right for the wrong
  reason. Found by driving the live GUI; verified red at 0.0095 pre-fix.

- **The Symmetry panel would never have appeared in a real session.**
  It resolved the active protein through `scene.selected_molecule_id`, which
  reads like the obvious accessor but is written by nothing except the rename
  operator - import does not set it. The panel therefore polled False forever
  while its tests passed, because those tests assigned the property by hand
  before polling. Fixed by `scene_manager.resolve_active_molecule_id`, which
  falls back from that property to the active `molecule_list_items` row and
  then to the manager's own `active_molecule`. The test helper no longer sets
  the property at all, so every panel/operator test now exercises the path a
  plain import leaves behind (verified red pre-fix: the poll, enum and
  no-argument operator tests all failed).

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

- Panel `poll()` — no registered panel defines a `poll` of its own any more, so
  there is nothing to exercise. The one that did, `PROTEINBLENDER_PT_domain_maker`,
  was removed along with its panel.
- Edit-mode operators (`dna_edit_bend`/`dna_finish_bend_edit`,
  `membrane_edit_deform`/`membrane_finish_deform`) degrade to a skip if
  headless mode-switching fails; their non-edit siblings are asserted.
- `draw()` for panels — no window/screen exists in `--background`, so panels
  are checked via registration + `poll`, not rendering.

## Known issues surfaced but not fixed here

- **STILL UNCONFIRMED: "Reset Deformation makes the whole membrane, hole and
  lattice disappear; you have to undo until it comes back."** Reported against a
  membrane that already existed and was reopened through the PB Outliner's edit
  pencil, with Reset clicked inside that dialog. Not reproducible from the
  operator: driven headless in Object mode, with a hole, from inside
  `EDIT_LATTICE`, on a fully keyframed lattice, and after a stale-`pb_gn_version`
  tree upgrade (the state a .blend saved by an older build lands in), the root,
  lattice, hole, per-membrane collection and all 1240 lipid instances survive
  every time. Two real defects in the same operator *were* found and fixed (see
  "Reset Deformation silently did nothing" above), but neither deletes anything.
  **The `invoke_props_dialog` + undo-push hypothesis has now been tested and
  eliminated.** It was driven in the foreground UI lane
  (`--enable-event-simulate`, steps advanced one per application timer so the
  window manager really processes the modal dialog): membrane with a hole and a
  keyframed lattice, edit dialog opened through the outliner pencil path, Reset
  clicked while the dialog was still up, then confirm / cancel / undo /
  double-Reset / Edit-Deformation-then-Reset. Everything survives every arm.
  One caution for anyone re-running this: operators driven from an application
  timer do **not** push undo steps of their own (`ed.undo.poll()` fails outright
  after a timer-built membrane), so without explicit `ed.undo_push` calls the
  dialog's push is the only step on the stack and a single undo lands on the
  factory-startup scene - which looks exactly like the reported disappearance
  but is an artifact of the harness. That false positive is what the no-dialog
  control arm exists to catch. What *was* real is the collection half of the old
  hypothesis, now fixed and no longer a candidate explanation either (see "A
  membrane vanished entirely if its `_Group` collection was unlinked" above).
  So the original report remains unexplained, and its stated trigger (Reset) is
  now positively ruled out on every path we can drive. Needs a live repro with
  the system console open - ideally the user's own .blend.

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
