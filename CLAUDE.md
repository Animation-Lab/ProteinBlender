# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProteinBlender is a Blender add-on for visualizing and animating protein structures.
It embeds MolecularNodes for the core molecular visualization and layers a full UI, an undo/redo-aware molecule model, domains/poses, flexible linkers, DNA/RNA and membrane builders, and Brownian motion on top.

## Development setup

### Prerequisites

- Blender 4.2 or higher.
  The manifest floor is `blender_version_min = "4.2.0"` and the add-on is developed against the 5.x series.
- Blender's bundled Python, not a system Python.
  Blender 4.2 ships Python 3.11 and Blender 5.x ships Python 3.13, so the add-on bundles wheels for both `cp311` and `cp313` (see `proteinblender/wheels/`).
- Use Blender's own Python interpreter to install dependencies, run scripts, and build.

### Environment variables

- `BLENDER_PATH`: absolute path to the Blender executable.
  Required by `build.py` and by the test runner's Blender auto-discovery.

### Key commands

```bash
# Build the multi-platform extension package into dist/ (prompts for a version bump).
python build.py

# Build the alpha "swap" channel zips (id = proteinblender_alpha), then restore the tree.
python build.py --alpha

# Load the add-on from source in a running Blender, without packaging or installing.
blender --python dev_register.py

# Run the headless test suite (auto-discovers Blender).
python tests/run_tests.py -v
```

`dev_register.py` appends the repo root to `sys.path`, adds Blender's user site-packages, and enables the `proteinblender` module.
`build.py` bumps the version across `proteinblender/blender_manifest.toml`, `pyproject.toml`, and `proteinblender/__init__.py`, downloads the per-platform wheels, and runs `blender --command extension build` for each target OS.

### Local dev environments

Two setups are in use; both load the add-on from source so edits are picked up on reload.

- VS Code with the "Blender Development" extension (cross-platform).
  It starts Blender, loads the add-on, and reloads it on save.
- WSL (repo) driving Windows Blender (this being a Windows machine).
  Helper tooling lives in an untracked, git-excluded `dev/` folder (`dev/pb gui` launches Blender with hot-reload on save, `dev/pb run`/`dev/pb test` run headless, `dev/install_deps.sh` installs the manifest-pinned deps into Blender's Python); see `dev/README.md`.

## Architecture

### Package layout (`proteinblender/`)

- `__init__.py`: add-on entry point.
  Handles dependency checking/installation and delegates registration to `addon.py`.
- `addon.py`: registration orchestration.
  `register()` / `unregister()` register all classes, properties, and handlers.
- `core/`: the molecule domain model - `MoleculeManager`, molecule wrapper/state, domains, selection manager, viewport sync.
- `operators/`: all Blender operators (import, domains, keyframes, poses, selection, pivots, Brownian).
- `panels/`: UI panels (main panel, molecule list, molecule edit, import, domain maker, poses, outliner, animation, visual setup).
- `properties/`: property groups - `protein_props`, `molecule_props`, `pose_props`, `brownian_props`.
- `linkers/`: the flexible-linker feature (geometry, operators, panel, props, handlers) as a self-contained module.
- `dna_builder/`: DNA/RNA strand builder (sequence, helix geometry, bend rig, operators, panel).
- `membrane_builder/`: geometry-nodes lipid-bilayer builder (shapes, holes, per-protein force field).
- `handlers/`: app handlers - load handlers (workspace persistence across Ctrl+N), selection sync, depsgraph, frame change (color animation).
- `layout/`: `ProteinWorkspaceManager`, which builds the custom ProteinBlender workspace.
- `utils/`: helpers including `scene_manager.py`, `pose_manager.py`, file I/O, chain/animation utilities, and the embedded MolecularNodes at `utils/molecularnodes/`.
- `resources/`, `data/`: bundled assets and data.
- `wheels/`: per-platform, per-Python-version dependency wheels bundled into the extension.

### Registration flow

Registration is centralized in `addon.py`.
Each subpackage exposes a `CLASSES` list (`core`, `handlers`, `operators`, `panels`, and the MolecularNodes `session`), and `register()` iterates them through `bpy.utils.register_class`.
Property groups are registered by their own module `register()` functions (`register_protein_props`, `register_molecule_props`, `register_pose_props`, `register_brownian_props`).
The MolecularNodes session is attached as `bpy.types.Scene.MNSession` and object properties as `bpy.types.Object.mn`.
`register()` calls `unregister()` first to clean up prior state, which is what makes source reloads safe.

### Adding new operators

1. Add the operator class to the appropriate file in `operators/` (or create a new module).
2. Ensure the class is included in the package's `CLASSES` list so `addon.py` registers it.

### Dependency management

- Runtime dependencies: `databpy`, `MDAnalysis`, `biotite`, `mrcfile`, `starfile`, `PyYAML`, plus `numpy`, `scipy`, and `msgpack`.
- MolecularNodes is embedded under `utils/molecularnodes/`, not a pip dependency.
- On first load, `__init__.py` verifies the dependencies and, if needed, installs them from `wheels/` (falling back to PyPI), with Windows DLL-locking handled gracefully and a daily cache to avoid re-checking every startup.
- Versions must stay consistent with the wheels pinned in `blender_manifest.toml`.
  The embedded MolecularNodes targets specific APIs (for example biotite 1.6.0; biotite 1.7 removed `structure.connect_via_residue_names`), so installing "latest" can break the add-on at runtime.

## Working with molecules

- The runtime molecule registry is the `ProteinBlenderScene` singleton in `utils/scene_manager.py`: `ProteinBlenderScene.get_instance()`.
  Its `.molecules` dict maps molecule id to the live `MoleculeWrapper`.
- The scene-persisted molecule list is `scene.molecule_list_items`, with `scene.molecule_list_index` as the active row.
- `scene.selected_molecule_id` identifies the active molecule and is the most-used accessor across operators and panels.
- Import settings live on `scene.protein_props` (for example `pdb_id`, `remote_format`).
- The main entry point for loading a structure by id is the `molecule.import_protein` operator, which reads `scene.protein_props` and calls `ProteinBlenderScene.get_instance().create_molecule_from_id(identifier, import_method='PDB', remote_format='pdb')`.

## Undo/redo

Molecule state is kept in sync across undo/redo by `sync_molecule_list_after_undo` (in `utils/scene_manager.py`), registered on `bpy.app.handlers.undo_post` and `redo_post`.
Selection sync and the frame-change color handler are registered alongside it.
Most molecule-sync issues trace back to these handlers or to property update callbacks.

## Testing

- Formal pytest suite in `tests/`, run **headless inside Blender's Python** so it exercises the real `bpy` API, real operators, and real geometry - not mocks.
- Run it: `python tests/run_tests.py` (whole suite), or a subset, for example `python tests/run_tests.py tests/unit`, `-k domain`, or `-m "not network"`.
- Lanes: `tests/unit/` (pure logic), `tests/integration/` (operator-driven, one module per subsystem), `tests/roundtrip/` (save/load state preservation, verified in a fresh Blender subprocess).
- Offline PDB fixtures live in `tests/data/`; an autouse fixture scrubs the scene around every test; geometry regressions use syrupy snapshots.
- Full guide: [tests/README.md](tests/README.md); coverage map plus known issues/xfails: [tests/COVERAGE.md](tests/COVERAGE.md).
- One-time setup (per Blender install): install `pytest syrupy pytest-xdist` into *Blender's* Python (see tests/README.md).
- The older hand-run scripts (`tests/feature_audit/`, `tests/stress_test/`) are kept for reference but are not part of the suite.

## Bug-fixing workflow (test-first, REQUIRED)

Every bug fix follows this order.
Do **not** change product code before step 2.

1. **Reproduce with a test.**
   Add an automated test to `tests/` (usually `tests/integration/`) that exercises the exact reported scenario and asserts the correct behaviour.
   Use bundled offline fixtures in `tests/data/` (fetch a new PDB into it if needed) - never depend on the network.
2. **Confirm it FAILS (red).**
   Run the test and verify it fails with the real bug signature *before* touching product code, so you know the test actually catches the bug rather than passing vacuously.
   Native crashes (segfault) kill the pytest process, so reproduce those in a subprocess first and prefer a deterministic in-process trigger for the committed test.
3. **Fix** the product code - the smallest change that addresses the root cause, not the symptom.
4. **Confirm it PASSES (green)**, then run the full suite (`python tests/run_tests.py`) to check for regressions.
   For version-sensitive bugs, verify on both Blender 5.0 and 5.1.
5. **Prove red->green rigour** for non-obvious fixes: confirm the test fails on the pre-fix code (`git stash push -- <product-file>` -> run the test -> `git stash pop`).
6. **Document**: add a one-line entry to the regression section of [tests/COVERAGE.md](tests/COVERAGE.md).

## Releases and alpha channel

- `python build.py` builds the release extension and (interactively) bumps the version.
- `python build.py --alpha` builds a parallel **ProteinBlender (Alpha)** extension (`id = proteinblender_alpha`) for testers, who subscribe through Blender's native updater; see `docs/alpha-testing.md`.
- The publish workflow routes zips by embedded id into per-channel indexes (release -> `extensions/index.json`, alpha -> `extensions/alpha/index.json`).

## Debugging tips

1. Watch Blender's system console for Python output (`Window > Toggle System Console` on Windows).
2. `print()` and the module loggers surface there; each package uses a `logging.getLogger(__name__)` logger.
3. For molecule-sync or undo/redo issues, start with the handlers in `handlers/` and `utils/scene_manager.py`.
4. Domains, poses, and selections are stored on the molecule model in `core/`; inspect `MoleculeManager` when state looks wrong.

## Conventions

- Commits omit any AI / Co-Authored-By attribution.
