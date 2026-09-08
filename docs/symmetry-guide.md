# Symmetry: concepts, controls, and structures to demo with

A reference for Create New Assembly and its PB Outliner child controls.
Part one defines the ideas, part two defines every control, part three lists structures to demo with and what each one shows off.

Every structure in part three was checked against the real files rather than picked from memory, so the operator counts quoted are what you will actually get.

---

# Part I - The concepts

## Asymmetric unit vs biological assembly

**Asymmetric unit** is what is usually in the file: the smallest piece the crystallographer had to solve.
It is frequently *not* the thing that exists in a cell.

**Biological assembly** is the real molecule: the dimer, the ring, the capsid, the filament.
It is built by repeating the asymmetric unit under a set of symmetry operations.

A file for a viral capsid may contain one or two proteins and a recipe for making the other fifty-nine copies.
Opening it without applying that recipe shows you a fragment.

## Operators

An **operator** is one instruction: rotate like *this*, move like *that*, and you have another copy.
Mathematically a 3x3 rotation plus a translation.

Every feature here comes down to a list of operators.
Where the list came from - read from the file or generated from parameters - makes no difference once it exists.

## BIOMT and mmCIF

The deposited operators live in the file.

- **Legacy PDB**: `REMARK 350` records, historically called **BIOMT** matrices.
- **mmCIF**: the `pdbx_struct_assembly_gen` and `pdbx_struct_oper_list` categories.

ProteinBlender reads both.
Downloads default to **mmCIF**, because legacy PDB cannot express a large assembly at all: it runs out of atom serial numbers at 99,999 and chain identifiers at 62.

## Point groups

The shorthand for a kind of symmetry.

| Symbol | Name | What it looks like |
|---|---|---|
| **C1** | Asymmetric | No symmetry at all |
| **Cn** | Cyclic | n copies evenly spaced around one axis - a ring |
| **Dn** | Dihedral | A Cn plus a perpendicular two-fold: 2n copies, two rings back to back |
| **T** | Tetrahedral | 12 copies |
| **O** | Octahedral | 24 copies - ferritin is the classic |
| **I** | Icosahedral | 60 copies - almost every spherical virus |
| **H** | Helical | Rise along an axis plus twist about it - filaments |

## Instances vs realized copies

The copies are **instances**: the atoms are stored once and drawn many times.
A 60-copy capsid costs one copy's worth of memory.

The tradeoff is that instances are anonymous.
There is nothing to click on, and no way to colour one subunit differently.

**Realizing** converts them into real objects, buying per-copy identity at the cost of many more objects.
ChimeraX makes exactly this tradeoff, and switches its default at twelve copies; ProteinBlender uses the same threshold.

## Why "is there symmetry" is subtler than it sounds

Nearly every deposited structure carries an assembly record.
For a monomer that record is a single **identity** operator, which is the asymmetric unit under another name.

So the deposited-assembly picker does not ask "does this file mention an assembly".
It asks "does this file describe an operator that would put something new on screen".
Structures failing that test show an explanatory message in the Assembly dialog, because building an identity-only assembly would visibly do nothing.

---

# Part II - The controls

## Create New Assembly

Open **Builders → Create New Assembly** for either source:

- **Generated Symmetry** repeats the protein, chain, or domain chosen in
  **Build from**. Other chains and domains remain as they were.
- **Deposited Assembly (BMT)** uses a whole protein's biological transformation
  matrices. The **Assembly** picker offers the file's assemblies that add
  symmetry, including subassemblies when available. If the protein already
  contains its complete assembly, the dialog explains that there is nothing
  additional to build.

For example, import **5IM3**, choose its protein row, select **Deposited
Assembly (BMT)**, then assembly **1**. Its two deposited protein chains become
the four-chain biological assembly. Both PDB BIOMT records and mmCIF biological
assembly matrices are supported; offline tests compare the copies with the
source coordinates in both formats.

The dialog always opens, including on an empty file.
It carries the same **Method / PDB ID / Download / Import Local File** controls the Protein Import panel has, so getting hold of a protein is part of the form rather than something to go and do first.
Download lands without closing the dialog, and the **Build from** picker gains the protein you just imported.
(Import Local File opens Blender's file browser, which cannot be nested inside a popup, so that one closes the dialog behind it; the import still lands and reopening finds the protein waiting.)

Everything that shapes a build lives in the same dialog:

- **Build from** - which structure to build the symmetry for.
  One at a time.
  The generator works in a molecule's own coordinate frame, so applying one operator set to two proteins would ring each about its own origin rather than building a single assembly out of both.
- **Cyclic (Cn)** - Order sets n.
- **Dihedral (Dn)** - Order sets n, giving 2n copies.
- **Helical** - Subunits, Rise (Angstrom along the axis), Twist (degrees about it).
- **Axis** - the direction the symmetry turns about. Z by default.
- **Trim Copies** - Range and Contact, described below.

Three ways out, and they mean different things:

- **Apply** builds it and leaves the dialog open, so the settings can be judged against the viewport rather than against the numbers.
  Press it as often as you like while dialling the shape in.
- **OK** builds it and closes, and the result takes its place in the PB Outliner as a row of its own.
- **Cancel** puts back whatever was on screen when the dialog opened.
  That is nothing, a deposited assembly, or an earlier generated symmetry, whichever it was.
  A preview you rejected is not what you are left with.

The pencil on either kind of assembly's outliner row reopens the dialog on the settings that build was actually made with.
Those settings travel with the build rather than with the panel, which is what lets two proteins carry different symmetries at once: the sliders are one set of controls standing in for whichever protein is active, so building a second protein moves them off the first.

Tetrahedral, octahedral and icosahedral are deliberately absent.
Each needs an explicit orientation convention, and picking one silently would put every subunit in the wrong place.
Use the deposited assembly for those.

### In the PB Outliner

A symmetry is a child of its source in the PB Outliner:

```
> 4hhb
    > Chain A
        Symmetry C5
    Chain B
```

A protein or domain source places the symmetry beneath that row instead.
Collapsing the source hides its symmetry row. The pencil reopens the build's
settings; the trash removes its copies and leaves the source hierarchy intact.
Biological assemblies appear beneath their protein as **Biological Assembly 1**
(or the chosen assembly number), with the same edit and delete controls.

Click the assembly child's name or checkbox to access **Assembly Controls**
for animation, axes, cutaway, and realization. A helical child also offers
bend controls. These live controls use the clicked child's protein, even when
another protein was imported more recently. Selecting the parent protein does
not open a separate assembly panel. Delete the assembly child to return to the
asymmetric unit (the imported protein without its generated copies).

The row is reconstructed from the built geometry nodes after undo and file
loading. Each protein currently carries one assembly; a new build replaces its
previous assembly, including when its source changes from a protein to a chain
or domain.

## Bend

Appears in Assembly Controls when a built **helical** child is clicked, because it is the only kind with a path to run along - a ring has nowhere to bend to.
It stays in the panel rather than moving into the builder's dialog because dragging the control nodes is a mode: a dialog that closed over it would end the drag at the moment it began.

Real filaments are not straight.
Actin curves, microtubules flex, amyloid twists across a field of view.
**Add Bend** puts a Bezier curve along the filament with draggable control nodes, the same rig the DNA builder uses, and lays the subunits along it.

- **Nodes** - how many handles shape the path, applied with the tick beside it.
  Changing the count resamples the path you already made rather than resetting it.
- **Straight / Arc / S-curve / Coil** - starting shapes. A starting point, not a constraint; the nodes still move afterwards.
- **Edit Bend** - selects the control nodes so you can grab them with the usual transform gizmo. The copies follow as you drag.
- **Remove** - deletes the rig; the filament runs straight along its axis again.

The line underneath reports whether the bend is actually doing anything - "drag one to bend" until it is, then how far the far end has moved off straight.

### The subunits stay rigid

The copies are re-placed along the curve; they are never deformed.
That is the physically right model - a filament bends by changing the relative orientation of rigid subunits, not by shearing each one - and it is also the only one available: the copies are geometry-nodes instances, which a deform modifier cannot reach at all.

DNA is the opposite case, which is why its bend works differently: a double helix genuinely bends along its length, so the DNA builder hands its curve to a Curve modifier and deforms the strand.
Same rig, opposite use.

Two consequences worth knowing:

- **The first subunit never moves.** The filament is anchored on the structure you imported and bends away from it, so bending the middle can swing the far end. That is what holding one end of a rope does.
- **A filament longer than its curve carries straight on** past the end rather than piling up on the last point, so raising Subunits after shaping a bend extends the filament rather than crowding it.

## Trim Copies

Part of the builder's dialog, so it is part of what a build is made of and travels with it.
Both values are in Angstrom; **0 means no limit**.

- **Range** - drop copies whose centre lands further than this from the original.
  Answers "show me the neighbourhood".
- **Contact** - keep only copies with an atom within this distance of the original.
  Answers "show me the subunits this one actually touches".

This is what turns a 60-copy capsid into a legible patch.

## Animation

Appears once something is built.

- **Assembled** - 0 puts every copy exactly back on the asymmetric unit, 1 is the full assembly, and anything between is a real intermediate.
- **Stagger** - 0 moves every copy together; 1 has them arrive one after another.
- **Keyframe** - keys the current state at the playhead.
  Key 0 on one frame and 1 on another to animate the assembly forming.
- **Clear** - removes the copies.
  This has the same effect as deleting the assembly child in the PB Outliner.

## Show Symmetry Axes

Draws the rotation axes as real, renderable cylinders, labelled by fold.
A C7 gives one axis; a D4 gives five (one four-fold and four two-folds).

## Cutaway

- **Direction** - the side to take away.
- **Cut Depth** - moves the plane in Angstrom. 0 cuts through the centre; larger values take less away.
- **Cut Away** - applies it.

Whole copies are removed rather than atoms being sliced, which is what published capsid figures do and leaves intact subunits around the opening.

## Realize Copies

Converts instances into real, separately selectable objects that still share their atom data.
Refused above twelve copies unless forced.

---

# Part III - Structures to demo with

Every structure below was imported and built in ProteinBlender before being listed here.
The counts are what the panel will show you, and the timings are from a normal desktop run.

## The short list

| PDB | What it is | Operators | Shows off |
|---|---|---|---|
| **1ubq** | Ubiquitin, monomer | none | No additional deposited assembly offered |
| **4ins** | Insulin | assembly 3: **3** | The clean first build; a visible 3-fold from the top |
| **1hho** | Haemoglobin | **2** | The smallest possible assembly: one operator makes the tetramer |
| **1fha** | Ferritin | **24** | Octahedral. One chain becomes a 24-copy shell, and it loads in under a second |
| **2tmv** | Tobacco mosaic virus | **49** | A *deposited* helical assembly. The filament case, straight from the file |
| **1m1c** | Small icosahedral virus | **60** | A full capsid from a 2-chain asymmetric unit - the light capsid |
| **1cd3** | Icosahedral capsid | **60** | The heavyweight: 14 chains x 60. Also carries pentamer and hexamer sub-assemblies |
| **2btv** | Bluetongue virus core | **60** (and **2500**) | Cautionary: its assembly 6 is a 2500-operator crystal lattice |
| **1atn** | Actin (bundled) | none useful | The generative helical demo: real actin parameters on a real actin |
| **2gls** | Glutamine synthetase | identity only | Gating on a *big* structure: 48 chains, already complete, nothing to build |

`1ubq`, `4ins`, `1atn`, `1aki` and `4hhb` are bundled in `tests/data/`; the rest download.

Measured on import and build:

| PDB | Import | Chains shown | Copies placed |
|---|---|---|---|
| 1hho | 1.4 s | 2 | 4 |
| 1fha | 0.4 s | 1 | 24 |
| 2tmv | 0.5 s | 2 | 98 |
| 1m1c | 1.7 s | 2 | 120 |
| 1cd3 | 4.2 s | 7 | 420 |

Building itself is effectively instant in every case; the wait is the download and import.
"Copies placed" is chains times operators, which is why 1fha's single chain is such good value and 1cd3 is the heavyweight.

## What each one is good for

### 1ubq - the gate
Choose Deposited Assembly in the dialog and it explains that no additional assembly is deposited for this protein.
The Symmetry Builder is still there, which is the point: a monomer is exactly when you want to *generate* symmetry.

### 4ins - the first build
Three operators, so the result is easy to read and impossible to misinterpret.
Look from the top: it should be a clean three-fold disc.
Good for demonstrating the Assembled slider, because you can follow individual copies with your eye.

Also the clearest asymmetric-unit round trip.
Choose Deposited Assembly, select assembly 3, and confirm. Its child pencil reopens on assembly 3; deleting the child returns the protein to the asymmetric unit.

### 1hho - the minimum case
One non-identity operator turns the deposited alpha-beta dimer into the haemoglobin tetramer.
Useful for making the asymmetric-unit-vs-biological-assembly point in one sentence.

### 1fha - the best value for money
Ferritin's 24-fold octahedral shell, built from a **single chain**, in well under a second.
The most shell for the least waiting of anything here, and the clearest demonstration that the atoms are stored once.

At 24 copies it is also over the twelve-copy threshold, so it doubles as the **Realize Copies** refusal and force-override demo.

### 2tmv - helical, from the file
Forty-nine operators of a real helical virus.
Worth contrasting with the generative helical builder: same shape, one read from the file and one typed in.

### 1m1c - the light capsid
A full 60-operator icosahedral capsid from a two-chain asymmetric unit: 120 copies placed, imported in under two seconds.
Like 1cd3 it carries sub-assemblies (it offers 1, 3, 4, 5 and 6), so it can tell the same pentamer-to-capsid story for half the wait.
The better choice for a live demo.

### 1cd3 - the heavyweight
Fourteen chains times sixty operators.
The one to use for the memory point: the base mesh stays at about 9,700 vertices no matter how many copies are drawn.

It also carries **sub-assemblies**, which is a nice surprise in a demo:

- assembly **3** - a pentamer (5 operators)
- assembly **4** - a hexamer (6 operators)
- assembly **1** - the whole capsid (60)

Build the pentamer first, then the whole shell, and the relationship is obvious.

### 2btv - the cautionary tale
Assembly 1 is the expected 60-operator capsid.
Assembly **6** is a **2500-operator** crystal lattice.
Worth knowing it exists before someone picks it in front of an audience, and a fair demonstration of why Trim Copies is there.

### 1atn - generative helical
Actin, bundled, and the natural subject for the helical builder.
Try Subunits 13, Rise **27.5**, Twist **-166.7**, which are actin's real parameters.

Then press **Add Bend** and drag the middle node: a curving actin filament, with every subunit still rigid.
The **Arc** preset gets there in one click if you would rather not drag on stage.

### 2gls - gating, at scale
Forty-eight chains and a deposited assembly consisting of one identity operator, because the file already contains the complete molecule.
Shows why an identity-only assembly is not offered as an additional build.

---

# Suggested demos

## Five minutes

1. **1ubq** - no deposited section. Explain the gate.
2. **4ins** - build deposited assembly 3: a three-fold you can read at a glance. Delete its child row to return to the asymmetric unit.
3. Drag **Assembled** to 0 and back. Keyframe 0 and 1, scrub.
4. **1fha** - build the 24-copy ferritin shell.
5. **Cut Away** on the ferritin. Interior revealed, subunits intact.

## Fifteen minutes

Add:

6. **1cd3** - pentamer (assembly 3), then hexamer (4), then the whole capsid (1).
7. **Trim Copies** with a Contact limit, reducing the capsid to one subunit's neighbours.
8. **Show Symmetry Axes** on the capsid.
9. **1atn** with the helical builder at actin's real rise and twist, then **Add Bend** and drag a node to curve the filament.
10. **Realize Copies** on something small, then click a single subunit to show per-copy identity.

---

# Known limitations

Worth stating before a demo rather than during one.

- **No point-group label.** The panel says "3 copies of 4 chains", not `C3` or `I`.
  Deriving the symbol needs either an external annotation or inference we chose not to guess at.
- **T, O and I cannot be generated**, only read from a file, for the orientation-convention reason above.
- **Instanced copies cannot be selected individually** until realized. This is deliberate.
- **On a capsid, the Assembled slider looks nearly finished by about 0.5.**
  This is geometry, not a bug: a rotation about an axis through the centre preserves distance from that centre, so copies slide around the shell rather than the shell growing outward.
  A radial option would give the "assembling from solution" look and does not exist yet.
- **Editing a domain changes that chain in every copy.**
  Expected, given the copies share one set of atoms, but worth knowing before editing on stage.
- **The panel is one long strip** of always-expanded sections.
  Collapsible sub-panels are the fix and are not built yet.
- **Only helical symmetry can be bent.** Cyclic and dihedral have no path to run along, so the Bend section does not appear for them.
- **A keyframed bend cannot change its node count.**
  Rebuilding the handles orphans the F-curves keyed against the old ones, so the operator refuses rather than silently losing an animation you cannot see has gone.
  Remove the keys, change the count, key it again.
