# State library redesign

2026-09-20. The preceding work is preserved in checkpoint commit `3140e8c`.

## Result

A Morphset now represents one animated subject and its reusable states. Create
it from a protein, chains/domains, or a complex. Imported conformer models become
available together. Browse, preview, add, and edit states in **Animate Scene →
Conformations**, then choose states in the existing keyframe editor.

The nested Morph 1 / Morph 2 endpoint-pair authoring UI is removed. **To next key**
explicitly chooses interpolation or a hold followed by a switch. Neighboring
keyed states and frames are visible in the editor. Independent subjects can have
independent timing; a complex can share one state choice and retain separate
member visibility.

See the [research and design notes](../design/conformation-workflow.md) and
[workflow guide](../morphsets.md). The design is informed by primary literature,
official scientific visualization documentation, and inspection of the actual
Blender workflows. It has not been evaluated in a user study.

## Verification

| Check | Result |
|---|---|
| Morph engine and state-library integration, Blender 5.1 | 33 tests passed |
| Same integration suite, Blender 5.2 | 33 tests passed |
| Installed normal-profile state-library UI, Blender 5.1 | 69 steps passed |
| Installed normal-profile state-library UI, Blender 5.2 | 69 steps passed |
| Broader foreground UI suite, Blender 5.2 | 130 steps passed |
| Fresh-process structural save/reopen, Blender 5.2 | 2 tests passed |
| Legacy 1D3Z shared-pair file, installed Blender 5.2 | 9 steps passed |
| Legacy 2BBN separate subjects, installed Blender 5.1 | 9 steps passed |
| Legacy 2BBN combined subject, installed Blender 5.2 | 9 steps passed |
| New 1D3Z and 2BBN files reopened in installed Blender 5.1 | 9 steps each passed |
| Saved-workspace layout upgrade, installed Blender 5.2 | 9 steps passed |

The 69-step runs include two consecutive Add State dialogs, state editing, real
preview-button clicks, keyboard confirmation/cancellation, Undo, save cleanup,
and live Surface/Cartoon changes with temperature motion on/off. Drivers set some
form values through the live Blender properties; they do not click every menu.
The broader 130-step run preceded the extra consecutive-addition test steps and
used the same final product code.

Geometry checks compare actual atom coordinates at endpoints and intermediate
frames, including the user's Model 1 → 3 → 8 → 9 example, holds/cuts, reverse
visits, and shared-member migration. Saved-file checks reopen and edit the real
keyframe form, verify the other keys remain intact, and restore the animation.

Deployment byte-verified 152 Python files in each of six installed addon copies.
Fresh normal-profile UI runs used the enabled 5.1 extension and 5.2 legacy addon.
Python compilation and `git diff --check` also passed.

### Reproduction

```sh
python tests/run_tests.py --blender '<Blender executable>' \
  tests/integration/test_conformation_sets.py tests/integration/test_morphsets.py -q -s
python tests/run_tests.py --blender '<Blender executable>' \
  tests/roundtrip/test_saveload.py -k morphsets -q -s
python scripts/deploy_normal_blender.py
python tests/run_ui_tests.py --blender '<Blender executable>' \
  --normal-profile --scenario state-library --artifact-dir /tmp/pb-state-library
```

The UI runner saves a ten-state 1D3Z teaching file alongside its report and
screenshots. Local ready-to-open 1D3Z and 2BBN examples and their instructions are
in `tmp_tests/conformation-redesign/` (generated artifacts, excluded from Git).

## Practical limits

- NMR model collections are alternatives, not measured movie frames or reaction
  pathways. The 2BBN example shows a bound calmodulin–peptide complex throughout.
- Inputs still require matching atom identities and externally prepared alignment.
  Straight-line interpolation does not perform molecular dynamics or prevent
  implausible intermediate geometry.
- Older libraries migrate automatically. Exact shared subjects merge; exceptional
  overlapping/transformed subjects remain separate to retain their animation.
- Existing Protein Blender workspaces recreate their side-panel and timeline
  areas once to apply the new saved panel order; the main viewport is retained.
  Subsequent setup calls preserve the resulting arrangement.
