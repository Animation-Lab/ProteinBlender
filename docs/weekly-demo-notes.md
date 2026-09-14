# Weekly improvements and demonstration notes

## Work organization

The work is divided into independent branches from `alpha` at `7ca96f0`. Each implementation branch includes its tests and a change note. **`demo/weekly-improvements` is the combined working version.** Review individual branches by topic; use the combined branch to rehearse and merge the complete result. It also contains integration fixes for flat-shader fades and morph-context opacity, plus the normal-profile UI test harness.

| Branch / topic commit | Scope | Change note |
|---|---|---|
| `fix/weekly-outliner` · `314af13` | Four-color swatches, three-color divider, Edit Chain pivots, labeled right-click actions | [Outliner](change-notes/outliner.md) |
| `fix/weekly-lighting` · `d884b10` | Flat illustration, contours, Apply without closing | [Lighting](change-notes/lighting.md) |
| `fix/weekly-membrane-force-fields` · `860822f` | Reproduced missing-gap defect; displayed geometry and moving-chain fields | [Membrane](change-notes/membrane.md) |
| `feat/weekly-morph-workflow` · `58c8269` | Independent morphs, frame timing, alignment control, context, breathing, captured conformations | [Morphing](change-notes/morphing.md) |
| `docs/weekly-motion-research` · `4b13883` | Sculpting, ChimeraX, Markov models, MolecularNodes trajectories, next milestones | [Research report](research/protein-motion-workflows.md) |

The exploratory items are treated as research and implementation planning. The report distinguishes proposed capabilities from implemented behavior. It recommends trajectory playback and restrained endpoint editing before a full molecular sculpting engine.

The follow-up **`feat/conformation-library`** branch builds on the combined
version and adds the persistent PDB ensemble browser, comparison controls,
library pose capture, and two-state animation. See its
[demo and change notes](change-notes/conformation-library.md).

## Todo coverage

| Requested item | Work |
|---|---|
| Multi-color width, maximum four colors, three-color divider | Native equal-width bands; underlying colors remain intact |
| Remove Start / Center / End from Edit Chain | Removed from original-chain and copied-chain dialogs |
| PB Outliner right-click menu with spelled-out actions | Shared row-action implementation with clicked-row context |
| Investigate membrane force field | Reproduced actual unchanged lipid clearance around a moved chain; geometry-based fix |
| Bright Illustration should look 2D, inspired by ChimeraX | Flat colors and optional surface contours; exact contour-method difference documented |
| Lighting Apply without closing | Dedicated Apply operator; modal lifecycle checked |
| Rename Align & Animate | Align & Morph |
| Morph as a sibling with no children | Independent top-level object; endpoint data owned by the morph |
| Start/end frames | Frame-based timing, with hidden duration compatibility for existing scripts |
| Explain 30% and three-residue restriction | Exact algorithm and thresholds documented below and in research report |
| Highlight morph regions and fade other areas | Colored morph with optional translucent surrounding geometry and preview |
| Control alignment | Stable core, all matched residues, chosen anchor region, current placement |
| Research Chimera alignment/morph UX | Comparison and proposed interaction model in research report |
| Morph back like breathing | Return frame and repeatable keyed cycle |
| Multiple chunks/chains | Residue ranges, explicit chain mapping, multiple independent morph objects |
| Create a new conformation from a puppet-like workflow | Capture native chain/domain poses as an independent endpoint |
| Sculpt atoms | Detailed feasibility, restraint/worker architecture, preparation and validation plan |
| Markov-model movement | Viable with state/transition data; distinguish authored weights from measured kinetics |
| PDB-defined morph menu | Named imported/captured endpoint workflow; PDBs alone do not specify a kinetic model |
| Brady/MolecularNodes trajectory shortcut | Verified documented topology-plus-trajectory loader and existing vendored code; exact intended video/shortcut remains unidentified |

## Suggested demo order

1. **Outliner usability:** use three colored domains to show the uninterrupted center band. Add more domains to show the four-color preview cap. Right-click a protein and a chain, then open Edit Chain.
2. **Lighting:** choose Bright Illustration, press Apply, toggle Outlines, and Apply again. Switch to Studio to show restored depth shading. Close after applying.
3. **Membrane:** move a chain off its protein origin, select the whole protein as the membrane target, and show the gap around the actual chain. Change its pivot, lift it above the membrane, and lower it again.
4. **Morph:** use bundled adenylate kinase structures `tests/data/1ake.pdb` and `tests/data/4ake.pdb`, chain A. Leave residue fields empty and choose `1-40` as an anchor to compare fitting. Then select `122-159` in both residue fields, choose All paired residues, and preview the colored region with faded context. Anchors must belong to the selected matched region. Cancel the preview to show restoration.
5. **Animation:** clear the residue fields to morph chain A, create it at frames 10–30, return at 50, enable Repeat, and disable Ease in and out. Scrub frames 10, 20, 30, 40, 50, 60, and 70 to show 0%, 50%, 100%, 50%, 0%, 50%, and 100%. The popup slider covers the forward leg; use Play to observe the repeat.
6. **Independence:** collapse the proteins and show that the morph remains visible as its own row. Create another morph for a different region. Delete one morph and retain the other.
7. **Authored conformation:** split a protein, pose one domain, capture a named conformation, and choose it as an endpoint. Explain the current capture scope: native chain/domain poses, without arbitrary deformers or ambiguous duplicate copies.
8. **Research discussion:** show the motion-workflow report. Emphasize externally supplied trajectories as the first extension, then restrained conformation editing. Keep Markov state scheduling separate from atom-path generation.

## Exact threshold explanation

Thirty percent is **sequence identity among aligned nongap residue pairs**, checked per chain pair. It is not structural overlap, motion amplitude, or confidence. Three residues means at least three paired amino-acid residues; a rigid fit additionally needs three non-collinear alpha carbons. Stable-core fitting excludes distant pairs above 2 Å while retaining at least half the matched residues and at least three points.

The existing interpolation is Cartesian atom-position interpolation between corresponding endpoints. Easing changes timing; it does not enforce molecular geometry. Intermediate frames may distort bonds or contain clashes. The research report explains the algorithm, omitted atoms, homomer ambiguity, and alternatives in detail.

## Verification record

- Broad offline checks: 708 passed per version in Blender 5.1 and 5.2. A modal-instance policy finding was resolved and its contract checks rerun; existing skips and platform diagnostics are detailed in the [verification record](change-notes/verification.md).
- Final affected checks: 46 lighting/morph/save-reopen tests passed in Blender 5.2; 55 including keyframes passed in Blender 5.1. An additional 28 contract/keyframe checks passed in Blender 5.2.
- Blender 5.0: 85 focused tests passed for morphing, lighting, membranes, and outliner colors. The final Blender 5.1 contract rerun passed all 19 checks.
- Foreground UI: 75 combined source scenarios passed per version. The expanded set of 79 scenarios passed against the enabled installed copies in fresh normal Blender 5.1 and 5.2 profiles.
- The membrane regression failed before the fix and passed afterward. Real rendered pixels verify flat shading, contours, molecular color, morph geometry, and swatch width. Seven save/reopen cases include breathing, capture, and illustration morphs.
- Deployment byte-verified 144 Python files per installed copy. The demonstration branch is ready locally; no branches were pushed or published.

The long test runs emitted Windows environment-variable diagnostics that also reproduce on unchanged `alpha`. The focused final checks and installed-profile UI checks did not emit them. See the verification record for exact commands, counts, and limitations.

## Follow-up boundaries

The first implementation supports multiple independent morphs and multiple regions/chains. An ordered multi-state A→B→C trajectory editor is a separate next milestone. Atom sculpting, molecular simulation, Markov-state import, and a PB trajectory-import UI are researched proposals, not shipped implementations. A specific source for Brady's intended shortcut would allow a more exact comparison.

Bright Illustration contours depend on surface curvature; they do not exactly match ChimeraX's constant-width depth-buffer silhouettes. Molecular geometry and color are validated through the tested supported materials. Arbitrary custom artist shader graphs remain outside the automatic flat-material conversion.
