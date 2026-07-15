# ProteinBlender test suite

Automated regression tests for the addon, run **inside Blender's Python** so
they exercise the real `bpy` API, real operators, and real geometry — not
mocks. The goal: change code without fear that a distant feature silently
broke.

## Quick start

```bash
# whole suite (auto-discovers Blender)
python tests/run_tests.py -v

# a single lane / module / keyword
python tests/run_tests.py tests/unit
python tests/run_tests.py tests/integration/test_domains.py
python tests/run_tests.py -k linker
python tests/run_tests.py -m "not network"     # skip tests that fetch from RCSB
python tests/run_tests.py -m "not slow"         # skip save/load subprocess tests

# pin a specific Blender
python tests/run_tests.py --blender "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"
```

`run_tests.py` finds Blender (via `--blender`, then `$BLENDER_PATH`, then the
standard install dirs) and launches the suite headless. To run *directly*
inside a Blender you already have open a shell to:

```bash
"<blender>" --background --factory-startup --python tests/run_blender.py -- tests -v
```

## One-time setup

The suite needs `pytest`, `syrupy`, and `pytest-xdist` in **Blender's** Python
(not your system Python):

```bash
"C:/Program Files/Blender Foundation/Blender 5.0/5.0/python/bin/python.exe" \
    -m pip install pytest syrupy pytest-xdist
```

The addon's scientific dependencies (numpy, biotite, MDAnalysis, databpy, …)
are already present in Blender's Python via the addon wheels, so there's
nothing else to install.

## Layout

```
tests/
  conftest.py        # registers the addon once; resets the scene around every test; fixtures
  helpers.py         # import_local / import_pdb / build_dna / build_membrane / snapshot utils
  snapshot_ext.py    # deterministic numpy snapshot serialization (syrupy)
  run_blender.py     # headless pytest entrypoint (runs inside Blender)
  run_tests.py       # system-python wrapper: find Blender, launch
  data/              # bundled structures: 1ubq (single chain), 1aki (lysozyme), 4hhb (4 chains)
  unit/              # pure logic — no scene needed (chain maths, DNA sequence, catenary, geometry)
  integration/       # operator-driven — one module per subsystem
  roundtrip/         # save/load state preservation (spawns a fresh Blender to reopen)
```

The older hand-run scripts (`tests/feature_audit/`, `tests/stress_test/`) are
kept for reference but are **not** part of this suite (excluded in
`pyproject.toml`'s `norecursedirs`). Their proven assertions have been ported
into the `integration/` and `roundtrip/` modules.

## How it works (the non-obvious bits)

- **One long-lived process.** Headless Blender runs every test in a single
  process, so state leaks unless you scrub it. The autouse `_clean_scene`
  fixture in `conftest.py` deletes all addon-managed data before *and* after
  each test. If a test sees leftover molecules, that fixture is the first
  suspect.
- **Register in-process, never `addon_disable`.** The addon is registered with
  `proteinblender._test_register()`. We never call `addon_disable` — on Windows
  it triggers wheel cleanup that half-deletes scipy/biotite/MDAnalysis from the
  dev install.
- **Offline by default.** `helpers.import_local(...)` loads bundled structures
  from `tests/data/` — no network. `helpers.import_pdb(...)` fetches from RCSB
  and its tests are marked `@pytest.mark.network`.
- **Save/load can't reopen in-process.** `open_mainfile` after the addon is
  registered segfaults (`EXCEPTION_STACK_OVERFLOW`) on Blender 5.0 and 5.1, so
  roundtrip tests save a `.blend` then spawn a *fresh* Blender that opens the
  file before registering (`roundtrip/_verify.py`). These are marked `slow`.
- **Panels can't be drawn headless.** `--background` has no window/screen, so
  panel tests assert registration and exercise `poll()` rather than `draw()`.

## Markers

| marker        | meaning                                             |
|---------------|-----------------------------------------------------|
| `unit`        | pure logic, no live scene                           |
| `integration` | drives addon operators against a real scene         |
| `roundtrip`   | save/load preservation (spawns a second Blender)    |
| `network`     | fetches from RCSB/AlphaFold (needs internet)        |
| `slow`        | more than a couple seconds                          |

## Writing a new test

```python
import pytest
import helpers as H

@pytest.mark.integration
def test_import_creates_object(scene, sm):
    mol_id = H.import_local("1ubq.pdb", "1ubq")
    assert mol_id in sm.molecules
    assert H.list_item(mol_id) is not None
```

Fixtures: `scene`, `sm`, `single_chain` (1ubq id), `multi_chain` (4hhb id),
`geo_snapshot`. Assert *observable* outcomes (scene properties, `bpy.data`,
scene-manager state), keep each test self-contained, and prefer the small
structures (1ubq/1aki) unless you specifically need multiple chains.

## Geometry regression (syrupy)

For features that generate geometry (DNA, membrane, linkers), snapshot the
evaluated output:

```python
def test_membrane_geometry(geo_snapshot):
    names = H.build_membrane(shape="RECTANGLE", width=10, height=10)
    obj = bpy.data.objects[names[0]]
    assert geo_snapshot == H.eval_positions(obj)
```

Regenerate baselines after an intentional change with `--snapshot-update` and
code-review the `.ambr` diff.

## Coverage

See [COVERAGE.md](COVERAGE.md) for the operator/panel → test-module map and the
list of known gaps / xfails.
