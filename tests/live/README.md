# The live-Blender lane

Tests that drive a **real, open, windowed Blender** over the BlenderMCP socket and observe what is actually on screen.

Every other lane runs headless *inside* Blender's Python.
This one runs in ordinary system Python and attaches to a Blender you already have open, with a real 3D viewport and the *deployed* add-on.

## Why this lane exists

`--background` has no screen.
That single fact bounds what the headless suite can ever prove, and it leaves three gaps this lane fills.

**It can see the viewport.**
The headless lane renders with Cycles through a temporary camera it creates itself.
This lane renders the actual 3D viewport, in the shading mode the user has selected, from the view the user is looking at.

**It can see color.**
Every pixel check in the headless suite reduces a render to an alpha mask (`px[:, 3] > 0.01`) and throws the RGB channels away.
A domain drawn in the wrong color, every domain drawn identically, or a material that never binds are all invisible to it.
This lane measures color, and that is where its most valuable assertions live.

**It runs against the deployed add-on.**
The live Blender loads ProteinBlender from a normal Blender profile, not from the repo.
CLAUDE.md requires changes to be proven in exactly that configuration, and this is the only automated lane that does it.

## Running it

```bash
python tests/run_live_tests.py --preflight      # check the connection, print the environment
python tests/run_live_tests.py -v               # the whole lane
python tests/run_live_tests.py -k membrane      # a subset
python tests/run_live_tests.py tests/live/test_live_dna.py
python tests/run_live_tests.py --required       # fail instead of skip when nothing is live
```

Setup, once per Blender session:

1. Open Blender with ProteinBlender enabled.
2. In the 3D viewport press `N`, choose the **BlenderMCP** tab, press **Connect**.

Without a live Blender the whole lane **skips**.
That is deliberate: an unopened Blender is a missing environment, not a product regression.
CI sets `PB_LIVE_REQUIRED=1` so the lane cannot silently stop running.

Use `tests/run_live_tests.py`, not a bare `pytest tests/live`.
The runner passes `--confcutdir` to keep the parent `tests/conftest.py` out of collection; that conftest imports `bpy`, which does not exist in system Python.

## Architecture

```
tests/live/
  mcp_client.py   runner side: the socket, JSON-RPC over execute_code, path translation
  remote.py       Blender side: capture, measurement, framing, scene inspection
  conftest.py     fixtures: blender, live_reset, shot, snapshot_state, content fixtures
  _artifacts/     PNGs written by every shot() call; wiped at session start
```

The split follows the data.
Pixels are large and JSON is small, so images are measured **inside Blender** and only compact numbers cross the socket.
Whole captures stay in a Blender-side registry (`R.capture` / `R.compare`), so a test can relate two images without transferring either.

`mcp_client.call()` sends the body of a function; use `return` to send a value back.
`bpy`, `H` (this repo's `tests/helpers.py`) and `R` (`tests/live/remote.py`) are already imported, and keyword arguments arrive as local names.

```python
count = blender.call("return len(bpy.data.objects)")
ids   = blender.call("return [x * n for x in values]", values=[1, 2], n=3)
```

A remote exception is re-raised locally with the full Blender-side traceback, so a failure points at the line inside Blender that broke.

## Fixtures

| fixture | gives you |
|---|---|
| `blender` | the session connection; skips the lane if none is live |
| `live_reset` | autouse; scrubs add-on state before and after each test, and screenshots failures |
| `shot(label)` | frames the view, captures the viewport, saves a PNG artifact, returns metrics |
| `snapshot_state()` | the add-on's scene state as a dict (molecules, rows, outliner, frame) |
| `single_chain` / `multi_chain` / `actin` | 1ubq / 4hhb / 1atn imported offline; return the molecule id |

## What a capture measures

`shot()` and `R.viewport_metrics` return:

`covered`, `coverage`, `bbox`, `centroid` (normalised 0-1), `mean_rgb`, `max_rgb`, `distinct_colors`, `dominant_channel`.

Two details are load-bearing and were both found the hard way.

**Overlays are switched off during capture.**
They are drawn into an OpenGL render, and the floor grid alone covers about a third of the frame.
With overlays on, "is any geometry on screen" is always true and every coverage assertion is vacuous.
`test_live_harness.py` asserts an empty scene captures **zero** covered pixels, which is the calibration the rest of the lane depends on.

**Color measurement forces `view_transform = 'Standard'`.**
Blender's default filmic-style transform remaps every channel, and "is this domain red" stops being stably answerable.
The scene's own setting is restored afterwards.

For color assertions set MATERIAL shading first:

```python
blender.call("return R.set_shading(kind='MATERIAL', color_type='MATERIAL')")
```

In SOLID/studio shading the molecule renders a flat gray and color assertions cannot work.

## Writing a live test

```python
import pytest


@pytest.mark.live
@pytest.mark.visual
def test_membrane_is_visible_after_build(blender, shot):
    blender.call("return H.build_membrane(shape='FLAT', width=20, height=20)")
    metrics = shot("built")
    assert metrics["covered"] > 0, "a built membrane rendered nothing"
```

Rules, most of which the rest of the suite already follows:

- Mark every test `@pytest.mark.live`, plus `@pytest.mark.visual` when it asserts on pixels.
- Drive the **public operator the panel uses**, through `H.*` where a helper exists.
  This is enforced: `tests/test_repository_contracts.py` scans this directory and rejects `bpy.ops.molecule.split_domain`, `bpy.ops.proteinblender.split_domain(` and `.import_molecule_from_file(`.
- Never hold an outliner row across an operator call.
  Most operators rebuild `scene.outliner_items`, leaving any captured row dangling, and Blender returns defaults rather than raising.
  Capture `item_id` strings, call the operator, re-resolve.
- Prefer **relationships between images** over absolute pixel values, matching the stance the headless visual test already takes.
  Assert that two styles differ, that a pivot change does not, that recoloring moves the dominant channel.
  Absolute coverage numbers vary with GPU and driver; ratios and orderings do not.
- Assert on an invariant the bug would violate, not on a number you read off the current build.
  A threshold copied from today's output passes whether the code is right or wrong.
- **Never leave a setting behind.**
  This lane drives the developer's own Blender, not a disposable one, so a test that writes `membrane_builder_props.color_head` and walks away changes what the next membrane *they* build looks like - and gets reported as a product bug.
  `R.reset()` returns every ProteinBlender property group to its registered defaults before and after each test, discovered from the RNA so new groups are covered automatically.
  That is a correctness requirement here, not housekeeping: a colour test once left head and tail at `#3F3FF9` and `#6C6C6C`, and the blue-and-grey membrane that produced was mistaken for a regression.

## Tests that crash Blender

The whole lane shares one Blender process, so a test that reliably kills it does
not merely fail: it takes every later test down and the run reports noise
instead of the one real defect.

Such tests are marked `@pytest.mark.crasher`, kept in the suite as the record of
the defect, and deselected by default. Reproduce one deliberately:

```bash
python tests/run_live_tests.py --include-crashers -k expansion
```

`dev/relaunch_live_blender.sh` (gitignored) brings Blender back up with the MCP
bridge armed, which is what makes crash isolation practical.

## Known failures this lane surfaced

`molecule.update_domain_color` records the new color on the domain model and creates a per-domain color node tree, but **neither the object's `domain_color` property nor the rendered pixels change**.
The control is unambiguous: driving `scene.visual_setup_color` over the same molecule moves the mean color from `[0.918, 0.186, 0.177]` to `[0.186, 0.186, 0.920]` and flips the dominant channel, while `molecule.update_domain_color` leaves the render byte-identical (`rgb_delta` exactly 0.0).

This is the class of bug COVERAGE.md predicted was unreachable: the existing tests assert on `mol.domains[id].color`, which *does* update, so they stay green while nothing on screen changes.
`test_live_visual_color.py` asserts the correct behaviour and currently fails.

**`molecule.update_domain_style` has the same shape.**
Restyling a single domain to `spheres` leaves the render byte-identical (`xor` 0), even though a style swap should change the silhouette completely.
Since both domain-level visual properties fail identically while the molecule-level equivalents work, the likely cause is one shared defect in how domain visual updates reach evaluated geometry, not two independent bugs.
Guarded by `test_live_domains.py::test_changing_one_domain_style_restyles_only_that_domain`.

**`molecule.toggle_domain_expanded` hard-crashed Blender 5.2** with `EXCEPTION_STACK_OVERFLOW`. **Fixed.**
Expanding a domain writes `scene.split_domain_new_start`, whose update callback clamps to `end - 1`; with `end` still at its default of 1 that asks for 0, but the property is declared `min=1`, so Blender stored 1, the callback recomputed 0, and the two fought until the C stack was gone.
Fixed in `molecule_props.py` by clamping into the range the property can actually hold and suppressing the nested callback around the write.
Guarded by `test_live_domains.py::test_toggling_domain_expansion_is_a_ui_change_only`, which took the process down before the change and passes after.

**Membranes rendered nothing on Blender 5.2, and then rendered wrongly.** **Fixed.**
Three separate defects, all found by looking at the viewport rather than at state: modifier inputs never bound (5.2 removed IDProperty support from `NodesModifier`, and the write was swallowed by `except: pass`), every lipid aligned to the (1,1,1) diagonal at a constant 54.7 degrees (`Capture Attribute` gained a `Selection` socket at index 1 and the normal was addressed positionally), and a visible seam down the midplane (the thickness default was larger than two lipid meshes could span).
The full write-up is in [../COVERAGE.md](../COVERAGE.md).
The standing lesson: **address geometry-node sockets by name or identity, never by index** - this was the third such bug in one file.
