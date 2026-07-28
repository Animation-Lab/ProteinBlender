# ProteinBlender test suite

Automated regression tests for the addon, run **inside Blender's Python** so
they exercise the real `bpy` API, real operators, and real geometry — not
mocks. The goal: change code without fear that a distant feature silently
broke.

## Quick start

```bash
# whole suite (auto-discovers Blender)
python tests/run_tests.py -v

# the whole suite on EVERY installed Blender (5.0 / 5.1 / 5.2), one summary
python tests/run_all_versions.py
python tests/run_all_versions.py --ui            # also the foreground UI suite
python tests/run_all_versions.py --bootstrap     # install pytest/deps into each first
python tests/run_all_versions.py --only 5.1 5.2  # limit to some versions

# a single lane / module / keyword
python tests/run_tests.py tests/unit
python tests/run_tests.py tests/integration/test_domains.py
python tests/run_tests.py -k linker
python tests/run_tests.py -m "not network"     # skip tests that fetch from RCSB
python tests/run_tests.py -m "not slow"         # skip save/load subprocess tests

# high-risk tests, each in a fresh Blender process
python tests/run_isolated_tests.py

# real foreground window/event loop (use xvfb-run on headless Linux)
python tests/run_ui_tests.py

# a Blender you already have open, observed through its viewport
python tests/run_live_tests.py --preflight
python tests/run_live_tests.py -v

# the actual shipped ZIP: build -> validate -> install -> enable -> reopen
python tests/artifact/run_artifact_tests.py --prepare-wheels

# pin a specific Blender
python tests/run_tests.py --blender "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"
```

## Mandatory normal-profile deployment

After every product-code change, deploy the tested working tree into both
normal Blender installations before reporting completion:

```bash
python scripts/deploy_normal_blender.py
```

The deployer updates Blender 5.2 and 5.1 in both legacy `scripts/addons` and
any installed `extensions/*/proteinblender` copy, preserves dependency wheels,
and byte-verifies every copied Python file. Then fully close Blender,
restart each applicable version without `--factory-startup`, and reproduce the
changed user workflow through its public UI operator. Repository tests alone
do not establish that a normal Blender profile is running the new code.

`run_tests.py` finds Blender (via `--blender`, then `$BLENDER_PATH`, then the
standard install dirs) and launches the suite headless. To run *directly*
inside a Blender you already have open a shell to:

```bash
"<blender>" --background --factory-startup --python tests/run_blender.py -- tests -v
```

## One-time setup

The suite needs `pytest` and `syrupy` in **Blender's** Python
(not your system Python):

```bash
"C:/Program Files/Blender Foundation/Blender 5.0/5.0/python/bin/python.exe" \
    -m pip install pytest syrupy
```

The addon's scientific dependencies (numpy, biotite, MDAnalysis, databpy, …)
are already present in Blender's Python via the addon wheels, so there's
nothing else to install.

## Running across Blender versions (5.0 / 5.1 / 5.2)

The suite is meant to pass identically on every supported Blender. Two
cross-version traps have bitten this project, so the runner now guards against
both:

- **Geometry-nodes modifier-input API changed in 5.2.** 4.2-5.1 store socket
  values at `mod[identifier]`; 5.2 moved them to
  `mod.properties.inputs[identifier]["value"]` and rejects the old subscript.
  All such access goes through `proteinblender/utils/gn_compat.py`, which
  supports both. Never read/write a modifier input directly - use that helper.

- **A broken dependency install fails cleanly, not cryptically.** Before
  collecting tests, `run_blender.py` imports every core dependency and, on any
  failure, aborts with an actionable message (which package, what error, how to
  repair) instead of a confusing downstream error. The classic failure is a
  Windows wheel unpacked without its sibling `<pkg>.libs` folder (missing
  OpenBLAS/Arrow DLLs), which makes `scipy` / `MDAnalysis` / `starfile` raise
  `ImportError: DLL load failed` while pure-Python packages still import - so
  the addon silently refuses to load. If you see this, repair that Blender's
  deps (see the dev helper `dev/install_deps.sh [version]`, which force-
  reinstalls the pinned wheels and then verifies imports inside Blender). Set
  `PB_SKIP_DEP_CHECK=1` to bypass the preflight.

  On Windows, a stale **installed** copy of the add-on (its `extensions/.local`
  deps) can shadow a good user-site install with a partial one. When testing
  from source, either keep that `.local` healthy or don't have the add-on
  installed as an extension in the Blender you test against.

CI runs the offline suite on 4.2/5.0/5.1/5.2 and the foreground-UI suite on
5.0/5.1/5.2 (`.github/workflows/test-blender.yml`).

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
  live/              # drives a Blender you already have open, over the BlenderMCP socket
```

The `live/` lane is the one exception to "runs inside Blender": it runs in
system Python and attaches to an open, windowed Blender, so it can observe the
actual viewport and, uniquely in this suite, assert on **color**. See
[live/README.md](live/README.md). It skips when no Blender is listening.

## Design goal these tests protect

ProteinBlender must stay a **self-contained UI**.
Every capability a user needs - select, colour, style, puppet, pose, DNA, keyframe - is exercised through the addon's own `proteinblender.*` / `molecule.*` operators and the PB outliner, never through `bpy.ops.object.*` or Blender's native outliner/timeline.
If a capability can only be reached through Blender-native UI, that is drift, and these tests are where it should surface.
Prefer driving a new test through the addon's own operator over reaching for a Blender-native fallback, even when the fallback is shorter.

The operator must also be the one exposed by the panel being tested. Imports
use `molecule.import_local`; domain splits select the Protein Outliner row and
invoke `proteinblender.split_domain_popup`. Lower-level methods are acceptable
for state inspection or narrowly scoped internal invariants, but not as a
substitute trigger in behavioral regressions. A repository contract prevents
direct scene-manager imports and lower-level split operators from returning to
the behavioral lanes.

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
  registered segfaults (`EXCEPTION_STACK_OVERFLOW`) on Blender 5.0 and 5.1, and
  hangs indefinitely on 5.2 (measured: killed after 9 minutes). So roundtrip
  tests save a `.blend` then spawn a *fresh* Blender that opens the file before
  registering (`roundtrip/_verify.py`). These are marked `slow`.
- **...which means `load_post` never fires there, so the verifier fires it.**
  Opening before registration is what makes the reopen survivable, and it is
  also why none of the add-on's ten load handlers run on their own.
  `_verify.simulate_file_load` calls the whole `load_post` chain by hand and
  then invokes the deferred bodies those handlers schedule - `bpy.app.timers`
  never ticks in `--background`, so the registry rebuild, the linker rebuild
  and the force-field re-apply are otherwise unreachable from any headless
  test. Do not "reconstruct" with `sync_molecule_list_after_undo`: it is an
  undo/redo handler, and using it is how this lane spent a long time reporting
  on file loading while exercising undo.
- **A save/load builder must assert the state it built.** An empty scene
  round-trips perfectly. `roundtrip/_builders.py` ends every builder with
  assertions that the poses, linkers, puppets or membranes it claims to have
  made are actually there, because a builder that fails quietly turns its case
  into a vacuous pass.
- **Panels can't be drawn headless.** `--background` has no window/screen, so
  panel tests assert registration and exercise `poll()` rather than `draw()`.
- **Never hold an outliner row across an operator.** Most PB operators finish by
  calling `build_outliner_hierarchy`, which clears and refills
  `scene.outliner_items`. Any row object captured beforehand is left dangling,
  and Blender does not raise on a stale `CollectionProperty` row - it returns
  defaults, so `item.item_id` silently reads `""` once the slot is reused. That
  made `test_linkers.py` fail roughly half the time. Capture `item_id` strings,
  call the operator, then re-resolve the rows you need from the rebuilt
  collection (see `_setup_puppet_two_chains`). The same applies to
  `molecule_list_items` and `pb2_linkers`.

## Markers

| marker        | meaning                                             |
|---------------|-----------------------------------------------------|
| `unit`        | pure logic, no live scene                           |
| `integration` | drives addon operators against a real scene         |
| `roundtrip`   | save/load preservation (spawns a second Blender)    |
| `network`     | fetches from RCSB/AlphaFold (needs internet)        |
| `slow`        | more than a couple seconds                          |
| `visual`      | renderer-observed visual regression                 |
| `live`        | drives an already-open, windowed Blender over MCP   |

## Release-quality lanes

The suite has deliberately separate trust boundaries:

- **Source suite** — fast pytest feedback from the checked-out package, inside
  real Blender. This is the main suite described above.
- **Process isolation** — reruns registration, native-crash, rendering, and
  save/load tests with one fresh Blender process per selected node id.
- **Installed artifact** — resolves release wheels, asks Blender to validate
  and build the extension, installs the ZIP into an isolated local repository,
  enables it under `bl_ext.pb_test.proteinblender`, imports an offline PDB, and
  verifies a saved file in a second process. Source-tree imports are rejected.
- **Foreground UI** — starts Blender with a real window and
  `--enable-event-simulate`; timer-separated scenarios force panel redraws,
  assert that the real Protein Blender workspace has a Scene Properties editor
  and that all nine expected panels are registered, context-compatible, and
  visible under valid live state; invoke/cancel real dialogs with window events, exercise custom-pivot
  deselection, enter/leave DNA and membrane edit modes, and drive undo/redo.
- **Visual** — real Cycles observations prove output is nonempty and that user
  style choices produce materially different images. These use robust image
  relationships rather than byte-identical PNGs, which vary across devices.
- **Live viewport** — attaches to an open, windowed Blender running the
  *deployed* add-on and observes its 3D viewport directly. This is the only lane
  that can see the shading path a user looks at, and the only one that asserts
  on colour rather than an alpha mask. Skips when no Blender is listening; set
  `PB_LIVE_REQUIRED=1` to make that a failure instead.

Set `PB_STRICT_CONTEXT=1` in a canonical environment. Context-sensitive tests
that are allowed to skip on an arbitrary developer machine then fail instead,
preventing a product regression from masquerading as a harmless headless skip.

CI definitions live in `.github/workflows/test-blender.yml` (required PR lanes)
and `test-blender-nightly.yml` (four-platform artifact installation, Blender
daily API drift, network contracts, and process isolation).

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
