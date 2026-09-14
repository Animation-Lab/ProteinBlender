---
layout: default
title: Conformational Transitions
---

# Alignment and morphing

## One Morph popup

Use **Morph** in Animate Scene or a protein's visual editor. A protein with
multiple conformations also has an icon in the PB Outliner that opens this same
popup with that protein selected. An existing morph's pencil opens the same
interface with its saved timing and playback controls.

1. Choose **From** and **To**. Both menus list proteins and their named states.
   You can choose two states of one protein, two separate proteins, or stored
   states from different proteins. The clicked protein is filled in automatically.
   **Current structure** uses the displayed coordinates; named states use stored
   coordinates even when another state is currently displayed.
2. For simple state browsing, use the **eye button** beside From or To. It shows
   that state on its protein without moving the playhead or creating a morph.
3. Set **Start frame** and **End frame**. Optionally enable **Return to start**,
   choose the return frame, and enable **Repeat** for a breathing cycle.
4. Click **Apply**. Preview the motion with the **From → To** slider, endpoint
   buttons, and **Play** in this popup. Change settings and Apply again to update
   the preview. An invalid Apply leaves the last valid preview intact.
5. Click **Create Morph** to keep the preview as one independent Outliner object.
   No second dialog opens. Cancel removes the temporary morph and restores the
   opening frame, playback range, and original visibility. States shown with the
   eye buttons stay applied; temporary comparison helpers are removed.
6. Reopen a saved morph with its pencil to scrub, play, or change timing and
   appearance. **Apply** commits edits without closing; **Done** applies and
   closes. Cancel discards pending fields, retains prior Apply results, stops
   playback, and restores the opening frame. Saved endpoints belong to the morph,
   so this editing workflow works after either source protein is deleted. To
   choose a different endpoint pair, create a new morph.

**Advanced** starts collapsed. It contains chain/residue selection, alignment,
easing, surrounding-region opacity, representation, color, original visibility,
and optional match details. Alignment and residue selection define new morph
endpoints; existing morphs use their stored endpoints. Residue fields accept
`1-40,65-76` for a selected chain or `A:1-40,B:10-50` for whole proteins.
Alignment can use the stable core, all paired residues, a chosen anchor region
such as `A:1-30`, or current placement. Chain pairing is automatic unless you
enter pairs such as `A:B,C:D`.

When both endpoints are states of the same protein, Advanced also offers a
transparent reference and orange motion markers. Use an eye button to show one
state; both use From as the fixed alignment reference. Show To to compare the
motion against From. The marker threshold is in Å; Cartoon
representation makes these backbone markers easiest to see.

**Library tools**, inside Advanced, includes renaming, provenance, Add from
File/PDB, Capture Pose, and Extract as Protein for the From protein. These named
actions take effect immediately. Capture and extraction use the displayed protein
pose. Stored states keep their original source/model provenance and are saved
inside the `.blend`, including states that are not currently displayed.

Added files must have compatible atom identities: chain, residue number,
insertion code, residue name, atom name, and element. A different atom order is
acceptable; the entire batch is checked before anything is added. For structures
with different numbering or atom content, import separately and choose them as
From/To for sequence-based partial matching.

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

Files imported before the library feature retain their saved geometry.
Reimport the original ensemble to obtain all its models and the browsing icon.
Legacy domains with separate atom meshes and proteins with existing shape keys
need a separate fresh import for browsing.

## Morph objects and matching

The morph is an independent top-level PB Outliner entry with no children. Its
pencil opens Morph; its checkbox selects it; its eye hides it; its trash
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
snapshot as an endpoint in Morph. Use Current placement when that authored
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
