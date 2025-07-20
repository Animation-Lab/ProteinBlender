# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProteinBlender is a Blender addon for visualizing and animating protein structures. It integrates MolecularNodes functionality and provides a comprehensive UI for working with molecular data in Blender.

## Development Setup

### Prerequisites
- Blender 4.4 or higher
- Python 3.11 (matching Blender's Python version)
- You must use Blender's Python environment to test and build code
- VS Code (recommended) with Blender extension
- For development user Windows PowerShell when running commands

### Environment Variables
- `BLENDER_PATH`: Path to Blender executable (required for build.py)

### Key Commands

```bash
# Build the addon package
python build.py

# Development mode - register addon without installing
blender --python dev_register.py

# VS Code tasks available:
# - "Dev: Register Addon" (Ctrl+Shift+B)
# - "Build: Package Addon"
```

## Architecture

### Core Structure
- `__init__.py`: Main addon registration and lifecycle management
- `operators/`: All Blender operators (add molecules, keyframes, etc.)
- `panels/`: UI panels for properties, animation, and about sections
- `properties.py`: Blender property definitions and RNA structure
- `utilities/`: Helper modules including embedded MolecularNodes
- `depends/`: Platform-specific wheel dependencies

### Key Components

1. **Dependency Management**: Custom system in `depends/` that installs required packages on first load
2. **MolecularNodes Integration**: Embedded as `utilities/molnodes/` - provides core molecular visualization
3. **Property System**: Uses Blender's RNA system with molecule lists stored in scene properties
4. **Undo/Redo Handling**: Custom handlers in `save.py` to sync molecule lists across undo steps

### Important Files
- `properties.py`: Defines all addon properties and data structures
- `operators/add_molecule.py`: Main entry point for loading molecular data
- `panels/panel_property.py`: Primary UI for molecule management
- `utilities/molnodes/`: Embedded MolecularNodes functionality

### MCP Access
- `blender-api`: Provides Blender API documentation assistance - A full description of the MCP can be found in documentation/MCP_DESCRIPTION.md

## Common Development Tasks

### Adding New Operators
1. Create new file in `operators/` directory
2. Define operator class inheriting from `bpy.types.Operator`
3. Register in `__init__.py` using `OPERATOR_CLASSES` list

### Working with Molecules
- Access molecule list: `bpy.context.scene.pb2_molecules`
- Current molecule: `bpy.context.scene.pb2_molecules[bpy.context.scene.pb2_molecules_idx]`
- Each molecule has domains, poses, and keyframes

### Testing
- Test scripts located in `tmp_tests/` directory
- Run individual tests directly in Blender
- No formal test framework currently implemented

## Key Concepts

### Molecule Structure
- Each molecule object contains:
  - `ob_name`: Name in Blender scene
  - `filepath`: Source PDB/structure file
  - `domains`: Selection domains for parts of the molecule
  - `poses`: Saved configurations
  - `keyframes`: Animation keyframes

## UI - Current Development
- Focussing on a UI redesign
  - `reference image`: A reference image with descriptions can be found in ui-development/proteinblender-proposed-layout.png

## Debugging Tips

1. Enable Blender console for Python output
2. Use `print()` statements - they appear in Blender's system console
3. Check `save.py` for undo/redo issues
4. Molecule sync issues often relate to property update callbacks

## Recent Development Focus

- Undo/redo functionality improvements
- Chain mapping fixes for multi-chain proteins
- Property synchronization across Blender contexts