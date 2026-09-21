---
layout: default
title: Conformations and Morphsets
---

# Conformations and Morphsets

A **Morphset** is a protein, chain/domain, or collection of members that shares
one library of structures. Choose a **state** at each movie keyframe. ProteinBlender
animates between those choices; you do not need to define Start/End morph pairs.

## Quick start: 1D3Z

1. Import **1D3Z** (ubiquitin, ten NMR models).
2. Under **Builders**, below **Create New Assembly**, click **Create Morphset**.
3. Choose **1D3Z · all chains**, or check its chains/domains in the PB Outliner.
   Optionally name the Morphset. Click **OK**. All ten models are now available.
4. At **frame 1**, click **Create Keyframe**, check the Morphset, and choose
   **Model 1**. Leave **To next key: Morph**. Confirm.
5. At **frame 45**, choose **Model 4** in the same way.
6. At **frame 90**, choose **Model 8**. Play the timeline.

Models 1 → 4 → 8 are movie choices you made. The model numbering in an NMR
ensemble does not establish the order or speed of molecular motion.

## Browse before animating

**Animate Scene → Conformations** contains the state library. The Morphset’s
PB Outliner pencil opens the same browser in a popup. Collapse the Conformations
header when you want more space for the keyframe list.

- Select a state in the scrollable list. Its source appears alongside its name.
- **Preview State** shows the saved coordinates in the viewport without adding
  or changing any keyframes. **Return to Timeline**, scrubbing, or saving ends
  the preview. Editing the protein or replacing/removing a state also restores
  the timeline. Rendering continues to use the keyed animation.
- **Keyframe State…** opens the usual keyframe editor with that state checked.
  You can set the frame and include other scene objects in the same keyframe.
- **+** adds an aligned structure or another imported model as a named state.
- The **state pencil** changes its source, model, or name. Existing keys retain
  their times and use the updated state.
- **−** removes an unkeyed state. First and last library entries have no special
  status; keep at least one state. Change/delete keys before removing a state
  that they use. Undo is available.

Adding the same members through Create Morphset again selects their existing
library. To extend their animation, add states or keys to that library.

## What happens between keyframes?

Each key has a **To next key** setting:

| Setting | Result |
|---|---|
| **Morph** | Atom coordinates interpolate toward the next keyed state. |
| **Hold, then switch** | Keep this structure until the next key, then switch immediately. |

For example, if **Model 3** is keyed at frame 50 and **Model 8** at frame 75:

- **Morph** at 50 makes the transition from Model 3 to Model 8 over frames 50–75.
- **Hold, then switch** at 50 keeps Model 3 through frame 74 and shows Model 8 at 75.

The editor shows the previous and next keyed states and frames. Repeat a state
at a later key to pause before continuing. Choose an earlier state to reverse
or revisit a conformation. Before the first key and after the last, the endpoint
state is held. Unchecked subjects retain their existing animation.

## Complexes, chains, and visibility

Members in one Morphset share a state choice. For a multi-model complex, choosing
Model 6 selects the corresponding coordinates of every included chain. For example,
**2BBN** has 21 NMR models of calmodulin with an MLCK peptide: creating a Morphset
from all chains lets you browse each deposited complex as a unit.

Create separate Morphsets for subjects that need independent state choices or
timing. You can check several in the same Create/Edit Keyframe dialog. Choosing
models independently for interacting partners creates a composite illustration;
it may not correspond to any deposited complex.

**Visible** controls the whole subject. Expand **Members** for chain/domain
visibility. Visibility switches at the keyframe and is held until the next key.
The outliner directs animated visibility edits to Keyframes.

## Using different structures

Import the structures, then use **+ Add State** to choose the matching source
protein/chains/domains and model. Member counts, atom identities, residues, and
member order must match. Chain letters can differ. Prepare matching, aligned
PDBs before import; ProteinBlender does not align them automatically.

Interpolation moves atoms along straight lines. Intermediate shapes are
illustrative, with no energy minimization, collision avoidance, kinetic model,
or guarantee of a physically valid molecular pathway. Large conformational
changes may need prepared intermediate structures.

Rigid placement changes use **puppets and poses**. B-factor motion is a separate
illustrative motion control in protein editing. Neither changes the state library.

## Existing projects

Older Morphsets are converted on load. Compatible transition pairs sharing the
same members become a single state library, retaining their keys and geometry.
Independent subjects become separate Morphsets. Custom state names and coordinate
snapshots are retained. Exceptional overlapping or differently transformed
subjects remain separate to preserve their original animation.

Removing a Morphset removes its animation and returns its members to their
proteins. Other subjects retain their keys. Undo restores the removed library.

For the rationale and primary sources, see the
[research and design notes](design/conformation-workflow.md).
