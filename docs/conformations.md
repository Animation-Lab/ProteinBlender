---
layout: default
title: Conformational Transitions
---

# Alignment and morphing

## Browsing a protein's conformations

Click **Conformations (N)** on a protein's PB Outliner row, or choose **Browse
Conformations** from its right-click menu. The browser stays open below the
Outliner. It shows the file/model provenance and the current conformation name.

- Choose a model from the dropdown, use **Previous / Next**, or drag **Browse**.
  This changes the displayed coordinates immediately without changing the scene
  frame, object placement, colors, chain/domain selections, or representation.
- Rename a conformation with **Name**. Its original source and model number stay
  attached to it.
- **Compare with** chooses a fixed reference. **Keep steady** aligns each model
  to that reference using the stable core, the whole protein, or entered anchor
  residues such as `A:1-30`. **Original placement** shows the stored coordinates.
  An invalid anchor leaves the last valid geometry visible and explains the error.
- **Show transparent reference** adds a gray reference cartoon. **Highlight
  motion (Cα markers)** places orange markers at alpha carbons displaced by at
  least the chosen threshold in Å. Compare in cartoon representation for a clear
  view of these backbone markers. Comparison helpers are for the viewport and
  are excluded from renders; closing the browser removes them.
- Choose a conformation and click **Set as Start**, then another and **Set as
  End**. **Animate Between Conformations…** opens the existing alignment/morph
  dialog with those endpoints filled in. The created morph owns its coordinates,
  appears as an independent sibling in the Outliner, and supports end frames,
  return frames, and repeated breathing cycles.

**Add from File…** and **Add from PDB…** append compatible conformations to the
same library. Atoms are matched by chain, residue number, insertion code, residue
name, atom name, and element, so a different atom order is acceptable. The entire
batch is checked before adding anything. Missing atoms, extra ligands, changed
residue numbering, or duplicate identities require importing a separate protein
and using **Align & Morph** for its sequence-based partial matching.

**Capture Current Pose…** saves a named coordinate snapshot in this library,
including native chain/domain and puppet transforms. Captured states compensate
for the current domain transforms when displayed, so the pose is not applied
twice. **Extract as Protein** creates a separate protein at the same placement
with the displayed conformation and presentation; move that protein for a
side-by-side comparison. Stored coordinate sets are immutable and saved inside
the `.blend`, including states that are not currently displayed.

### Importing model ensembles and assemblies

NMR ensembles are detected in PDB and mmCIF files, including compressed files.
Each model becomes a named conformation under one protein. Existing biological
assembly controls remain separate. Legacy `.pdb1`, `.pdb2`, etc. assembly files
combine their model copies into one assembly, with distinct chain labels.
For an ambiguous local file, choose **Multiple models → Conformations** or
**Assembly copies** in the file browser. The importer does not infer a trajectory
or conformational states from coordinate similarity. Alternate atom locations
continue to use the parser's existing alternate-location policy and do not become
whole-protein states.

An NMR ensemble is a collection of models consistent with experimental
restraints. The numbering does not establish a chronological motion path; the
animation order and timing are authored by the user. See [RCSB's NMR guide](https://pdb101.rcsb.org/learn/guide-to-understanding-pdb-data/methods-for-determining-structure).

Files imported before the library feature can open a one-state library from
their saved geometry. Reimport the original ensemble to obtain all its models.
Legacy domains with separate atom meshes and proteins with existing shape keys
need a separate fresh import for browsing.

## Morphing separately imported proteins

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
