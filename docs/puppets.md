---
layout: default
title: Protein Puppets
---

# Protein Puppets

[Back to Home](index.html)

Learn how to create and manage protein puppets for coordinated animation and manipulation.

Watch the full tutorial:

[![ProteinBlender Tutorial](https://img.youtube.com/vi/XLPvo1Ax3G4/0.jpg)](https://www.youtube.com/watch?v=XLPvo1Ax3G4 "ProteinBlender Tutorial")

## What is a Puppet?

A **puppet** groups protein chains, domains, and Morphsets. Puppets allow you to:
- Move multiple parts as a single unit
- Apply transformations to groups
- Create coordinated animations
- Organize complex multi-protein scenes

Think of puppets as "handles" for controlling multiple protein parts at once.

## Creating a Puppet

### Step-by-Step

1. **Select items** in the Protein Outliner
   - Click checkboxes next to chains, domains, or whole Morphsets you want to group
   - You can select multiple items from the same or different proteins

2. **Open Protein Puppet Maker** panel

3. Click **Create New Puppet**

4. **Name your puppet** in the dialog that appears

5. Click **OK**

The puppet will now appear in the outliner with all selected items as members.

## Puppet Membership Rules

- **Exclusive membership**: Each chain, domain, or Morphset can belong to only one puppet
- **Morphsets stay together**: Add the Morphset itself. Its children remain controlled by that Morphset. For a partially morphed split chain, select its remaining individual domains separately.
- **Cannot puppet proteins**: Choose their chains, domains, or Morphsets
- **Cannot puppet other puppets**: Puppets cannot contain other puppets

If you try to create a puppet with items already in another puppet, you'll see an error message.

## Managing Puppets

### Selecting a Puppet

- Click the checkbox next to the puppet name in the outliner
- This selects the puppet's Empty controller object

### Moving a Puppet

1. Select the puppet in the outliner
2. Use Blender's transform tools (G, R, S) or manipulators
3. All members move together

### Adding Members to a Puppet

1. Click the puppet's **Edit** pencil in the PB Outliner.
2. Check or uncheck chains, domains, and Morphsets in **Puppet Members**.
3. Click **OK**. Members keep their current positions when joining or leaving.

Items already assigned to another puppet are disabled with an explanation.

### Animate a Morphset inside a Puppet

1. Create a [Morphset](morphsets.html) from a protein with imported models, such as **1D3Z**.
2. Add that Morphset to a new or existing puppet. Other chains, domains, and Morphsets can share the puppet.
3. In **Create/Edit Keyframe**, check the puppet to capture its movement and pose. Check the Morphset separately to choose its model at that frame.
4. At a later frame, move the puppet and choose another model. Both animations play together; each Morphset can use its own timing.

The Morphset remains under its protein and also appears as an expandable reference under the puppet, with its chains/domains beneath it. The reference controls edit the same Morphset and members.

The puppet's eye hides or shows its Morphset members too. Deleting the puppet keeps the Morphset and its model keys. Removing the Morphset releases its chains/domains into the puppet, keeping the puppet's movement keys.

### Removing a Puppet

1. Find the puppet in the Protein Outliner
2. Click the **delete (trash)** icon next to the puppet name
3. Confirm deletion

**Note**: Deleting a puppet removes the grouping but keeps all member chains, domains, and Morphsets at their current positions.

## Puppet Hierarchy in Outliner

Puppets appear in a special section at the bottom of the Protein Outliner:

```
Proteins
├─ Protein A
│  └─ Chain A
│     └─ Domain 1
└─ Protein B
   └─ Chain B

─── Puppets ───
└─ My Puppet
   ├─ Protein A > Chain A > Domain 1
   └─ Protein B > Chain B
```

Members shown under puppets are references - the originals remain in their protein hierarchy.

## Use Cases for Puppets

### Multi-Chain Complexes

Group all chains of a protein complex to move them as a unit:
1. Select all chains of the complex
2. Create a puppet called "Complex"
3. Animate the entire complex together

### Functional Units

Group domains by function:
- "Active Site" puppet with catalytic residues
- "Binding Domain" puppet with substrate-binding regions
- "Regulatory Domain" puppet

### Comparative Views

Create puppets of equivalent domains from different proteins to compare them side-by-side.

## Puppets and Poses

Puppets are essential for the pose system:
- Poses save the positions of objects in puppets
- You select which puppets to include in each pose
- See [Manage Poses](poses.html) for details

## Tips and Best Practices

### Naming Conventions

Use descriptive puppet names:
- "Kinase_Domain"
- "DNA_Binding_Region"  
- "Full_Complex"
- "Chain_A_B_C"

### Organization

- Create puppets for functional units
- Group related chains/domains
- Use puppets to simplify complex scenes

### Animation Workflow

1. Create puppets for parts that move together
2. Create poses for different conformations
3. Keyframe the poses for animation

## Troubleshooting

### Cannot Create Puppet

- **Items already in puppet**: Remove from existing puppet first
- **Nothing selected**: Select at least one chain, domain, or whole Morphset
- **Protein selected**: Cannot puppet entire proteins, select chains/domains

### Puppet Doesn't Move Members

- Check that members are actually part of the puppet (look under puppet in outliner)
- Make sure you're moving the puppet controller (Empty object), not individual members

### Members Appear Twice

This is normal - members appear both in their original protein hierarchy AND under the puppet (as references).

## Next Steps

Now that you understand puppets, learn how to:

- [Manage Poses](poses.html) - Save and restore puppet positions
- [Keyframe Animation](keyframes.html) - Animate your puppets

---

[Back to Home](index.html) | [Previous: Update Visuals](visuals.html) | [Next: Manage Poses](poses.html)

