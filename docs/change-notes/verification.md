# Weekly verification record

The changes were exercised inside real Blender processes, using bundled offline
structures and the public ProteinBlender operators. Source tests and installed
normal-profile tests cover different loading paths.

## Results

| Check | Result |
|---|---|
| Initial focused baseline, Blender 5.2 | 42 passed |
| Outliner topic, Blender 5.2 | 52 passed; foreground swatch pixels and right-click target checked |
| Lighting topic, Blender 5.2 | 17 passed, including flat/outlined/Studio renders |
| Membrane topic, Blender 5.1 and 5.2 | 34 passed per version; missing-gap regression failed before the fix |
| Morph topic, Blender 5.2 | 21 passed; four fresh-process save/reopen cases passed |
| Broad combined offline suites, Blender 5.1 and 5.2 | 708 passed per version, 7 skipped, 1 expected failure; one modal-identity policy finding resolved as described below |
| Final lighting + morph + relevant save/reopen, Blender 5.2 | 46 passed |
| Same final set plus keyframes, Blender 5.1 | 55 passed |
| Final repository/persistence contracts + keyframes, Blender 5.2 | 28 passed |
| Final repository/persistence contracts, Blender 5.1 | 19 passed |
| Affected morph, lighting, membrane, and outliner tests, Blender 5.0 | 85 passed |
| Combined factory-profile UI, Blender 5.1 and 5.2 | 75 scenarios passed per version |
| Installed normal-profile UI, Blender 5.1 and 5.2 | 79 scenarios passed per version, including four additional preview-confirmation checks |

The seven final save/reopen cases cover membrane, lighting, ordinary morph,
surface morph, breathing morph, captured conformation, and illustration morph.
They reopen the saved file in a new Blender process and compare actual scene,
node, material, animation, and registry state. The illustrative alpha test also
checks evaluated animated opacity at an intermediate frame.

The broad run's single finding was the repository's ban on Python `is` comparisons
for Blender data. The creation dialog intentionally compares its own Python
operator instance to the active modal slot, matching an already permitted pattern
in the keyframe dialog. A narrow documented exemption was added. The real UI test
then confirmed a preview through the parent dialog and verified that it created
exactly one permanent morph, removed the preview, and released the active slot.
The contract rerun passed. The seven skips are panels without their own `poll()`;
the expected failure is an existing background-only pose-dialog limitation. The
foreground suite exercises the actual registered panels and modal dialogs.

## Windows test-environment diagnostics

The long combined runs printed Windows access-violation diagnostics while pytest
updated its current-test environment variable (`<frozen os>.__setitem__`), and
continued running. These diagnostics also reproduced on unchanged `alpha` at
`7ca96f0`, including during unit-test teardown. The baseline comparison was stopped
after reproducing the issue; it is not counted as a completed baseline suite.

The final focused lighting/morph/persistence runs and the normal-profile UI runs
did not report these diagnostics. Treat the broad assertion counts alongside
this platform limitation; they are not evidence of an entirely clean native
runtime. No test suppresses these diagnostics.

## Installed copies

`scripts/deploy_normal_blender.py` copied and byte-verified 144 Python files per
installed copy, preserving dependency wheels. It updated legacy and extension
copies for Blender 5.2, 5.1, and 5.0. Normal-profile tests launched fresh foreground
processes without `--factory-startup`, rejected source-tree package loading, and
used the enabled installed package:

- Blender 5.2: `scripts/addons/proteinblender`.
- Blender 5.1: `extensions/animation_lab_github_io/proteinblender`.

The test processes dismissed the startup splash, exercised public operators and
window events, and exited without saving their test scenes or preferences. No
existing user Blender session was closed.

## Reproduce the checks

```bash
python tests/run_tests.py --blender '<blender>' \
  tests/unit tests/integration tests/roundtrip/test_persistence_contract.py \
  tests/test_repository_contracts.py tests/test_harness_smoke.py \
  -m 'not network and not slow' -q

python tests/run_tests.py --blender '<blender>' \
  tests/integration/test_lighting.py tests/integration/test_conformations.py \
  tests/integration/test_keyframes.py tests/roundtrip/test_saveload.py \
  -k 'not saveload or conformation or lighting or membrane' -q

python tests/run_ui_tests.py --blender '<blender>' --timeout 300
python scripts/deploy_normal_blender.py
python tests/run_ui_tests.py --normal-profile --blender '<blender>' \
  --artifact-dir /tmp/pb-week-ui --timeout 300
```

Session logs are retained under `/tmp/pb-week-*.log`. Final normal-profile reports
and screenshots are in `/tmp/pb-week-normal-51/` and `/tmp/pb-week-normal-52/`.
The source suites intentionally exclude network fetches. A full installed-ZIP
release build, CI matrix, and external live-MCP suite were not run for this local
weekly demonstration.
