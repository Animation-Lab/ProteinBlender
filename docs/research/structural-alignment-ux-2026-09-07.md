# Structural alignment and playback: UI decisions

Reviewed official documentation on 2026-09-07. This is a documentation comparison
and a tested ProteinBlender implementation, not a usability study with biochemists
or a runtime comparison of the other applications.

| Tool | Documented workflow | Design implication for ProteinBlender |
|---|---|---|
| [ChimeraX Matchmaker](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/matchmaker.html) | Sequence-guided chain pairing, optional explicit chain pairs, iterative fitting, RMSD and sequence-alignment output. | Show actual chain assignments and matched-residue coverage next to fit quality; separate core-fit RMSD from all-pair RMSD. |
| [ChimeraX morph](https://www.rbvi.ucsf.edu/chimerax/docs/user/commands/morph.html) | Superpose structures first, then create a morph trajectory; a slider provides playback. Supports more sophisticated rigid-group/internal-coordinate interpolation. | Combine preparation and creation, then provide an immediately usable scrubber. Clearly describe our initial Cartesian interpolation and its geometric limits. |
| [PyMOL movie tutorial](https://pymol.org/tutorials/moviemaking/) | Object actions first align, then generate a morph toward another object. The resulting multistate object participates in movie animation. | Keep creation accessible from the protein, and give the resulting transition its own persistent identity and contextual controls. |
| [Mol* measurements](https://molstar.org/viewer-docs/tips/measurements/) and [display management](https://molstar.org/viewer-docs/managing-the-display/) | Structure-oriented tools and components put actions near molecular objects and selections. | Put playback under the relevant protein rather than adding another global management panel. |

## Chosen flow

**Choose endpoints → review correspondence → create → scrub/play.** One action in
existing Animate Scene makes the feature discoverable; an Edit Protein shortcut
seeds its start structure. The creation popup names the biological intent (start
and end conformations) before presenting alignment controls. Whole-protein matching
is the default; explicit chain pairing is available without a separate wizard.

The popup computes the match without altering the scene. It presents sequence
identity, matched/total residues, chain assignment, and two clearly named RMSDs.
This removes the need to consult a console before deciding whether a match makes
sense. Invalid input leaves the scene untouched and explains what to change.

On creation, a separate transition becomes a child of the starting protein and
opens a playback popup automatically. It preserves input structures and owns its
own animation. Endpoint buttons make comparison quick; a synchronized scrubber
supports inspection; repeating forward/backward preview makes subtle movements
easier to see. Duration is expressed in seconds, with a start-frame field for
users integrating it into a larger scene. Optional match details are collapsed
when revisiting an existing transition.

## Why contextual popups, and where they stop helping

Popups suit short setup and inspection tasks and keep the established PB workspace
compact. A popup alone is insufficient for a persistent object: users need a
stable way to find the result later. The Outliner child supplies that anchor.

Blender's modal dialog temporarily limits free viewport interaction. Done closes
it so users can rotate the view, then reopen from the same child. This is an
accepted first-version tradeoff, not evidence that popups are universally better.
If user observation shows frequent close/rotate/reopen friction, the next step
should be a small floating viewport playback control, retaining the same Outliner
entry and avoiding a permanent settings panel.

Potential improvements over copying competitors' flows are design hypotheses:
fewer separate setup actions, immediate correspondence feedback, biological
endpoint names, seconds-based timing, and contextual rediscovery. The Blender
harness verifies behavior and visibility, but these still need evaluation with
biochemists before claiming improved usability.

## Scientific boundaries and later extensions

Our first implementation uses [Biotite's protein sequence alignment](https://www.biotite-python.org/latest/apidoc/biotite.sequence.align.align_optimal.html)
and a proper Kabsch fit (see the [Biotite superposition reference](https://www.biotite-python.org/latest/apidoc/biotite.structure.superimpose.html)).
It supports protein chains with a sufficient sequence match. It does not attempt
ChimeraX's secondary-structure scoring, distant-fold alignment, internal-coordinate
morphs, multi-endpoint trajectories, or dynamics simulation. The shipped dialog
identifies interpolated motion rather than suggesting mechanistic certainty.

Next extensions should follow observed needs: manually editable multichain pairing,
explicit anchor-residue/domain selection, paired sequence inspection, and
rigid-group/internal-coordinate interpolation for large hinge motions. They should
share the same contextual entry point rather than becoming separate panels.

Regression coverage includes rigid transformations, independent adenylate kinase
superposition, renumbering/insertion codes, missing residues and substitutions,
stable-core retention, actual geometry and rendered changes at three frames,
visibility ownership, deletion, save/reopen, native popup cancellation, synchronized
scrubbing/playback, and undo/redo. See [the user guide](../conformations.md).
