# Implementation Plan: DNA Builder & Phospholipid Membrane Builder

**Date:** 2026-04-21
**Status:** Proposal — Pending Review
**Author:** Generated via Claude Code
**Target:** ProteinBlender Addon (Blender 4.2+)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Background & Motivation](#2-background--motivation)
3. [Current State of the Codebase](#3-current-state-of-the-codebase)
4. [Phase 1: B-Form DNA Builder](#4-phase-1-b-form-dna-builder)
5. [Phase 2: Phospholipid Membrane Builder](#5-phase-2-phospholipid-membrane-builder)
6. [Phase 3: A-Form & Z-Form DNA Support](#6-phase-3-a-form--z-form-dna-support)
7. [MolecularNodes Upgrade Considerations](#7-molecularnodes-upgrade-considerations)
8. [New File & Directory Structure](#8-new-file--directory-structure)
9. [Dependency Changes](#9-dependency-changes)
10. [Risk Assessment & Open Questions](#10-risk-assessment--open-questions)
11. [Appendix A: DNA Helix Parameter Reference](#appendix-a-dna-helix-parameter-reference)
12. [Appendix B: Lipid Bilayer Parameter Reference](#appendix-b-lipid-bilayer-parameter-reference)

---

## 1. Executive Summary

This plan introduces two new builder systems to ProteinBlender:

1. **DNA Builder** — Generates double-stranded DNA structures from a user-supplied nucleotide sequence. The initial implementation targets B-form DNA, with A-form and Z-form as follow-up work. The user types a sequence (e.g. `ATCGATCG`), picks a form, and gets a fully visualized DNA object in the Blender scene.

2. **Phospholipid Membrane Builder** — Generates a lipid bilayer from a template lipid structure. The user selects a lipid type (DPPC, POPC, etc.), specifies membrane dimensions, and gets a bilayer object placed in the scene. This is a procedural/visualization-first approach — not a simulation-grade builder.

Both features follow the existing ProteinBlender architecture: operators with dialog-based input, integration via the MolecularNodes molecule pipeline, and full undo/redo support through the existing property system.

**No MolecularNodes upgrade is required** for either feature. The upstream MN (4.5.12) does not include DNA or membrane builders — these are custom features we build ourselves. An MN upgrade is discussed separately as a maintenance task.

---

## 2. Background & Motivation

### Why DNA?

Protein-DNA interactions are central to gene regulation, chromatin structure, and drug design. Currently, ProteinBlender can load pre-existing DNA structures from PDB files, but cannot generate DNA from a sequence. A DNA builder enables:

- Quick creation of DNA fragments for protein-DNA complex scenes
- B-form DNA of arbitrary length and sequence for educational/presentation use
- A foundation for future features (DNA-protein docking visualization, chromatin scenes)

### Why Membranes?

Membrane proteins represent ~30% of all proteins. Visualizing them in their native lipid bilayer context is essential for:

- Showing transmembrane protein topology
- Building scenes with membrane-embedded receptors (GPCRs, ion channels)
- Educational content about cell membrane structure

### Why Not Just Load From PDB?

- No PDB entry exists for "a 100x100 Angstrom DPPC membrane" — membranes are built, not downloaded
- DNA structures in the PDB are short crystallographic fragments, not arbitrary sequences
- Generating structures programmatically gives users precise control over dimensions and composition

---

## 3. Current State of the Codebase

### What Already Exists

| Capability | Status | Location |
|-----------|--------|----------|
| DNA/RNA residue definitions | Complete | `utils/molecularnodes/data.py` (lines 764-776) |
| DNA backbone atom names | Complete | `utils/molecularnodes/data.py` (lines 824-875) |
| oxDNA trajectory import | Complete | `utils/molecularnodes/entities/trajectory/dna.py` |
| Lipid residue names (500+) | Complete | `utils/molecularnodes/data.py` (lines 3254+) |
| `is_lipid` boolean attribute | Complete | `utils/molecularnodes/entities/trajectory/trajectory.py` |
| `is_nucleic` boolean attribute | Complete | `utils/molecularnodes/entities/molecule/molecule.py` |
| SDF/MOL small molecule import | Complete | `utils/molecularnodes/entities/molecule/sdf.py` |
| AtomArray → Blender object pipeline | Complete | `utils/molecularnodes/entities/molecule/molecule.py` |
| Geometry node styling (ball+stick, ribbon, etc.) | Complete | `utils/molecularnodes/style.py` |

### What Does NOT Exist

- No sequence-to-structure DNA generation
- No DNA form (A/B/Z) builder
- No phospholipid membrane assembly
- No `proteinblender/builders/` directory
- No SMILES/RDKit integration

### Bundled Dependencies

- **biotite 1.4.0–1.6.0** — Structure I/O and filtering. Does NOT have a DNA builder.
- **MDAnalysis 2.9.0–2.10.0** — Trajectory analysis. Not needed for building.
- **scipy** — Available for numerical work (Newton solvers, rotations, etc.)
- **numpy** — Available everywhere.

### Architecture Patterns to Follow

All new features should follow the established patterns in the codebase:

- **Operators**: Class naming `[DOMAIN]_PB_OT_[action]`, use `invoke_props_dialog()` for parameter input, return `{'FINISHED'}` or `{'CANCELLED'}`
- **Registration**: Add to `CLASSES` tuple in the relevant `__init__.py`; PropertyGroups must register before operators that use them
- **Scene integration**: Molecules created via `scene_manager.create_molecule_*` methods, stored in `ProteinBlenderScene.molecules` dict
- **Property persistence**: Serializable PropertyGroups for undo/redo safety; string-based object references (never Blender pointers)
- **MolecularNodes pipeline**: Build a biotite `AtomArray` → call `Molecule.create_object()` → geometry node tree is applied automatically

---

## 4. Phase 1: B-Form DNA Builder

### 4.1 Overview

The DNA builder takes a nucleotide sequence string and generates a double-stranded B-form DNA helix as a biotite `AtomArray`. This array is then fed into the existing MolecularNodes molecule pipeline to produce a styled Blender object.

### 4.2 User Interface

#### Panel Location

A new section within the existing **Import panel** (`panels/panel_import_protein.py`), or alternatively a new dedicated panel. The section is titled **"DNA Builder"** and appears below the existing protein import controls.

```
┌─────────────────────────────────────┐
│  ProteinBlender                     │
├─────────────────────────────────────┤
│  Import Protein                     │
│  ┌───────────────────────────────┐  │
│  │ PDB ID: [________]  [Import] │  │
│  └───────────────────────────────┘  │
│                                     │
│  DNA Builder                        │
│  ┌───────────────────────────────┐  │
│  │ Sequence (5'→3'):             │  │
│  │ [ATCGATCGATCG____________]   │  │
│  │                               │  │
│  │ Form:  (●) B-form             │  │
│  │        ( ) A-form  [grayed]   │  │
│  │        ( ) Z-form  [grayed]   │  │
│  │                               │  │
│  │ Name: [DNA_001___________]   │  │
│  │                               │  │
│  │ Style: [Ball and Stick ▾]    │  │
│  │                               │  │
│  │ Info: 12 bp, 40.8 Å length   │  │
│  │       1 full turn + 1.5 bp   │  │
│  │                               │  │
│  │         [ Build DNA ]         │  │
│  └───────────────────────────────┘  │
│                                     │
│  Membrane Builder                   │
│  ┌───────────────────────────────┐  │
│  │ ...                           │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

#### User Flow

1. User types a nucleotide sequence using characters `A`, `T`, `G`, `C` (case-insensitive)
2. The complementary strand is auto-generated (A↔T, G↔C)
3. Info line updates in real-time showing base pair count, helix length in Angstroms, and number of turns
4. User optionally changes the name and visualization style
5. User clicks **"Build DNA"**
6. A double-stranded DNA object appears in the scene at the 3D cursor location
7. The DNA molecule is added to the ProteinBlender molecule list and outliner

#### Validation Rules

- Only characters `A`, `T`, `G`, `C` are accepted (whitespace and digits are stripped)
- Minimum length: 2 base pairs
- Maximum length: 1000 base pairs (soft limit with warning above 500)
- Empty sequence shows error message in the info line

### 4.3 Technical Implementation

#### 4.3.1 Core Algorithm: `builders/dna_builder.py`

The builder constructs a B-form DNA double helix using known geometric parameters and reference nucleotide coordinates.

**B-Form Parameters:**

| Parameter | Value |
|-----------|-------|
| Rise per base pair | 3.4 Å |
| Twist per base pair | 36.0° (= 360° / 10 bp per turn) |
| Base pairs per turn | 10.0 |
| Helix diameter | 20.0 Å |
| Propeller twist | -11.4° |
| Sugar pucker | C2'-endo |

**Algorithm (pseudocode):**

```python
class DNABuilder:
    """Generates double-stranded DNA as a biotite AtomArray."""

    # B-form helix parameters
    RISE_PER_BP = 3.4        # Angstroms
    TWIST_PER_BP = 36.0      # Degrees
    HELIX_RADIUS = 10.0      # Angstroms (half of 20 Å diameter)

    def __init__(self, sequence: str, form: str = "B"):
        self.sequence = self._validate_sequence(sequence)
        self.complement = self._complementary_strand(self.sequence)
        self.form = form
        self.params = HELIX_PARAMS[form]

    def build(self) -> biotite.structure.AtomArray:
        """
        Build the full double-stranded DNA.

        Returns a biotite AtomArray with all atoms, bonds,
        chain IDs ('A' for sense, 'B' for antisense),
        residue IDs, and residue names.
        """
        arrays = []

        # Build sense strand (5' → 3')
        for i, base in enumerate(self.sequence):
            nucleotide = self._build_nucleotide(
                base_char=base,
                strand='sense',
                position_index=i,
                chain_id='A',
                res_id=i + 1
            )
            arrays.append(nucleotide)

        # Build antisense strand (3' → 5', reversed)
        for i, base in enumerate(self.complement):
            nucleotide = self._build_nucleotide(
                base_char=base,
                strand='antisense',
                position_index=i,
                chain_id='B',
                res_id=i + 1
            )
            arrays.append(nucleotide)

        # Concatenate and add inter-residue bonds
        full_array = struc.array(arrays)
        full_array.bonds = self._build_bonds(full_array)
        return full_array

    def _build_nucleotide(self, base_char, strand, position_index, chain_id, res_id):
        """
        Place a single nucleotide at the correct helical position.

        1. Load reference nucleotide atom coordinates (template)
        2. Rotate around helix axis by (twist * position_index)
        3. Translate along helix axis by (rise * position_index)
        4. For antisense strand: rotate 180° + apply base-pair offset
        """
        template = self._get_nucleotide_template(base_char, strand)

        # Helical transformation
        theta = math.radians(self.params['twist'] * position_index)
        z_offset = self.params['rise'] * position_index

        if strand == 'antisense':
            # Antisense runs in opposite direction
            # Offset by ~154° (B-form base pair displacement angle)
            theta += math.radians(154.0)

        rotation = scipy.spatial.transform.Rotation.from_euler('z', theta)
        coords = rotation.apply(template.coord)
        coords[:, 2] += z_offset

        nucleotide = template.copy()
        nucleotide.coord = coords
        nucleotide.chain_id[:] = chain_id
        nucleotide.res_id[:] = res_id
        return nucleotide
```

#### 4.3.2 Nucleotide Templates

We need reference atomic coordinates for each nucleotide type. Two approaches:

**Option A: Extract from a known PDB structure (Recommended)**

1. Bundle a short, high-resolution B-form DNA crystal structure (e.g., PDB ID `1BNA` — the Dickerson dodecamer, 1.9 Å resolution)
2. At build time, parse the PDB, extract one instance of each nucleotide type (DA, DT, DG, DC)
3. Center each template at its glycosidic bond (C1' atom) for consistent placement
4. Store extracted templates in memory (lazy-loaded singleton)

**File:** `proteinblender/builders/data/1BNA.pdb` (~50 KB, well within addon size budget)

**Option B: Hardcoded coordinates**

Define the ~30-35 atoms per nucleotide as coordinate arrays directly in Python. More self-contained but harder to maintain.

**Recommendation:** Option A. It's cleaner, uses real crystallographic data, and biotite already has the PDB parser.

#### 4.3.3 Bond Generation

Bonds are critical for ball-and-stick visualization:

1. **Intra-residue bonds**: Use `biotite.structure.connect_via_residue_names()` — this already knows DNA residue bond topology from the component dictionary
2. **Backbone bonds**: Connect O3' of residue _i_ to P of residue _i+1_ within each strand
3. **Hydrogen bonds** (optional, Phase 1 can skip): Connect base-pair hydrogen bond donors/acceptors across strands

#### 4.3.4 Integration with MolecularNodes Pipeline

Once we have a biotite `AtomArray`, we feed it into the existing pipeline:

```python
from proteinblender.utils.molecularnodes.entities.molecule.molecule import Molecule

class DNAMolecule(Molecule):
    """Thin subclass that wraps a builder-generated AtomArray."""

    def __init__(self, array: struc.AtomArray, name: str):
        # Molecule base class expects an AtomArray
        self.array = array
        self.name = name
        # Skip file I/O — we already have the array

    def create_object(self, name, style="ball_and_stick", ...):
        # Delegates to parent Molecule.create_object()
        # which handles AtomArray → mesh → geometry nodes
        return super().create_object(
            name=name,
            style=style,
            ...
        )
```

Alternatively, if subclassing `Molecule` is too coupled, we can create a standalone function:

```python
def create_dna_blender_object(array, name, style):
    """
    Convert a biotite AtomArray to a Blender object
    using MolecularNodes internals.
    """
    mol = Molecule.__new__(Molecule)
    mol.array = array
    mol.file = None
    mol.file_path = None
    obj = mol.create_object(name=name, style=style)
    return mol, obj
```

The developer should examine `Molecule.__init__()` and `Molecule.create_object()` to determine the least-invasive integration point. The key requirement is: we have an `AtomArray` and need a Blender object with geometry nodes — the existing pipeline already does this.

#### 4.3.5 Scene Manager Integration

After the Blender object is created, register it with ProteinBlender's molecule tracking:

```python
# In the operator's execute():
scene = ProteinBlenderScene.get_instance()
identifier = scene.generate_unique_id("DNA")  # e.g., "DNA_001"

# Build the DNA
builder = DNABuilder(sequence, form="B")
array = builder.build()

# Create Blender object via MN pipeline
mol, obj = create_dna_blender_object(array, identifier, style)

# Wrap in MoleculeWrapper
wrapper = MoleculeWrapper(mol, identifier)

# Register
scene.molecules[identifier] = wrapper
scene._finalize_imported_molecule(wrapper)
```

This ensures the DNA molecule appears in:
- The molecule list panel
- The protein outliner
- The domain maker (user can create domains on DNA chains)
- The pose library
- The animation timeline

### 4.4 Operator Definition

**File:** `proteinblender/operators/dna_operators.py`

```python
class DNA_PB_OT_build(Operator):
    bl_idname = "dna.build"
    bl_label = "Build DNA"
    bl_description = "Generate a double-stranded DNA helix from a nucleotide sequence"
    bl_options = {'REGISTER', 'UNDO'}

    sequence: StringProperty(
        name="Sequence (5'→3')",
        description="Nucleotide sequence using A, T, G, C characters",
        default="ATCGATCG"
    )
    form: EnumProperty(
        name="Form",
        items=[
            ('B', "B-form", "Standard B-form DNA (most common)"),
            ('A', "A-form", "A-form DNA (dehydrated, RNA-like) [Coming Soon]"),
            ('Z', "Z-form", "Z-form DNA (left-handed) [Coming Soon]"),
        ],
        default='B'
    )
    name: StringProperty(
        name="Name",
        default="DNA"
    )
    style: EnumProperty(
        name="Style",
        items=[
            ('ball_and_stick', "Ball and Stick", ""),
            ('cartoon', "Cartoon", ""),
            ('ribbon', "Ribbon", ""),
            ('spheres', "Spheres (VDW)", ""),
            ('sticks', "Sticks", ""),
            ('surface', "Surface", ""),
        ],
        default='ball_and_stick'
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "sequence")
        layout.prop(self, "form")
        layout.prop(self, "name")
        layout.prop(self, "style")

        # Info readout
        seq = self._clean_sequence(self.sequence)
        if seq:
            bp = len(seq)
            length_a = bp * 3.4  # B-form rise
            turns = bp / 10.0
            box = layout.box()
            box.label(text=f"{bp} base pairs, {length_a:.1f} Angstrom length")
            box.label(text=f"{turns:.1f} helical turns")
        else:
            layout.label(text="Enter a valid sequence (A, T, G, C)", icon='ERROR')

    def execute(self, context):
        seq = self._clean_sequence(self.sequence)
        if not seq:
            self.report({'ERROR'}, "Invalid sequence. Use only A, T, G, C characters.")
            return {'CANCELLED'}
        if len(seq) < 2:
            self.report({'ERROR'}, "Sequence must be at least 2 nucleotides.")
            return {'CANCELLED'}
        if len(seq) > 1000:
            self.report({'WARNING'}, f"Long sequence ({len(seq)} bp). This may be slow.")

        if self.form != 'B':
            self.report({'ERROR'}, f"{self.form}-form DNA is not yet implemented.")
            return {'CANCELLED'}

        try:
            builder = DNABuilder(seq, form=self.form)
            array = builder.build()
            # ... create object and register (see 4.3.5)
            self.report({'INFO'}, f"Created {len(seq)} bp {self.form}-form DNA: {self.name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"DNA build failed: {str(e)}")
            return {'CANCELLED'}

    @staticmethod
    def _clean_sequence(seq: str) -> str:
        """Strip whitespace/digits, uppercase, validate characters."""
        cleaned = ''.join(c for c in seq.upper() if c in 'ATGC')
        return cleaned
```

### 4.5 Panel Integration

**File:** `proteinblender/panels/builder_panel.py`

```python
class PROTEINBLENDER_PT_builders(Panel):
    bl_label = "Builders"
    bl_idname = "PROTEINBLENDER_PT_builders"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_parent_id = "PROTEINBLENDER_PT_main"  # Nest under main panel
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.pb_builder_props

        # DNA Builder section
        box = layout.box()
        row = box.row()
        row.label(text="DNA Builder", icon='RNA')

        box.prop(props, "dna_sequence")
        box.prop(props, "dna_form")
        box.prop(props, "dna_style")

        # Info readout
        seq = ''.join(c for c in props.dna_sequence.upper() if c in 'ATGC')
        if seq:
            info_box = box.box()
            bp = len(seq)
            info_box.label(text=f"{bp} bp | {bp * 3.4:.1f} Angstrom | {bp/10:.1f} turns")
        
        box.operator("dna.build", text="Build DNA", icon='MESH_CYLINDER')

        layout.separator()

        # Membrane Builder section (Phase 2)
        box = layout.box()
        row = box.row()
        row.label(text="Membrane Builder", icon='SURFACE_NSPHERE')
        # ... (see Phase 2)
```

### 4.6 Properties

**File:** `proteinblender/properties/builder_props.py`

```python
class BuilderProperties(PropertyGroup):
    """Properties for the DNA and Membrane builder panels."""

    # DNA Builder
    dna_sequence: StringProperty(
        name="Sequence (5'→3')",
        description="Nucleotide sequence (A, T, G, C)",
        default="ATCGATCG",
    )
    dna_form: EnumProperty(
        name="Form",
        items=[
            ('B', "B-form", "Standard right-handed B-form DNA"),
            ('A', "A-form", "A-form DNA (coming soon)"),
            ('Z', "Z-form", "Left-handed Z-form DNA (coming soon)"),
        ],
        default='B',
    )
    dna_style: EnumProperty(
        name="Style",
        items=[
            ('ball_and_stick', "Ball and Stick", ""),
            ('cartoon', "Cartoon", ""),
            ('ribbon', "Ribbon", ""),
            ('spheres', "Spheres", ""),
            ('sticks', "Sticks", ""),
        ],
        default='ball_and_stick',
    )

    # Membrane Builder (Phase 2 — see section 5)
    membrane_lipid_type: EnumProperty(...)
    membrane_size_x: FloatProperty(...)
    membrane_size_y: FloatProperty(...)
    # ... etc.
```

Register in `proteinblender/properties/__init__.py` and attach to `bpy.types.Scene` as `pb_builder_props`.

### 4.7 Testing Strategy

1. **Unit test** (`tmp_tests/test_dna_builder.py`): Run in Blender Python console
   - Build a 10 bp sequence, verify atom count matches expected (2 strands x ~30 atoms/nucleotide x 10 residues)
   - Verify chain IDs are 'A' and 'B'
   - Verify rise between consecutive base pairs is ~3.4 Å
   - Verify total helix length is ~34 Å for 10 bp
   - Verify complementary strand correctness

2. **Visual test**: Build DNA, apply ball-and-stick style, visually confirm double helix shape

3. **Integration test**: Build DNA, verify it appears in molecule list, can create domains, can animate

### 4.8 Estimated Scope

| Component | Files | Complexity |
|-----------|-------|-----------|
| `builders/dna_builder.py` | 1 new file (~300-400 lines) | High — core algorithm |
| `builders/data/1BNA.pdb` | 1 bundled data file | None — static asset |
| `builders/__init__.py` | 1 new file | Trivial |
| `operators/dna_operators.py` | 1 new file (~100-150 lines) | Medium |
| `panels/builder_panel.py` | 1 new file (~80-120 lines) | Medium |
| `properties/builder_props.py` | 1 new file (~50-80 lines) | Low |
| Registration changes | 3 existing files modified | Low |
| Scene manager changes | 1 existing file modified | Low-Medium |

---

## 5. Phase 2: Phospholipid Membrane Builder

### 5.1 Overview

The membrane builder creates a lipid bilayer by replicating a template lipid structure on a 2D grid. This is a **visualization-oriented** approach — it produces a geometrically correct bilayer for rendering, not a simulation-ready system with proper forcefield parameters.

### 5.2 User Interface

Added to the same **Builders** panel as the DNA builder:

```
┌─────────────────────────────────────┐
│  Membrane Builder                   │
│  ┌───────────────────────────────┐  │
│  │ Lipid Type: [DPPC ▾]         │  │
│  │                               │  │
│  │ Dimensions:                   │  │
│  │   X: [100.0] Angstrom        │  │
│  │   Y: [100.0] Angstrom        │  │
│  │                               │  │
│  │ Composition:                  │  │
│  │   ☑ Single lipid type        │  │
│  │   ☐ Mixed (advanced)         │  │
│  │                               │  │
│  │ Options:                      │  │
│  │   ☑ Randomize rotation       │  │
│  │   ☐ Add solvent shell        │  │
│  │                               │  │
│  │ Name: [Membrane_001_____]    │  │
│  │ Style: [Ball and Stick ▾]    │  │
│  │                               │  │
│  │ Info: 15x15 grid, 225 lipids │  │
│  │       per leaflet             │  │
│  │                               │  │
│  │     [ Build Membrane ]        │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

#### User Flow

1. User selects a lipid type from the dropdown (DPPC, POPC, DOPE, cholesterol, etc.)
2. User specifies membrane X and Y dimensions in Angstroms
3. Info line shows the resulting grid size and lipid count
4. User clicks **"Build Membrane"**
5. A bilayer object appears in the scene — two leaflets of lipids oriented head-out, tails-in
6. The membrane is registered in the molecule list

#### Advanced Option: Mixed Composition

When "Mixed" is enabled, additional controls appear:

```
│  Composition (Mixed):             │
│    DPPC: [70] %                   │
│    Cholesterol: [30] %            │
│    [+ Add Lipid Type]             │
```

This is a stretch goal for Phase 2. Single-type membranes come first.

### 5.3 Technical Implementation

#### 5.3.1 Approach: Template Replication

The builder works by:

1. **Loading a template lipid** — a single lipid molecule from a bundled PDB file
2. **Defining the grid** — compute how many lipids fit in the requested X × Y area based on area-per-lipid
3. **Placing lipids on a 2D grid** — for each grid position:
   - Clone the template
   - Translate to grid position (X, Y)
   - Randomize rotation around the membrane normal (Z-axis) if enabled
4. **Creating both leaflets** — the upper leaflet is the original grid; the lower leaflet is a copy rotated 180° around the X-axis and offset by the bilayer thickness

#### 5.3.2 Core Algorithm: `builders/membrane_builder.py`

```python
class MembraneBuilder:
    """Generates a lipid bilayer from a template lipid structure."""

    # Default parameters (DPPC)
    LIPID_PARAMS = {
        'DPPC': {
            'area_per_lipid': 65.0,    # Angstrom^2
            'bilayer_thickness': 34.3,  # Angstrom (head-to-head)
            'template_file': 'DPPC.pdb',
        },
        'POPC': {
            'area_per_lipid': 68.3,
            'bilayer_thickness': 36.5,
            'template_file': 'POPC.pdb',
        },
        'DOPE': {
            'area_per_lipid': 69.0,
            'bilayer_thickness': 35.0,
            'template_file': 'DOPE.pdb',
        },
        'CHL1': {
            'area_per_lipid': 40.0,
            'bilayer_thickness': 34.0,
            'template_file': 'CHL1.pdb',
        },
    }

    def __init__(self, lipid_type: str, size_x: float, size_y: float,
                 randomize_rotation: bool = True):
        self.lipid_type = lipid_type
        self.size_x = size_x  # Angstroms
        self.size_y = size_y  # Angstroms
        self.randomize = randomize_rotation
        self.params = self.LIPID_PARAMS[lipid_type]

    def build(self) -> biotite.structure.AtomArray:
        """Build the full bilayer."""
        template = self._load_template()
        template = self._orient_template(template)  # Ensure tail-down orientation

        spacing = math.sqrt(self.params['area_per_lipid'])
        nx = int(self.size_x / spacing)
        ny = int(self.size_y / spacing)

        upper_leaflet = self._build_leaflet(
            template, nx, ny, spacing,
            z_offset=self.params['bilayer_thickness'] / 2,
            flip=False,
            chain_id='A'
        )
        lower_leaflet = self._build_leaflet(
            template, nx, ny, spacing,
            z_offset=-self.params['bilayer_thickness'] / 2,
            flip=True,
            chain_id='B'
        )

        full = struc.array([upper_leaflet, lower_leaflet])
        return full

    def _build_leaflet(self, template, nx, ny, spacing, z_offset, flip, chain_id):
        """Place lipids on a grid for one leaflet."""
        lipids = []
        res_id_counter = 1

        for ix in range(nx):
            for iy in range(ny):
                lipid = template.copy()

                # Position on grid (centered)
                x = (ix - nx/2) * spacing
                y = (iy - ny/2) * spacing

                # Random rotation around Z
                if self.randomize:
                    angle = random.uniform(0, 2 * math.pi)
                    rot = Rotation.from_euler('z', angle)
                    lipid.coord = rot.apply(lipid.coord)

                # Flip for lower leaflet (rotate 180° around X)
                if flip:
                    rot = Rotation.from_euler('x', math.pi)
                    lipid.coord = rot.apply(lipid.coord)

                # Translate to grid position
                lipid.coord[:, 0] += x
                lipid.coord[:, 1] += y
                lipid.coord[:, 2] += z_offset

                lipid.chain_id[:] = chain_id
                lipid.res_id[:] = res_id_counter
                res_id_counter += 1

                lipids.append(lipid)

        return struc.array(lipids)

    def _load_template(self):
        """Load template lipid from bundled PDB file."""
        template_path = Path(__file__).parent / "data" / self.params['template_file']
        pdb_file = biotite.structure.io.pdb.PDBFile.read(str(template_path))
        return pdb_file.get_structure(model=1)

    def _orient_template(self, template):
        """
        Orient the template lipid so that:
        - The headgroup is at +Z
        - The tail is at -Z
        - The lipid center of mass is at the origin
        """
        # Center at origin
        com = template.coord.mean(axis=0)
        template.coord -= com

        # Identify headgroup atoms (phosphorus, nitrogen in head)
        # and tail atoms (terminal carbons)
        # Orient so head is +Z direction
        # (Implementation depends on lipid topology)
        return template
```

#### 5.3.3 Template Lipid Files

We need to bundle PDB files for each supported lipid type. Sources:

1. **Extract from existing MD simulations** — Take a single lipid from a CHARMM-GUI or Martini equilibrated membrane
2. **Use RCSB ligand entries** — Some lipids have component definitions in the PDB Chemical Component Dictionary
3. **Generate with CHARMM-GUI** — Build a minimal membrane, extract one lipid

**Bundled files** (in `proteinblender/builders/data/`):
- `DPPC.pdb` — Dipalmitoylphosphatidylcholine (~130 atoms)
- `POPC.pdb` — Palmitoyloleoylphosphatidylcholine (~134 atoms)
- `DOPE.pdb` — Dioleoylphosphatidylethanolamine (~130 atoms)
- `CHL1.pdb` — Cholesterol (~74 atoms)

Total bundle size: ~50-80 KB (negligible).

#### 5.3.4 MolecularNodes Integration

Same pattern as DNA builder — the resulting `AtomArray` is fed through `Molecule.create_object()`. The lipid residue names (DPPC, POPC, etc.) are already in MolecularNodes' `data.py`, so `is_lipid` attributes will be set correctly automatically.

#### 5.3.5 Performance Considerations

A 100×100 Å membrane with DPPC (spacing ~8.06 Å) = ~12×12 grid = 144 lipids per leaflet = 288 lipids total. At ~130 atoms/lipid = ~37,440 atoms. This is comparable to a large protein and should render fine.

A 500×500 Å membrane = ~62×62 grid = 3,844 lipids/leaflet = ~1M atoms. This will be slow. The operator should warn for large membranes and potentially offer a coarse-grained option (single sphere per lipid) for very large systems.

**Suggested limits:**
- Default max: 200×200 Å (manageable atom count)
- Soft warning above 300×300 Å
- Hard limit at 500×500 Å

### 5.4 Operator Definition

**File:** `proteinblender/operators/membrane_operators.py`

```python
class MEMBRANE_PB_OT_build(Operator):
    bl_idname = "membrane.build"
    bl_label = "Build Membrane"
    bl_description = "Generate a phospholipid bilayer membrane"
    bl_options = {'REGISTER', 'UNDO'}

    lipid_type: EnumProperty(
        name="Lipid Type",
        items=[
            ('DPPC', "DPPC", "Dipalmitoylphosphatidylcholine"),
            ('POPC', "POPC", "Palmitoyloleoylphosphatidylcholine"),
            ('DOPE', "DOPE", "Dioleoylphosphatidylethanolamine"),
            ('CHL1', "Cholesterol", "Cholesterol"),
        ],
        default='DPPC',
    )
    size_x: FloatProperty(
        name="X Size",
        description="Membrane width in Angstroms",
        default=100.0,
        min=20.0,
        max=500.0,
        unit='NONE',
    )
    size_y: FloatProperty(
        name="Y Size",
        description="Membrane depth in Angstroms",
        default=100.0,
        min=20.0,
        max=500.0,
        unit='NONE',
    )
    randomize_rotation: BoolProperty(
        name="Randomize Rotation",
        description="Randomly rotate each lipid around the membrane normal",
        default=True,
    )
    name: StringProperty(name="Name", default="Membrane")
    style: EnumProperty(
        name="Style",
        items=[
            ('ball_and_stick', "Ball and Stick", ""),
            ('spheres', "Spheres", ""),
            ('surface', "Surface", ""),
        ],
        default='ball_and_stick',
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "lipid_type")
        row = layout.row(align=True)
        row.prop(self, "size_x", text="X (Å)")
        row.prop(self, "size_y", text="Y (Å)")
        layout.prop(self, "randomize_rotation")
        layout.prop(self, "name")
        layout.prop(self, "style")

        # Info readout
        params = MembraneBuilder.LIPID_PARAMS.get(self.lipid_type, {})
        if params:
            spacing = math.sqrt(params['area_per_lipid'])
            nx = int(self.size_x / spacing)
            ny = int(self.size_y / spacing)
            total = nx * ny * 2
            box = layout.box()
            box.label(text=f"{nx}x{ny} grid | {total} lipids total")
            box.label(text=f"Bilayer thickness: {params['bilayer_thickness']:.1f} Angstrom")

    def execute(self, context):
        try:
            builder = MembraneBuilder(
                lipid_type=self.lipid_type,
                size_x=self.size_x,
                size_y=self.size_y,
                randomize_rotation=self.randomize_rotation,
            )
            array = builder.build()
            # ... create object and register (same pattern as DNA)
            self.report({'INFO'}, f"Created {self.lipid_type} membrane: {self.name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Membrane build failed: {str(e)}")
            return {'CANCELLED'}
```

### 5.5 Testing Strategy

1. **Unit test**: Build a small 50×50 Å DPPC membrane
   - Verify bilayer has two leaflets
   - Verify upper leaflet headgroups at +Z, lower at -Z
   - Verify lipid spacing matches expected area-per-lipid
   - Verify total atom count = (lipids_per_leaflet × 2) × atoms_per_lipid

2. **Visual test**: Render with ball-and-stick, verify bilayer shape

3. **Performance test**: Build 200×200 Å membrane, measure time and viewport responsiveness

### 5.6 Estimated Scope

| Component | Files | Complexity |
|-----------|-------|-----------|
| `builders/membrane_builder.py` | 1 new file (~250-350 lines) | Medium-High |
| `builders/data/DPPC.pdb` etc. | 4 template PDB files | None — static assets |
| `operators/membrane_operators.py` | 1 new file (~100-150 lines) | Medium |
| Panel additions to `builder_panel.py` | Existing file modified | Low |
| Property additions to `builder_props.py` | Existing file modified | Low |

---

## 6. Phase 3: A-Form & Z-Form DNA Support

### 6.1 A-Form DNA

Uses the same `DNABuilder` class with different parameters:

| Parameter | B-form | A-form |
|-----------|--------|--------|
| Rise per bp | 3.4 Å | 2.6 Å |
| Twist per bp | 36.0° | 32.7° |
| bp per turn | 10.0 | 11.0 |
| Diameter | 20.0 Å | 23.0 Å |
| Sugar pucker | C2'-endo | C3'-endo |

The A-form template nucleotides should be extracted from an A-form crystal structure (e.g., PDB `440D` or similar).

Key differences beyond parameters:
- Base pairs are tilted ~19° relative to the helix axis (inclination)
- The major groove is deeper and narrower
- Sugar pucker changes affect backbone geometry

**Implementation**: Add `A` case to `HELIX_PARAMS` dict, bundle an A-form template PDB.

### 6.2 Z-Form DNA

Z-form is structurally distinct:

| Parameter | B-form | Z-form |
|-----------|--------|--------|
| Rise per bp | 3.4 Å | 3.7 Å |
| Twist per bp | 36.0° | −30.0° (left-handed) |
| bp per turn | 10.0 | 12.0 |
| Diameter | 20.0 Å | 18.0 Å |
| Handedness | Right | **Left** |
| Repeat unit | 1 bp | **2 bp** (dinucleotide) |

Z-form adds complexity:
- Left-handed helix (negative twist)
- Alternating syn/anti glycosidic conformations (the zig-zag pattern)
- Preferentially forms with alternating purine-pyrimidine sequences (GC repeats)
- The builder should warn if the sequence is not a good Z-DNA candidate

**Implementation**: Requires a Z-form template PDB (e.g., PDB `4OCB`) and a 2-step placement algorithm (alternating the nucleotide conformation every other position).

### 6.3 Timeline

Phase 3 should only begin after Phase 1 (B-form) is validated. The builder architecture is designed to be extensible — adding new forms is primarily about new parameter sets and template structures, not new algorithms.

---

## 7. MolecularNodes Upgrade Considerations

### Current State

- **Bundled version**: 4.2.10
- **Latest upstream**: 4.5.12
- **Upstream requires**: Blender 5.1+, Python 3.13

### What the Upgrade Would Give Us

- Bug fixes and performance improvements
- Potentially new geometry node presets
- Better BCIF parsing
- Updated biotite/MDAnalysis compatibility

### What It Would NOT Give Us

- No DNA builder (doesn't exist upstream)
- No membrane builder (doesn't exist upstream)
- No small molecule SMILES support

### Recommendation

**Do not upgrade MN as part of this work.** The features in this plan are built on top of MN, not within it, and do not require any upstream changes. An MN upgrade is a separate maintenance task with its own risks:

1. Blender 5.1 / Python 3.13 requirement means rebuilding all wheels
2. API changes in MN internals could break our `MoleculeWrapper` integration
3. Should be tested in isolation, not combined with feature work

**When to upgrade**: After Phase 1 and 2 are stable, as a dedicated maintenance sprint. The `molecule_wrapper.py` integration layer will need careful testing against MN 4.5.x API changes.

---

## 8. New File & Directory Structure

```
proteinblender/
├── builders/                          # NEW DIRECTORY
│   ├── __init__.py                    # Builder registration
│   ├── dna_builder.py                 # Phase 1: DNA generation algorithm
│   ├── membrane_builder.py            # Phase 2: Membrane generation algorithm
│   └── data/                          # Bundled template structures
│       ├── 1BNA.pdb                   # B-form DNA reference (Dickerson dodecamer)
│       ├── A_form_template.pdb        # Phase 3: A-form reference
│       ├── Z_form_template.pdb        # Phase 3: Z-form reference
│       ├── DPPC.pdb                   # DPPC lipid template
│       ├── POPC.pdb                   # POPC lipid template
│       ├── DOPE.pdb                   # DOPE lipid template
│       └── CHL1.pdb                   # Cholesterol template
├── operators/
│   ├── dna_operators.py               # NEW: DNA build operator
│   ├── membrane_operators.py          # NEW: Membrane build operator
│   └── ... (existing)
├── panels/
│   ├── builder_panel.py               # NEW: Combined builder panel
│   └── ... (existing)
├── properties/
│   ├── builder_props.py               # NEW: Builder PropertyGroup
│   └── ... (existing)
└── ... (existing unchanged)
```

**Modified existing files:**
- `operators/__init__.py` — Add DNA and membrane operator classes to `CLASSES`
- `panels/__init__.py` — Add builder panel to `CLASSES`, call property registration
- `properties/__init__.py` — Register `BuilderProperties`
- `__init__.py` (addon root) — Ensure builder module imports

---

## 9. Dependency Changes

### No New External Dependencies Required

Both builders use only libraries already bundled:
- **biotite** — AtomArray construction, PDB parsing, bond inference
- **scipy** — `scipy.spatial.transform.Rotation` for coordinate transformations
- **numpy** — Array operations

### Optional Future Dependencies

If we later want:
- **SMILES → 3D structures**: Would require RDKit (~50 MB wheel). Not needed for Phase 1-2.
- **MDNA library**: A Python DNA structure generator. Could replace our custom builder. Worth evaluating but adds a dependency.
- **Simulation-ready membranes**: Would require packmol or insane.py. Not in scope.

---

## 10. Risk Assessment & Open Questions

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Template nucleotide extraction from 1BNA produces incorrect geometry | Medium | High | Validate against known B-form parameters; cross-check with 3DNA output |
| Bond generation misses inter-residue connections | Medium | Medium | Use biotite's `connect_via_residue_names()` + manual backbone bonds |
| Large membranes crash Blender viewport | Low | High | Enforce size limits; offer coarse-grained fallback for large systems |
| MolecularNodes `Molecule` class API changes in future upgrade | Medium | Medium | Our builder returns an `AtomArray` — the conversion layer is a thin adapter |
| Lipid template orientation varies between PDB sources | Medium | Medium | Standardize orientation in `_orient_template()` with clear comments |

### Open Questions for Discussion

1. **Panel placement**: Should the builders be in the existing import panel, a sibling panel, or a completely new tab? The mockup above shows a sibling panel under the main ProteinBlender tree.

2. **DNA naming**: Should generated DNA auto-appear in the outliner as a "molecule" like proteins do? Or should it have its own category? Current plan treats it as a molecule (simplest integration).

3. **Membrane + protein combination**: Should we add a convenience operator to "embed protein in membrane" (position a transmembrane protein at the center of the membrane and delete overlapping lipids)? This is a natural follow-up but may be out of scope.

4. **Coarse-grained option**: For very large membranes, should we offer a simplified representation (one sphere per lipid, no atomic detail)? This would be a geometry-nodes-only approach, much faster.

5. **Template lipid source**: Do we have access to pre-equilibrated lipid coordinates, or should we extract from published PDB structures? The quality of the bilayer visualization depends heavily on realistic lipid conformations.

6. **RNA support**: The DNA builder could be extended to build RNA duplexes (A-form helix with U instead of T, 2'-OH on ribose). Should this be a Phase 3 goal alongside A/Z-form DNA?

---

## Appendix A: DNA Helix Parameter Reference

### Comparison of DNA Forms

| Parameter | B-DNA | A-DNA | Z-DNA |
|-----------|-------|-------|-------|
| Handedness | Right | Right | Left |
| Rise per bp (Å) | 3.4 | 2.6 | 3.7 |
| Twist per bp (°) | 36.0 | 32.7 | −30.0 (avg) |
| Base pairs per turn | 10.0 | 11.0 | 12.0 |
| Helix diameter (Å) | 20.0 | 23.0 | 18.0 |
| Pitch per turn (Å) | 34.0 | 28.6 | 44.4 |
| Major groove width (Å) | 22.0 | Narrow/deep | Flat |
| Minor groove width (Å) | 12.0 | Wide/shallow | Narrow/deep |
| Base inclination (°) | ~0 | +19 | Variable |
| Propeller twist (°) | −11.4 | Variable | Variable |
| Sugar pucker | C2'-endo | C3'-endo | Alternating |
| Glycosidic angle | Anti | Anti | Alternating syn/anti |
| Sequence preference | Any | Any | Alternating purine-pyrimidine |

### Watson-Crick Base Pairing

| Base Pair | Hydrogen Bonds | Complementary |
|-----------|---------------|---------------|
| A — T | 2 | A ↔ T |
| G — C | 3 | G ↔ C |

### Nucleotide Atom Counts (approximate)

| Residue | Heavy Atoms | With Hydrogens |
|---------|-------------|----------------|
| dA (deoxyadenosine) | 22 | 33 |
| dT (deoxythymidine) | 20 | 31 |
| dG (deoxyguanosine) | 23 | 34 |
| dC (deoxycytidine) | 19 | 30 |

### Reference Structures

| PDB ID | Description | Resolution | Use |
|--------|-------------|-----------|-----|
| 1BNA | Dickerson dodecamer (B-DNA) | 1.9 Å | B-form template extraction |
| 440D | A-form DNA decamer | 1.6 Å | A-form template extraction |
| 4OCB | Z-form DNA | 1.2 Å | Z-form template extraction |

---

## Appendix B: Lipid Bilayer Parameter Reference

### Common Lipid Parameters

| Lipid | Area per Lipid (Å²) | Bilayer Thickness (Å) | Atoms per Molecule |
|-------|---------------------|----------------------|-------------------|
| DPPC | 65.0 | 34.3 | ~130 |
| POPC | 68.3 | 36.5 | ~134 |
| DOPE | 69.0 | 35.0 | ~130 |
| Cholesterol | 40.0 | 34.0 | ~74 |

### Grid Calculation

For a membrane of dimensions X × Y Angstroms with lipid of area A:

```
spacing = sqrt(A)          # Grid spacing in Angstroms
nx = floor(X / spacing)    # Grid points in X
ny = floor(Y / spacing)    # Grid points in Y
lipids_per_leaflet = nx × ny
total_lipids = lipids_per_leaflet × 2
total_atoms ≈ total_lipids × atoms_per_lipid
```

### Example Size Estimates

| Membrane Size | DPPC Lipids | Total Atoms | Expected Performance |
|--------------|-------------|-------------|---------------------|
| 50 × 50 Å | ~76 | ~9,880 | Fast |
| 100 × 100 Å | ~308 | ~40,040 | Good |
| 200 × 200 Å | ~1,232 | ~160,160 | Moderate |
| 500 × 500 Å | ~7,692 | ~999,960 | Slow (warn user) |

### Sources

- Nagle & Tristram-Nagle (2000), "Structure of lipid bilayers," _Biochim. Biophys. Acta_
- Kučerka et al. (2011), "Fluid phase lipid areas and bilayer thicknesses," _BBA - Biomembranes_
- Web 3DNA 2.0, _Nucleic Acids Research_ 47(W1), W26-W34 (2019)
- DNA structural parameters from Calladine & Drew, _Understanding DNA_ (3rd ed., Academic Press)
