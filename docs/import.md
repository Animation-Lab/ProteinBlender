---
layout: default
title: Import Proteins
---

# Import Proteins

[Back to Home](index.html)

Learn how to load protein structures into Blender using ProteinBlender.

Watch the full tutorial:

[![ProteinBlender Tutorial](https://img.youtube.com/vi/XLPvo1Ax3G4/0.jpg)](https://www.youtube.com/watch?v=XLPvo1Ax3G4 "ProteinBlender Tutorial")

## Overview

ProteinBlender supports importing proteins from:
- Local PDB or mmCIF files (button, File > Import, or drag and drop)
- RCSB Protein Data Bank (online)
- AlphaFold Database (online)

## Opening the Importer

1. Open Blender and make sure ProteinBlender is installed.
2. The **Protein Blender** workspace opens automatically.
   If it does not, choose it from the workspace tabs along the top of the window.
3. The **Protein Import** box is at the top of the Scene Properties editor on the right.
   It has a **Method** menu and an ID field, then two buttons: **Download** and **Import Local File**.

## Import from File

There are three ways to open a structure file from your computer.

### Import Local File button

1. In the **Protein Import** box, click **Import Local File**.
2. Blender's file browser opens.
   Navigate to your PDB or mmCIF file.
3. Click the file, then click **Import**.
   Select several files (Ctrl-click or Shift-click) to import them all at once.
4. The protein appears in the 3D viewport and in the **Protein Outliner** panel.

### File > Import

Choose **File > Import > Protein Structure (.pdb, .cif, .mmcif)**.
This opens the same file browser as the button.

### Drag and drop

Drag one or more structure files from your file manager onto the Blender window.
They are imported straight away.
Compressed files (such as `.cif.gz`) can't be dropped.
Open those with the button or **File > Import**.

> **Note:** Blender's own **File > Open** only opens `.blend` files.
> Use one of the three routes above for protein structures.

### Importing the same file twice

Importing a file that is already loaded adds a second, independent protein.
The copy is named with a numeric suffix, such as `4hhb_002`.

### Files with several models

A file that holds several models (for example an NMR ensemble or a molecular dynamics snapshot) needs to be read one of two ways.
Models that are alternative states of one protein are loaded as states for Morphsets.
Models that are simultaneous copies forming one assembly are loaded as assembly copies.
ProteinBlender detects NMR ensembles and `.pdb1`-style assembly files by itself.
For any other multi-model file, set **Multiple models** in the file browser's options panel before clicking **Import**.
Dropped files use automatic detection only.

### Supported File Formats

- **.pdb**, **.ent** - Protein Data Bank format
- **.cif**, **.mmcif**, **.pdbx** - Macromolecular Crystallographic Information File
- **.bcif** - Binary CIF
- **.pdb1**, **.pdb2**, ... - biological assembly files from the RCSB (drag and drop covers up to **.pdb30**)
- Any of these compressed as **.gz**

## Import from Online Database

### From RCSB PDB

1. In the **Protein Import** box, set **Method** to **PDB** (or **mmCIF** to download the mmCIF file).
2. Enter a **4-character PDB ID** (e.g., 1CRN, 6LU7, 7BV2).
3. Click **Download**.
4. The structure will be downloaded and imported automatically.

**Popular PDB IDs to try:**
- **1CRN** - Crambin (small protein, good for testing)
- **6LU7** - SARS-CoV-2 Main Protease
- **1ATP** - ATP Synthase

### From AlphaFold

1. In the **Protein Import** box, set **Method** to **AlphaFold**.
2. Enter a **UniProt ID** (e.g., P69905, Q9Y6K9).
3. Click **Download**.
4. The predicted structure will be downloaded and imported.

## After Import

Once imported, your protein will:
- Appear in the 3D viewport
- Be listed in the **Protein Outliner** panel
- Be centered at the world origin
- Display with default cartoon representation

## Managing Multiple Proteins

You can import multiple proteins into the same scene:

1. Simply import additional proteins using any method
2. Each protein appears as a separate entry in the Protein Outliner
3. Use the outliner to select and manage individual proteins

## Troubleshooting

### Import Fails

- Check your internet connection (for online imports)
- Verify the PDB ID or UniProt ID is correct
- For a local file, make sure it ends in one of the supported extensions above
- If the error mentions multiple models, import the file with **Import Local File** and set **Multiple models**
- Check the Blender console for error messages

### Protein Doesn't Appear

- Check that you're in the 3D viewport (not another editor)
- Press Numpad . (period) to frame the imported protein
- Look in the Protein Outliner to verify the protein was imported

### Very Slow Import

- Large proteins (1000+ residues) may take 30-60 seconds
- Complex multi-chain assemblies take longer
- Check progress in the bottom-left corner of Blender

## Understanding the Protein Structure

After import, you'll see:

- **Chains**: Individual polypeptide chains (labeled A, B, C, etc.)
- **Domains**: Full chain domains (you can split these later)
- **Hierarchy**: Organized in the Protein Outliner panel

## Next Steps

Now that you've imported a protein, learn how to:

- [Update Visuals](visuals.html) - Change colors and molecular styles
- [Create Puppets](puppets.html) - Group parts for animation

---

[Back to Home](index.html) | [Previous: Installation](installation.html) | [Next: Update Visuals](visuals.html)

