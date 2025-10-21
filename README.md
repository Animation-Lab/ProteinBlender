# ProteinBlender

## Overview
ProteinBlender is a powerful Blender addon for biochemists and researchers that enhances protein visualization and animation. Built on top of MolecularNodes, it provides a user-friendly interface for creating high-quality molecular visualizations and animations directly within Blender.

## Features
- Import and visualize protein structures from PDB files
- Manage multiple molecules in a single scene
- Create domain selections for specific parts of proteins
- Customize molecular representations (cartoon, surface, ball-and-stick, etc.)
- Animate protein dynamics and interactions
- Dedicated workspace with specialized panels for molecular editing

## Requirements
- Blender 4.2 or newer
- MolecularNodes (included)

## Installation

### Option 1: Extension Repository (Recommended - Auto-Updates!)

Get automatic update notifications directly in Blender:

1. Open Blender 4.2+
2. Go to `Edit` → `Preferences` → `Get Extensions` → `Repositories`
3. Click `+` → `Add Remote Repository`
4. Enter:
   - **Name**: `ProteinBlender`
   - **URL**: `https://PLACEHOLDER_URL_HERE/index.json` _(will be updated after repo transfer)_
5. Browse extensions and install ProteinBlender
6. Enable "Check for Updates on Start" for automatic update notifications

See [EXTENSION_REPOSITORY.md](EXTENSION_REPOSITORY.md) for detailed instructions.

### Option 2: Manual Installation

1. Download the latest `.zip` from [Releases](https://github.com/dillonleelab/proteinblender/releases)
2. In Blender, go to `Edit` → `Preferences` → `Get Extensions`
3. Click `Install from Disk` and select the downloaded zip file
4. Restart Blender

**Note**: Manual installation does not provide automatic update notifications.

## Project Structure
The addon is organized into several key components:

- **Core**: Contains the main functionality for molecule management and domain selection
- **Operators**: Implements the operations for protein import, domain manipulation, and more
- **Panels**: Defines the UI panels for the addon
- **Properties**: Contains property definitions for proteins and molecules
- **Utils**: Includes utility functions and MolecularNodes integration

## Author
Dillon Lee

## License
[License information]


