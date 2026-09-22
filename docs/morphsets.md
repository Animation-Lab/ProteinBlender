---
layout: default
title: Morphsets
---

# Morphsets

A **Morphset** identifies the chains/domains that change shape together.
**Keyframes** choose their model and the frame at which they reach it.
The available models come from the imported protein; you do not define
Start/End pairs or add individual morphs.

## Create a Morphset

1. Import a protein containing multiple conformation models, such as **1D3Z**.
2. Check its chains/domains in the PB Outliner, or choose them in the next dialog.
3. In **Builders**, click **Create Morphset**, below **Create New Assembly**.
4. Choose the protein, check the members, and give the Morphset a name.
5. Click **OK**. The Morphset appears **under that protein**, with the selected
   chains/domains beneath it. Its models are immediately available in keyframes.

Members in one Morphset use the same model and timing. Use separate Morphsets
for chains/domains that need independent timing. Each member can belong to one
Morphset; selecting a chain and an overlapping domain is not allowed.

The dialog explains unavailable members. This workflow requires at least two
imported models, matching atom identities, and valid coordinates for the selected
members. Puppet-controlled members must be removed from their puppet first.
ProteinBlender preserves the supplied coordinates; prepare alignment externally.
Adding or authoring new states is outside this workflow.

## Choose a model at each keyframe

1. Go to a frame and click **Create/Edit Keyframe**.
2. Check the Morphset's row and select its model.
3. Confirm, then repeat at another frame.

For **1D3Z**, one Morphset can use:

| Frame | Model |
| --- | --- |
| 1 | Model 1 |
| 50 | Model 3 |
| 75 | Model 8 |
| 100 | Model 9 |

The chain interpolates directly between these choices, including Model 3 to
Model 8 between frames 50 and 75. Intermediate model numbers are not visited
unless you key them. The dialog shows the previous and next keys for a checked
Morphset. Creating keys in a different order produces the same animation.

- Before the first key and after the last key, the endpoint model holds.
- One key holds one model. Two different keyed models create a transition.
- To pause, key the same model at two frames.
- To reverse, choose an earlier model at a later frame.
- Edit a key to change its model; remove it to interpolate between its neighbors.
- An unchecked row leaves that Morphset's existing animation alone.

The eye controls visibility at that frame. Expand the arrow to control individual
members. Visibility changes at the keyed frame and holds until its next key.
The keyframe checkbox records animation; it does not hide or show the protein.

## Edit or remove a Morphset

Each child chain/domain keeps its **color swatch**, **Edit Pivot** control,
**Edit** pencil, **Select** checkbox, and **eye**. The swatch recolors the chain
directly. Edit Pivot places its rotation origin without moving the atoms; the
pivot survives keyframe edits, membership changes, and save/reopen.
Edit changes its name, color, and representation, including its animated
geometry. Select targets that visible geometry. The Outliner eye hides the member
in the viewport and render across the timeline; showing it again restores its
keyframed visibility without changing the keys.

Right-click a Morphset for **Edit**, which opens its name and membership dialog.
The menu omits Blender's property-editing commands (drivers, keyframes, and
defaults); Blender still supplies its standard Online Manual link.

Its Outliner pencil edits the name and members. Membership changes apply to all
its existing keyframes. Remaining members keep their visibility keys; newly added
members follow the group's visible/hidden state. Removed members return to their
protein. Models and keyed times retain their identities.

Moving the parent protein moves the Morphset. Protein style and temperature-motion
controls apply to its animated members. Removing the Morphset removes its shape
animation and restores its members to the protein. Undo restores the Morphset and
its keys. Membership, snapshots, hierarchy, and animation save in the `.blend`.

Existing projects using the older morph-pair format retain their saved states
and animation. Those states remain selectable in Create/Edit Keyframe. New
Morphsets use the member-and-model workflow described here.
