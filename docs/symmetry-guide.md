# Symmetry: concepts, controls, and structures to demo with

A reference for the Symmetry panel.
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

So the panel does not ask "does this file mention an assembly".
It asks "does this file describe an operator that would put something new on screen".
Structures failing that test get no Deposited Assembly controls, because building one would visibly do nothing.

---

# Part II - The controls

## Deposited Assembly

Appears only when the file describes symmetry worth building.

- **Dropdown** - what to show the structure as.
  It names states, not just builds, so the first entry is **Asymmetric Unit - as deposited**: the structure exactly as the file contains it, which is what is on screen before anything is built.
  That entry is also the default, because it is the honest description of an untouched import.
  After it come the assemblies the file describes.
  Many entries carry several: a whole capsid, a pentamer, a hexamer, sometimes a crystal lattice.
- **Build Assembly** - applies the chosen assembly.
  With the asymmetric unit chosen the same button reads **Show Asymmetric Unit** and takes the copies away instead, which is the one-step way back from any build - a deposited assembly or a generated symmetry alike.

The dropdown follows what is built rather than only what will be built next: build assembly 3 and it reads "Assembly 3", clear and it returns to the asymmetric unit.

## Symmetry Builder

Always available, including on a monomer.
This is a construction tool, not a reader, so it is not gated on the file.

- **Cyclic (Cn)** - Order sets n.
- **Dihedral (Dn)** - Order sets n, giving 2n copies.
- **Helical** - Subunits, Rise (Angstrom along the axis), Twist (degrees about it).
- **Axis** - the direction the symmetry turns about. Z by default.
- **Build Symmetry** - applies it.

Tetrahedral, octahedral and icosahedral are deliberately absent.
Each needs an explicit orientation convention, and picking one silently would put every subunit in the wrong place.
Use the deposited assembly for those.

## Trim Copies

Applies to the next build.
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
  The same result as choosing Asymmetric Unit in the dropdown above; this button is simply nearer to hand once something is built.

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
| **1ubq** | Ubiquitin, monomer | none | Gating: no Deposited Assembly section at all |
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
Import it and the Deposited Assembly section is simply absent, replaced by "No assembly deposited with this structure".
The Symmetry Builder is still there, which is the point: a monomer is exactly when you want to *generate* symmetry.

### 4ins - the first build
Three operators, so the result is easy to read and impossible to misinterpret.
Look from the top: it should be a clean three-fold disc.
Good for demonstrating the Assembled slider, because you can follow individual copies with your eye.

Also the clearest asymmetric-unit round trip.
Its picker opens on **Asymmetric Unit**, which is the deposited unit already on screen.
Choose assembly 3, build, and the picker follows to "Assembly 3"; choose Asymmetric Unit again and the button relabels itself to **Show Asymmetric Unit**, putting the structure back where the import left it.

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

### 2gls - gating, at scale
Forty-eight chains and a deposited assembly consisting of one identity operator, because the file already contains the complete molecule.
Makes the point that "no Deposited Assembly section" is not a failure to detect anything.

---

# Suggested demos

## Five minutes

1. **1ubq** - no deposited section. Explain the gate.
2. **4ins** - the picker opens on Asymmetric Unit. Build assembly 3: a three-fold you can read at a glance. Pick Asymmetric Unit again to go straight back.
3. Drag **Assembled** to 0 and back. Keyframe 0 and 1, scrub.
4. **1fha** - build the 24-copy ferritin shell.
5. **Cut Away** on the ferritin. Interior revealed, subunits intact.

## Fifteen minutes

Add:

6. **1cd3** - pentamer (assembly 3), then hexamer (4), then the whole capsid (1).
7. **Trim Copies** with a Contact limit, reducing the capsid to one subunit's neighbours.
8. **Show Symmetry Axes** on the capsid.
9. **1atn** with the helical builder at actin's real rise and twist.
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
