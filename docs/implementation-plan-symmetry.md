# Symmetry in ProteinBlender - goals, research notes and proposal

Research response to the meeting notes on symmetry (BioMT, "symmetry builder should only show up if symmetry is present", "check with Molecular Nodes on symmetry").
Everything in the "What we already have" section was verified empirically against Blender 5.2 with the embedded MolecularNodes, not read off the source.

---

# Part I - Goals

## The goal

**ProteinBlender can show and animate the real biological assembly of a structure - the capsid, the ring, the filament - not just the asymmetric unit the file happens to contain.
Where the file does not describe an assembly, the user can build one.**

The emphasis on *animate* is deliberate.
ChimeraX and Mol\* already display assemblies well and we will not beat them at static display.
Nobody animates assembly formation, that is precisely what ProteinBlender is for, and Finding 4 below shows the machinery for it already runs.

## What we are building

Three capabilities, sharing one underlying representation (a list of transform matrices applied as instances).

**1. Deposited assemblies.**
When an imported structure carries a biological assembly containing real symmetry, offer to build it.
Let the user choose which assembly - entries like 1cd3 carry six - and name what it is ("Icosahedral (I), 60 copies").
The controls appear only when the file genuinely describes something beyond the asymmetric unit, per the non-identity test in Finding 5.

**2. A generative symmetry builder.**
Always available, independent of the file.
Point groups Cn, Dn, T, O and I, plus helical (rise, twist, copy count), applied about a user-specified axis and centre.
This covers designed assemblies, structures whose deposited assembly is absent or wrong, and filaments the PDB does not describe as such.
Icosahedral orientation convention is an explicit option, not a hardcoded assumption - see the ChimeraX notes.

**3. Assembly animation.**
A keyframeable assemble/disassemble factor, so a capsid can form on the timeline.
Optional per-copy stagger so subunits arrive in sequence rather than all at once.
Composable with the Brownian motion we already ship, so subunits jitter in from solution and lock into the lattice.

Supporting these, a **realize copies** operator that converts instances into real geometry, mirroring ChimeraX's `copies true`, for when a user needs to select, colour or simulate subunits individually.

## Non-goals

Stating these explicitly because each is a plausible-sounding place to lose months.

- **Crystallographic symmetry and unit-cell packing.**
  A different feature for a different audience, as argued in Part II section 1.
- **Symmetry *detection*.**
  We read the point group from file annotations or from what the user asks for.
  We do not infer symmetry from coordinates - that is a hard problem RCSB solves offline, and their annotations are available to us.
- **Editing or refining assemblies.**
  We build what the file or the user specifies. We do not fit, dock or optimise.
- **Per-copy structural divergence.**
  Every copy is the same geometry under a different transform. Copies that differ internally are out of scope.

## Definition of done

Concrete and testable.
Per the repo's testing rules, expected values come from independent ground truth, never from the code under test.

1. Importing 1cd3 as either `.pdb` or `.cif` and building assembly 1 yields 60 transforms without raising.
2. A monomer (1ubq) shows no deposited-assembly controls, because its only transform is the identity.
3. Applying generative C7 to a monomer produces 7 copies at 360/7 degree intervals, checked against hand-computed positions rather than against our own transform code.
4. Helical with a given rise and twist produces a filament whose measured rise per subunit matches the input.
5. Keyframing the assembly factor 0 to 1 renders frames showing progressive assembly, verified through the existing render-coverage approach rather than by trusting the node graph.
6. The full suite is green on Blender 5.0, 5.1 and 5.2.

## Phasing

The scope above is large, so it is sequenced to be shippable at each step rather than delivered as one drop.

- **Phase 0 - unblock.**
  Fix the PDB assembly parser contract and switch the remote format default to `cif`.
  Small, well-understood, has a clean red/green test, and everything else depends on it.
- **Phase 1 - deposited assemblies.**
  Build, assembly selection, the non-identity gating, and the point-group label.
- **Phase 2 - animation.**
  The assemble/disassemble factor, stagger, and Brownian composition.
- **Phase 3 - generative builder.**
  Cn and Dn first, then helical, then the cubic groups T/O/I with orientation conventions.
- **Phase 4 - polish.**
  Realize copies, symmetry axes as renderable objects, contact/range filtering, capsid cutaway.

Phases 0 to 2 deliver the differentiating feature.
Phase 3 is the largest single chunk of new code and is deliberately sequenced after we have something working end to end.

## Open risks

Carried forward from the integration notes in Part II section 5, and worth revisiting at each phase boundary.
The two that most affect design are that instances are not real geometry, and that a domain edit propagates into every copy.

---

# Part II - Research

## 1. Two different things are called "symmetry"

Getting this distinction right up front decides most of the scope.

**Biological assembly symmetry (point groups).**
The biologically meaningful oligomer: the dimer, the ring, the capsid, the filament.
Stored as `REMARK 350` / `BIOMT` matrices in legacy PDB files, and as `pdbx_struct_assembly_gen` + `pdbx_struct_oper_list` in mmCIF.
Described by point groups: Cn (cyclic), Dn (dihedral), T, O, I (cubic/icosahedral), H (helical), C1 (asymmetric).
This is what the meeting notes are about, and it is where essentially all of the visual payoff is.

**Crystallographic symmetry (space groups).**
Unit-cell packing from `CRYST1` and the space group.
This is PyMOL's `symexp`, ChimeraX's `crystalcontacts`, Chimera's "Unit Cell" tool.
It answers "how did the molecules stack in the crystal", which is a crystallographer's question, not a storytelling one.

**Recommendation: build the first, skip the second.**
ProteinBlender's audience wants a virus capsid or an actin filament, not a unit cell.
Crystal packing can come later as a small separate tool if anyone asks.

## 2. How the established viewers do it

### ChimeraX - the `sym` command

The most complete model, and the one worth borrowing from.

- **Deposited assemblies**: `sym #1 assembly 1`, or `sym #1 biomt` to use the BIOMT records directly.
- **Generative symmetry**, for when no assembly is deposited: cyclic `Cn`, dihedral `Dn`, tetrahedral `T`, octahedral `O`, icosahedral `I`, helical `H` (rise, angle per subunit, copy count), pure translation (`shift`), and products of groups multiplied together.
- **Icosahedral orientation conventions** matter and are explicit: `222` (default), `2n5`, `n25`, `2n3`, plus rotated `r` variants.
  Different databases orient capsids differently, so a builder that hardcodes one convention will silently misplace subunits.
- **`copies true|false`** - the single most transferable idea.
  Copies are either full atomic models or lightweight *graphical clones*, and the default flips at 12 copies so viral capsids get clones automatically.
  This is exactly Blender's instances-vs-realized-geometry tradeoff.
- **`contact` / `range` filters** - drop copies that have no atoms within a distance of the original, or whose centres are too far away.
  This is how you show "the local neighbourhood of one capsid protein" instead of the whole shell.
- **`surfaceOnly`** - show only surfaces for the copies, for cheap capsid renders.

### Mol\* / RCSB - the presentation layer

The "Assembly Symmetry" panel colours subunits by **symmetry cluster** and draws the **symmetry axes and a polyhedral cage** over the assembly.
RCSB annotates every entry with global symmetry, local symmetry and pseudosymmetry, giving a point group symbol (`C2`, `D7`, `I`) plus subunit stoichiometry.
That annotation is a ready-made source for a human-readable label in our UI.

### PyMOL

`set assembly, 1` before loading gives the biological unit from mmCIF; `symexp` covers crystal mates.
Less to borrow here, but it confirms the same split as above.

## 3. What we already have (all verified in Blender 5.2)

The embedded MolecularNodes contains a complete biological-assembly pipeline that ProteinBlender never turns on.

- Parsers for both formats: `PDBAssemblyParser` (REMARK 350/BIOMT) and `CIFAssemblyParser` (`pdbx_struct_assembly_gen`), in `utils/molecularnodes/entities/molecule/`.
- The parsed transforms are stored as JSON on `obj.mn.biological_assemblies`.
- A data object holds per-chain, per-transform quaternion + translation.
- A geometry-nodes group splits the molecule into centred per-chain instances and instances them onto the transforms, inserted **last** in the node tree.

### Finding 1 - the feature is switched off

`build_assembly=False` is hardcoded in `proteinblender/core/molecule_manager.py:40`.
That is the "commented out biological unit" from the meeting notes.

### Finding 2 - the PDB path is broken, and it is our default

`PDBAssemblyParser.get_transformations` returns `(chain_ids, matrix)` **tuples**, while the consumer `array_quaternions_from_dict` expects **dicts** with `chain_ids` / `matrix` / `pdb_model_num` keys.
`CIFAssemblyParser` returns the correct dict form.
The embedded snapshot is mid-refactor: mmCIF was updated, PDB was not, and the abstract docstring in `assembly.py` still documents the old tuple contract.

Verified end to end:

| Path | Result |
|---|---|
| `.pdb` + `build_assembly=True` | `TypeError: list indices must be integers or slices, not str` |
| `.cif` + `build_assembly=True` | Builds correctly, `Assembly <name>` node group created |

This is a real defect in the repo source, not a stale installed copy - the installed and repo files are byte-identical.

**And `remote_format` defaults to `'pdb'`** (`properties/protein_props.py:174`).
So the default import path is the broken one, and simply flipping `build_assembly=True` would ship a crash.

### Finding 3 - scale is a non-issue

Built the icosahedral capsid 1cd3 (60 transforms) through the CIF path:

- build time **1.6 s**
- base mesh **9,755 vertices - atoms stored once**, not duplicated 60 times
- **420 instances** (60 transforms x 7 chains)
- depsgraph evaluation effectively instant

Instancing is the right primitive and it comfortably handles capsids.
This is the same call ChimeraX makes with graphical clones.

### Finding 4 - we get an assemble/disassemble animation almost for free

The assembly node exposes `Rotation`, `Translation` and `assembly_id` inputs.
The **`Rotation` factor is a working 0 -> 1 assembly control**, verified by measuring instance positions on 1cd3:

| Rotation | Unique instance positions | Mean radius |
|---|---|---|
| 0.0 | 7 (collapsed onto the asymmetric unit) | 0.311 |
| 0.5 | 420 | 1.077 |
| 1.0 | 420 (full shell) | 1.386 |

Keyframing that one value animates a capsid assembling from a single subunit.

The `Translation` factor is a no-op *for 1cd3 specifically* - that entry's BIOMT operators are pure rotations with an all-zero translation column, so there is nothing for it to scale.
It is not a bug; it will matter for assemblies whose operators carry real translations.

### Finding 5 - "is symmetry present" is subtler than it looks

The meeting note says the builder should only appear when symmetry is present.
Presence of an assembly record is **not** a usable test.
All four of our offline fixtures (1ubq, 1aki, 4hhb, 1atn) contain a `REMARK 350` assembly with exactly **one identity transform** - the assembly is just the asymmetric unit.

Gating on "has assemblies" would show the builder on every monomer and have it do nothing.
The correct test is **"has at least one non-identity transform"**, i.e. applying the assembly actually creates geometry that is not already there.
Legacy PDB format also cannot represent a large capsid at all (99,999 atom and 62 chain ceilings), which is an independent reason to move to mmCIF.

## 4. Proposal

### Tier 1 - make deposited assemblies work

1. Fix `PDBAssemblyParser.get_transformations` to return the dict form, and correct the stale contract docstring in `assembly.py` so both parsers agree.
2. Switch the `remote_format` default from `pdb` to `cif`.
   Needed for assemblies, needed for large structures, and the modern default anyway.
3. Expose "Build biological assembly" as an import option and as a toggle in the molecule panel, gated on the non-identity-transform test from Finding 5.
4. Show the assembly identity in the UI - point group and stoichiometry, e.g. "Icosahedral (I), 60 copies", optionally enriched from RCSB's symmetry annotations.

### Tier 2 - animate it (this is where we beat the other tools)

ChimeraX and Mol\* *display* assemblies.
Nobody animates them well, and animation is what ProteinBlender is for.

- **Self-assembly animation** - keyframe the `Rotation` factor 0 -> 1. Already works today.
- **Staggered assembly** - subunits arriving in sequence rather than all at once, driven by a per-instance delay derived from `transform_id`. More interesting than the uniform version and a genuinely new capability.
- **Compose with Brownian motion** - subunits jitter in from solution and lock into the lattice. This combines two features we already own and is the single most compelling demo I can imagine for the add-on.
- **Explode / implode** for showing subunit interfaces.

### Tier 3 - the generative symmetry builder

For designed assemblies, structures with no deposited assembly, and teaching.
Mirror ChimeraX's vocabulary: Cn, Dn, T, O, I, and helical.

**Helical deserves priority** - filaments (actin, microtubules, amyloid) are rise + twist + copy count, they are visually spectacular, and they fit the vocabulary of the DNA helix and membrane builders we already ship.

Note the UI consequence: a *generative* builder is a construction tool and should always be available, whereas the *deposited assembly* controls are the part that should be conditional on the file.
That resolves the ambiguity in the meeting note.

If we implement icosahedral generation, follow ChimeraX and make the orientation convention an explicit option rather than a hardcoded assumption.

### Tier 4 - visualisation

- **Symmetry axes as real objects** (Mol\* style) - the C5/C3/C2 axes of an icosahedron. Excellent for figures and teaching, and trivially renderable once they are Blender objects.
- **Colour by symmetry cluster / transform id.**
- **Contact and range filtering**, per ChimeraX - show only the subunits touching a chosen one.
- **Capsid cutaway** - hide a hemisphere to reveal the interior. This is *the* canonical virus figure and is natural in Blender.

## 5. Integration risks worth deciding early

- **Instances are not real geometry.**
  Per-copy selection, per-copy colour and physics will not work on them.
  Mirror ChimeraX's `copies true` with a "Realize copies" operator for when a user needs to treat subunits individually.
- **Domain edits propagate to every copy.**
  The assembly node is inserted last, so upstream domain masks and colours flow into all instances - almost certainly the behaviour we want, but it means a domain pivot moves that chain in all 60 copies.
  Worth confirming that is the intended semantics before building UI on top of it.
- **The transforms data object is an extra `bpy` object** that `scene_manager` does not currently know about.
  It needs to be tracked for delete and undo/redo alongside the molecule.
- **Per-chain centred instances interact with the pivot rules** in `core/domain_space.py`.
  Any code reading assembly-instanced coordinates must respect the existing "never `matrix_world @ co`" rule.

## 6. Suggested next step

Tier 1 item 1 is a small, well-understood fix with a clear red/green test available (build the assembly from a `.pdb` fixture and assert it does not raise), and it unblocks everything else.
Doing that plus the `cif` default turns a crash into a working feature, after which the animation work in Tier 2 is mostly UI over machinery that already runs.
