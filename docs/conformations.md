---
layout: default
title: Conformational Transitions
---

# Structural alignment and conformational playback

Import two conformations, then click **Align & Animate** in **Animate Scene**.
The same action is available from a protein's Edit pencil.

1. Choose the **Start structure** and **End structure**. The transition stays in
   the starting protein's coordinate frame.
2. Choose **Whole protein**, or a specific chain from each structure. Whole
   protein matches chains by sequence; inspect the displayed chain assignments.
3. Review the paired residue count, sequence identity, coverage, and RMSD in Å.
   **Stable core** fits the similar regions while allowing moving regions to
   differ. **All paired residues** includes every matched alpha carbon in the fit.
4. Set the starting frame and duration in seconds, then **Create Transition**.
5. The playback popup opens automatically. Scrub **Start → End**, compare the
   **Start** and **End**, or **Play** a repeating forward/backward preview.
   **Done** applies timing, color, and representation changes. **Cancel** restores the
   frame at which the popup opened. Closing either way stops preview playback.

The transition appears as a child of the starting protein in the PB Outliner.
Its pencil reopens playback; its checkbox selects it; its eye controls visibility;
its trash button removes it. There is no additional permanent panel. Preview
playback leaves the scene's playback range alone. The transition's saved animation
also evaluates during ordinary scene animation and rendering. Creating or retiming
one extends the scene end frame if necessary.

Original structures are initially hidden in both the viewport and render. Uncheck
**Hide original structures** and press Done to restore their prior visibility.
Removing the transition restores it too; when multiple transitions hide the same
original, the original remains hidden until all of those transitions release it.
Deleting the starting protein also deletes its transitions. Deleting the ending
protein leaves the saved transition usable.

## What is being compared

This workflow compares **imported protein coordinates**, rather than puppet/domain
poses, generated assembly copies, or molecular dynamics frames. Moving, rotating,
or scaling an imported protein in the scene does not change its reported RMSD.
The transition inherits the starting protein's transform.

Residues are paired by global protein sequence alignment (BLOSUM62, affine gap
penalties −10/−1, free terminal gaps). Residue numbering and insertion codes are
preserved; renumbering does not prevent a sequence match. Whole-protein matching
uses a one-to-one chain assignment. Chain labels resolve otherwise equivalent
sequence scores; this is a suggestion to inspect, especially for homomers.
Different chain counts can leave chains unpaired, reflected in the coverage.
For a chosen chain pair, only those chains appear in the transition.

The fit is a proper rigid Kabsch superposition of paired Cα atoms. Stable-core
fitting iteratively excludes distant pairs above 2 Å, retaining at least half
of the paired residues and at least three non-collinear points. Both the final
fit RMSD and the RMSD of **all paired Cα atoms after that same fit** are shown;
a low core RMSD alone does not imply the whole protein is similar.

Playback includes shared protein atoms by atom name and element. At substitutions,
only shared backbone atoms are retained. Unmatched residues/atoms, solvents,
ligands, and nucleic acids are omitted from the transition copy. Original
structures retain all their imported data. The initial workflow requires at least
three matched residues, 30% sequence identity per chain pair, and a non-degenerate
fit. This is sequence-guided superposition, not a general fold-search method for
distantly related proteins.

Intermediate coordinates use Cartesian interpolation. They illustrate the change
between endpoints and **can distort bonds and pass through clashes**; they do not
represent a simulated or experimentally established pathway. Cartoon is the
starting representation. Surface, spheres, and ball-and-stick are available in the playback
popup; detailed atomic interpretation should use the endpoint structures.

Cartoon playback keeps ribbon orientation choices consistent with the starting
structure, preventing arrows from suddenly flipping as the conformation changes.
The ribbons still bend and move with the atoms. Opening an older transition's
pencil applies this improvement automatically; new transitions include it.

Atom identities, including insertion codes, are stored in newly imported
structures so alignment can be created after saving and reopening a `.blend`.
An older saved file that lacks this metadata may require re-importing the two
structures. Existing unsaved imports with complete molecular arrays remain usable.

## Example

Import PDB **1AKE** and **4AKE** (adenylate kinase), choose **Chain A** in both, and
create a transition. They share 214 paired residues. Stable core emphasizes the
moving lid; all-residue fitting gives a different, explicitly reported frame of
reference. This pair is also used in the official
[PyMOL morphing tutorial](https://pymol.org/tutorials/moviemaking/).
