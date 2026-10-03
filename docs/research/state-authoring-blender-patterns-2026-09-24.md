# Protein state authoring: patterns from Blender add-ons

Research date: 2026-09-24. This is a review of primary documentation and the
current ProteinBlender source. The third-party tools were not installed or
benchmarked. Recommendations below are design proposals, not measured usability
results or shipped ProteinBlender features.

## Recommendation

Build a persistent **Protein States** editor, opened for a protein or chain.
It prepares named conformations for the existing Morphset/keyframe workflow.
The central task is: choose a state, inspect or edit its coordinates, save it,
then choose that state in Create/Edit Keyframe.

Separate three operations in both terminology and implementation:

1. **Match:** identify corresponding chains, residues, and atoms.
2. **Align:** rotate and translate an existing conformation into a reference
   coordinate frame. This preserves its internal shape.
3. **Author:** change internal coordinates to make an additional conformation.

Alignment can add a state obtained from another structure to a working library.
Alignment alone does not invent a new conformation or determine the transition
path between conformations. State creation and animation timing should remain
separate tasks.

## The most useful precedents outside molecular graphics

| Tool | Documented behavior | Proposed application to ProteinBlender |
| --- | --- | --- |
| [Faceit: Expressions](https://faceit-doc.readthedocs.io/en/latest/expressions/) | A named expression list gives access to poses; expressions support posing, corrective sculpting, and restoration of original values. | A list of Open, Closed, and user-named states, with preview, duplicate, edit, and reset. Adapt its state organization while keeping authoring independent of the scene timeline. |
| [Pose Shape Keys, Blender Studio](https://extensions.blender.org/add-ons/pose-shape-keys/) | Stores sculpted target shapes separately and reapplies them after rig/weight changes, provided topology remains unchanged. Supports masks for component shapes. | Preserve reference coordinates and editable targets separately from the temporary control rig. Domain selections define which atoms an edit affects. |
| [Auto-Rig Pro: Remap](https://www.lucky3d.fr/auto-rig-pro/doc/remap_doc.html) | Generates a source-to-target bone mapping, permits correction, synchronizes selection with the viewport, and saves mapping presets. | Suggest chain/residue correspondences, highlight the paired parts on hover, and reveal mapping controls when the match is ambiguous. Protein mapping needs sequence and atom identity rather than bone-name heuristics. |
| [KeenTools FaceBuilder](https://keentools.io/help/faqs-and-links) and [GeoTracker](https://keentools.io/products/geotracker-for-blender) | FaceBuilder adjusts its solution from user pins; GeoTracker offers object alignment and masks that exclude geometry from tracking. | Pick corresponding residues or a domain in the viewport; show exactly which atoms contribute to fitting. Landmark controls are a useful interaction precedent, although image fitting and molecular superposition require different solvers. |
| [RetopoFlow 4](https://docs.retopoflow.com/v4/general.html) | Integrates task-specific tools into Edit Mode, adjusts viewport/selection settings automatically, and restores previous settings when leaving its tools. | Enter a focused state-editing session with reference ghosts, residue selection, and relevant handles. Keep view rotation available. Restore the regular PB scene when finished. |
| [Object Alignment](https://github.com/patmo141/object_alignment) | Offers picked-point/iterative closest point alignment and can carry other objects along with a fitted object. Its README documents Blender 3.2.2 support. | Useful scan-registration interaction precedent. Fit a selected molecular core and apply the resulting transform to the entire intended mobile group. Modern Blender compatibility was not verified. |

The strongest combination is Faceit's named targets, Auto-Rig Pro's visible
correspondence, and RetopoFlow's focused viewport interaction.

Closest-surface alignment is insufficient for molecular identity: a close point
on a ribbon or surface need not represent the corresponding residue. Rendered
mesh topology also depends on representation and settings. Fit molecular atom
coordinates and regenerate the visualization from the resulting coordinates.

## Molecular precedents and the actual competitive bar

- [ChimeraX Matchmaker](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/matchmaker.html)
  already combines sequence/secondary-structure correspondence with fitting,
  explicit chain pairing, iterative removal of poorly fitting pairs, and fit
  statistics. Its
  [documented morph API](https://chimerax.readthedocs.io/en/release-v1.8/modules/core/commands/user_commands.html#morph)
  includes hinged rigid groups and internal-coordinate interpolation that
  preserves bond lengths. A basic Cartesian shape-key morph would not improve
  on those molecular capabilities.
- [ISOLDE](https://tristanic.github.io/isolde/) is a ChimeraX extension for
  molecular model building. Its
  [interactive molecular dynamics](https://tristanic.github.io/isolde/features-main/features-interactive-md/index.html)
  and [restraints](https://tristanic.github.io/isolde/features-main/interactive-restraints/index.html)
  are relevant precedents for manipulating molecular structures with chemical
  constraints. Its focus is model building/refinement; our proposed focus is
  preparing reusable states for animation.
- [Molecular Maya](https://clarafi.com/tools/mmaya/) is a particularly close
  precedent in another animation application. Its documented kits include
  chain alignment, gap modeling, molecular rigs, domain handles, elastic
  networks, and target-conformation morphing. The page lists older Maya version
  support, so treat it as a feature/workflow reference, not verified current
  installation guidance.
- [BioBlender's original work](https://arxiv.org/abs/1009.4801) explicitly
  explored all-atom morphing with Blender's former game engine. Its later
  [Blender 2.8 port notes](https://www.bioblender.org/2020/10/19/new-version-of-bioblender-2/)
  say that simulation capability was unavailable in that port. This establishes
  historical precedent, not a ready backend for current Blender.

A credible advantage would be faster preparation, clearer state ownership,
direct editing, and integration with PB animation. Claims of more accurate
alignment, more plausible motion, or easier use require comparative evidence.

## Proposed editor

Entry point: **Edit States…** on a protein, with a chain/domain selection carried
into the editor when invoked from that member. A single-conformation protein
must be able to enter this editor so a second state can be added.

```text
Protein States — Adenylate kinase / Chain A

STATES                 VIEWPORT                     SELECTED STATE
Open                   Active state                 Name: Closed
Closed                 Reference ghost              Source: 1AKE / A
Partly closed          Pick residues/domains         Align to: Open
                                                    Fit using: Core
+ Add from structure                                [Align]
  Duplicate                                         [Save State]
```

This is a layout sketch, not a requirement for three separate Blender editors.
A persistent panel and viewport tools can provide it without a custom editor
type or a chain of modal popups. A compact sequence strip can appear when the
user needs to inspect pairing or choose an anchor region.

### Add from another structure

1. Choose a file, PDB entry, or already imported structure/model.
2. Suggest a corresponding chain and expose ambiguity clearly.
3. Choose an alignment reference and fit region: whole matched chain, automatic
   core, or a selected domain/residue region.
4. Preview the reference as a ghost and the proposed state as solid geometry.
5. Show coverage, missing atoms/residues, substitutions, and fit statistics.
   Distinguish RMSD over the fitted atoms from deviation across all matched
   atoms; RMSD is a geometric distance measure, not a biological confidence score.
6. Name and save the state; retain source coordinates, mapping, transform, and
   provenance so the operation can be revisited.

The correspondence details should expand when needed. A clean, unambiguous match
should not require working through a large form. All states use one stable
reference frame; repeated alignment to whichever state happened to be viewed
last would introduce drift and surprising changes.

### Author a state later

Duplicate a state, pin a core domain, and manipulate another domain with a
rotation handle. Show which region is fixed and which can adapt. Save the result
with an **Authored** origin label; show the derived source and editing method in
its details.

Blender can provide handles, selections, armatures, masks, undo, and display.
Maintaining a peptide chain across a moving hinge requires additional molecular
handling. Generic deformation weights can stretch bonds or distort residues.
A future solver should operate on molecular coordinates, preserve chosen rigid
regions, constrain linkage geometry, and report clashes. Energy minimization can
help repair local geometry, but it does not establish a biologically occupied
state or the physical transition pathway.

Free sculpting is a possible advanced illustrative tool. It should not be the
default mechanism for generating atomic conformations. Shape keys can store
results; they do not supply molecular validation.

## A concrete design exercise: adenylate kinase

[4AKE](https://www.rcsb.org/structure/4AKE) provides unligated adenylate kinase;
[1AKE](https://www.rcsb.org/structure/1AKE) provides the inhibitor-bound complex.
Use one corresponding protein chain from each entry to explore open/closed
domain motion. Treat ligands as separate components of the scene.

Proposed experience:

1. Import 4AKE chain A and name its state **Open**.
2. Add 1AKE chain A as **Closed**; inspect mapping and alternate locations before
   creating a compatible state.
3. Fit on a chosen core region and observe the remaining domain displacement.
4. Save and create/use a Morphset for that chain.
5. Choose Open at frame 1, Closed at frame 60, and Open at frame 120 in the usual
   Create/Edit Keyframe dialog.
6. In a later authoring version, duplicate a state and make a **Partly closed**
   illustrative state with a domain handle. Keep its authored origin visible.

This is a proposed acceptance scenario, not a claim that current PB can execute
the cross-PDB state-creation steps. The research did not run this new workflow
or verify full atom compatibility between those files.

## Decisions required for a trustworthy implementation

- **Fit region and moved group are separate.** Aligning one core may move a
  whole chain or assembly with one rigid transform. Fitting every chain
  independently can erase a real change in subunit arrangement.
- **Atom correspondence is a hard boundary.** Chain labels, residue numbering,
  insertion codes, alternate locations, missing loops, mutations, and ligands
  need explicit handling. Do not fabricate absent coordinates silently.
- **Partial compatibility needs an explicit scope.** A fully matched domain
  may be usable when the whole protein is not. Report that domain scope. A
  backbone-only animation would be a separately identified representation;
  it must not imply complete all-atom states.
- **Preserve stable state identities.** Renaming/reordering should not alter
  keys. Editing a state should identify which animation uses it. Duplicate is
  the natural operation for making a variant without altering existing shots.
- **Keep placement independent.** State coordinates are local to the molecule;
  puppet motion and scene placement remain separate transforms.
- **Keep molecular coordinates authoritative.** Display style, ribbon smoothing,
  and B-factor motion must not be accidentally baked into an imported state.
- **Preserve provenance.** Imported, transformed, interpolated, and manually
  authored coordinates carry different evidence. An NMR MODEL index by itself
  supplies no temporal ordering.

## Relationship to current ProteinBlender

Source inspection shows useful groundwork:

- `core/conformation_library.py` stores protein-owned coordinate sets with
  stable IDs and source metadata. `compatible_coordinates()` currently requires
  exact atom identities across the complete molecule; `add_coordinates()`
  requires a position for every atom.
- `core/structural_alignment.py` contains sequence pairing, rigid Kabsch fitting,
  core fitting, explicit chain pairing, and anchor-region support.
- `core/model_morphsets.py` captures the protein's available models as snapshots
  and the existing keyframe UI selects them by identity.
- The current user workflow in `docs/morphsets.md` still requires multiple
  imported models and external alignment. Older state-authoring operators are
  deliberately absent from the registered interface, as checked by
  `tests/integration/test_conformation_library.py`.

These are reusable foundations, not a completed authoring feature. Adding or
editing library states also needs deliberate synchronization of existing
Morphset snapshots while preserving keys, member controls, and puppet parenting.
The older research document describes a previous UI that the user rejected;
its proposed interface should not be treated as a current product requirement.

## Recommended scope and evaluation

**First milestone:** named state library; add an existing compatible chain
conformation; explicit chain mapping; rigid alignment to a common reference or
selected core; clear mismatch feedback; save/reopen; existing Morphset keyframes.

**Second milestone:** duplicate and edit states through domain handles, with
molecular linkage constraints and geometry checks. Keep it within the same
state editor. This is a substantial modeling feature with its own validation.

Evaluate with real users on three tasks: a compatible pair, a pair with missing
residues/alternate locations, and a multichain assembly whose relative geometry
must survive fitting. Compare completion time, incorrect chain assignments,
recovery from mismatches, and whether users understand what each keyframe
selects. Inspect intermediate molecular geometry separately from interface
usability. Test chain ownership, independent domain timing, puppet transforms,
undo/cancel, source immutability, and saved-file restoration.

The product hypothesis is that a named state library with direct viewport
editing makes molecular animation preparation understandable. Test that small
workflow before expanding into general molecular modeling.
