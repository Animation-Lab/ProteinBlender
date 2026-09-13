---
layout: default
title: Conformational Transitions
---

# Alignment and morphing

Import two conformations, then click **Align & Morph** in **Animate Scene** or a
protein's Edit dialog.

1. Choose the **Start structure** and **End structure**, then whole proteins or
   one chain from each. Whole-protein mode pairs chains by sequence. **Chain
   pairing** can override it, for example `A:B,C:D`.
2. Leave residue fields empty for all residues, or enter inclusive ranges such as
   `1-40,65-76` for a chosen chain and `A:1-40,B:10-50` for whole-protein mode.
   Insertion-code variants at an included residue number are included together.
3. Choose the reference frame: **Stable core**, **All paired residues**, **Chosen
   anchor region**, or **Current placement**. An anchor is specified in start
   residue numbering and must include at least three non-collinear matched Cα
   atoms. Current placement skips superposition and uses the objects' transforms.
4. Inspect the sequence match, coverage, chain assignment, and RMSD in Å.
   **Preview Regions and Alignment** shows morphing atoms in blue with optional
   translucent gray surrounding regions. Change settings and use **Update
   Preview**. Cancelling removes the preview and restores visibility and timing.
5. Set **Start frame** and **End frame**. Optionally enable **Return to start**,
   set a later **Return frame**, and enable **Repeat breathing cycle**. Disable
   **Ease in and out** for constant interpolation speed.
6. Click **Create Morph**. The playback dialog opens. Scrub **Start → End**, jump
   to either endpoint, or **Play**. Timing, color, representation, context
   visibility/opacity, and original visibility are applied with **Done**.
   Cancelling this playback dialog restores its opening frame; either exit stops
   preview playback.

The morph is an independent top-level PB Outliner entry with no children. Its
pencil opens playback; its checkbox selects it; its eye hides it; its trash
button deletes it. Deleting either input protein leaves the morph usable. The
morph initially copies the start protein's placement and then moves independently.
Older saved morphs become independent when the outliner is rebuilt.

Original structures are initially hidden in viewport and render. Uncheck **Hide
original structures** and press Done to restore prior visibility. Removing the
morph restores it too. If multiple morphs hide an original, it stays hidden until
all release it. Multiple independent morphs can have different regions, chain
pairs, timing, and colors. This is not an ordered A→B→C state editor.

Animation is saved as shape-key keyframes and evaluates during ordinary scene
playback and rendering. Creating or retiming a morph extends the scene end frame
if necessary. The preview obeys its saved return/repeat settings. A 10→30→50
linear breathing cycle reaches the end at 30, returns to the start at 50, and
reaches the end again at 70 when repeating. Invalid frame order is rejected before
existing animation is changed. The old script-only `duration` argument remains
supported; the visible controls use frames.

## Capturing an authored conformation

Use **Capture Conformation** in Animate Scene or a protein's Edit dialog. Pose
native chains/domains, including those controlled by a puppet, choose the protein,
and name its new conformation. Capture creates an independent imported coordinate
snapshot at the current frame without changing the original pose. Select the
snapshot as an endpoint in Align & Morph. Use Current placement when that authored
placement should be retained, or an anchor to hold one region stationary.

Capture supports native chain/domain transforms. Ambiguous duplicate domains,
legacy domains with separate meshes, arbitrary mesh deformers, and shape-key
sources are rejected rather than silently capturing the wrong geometry. This is
coordinate capture, not an atom-sculpting or force-field simulation tool.

## What the algorithm does

Outside Current placement, matching uses stored imported atom coordinates. Pose
changes must first be captured to become endpoint coordinates. Moving an imported
protein in the scene does not change the RMSD for superposed fits.

Residues are paired by global sequence alignment: BLOSUM62 scores, affine gap
penalties −10/−1, and free terminal gaps. Numbering and insertion codes are retained;
renumbering does not prevent sequence matching. Whole-protein matching uses a
one-to-one chain assignment. Chain labels break equivalent sequence-score ties,
so inspect homomer assignments. Different chain counts can leave chains unpaired.

Thirty percent means **sequence identity among aligned nongap residue pairs**, per
chain pair. It does not measure overlap, motion amplitude, or confidence. At least
three amino-acid residue pairs are required. A rigid fit additionally requires
three non-collinear alpha carbons. Current placement skips that rigid fit.

Superposition uses a proper rigid Kabsch fit. Stable core iteratively excludes
pairs more than 2 Å apart, retaining at least half the matched residues and at
least three points, for at most 30 iterations. The dialog reports core-fit RMSD
and all-paired-Cα RMSD under the same transformation. Low core RMSD alone does not
imply a similar whole protein.

The morph retains shared protein atoms by name and element. At substitutions,
only shared backbone atoms remain. Unpaired atoms/residues, solvents, ligands, and
nucleic acids are omitted from the moving copy. Optional context includes unmatched
source protein atoms, rendered as a gray cartoon; it is reference geometry that
stays in the starting conformation. Original imported data is preserved.

Intermediate coordinates use Cartesian interpolation. Easing changes timing;
it does not constrain chemistry. Intermediate frames can distort bonds and pass
through clashes and are not a simulated or experimentally established pathway.
Cartoon, surface, spheres, and ball-and-stick are available. Ribbons retain the
starting orientation convention while bending with the atoms to avoid sudden
arrow flips. Detailed atomic interpretation should use the endpoints.

Atom identities are stored on newly imported structures and captured conformations
so matching remains available after saving and reopening a `.blend`. Older inputs
without these identities may need reimporting. Existing morphs own their endpoints
and can play without the original PDB files.

## Example

Use bundled **1AKE** and **4AKE**, chain A (adenylate kinase): 214 paired residues.
Compare stable-core and all-residue fitting, then select `1-40` as an anchor with
**Chosen anchor region**. To emphasize a lid region, try `122-159` in both residue
fields and enable surrounding regions. Anchors must be within the selected match;
leave the residue fields empty when fitting against a separate core region.
