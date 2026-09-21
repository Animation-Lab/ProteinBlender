---
layout: default
title: Morphsets
---

# Morphsets

A **Morphset** groups named morphs. Each **morph** defines the chains/domains that
move together and their saved **Start**, **End**, and optional intermediate states.
Each morph has its own keyframe entries. Different proteins can move together
or at different times; morphs using the same chain contribute to one animation.

## Define the shapes

1. Align your structures before exporting the PDBs. ProteinBlender preserves
   those coordinates and does not align structures in the UI.
2. Import your proteins, including any multi-model PDBs.
3. In **Builders**, choose **Create Morphset** below **Create New Assembly** and name it.
4. In its editor, click **Add Morph**. Name the morph, select its members, and
   choose the model and state name for **Start** and **End**.
5. Add more morph rows for the same protein or for other proteins and chains.
   Use **−** to remove a morph and its keys. Its members return to their proteins
   once no other morph uses them. Undo is available.

Each new row starts with checked members, or prefers an unassigned protein or
chain if one is available. You can select a protein that is already used by
another morph. When continuing with the same members, Start defaults to the
previous morph's End model. You can also add intermediate shapes within one
morph using **Edit → Add Model / State**.

Members can be an entire protein, one chain/domain, or several checked PB
Outliner rows. For a separate destination structure, change the End **Members**
selector. The number of members and atom identities must match between states;
chain labels may differ. Multiple morphs can use the same chain/domain; their
keyframes drive one animated member rather than creating overlapping copies.

Participating source members move beneath the Morphset in the PB Outliner.
The Morphset's pencil opens its list of morphs. A morph's pencil opens its named
states: use **Add Model / State** to capture an intermediate model. It starts
with the morph's existing members, so you can choose another PDB model without
reselecting the protein. A state's pencil opens **Edit Model / State** to change
its model, source members, or name. Start and End are editable too. Existing
keyframes keep their times and use the updated state; Cancel leaves it unchanged.
The state list and Keyframe menu show model names such as **Model 4**.
Remove an intermediate state with **−** after removing or changing
any keys that refer to it. Start and End remain the endpoints.

### Example: 1D3Z models 1 → 4 → 8

1. Create one Morphset and add a morph named **1 → 4** for **1D3Z**, with
   **Model 1** as Start and **Model 4** as End.
2. Click **Add Morph** again. Select the same **1D3Z** protein, name the row
   **4 → 8**, and choose **Model 4** as Start and **Model 8** as End.
3. Open **Create/Edit Keyframe** at each frame below and check the listed rows:

   | Frame | 1 → 4 | 4 → 8 |
   | --- | --- | --- |
   | 1 | Start — Model 1 | Unchecked |
   | 45 | End — Model 4 | Start — Model 4 |
   | 90 | Unchecked | End — Model 8 |

The shared endpoint at frame 45 is allowed because both rows specify the same
shape and visibility. Different shapes or visibility for the same member at
the same frame produce an error naming the conflicting rows; existing keys
remain unchanged.

Alternatively, define one morph with Start Model 1, End Model 8, and an
intermediate Model 4 through **Edit → Add Model / State**. Key those three
states at frames 1, 45, and 90. Both workflows produce one animated protein.

Older Morphsets without saved model names show **Keep saved coordinates** when
edited. Choose a model to replace that snapshot, or leave it unchanged to keep
the saved shape. Internal identifiers are not editable fields.

## Choose a shape at each keyframe

1. Open **Create Keyframe** at frame 1.
2. Check the morphs to record, then select **Start — [state name]** for each.
3. At frame 60, check the desired morphs and choose **End — [state name]**.
4. Play or scrub: coordinates interpolate between the keyed states.

An unchecked row leaves that morph's existing animation alone. Each checked row
records its state and visibility at the selected frame. A state selector also
lists any intermediate states you have defined; key those at the frames when
you want to reach them.

- **Different timing:** key one morph's End at frame 30 and another's at frame 60.
- **Hold:** repeat the same state at two frames.
- **Reverse:** key End, then Start at a later frame.
- **Remove one key:** use the key icon on that morph's row at an existing keyframe.
- **Remove the whole frame:** use the Keyframes list's delete button.

The eye toggle controls the morph's visibility at that frame. Expand the arrow
for individual member checkboxes. Visibility changes at the keyed frame and
holds until the next key; the keyframe checkbox itself does not hide the protein.

During playback, animated geometry replaces the participating originals.
Removing a morph's last key restores its original members unless another morph
still animates them. Removing one morph leaves the other morphs' keys intact.
Definitions, snapshots, styles, member
ownership, and animation save with the `.blend` file.

Files using the previous snapshot-per-Morphset design are converted on load:
compatible snapshots become named states in a morph and retain their keyframes.
Older legacy Align & Morph animations are not automatically converted.

## Style and temperature motion

Change a participating protein's style through its edit pencil. Its animated
members update immediately and retain their style when keys change or the file
is reopened. Each animated member uses one representation throughout its morph.

Enable **B-factor (Temperature) Motion** in the source protein's edit dialog to
add smooth movement weighted by its imported B-factors. Disabling it restores
the underlying geometry. The motion is deterministic when scrubbing/rendering
and is applied before the molecular representation is built.

This is an illustrative effect. B-factors describe displacement and disorder,
not a measured trajectory; AlphaFold files often store confidence in that field.
The amplitude uses the isotropic relation in the
[wwPDB B-factor definition](https://mmcif.wwpdb.org/dictionaries/mmcif_rcsb_nmr.dic/Items/_atom_site.B_iso_or_equiv.html).
Missing, negative, and nonfinite B-factors give zero displacement.
