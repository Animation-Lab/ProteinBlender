# Conformation library and browser

Branch: `feat/conformation-library`, based on `demo/weekly-improvements`.

One protein now owns a library of named coordinate sets. Clicking its
**Conformations (N)** badge opens a persistent browser beneath the PB Outliner.
Switching states preserves the playhead, transforms, styling, and domain layout.
The library supplies two endpoints to the existing independent morph workflow.

![Conformation browser with a transparent reference and orange motion markers](../images/conformation-browser.png)

## Demo

1. Import **1D3Z** from PDB, or the bundled `tests/data/1d3z.pdb.gz`. Its Outliner
   row shows **Conformations (10)**. Set the protein representation to Cartoon.
2. Click the badge. Use the model dropdown, Previous/Next, and Browse slider.
   Point out that the current scene frame remains unchanged.
3. Compare with Model 1 and choose Stable core. Enable the transparent reference
   and orange motion markers. Lower the motion threshold to **0.5 Å** to see
   differences in this fairly similar ensemble. Change the reference or use
   Selected region with `A:1-30` to demonstrate alignment control.
4. Rename Model 1 to "Rest" and set it as Start. Select Model 8, rename it to
   "Alternate", and set it as End. Show that browsing another model leaves those
   choices intact.
5. Click **Animate Between Conformations…**. Set frames **10 → 30**, enable
   Return to start at **50**, and enable Repeat breathing cycle. Create the morph.
   Its independent Outliner entry has no children. Its pencil opens playback.
6. Demonstrate Add from File/PDB, Capture Current Pose, and Extract as Protein.
   Extraction places the copy at the same location; move it for side-by-side use.
7. Save and reopen. The named library, inactive states, active model, comparison
   settings, and animation endpoints remain available without the input file.

## Implementation notes

- Coordinate meshes belong to the protein controller and are referenced through
  persistent Blender properties. Domain objects share the live atom mesh but
  do not inherit their own libraries. Protein duplication can share immutable
  coordinate sets safely; extraction creates a one-state library.
- MolecularNodes' implicit frame animation is bypassed when an ensemble enters
  the library. Browsing and explicit morph animation have separate timing.
- Every state aligns to the selected immutable reference. Revisiting a model
  does not accumulate alignment drift.
- Comparison helpers follow native chain/domain transforms, preserve source
  materials, and stay out of renders and the PB Outliner. Captured pose states
  compensate for existing domain transforms when displayed.
- Added-file batches require exact atom identities, including ligands. Atom
  order may differ. A mismatch reports missing/additional atoms before changing
  the library; separate imports retain the existing partial-match morph route.
- PDB/mmCIF experiment metadata identifies NMR ensembles. Legacy assembly
  filenames identify simultaneous copies. Ambiguous local model records need
  an explicit interpretation in the import dialog.
- The new badge exposed Outliner layout stretching. Right-aligned controls
  preserve equal total widths for solid and mixed-color swatches.
- A partial morph's surrounding context uses its chosen start state, even when
  a different model is currently displayed in the browser.

## Verification

Regression coverage includes deposited PDB/mmCIF ensembles, a legacy assembly,
ambiguous imports, raw coordinate endpoints, rendered atom geometry, fixed
alignment references, invalid anchors, comparison cleanup, named endpoints,
breathing cycles, append rejection, pose capture, extraction, and deletion.
Foreground scenarios exercise the actual panel, undo/redo, and the morph dialog.
The save/reopen lane checks every stored coordinate mesh and switches states
again after reconstructing the scene in a fresh process.

| Validation | Result |
|---|---|
| Blender 5.2: affected integration suites, all save/reopen cases, persistence and repository contracts | 112 passed; one network test excluded |
| Blender 5.2: final library and existing morph tests, including PDB downloads and partial-region context | 34 passed |
| Blender 5.1: conformation integration and save/reopen cases | 37 passed |
| Blender 5.0: library compatibility and PDB download path | 11 passed |
| Final installed build: foreground UI, Blender 5.1 normal profile | 94/94 scenarios passed |
| Final installed build: foreground UI, Blender 5.2 normal profile | 94/94 scenarios passed |

The broader Blender 5.2 run emitted the same Windows access-violation diagnostics
inside pytest's environment-variable bookkeeping documented in the earlier
[verification notes](verification.md). It continued to completion with exit code
zero and all 112 tests passing. The final focused run completed
without those diagnostics. The 5.1 and 5.0 runs also completed without them.

The final code was deployed and byte-verified in all six local addon copies
(legacy and extension installations for Blender 5.0, 5.1, and 5.2). Validation
uses fresh normal-profile windows; an already-running user session needs a
restart to load the new code. No user session was closed.

## Scope

This release provides browsing and two-state morph creation. Ordered multi-state
sequence editing remains a follow-up. NMR model numbering supplies no motion
timing. Morph interpolation remains illustrative and can distort intermediate
atomic geometry. Comparison markers show backbone displacement; use Cartoon to
see them clearly. Exact file/PDB append and sequence-based partial morph matching
are deliberately different operations, with their compatibility rules visible
in the relevant error message.
