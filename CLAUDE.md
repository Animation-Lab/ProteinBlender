# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProteinBlender is a Blender addon for visualizing and animating protein structures. It integrates MolecularNodes functionality and provides a comprehensive UI for working with molecular data in Blender.

## Development Setup

### Prerequisites
- Blender 4.2 or higher (including Blender 5.0)
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
- Formal pytest suite in `tests/` — runs **headless inside Blender's Python**.
- Run it: `python tests/run_tests.py` (whole suite), or a subset, e.g.
  `python tests/run_tests.py tests/unit` / `-k domain` / `-m "not network"`.
- Lanes: `tests/unit/` (pure logic), `tests/integration/` (operator-driven, one
  module per subsystem), `tests/roundtrip/` (save/load via a subprocess).
- Full guide: [tests/README.md](tests/README.md); coverage map + known
  issues/xfails: [tests/COVERAGE.md](tests/COVERAGE.md).
- One-time setup (per Blender install): install `pytest syrupy pytest-xdist`
  into *Blender's* Python (see tests/README.md).
- The old hand-run scripts (`tests/feature_audit/`, `tests/stress_test/`,
  `tmp_tests/`) are kept for reference but are not part of the suite.

## Bug-Fixing Workflow (test-first — REQUIRED)

Every bug fix follows this order. Do **not** change product code before step 2.

1. **Reproduce with a test.** Add an automated test to `tests/` (usually
   `tests/integration/`) that exercises the exact reported scenario and asserts
   the correct behaviour. Use bundled offline fixtures in `tests/data/`
   (fetch a new PDB into it if needed) — never depend on the network.
2. **Confirm it FAILS (red).** Run the test and verify it fails with the real
   bug signature *before* touching product code. This proves the test actually
   catches the bug rather than passing vacuously.
   - Native crashes (segfault) kill the pytest process — reproduce those in a
     **subprocess** first, and prefer a **deterministic in-process trigger**
     for the committed test (e.g. a removed-node reference raises a catchable
     `ReferenceError`, the analog of the native crash).
3. **Fix** the product code — the smallest change that addresses the root
   cause, not the symptom.
4. **Confirm it PASSES (green)**, then run the **full suite**
   (`python tests/run_tests.py`) to check for regressions. For
   version-sensitive bugs, verify on both Blender 5.0 and 5.1.
5. **Prove red→green rigour** for non-obvious fixes: confirm the test fails on
   the pre-fix code — `git stash push -- <product-file>` → run the test →
   `git stash pop`.
6. **Document**: add a one-line entry to the regression section of
   [tests/COVERAGE.md](tests/COVERAGE.md).

Commits omit any AI/Co-Authored-By attribution.

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
