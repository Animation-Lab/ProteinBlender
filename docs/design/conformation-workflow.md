# Conformations and animation: research and design

2026-09-20. Checkpoint before redesign: `3140e8c`.

## What the interface is for

Choose **which molecular structure to show, for which subject, at which movie
frame**. A subject may be one protein, a chain/domain, or a complex whose members
change together. A saved structure and its placement on the movie timeline are
separate decisions. Morphing is the interpolation between those decisions.

This is a design inference from the sources below and our actual 1D3Z/2BBN
workflows, not a claim that we interviewed users or established usability by
field study.

## Research findings

- Structural biologists distinguish conformations, ligand/experimental conditions,
  and kinetic pathways. Adenylate kinase can visit open/closed states repeatedly;
  a single closure is not synonymous with one catalytic event. Preserve reusable
  named states and allow revisiting them in any order. [Primary smFRET study,
  2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC5879700/).
- NMR conformer collections do not establish a time sequence. Their variation
  also reflects how well the experimental data constrain coordinates. Imported
  model numbers must remain source labels, without implying ordered reaction
  steps. [wwPDB NMR Validation Task Force](https://pmc.ncbi.nlm.nih.gov/articles/PMC3884077/).
- PDB MODEL records can encode alternate conformers or simultaneous assembly
  copies. Keep our existing import interpretation; do not automatically animate
  assembly copies. [RCSB coordinate guide](https://pdb101.rcsb.org/learn/guide-to-understanding-pdb-data/dealing-with-coordinates).
- PyMOL separates molecular states from movie frames and keys state choices
  alongside object/camera motion. Its adenylate kinase example combines a protein
  conformation sequence with a separately animated ligand. The useful independence
  is between molecular subjects; named endpoint pairs need not be authored first.
  [Official movie tutorial](https://pymol.org/tutorials/moviemaking/).
- ChimeraX accepts two **or more** structures and constructs transitions between
  neighbors. It separates prior alignment, atom correspondence, interpolation,
  and playback. Cartesian atom interpolation can distort structures; its more
  sophisticated hinge/internal-coordinate methods are a distinct capability.
  Keep our interpolation accurately described and retain externally prepared
  alignment. [Official morph documentation](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/morph.html)
  (read from the [official source mirror](https://raw.githubusercontent.com/RBVI/ChimeraX/develop/docs/user/commands/morph.html)).
- VMD treats trajectory frames as coordinate sets and offers playback, smoothing,
  and synchronized active molecules. This illustrates a separate task: showing
  a supplied trajectory, rather than inferring motion from endpoint structures.
  This redesign does not add an MD trajectory simulator/importer.
  [Official trajectory tutorial](https://www.ks.uiuc.edu/Training/Tutorials/vmd-imgmv/imgmv/tutorial-html/node3.html).

## Observed baseline in Blender 5.2

Opened the installed addon in fresh normal-profile Blender windows, loaded the
saved 1D3Z and 2BBN examples, opened the set editor, nested morph editor, and frame
50 editor, and changed one chain's state/visibility. The geometry worked, but:

1. Create Morphset initially asks for a name, then Add Morph requires two source
   and state sections before there is anything to animate.
2. Model 1 -> 4 -> 8 can be expressed by one three-state row or two endpoint-pair
   rows. Identical physical objects appear twice in the outliner and keyframe form.
3. The state picker calls the same structure Start, State, or End according to its
   library position, even when the animation revisits it or runs backwards.
4. The editor presents transition pairs but playback bridges keys across pairs.
   The user cannot see the actual neighboring states/times or request a cut.
5. A large imported ensemble requires repetitive state creation and a large dialog.
6. No separate preview makes choosing an unfamiliar model unnecessarily expensive.

## Decisions

- A **Morphset** is one animated subject: its members and reusable state library.
  Remove the user-facing nested Morph 1 / Morph 2 transition definitions.
- Creation chooses members once. PDB conformer models are available immediately.
  Other aligned structures can be added as named states. A complex can share one
  state choice; create separate subjects only when independent choices are wanted.
- A persistent Conformations browser provides a scrollable state library,
  provenance, preview/return-to-timeline, and direct access to state editing.
- Keyframe forms use one subject card: checkbox, State, visibility, and
  **To next key: Morph / Hold, then switch**. Show adjacent keyed frames/states.
  First/last states have no special status. A repeated state gives a pause;
  a Hold segment gives a deliberate discontinuity at the next key.
- Visibility stays constant until its next key, including member-level controls.
- Preview is temporary viewport-only inspection, restores timeline display on
  scrub/save/key insertion, and never creates or changes an animation key.
- Keep lighting outside the continuous Create/Edit Keyframe and keyframe list.
- Preserve the old coordinate engine and stable action bindings. Upgrade saved
  pair definitions into libraries, merge duplicate subjects when safe, and retain
  exceptional shared-member definitions if a merge would alter their animation.

## Practical examples

- [1D3Z](https://www.rcsb.org/structure/1D3Z): ubiquitin, ten deposited NMR models.
  Create once, choose Model 1 at frame 1, Model 4 at 45, Model 8 at 90. There is
  no transition-pair setup and no significance to model order beyond the author's
  movie choices.
- [2BBN](https://www.rcsb.org/structure/2BBN): 21 models of calcium-bound calmodulin
  with an MLCK peptide. Use the whole complex as one subject to preserve each
  deposited model's joint coordinates. Independent chain state choices create
  an illustrative hybrid, not a deposited complex or measured binding trajectory.

## Acceptance checks

Real Blender geometry checks for endpoints, bridges, holds/cuts, reverse visits,
visibility, styles and temperature motion; atomic errors on mismatched structures;
old-file upgrade without coordinate/key loss; transient preview cleanup; UI events,
Undo, scrolling and save/reopen; installed normal-profile Blender 5.1 and 5.2.
