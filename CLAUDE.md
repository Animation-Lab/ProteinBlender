# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProteinBlender is a powerful Blender addon for biochemists and researchers that enhances protein visualization and animation. Built on top of MolecularNodes, it provides a user-friendly interface for creating high-quality molecular visualizations and animations directly within Blender.

Key features:
- Import and visualize protein structures from PDB files
- Manage multiple molecules in a single scene
- Create domain selections for specific parts of proteins
- Customize molecular representations (cartoon, surface, ball-and-stick, etc.)
- Animate protein dynamics and interactions
- Dedicated workspace with specialized panels for molecular editing

## Development Setup

### Prerequisites
- Windows development environment (primary development platform)
- Blender 4.2.0 or higher (as specified in blender_manifest.toml)
- Python 3.11 (matching Blender's Python version)
- VS Code (recommended) with Blender extension

### Environment Variables
- `BLENDER_PATH`: Path to Blender executable (required for build.py)

### Key Commands

**Important**: On Windows, you must use Blender's bundled Python installation to build the addon, not the system Python.

```powershell
# Build the addon package (Windows PowerShell)
& "C:\Program Files\Blender Foundation\Blender 4.4\4.4\python\bin\python.exe" proteinblender/temp_scripts/build.py

# Development mode - register addon without installing
blender --python proteinblender/temp_scripts/dev_register.py

# Run specific tests
blender --python tmp_tests/test_chain_selection_visibility.py
blender --python tmp_tests/test_operator_registration_debug.py
```

## Architecture

### Core Structure
- `__init__.py`: Main addon registration with dependency management
- `addon.py`: Modular registration system for all addon components
- `core/`: Core functionality modules
  - `domain.py`: Domain creation and management
  - `manager.py`: Base manager classes
  - `molecule_manager.py`: Molecule lifecycle management
  - `molecule_state.py`: State tracking for molecules
  - `molecule_wrapper.py`: Wrapper for molecule objects
- `handlers/`: Event handlers
  - `outliner_handler.py`: Outliner sync and selection handling
- `operators/`: Blender operators
  - `domain_operators.py`: Domain creation and editing
  - `molecule_operators.py`: Molecule import and management
  - `outliner_operators.py`: Outliner-specific operations
  - `pose_operators.py`: Pose saving and loading
  - `selection_operators.py`: Selection utilities
- `panels/`: UI panels
  - `outliner_panel.py`: Protein outliner with tree view
  - `panel_import_protein.py`: Molecule import UI
- `properties/`: Property definitions
  - `molecule_props.py`: Molecule data structures
  - `outliner_properties.py`: Outliner-specific properties
  - `protein_props.py`: Protein-specific properties
- `utils/molecularnodes/`: Full embedded MolecularNodes addon
- `wheels/`: Pre-downloaded platform-specific dependencies

### Key Components

1. **Dependency Management**: 
   - Custom system in `__init__.py` that checks and installs required packages on first load
   - Prefers local wheels in `wheels/` directory before falling back to PyPI
   - Core dependencies: databpy>=0.0.18, MDAnalysis>=2.7.0, biotite>=1.1, mrcfile, starfile, PyYAML
   - Filters out packages provided by Blender (numpy, requests, etc.)

2. **MolecularNodes Integration**: 
   - Embedded as `utils/molecularnodes/` - full addon, not just utilities
   - Provides core molecular visualization and geometry nodes
   - Has its own property system and operators

3. **Property System**: 
   - Uses Blender's RNA system
   - Molecule lists stored in scene properties (`bpy.context.scene.pb2_molecules`)
   - Each molecule has domains, poses, and keyframes
   - Outliner properties for UI state management

4. **Build System**:
   - Downloads platform-specific wheels for Windows x64, Linux x64, macOS ARM64, and macOS x64
   - Updates `blender_manifest.toml` with downloaded wheels
   - Uses Blender's extension build command with `--split-platforms`
   - Requires `BLENDER_PATH` environment variable

### Important Files
- `addon.py`: Central registration point for all addon components
- `core/molecule_manager.py`: Core molecule management logic
- `operators/molecule_operators.py`: Main entry point for loading molecular data
- `panels/outliner_panel.py`: Primary UI with tree view for molecule management
- `utils/molecularnodes/`: Full embedded MolecularNodes addon
- `blender_manifest.toml`: Extension manifest with platform-specific dependencies
- `pyproject.toml`: Python project configuration

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
- Run individual tests directly in Blender: `blender --python tmp_tests/test_name.py`
- Test coverage includes:
  - Chain selection and visibility (`test_chain_selection_visibility.py`)
  - Operator registration (`test_operator_registration_debug.py`)
  - Outliner functionality (`test_outliner_operators.py`)
  - Property system (`test_property_system_debug.py`)
  - Update function calls (`test_update_function_call.py`)
- No formal test framework currently implemented

## Key Concepts

### Molecule Structure
- Each molecule object contains:
  - `ob_name`: Name in Blender scene
  - `filepath`: Source PDB/structure file
  - `domains`: Selection domains for parts of the molecule
  - `poses`: Saved configurations
  - `keyframes`: Animation keyframes

### Chain Mapping
- Recent focus on chain mapping issues (see recent commits)
- Handles multi-chain proteins and domain selections
- Critical for proper visualization and animation

### Animation System
- Poses: Save current molecule state
- Keyframes: Animate between poses over time
- Uses Blender's native animation system

## Debugging Tips

1. Enable Blender console for Python output
2. Use `print()` statements - they appear in Blender's system console
3. Check handlers in `handlers/` directory for UI sync issues
4. Molecule sync issues often relate to property update callbacks
5. Test scripts in `tmp_tests/` provide debugging examples for common issues
6. Documentation in `docs/` covers specific debugging scenarios

## Recent Development Focus

- Protein Outliner implementation with 2-way connectivity
- UI updates and workspace improvements
- Chain selection and visibility fixes
- Removed automatic protein chain splitting for more intuitive grouping
- Domain management dialog preparation