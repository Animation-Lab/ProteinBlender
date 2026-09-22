# Morphsets from imported models

September 21, 2026

## Behavior

Create Morphset selects a protein and its chains/domains. All imported models
become available automatically. Each new Morphset has one row in Create/Edit
Keyframe, with a model selector, visibility, and neighboring-key context.
The PB Outliner nests it under its source protein and places its members below it.

Members in a set share timing. Separate sets give disjoint chains/domains
independent timing. Unavailable selections explain their limitations. Membership
edits preserve model identities and key times, and update all existing keys.
Deleting a Morphset restores its original members. Parent protein transforms,
style changes, and temperature motion continue to apply.

This change does not introduce state authoring or import of additional states.
Existing saved pair definitions retain their snapshots and animation. Their
legacy authoring operators remain internal for compatibility; new UI creation
uses the imported-model workflow.

## Implementation

`core/model_morphsets.py` supplies membership validation, imported-model capture,
and editing on top of the existing snapshot/keyframe engine. New roots are
marked `pb_model_morphset` and retain an ID reference to their source protein.
Hidden source transforms are evaluated from parenting and transform channels
when capturing or restoring members, avoiding stale cached world matrices.

Operator source-change callbacks use an RNA dialog marker because Blender passes
OperatorProperties to those callbacks, rather than the Python operator instance.
Scripted execution does not populate extra members alongside explicitly supplied
member collections.

## Validation

- Blender 5.2: 50 integration tests covering new and legacy Morphsets, keyframes,
  and the Outliner; the 9 new workflow tests also passed after the final UI fix.
- Blender 5.1: 32 new/legacy Morphset integration tests.
- Both versions: save/reopen checks for new Morphsets and legacy animated
  Morphsets with temperature motion and lighting (4 roundtrip cases total).
- Fresh installed profiles: 47 focused UI steps on 5.1 and 131 broader UI steps
  on 5.2. These include source switching, actual keyframe checkbox clicks,
  Enter confirmation, geometry interpolation, membership editor, removal/Undo,
  and style/B-factor interaction in the broader suite.
- The UI-generated example was reopened in fresh installed profiles on both
  versions. Each ran 8 checks of hierarchy, models, coordinates, saved-key
  editing through the keyframe-list pencil, and deletion/reconnection of keys.
- Python compilation and `git diff --check` passed.

Geometry cases include 1D3Z Models 1/3/8/9 at frames 1/50/75/100, direct
interpolation between Models 3 and 8, out-of-order key creation, holds, reversals,
independent domains, and a two-chain 2BBN ensemble with shared or independent
model timing. Invalid selections and snapshots are checked for atomic failure.

## Reproduction

```sh
python tests/run_tests.py --blender '<blender>' tests/integration/test_model_morphsets.py tests/integration/test_morphsets.py -q -s
python tests/run_ui_tests.py --blender '<blender>' --normal-profile --scenario model-morphsets --artifact-dir /tmp/pb-model-ui
python tests/run_ui_tests.py --blender '<blender>' --normal-profile --scenario saved-model-morphsets --blend /tmp/pb-model-ui/1d3z-model-keyframes.blend
```

`tmp_tests/model-morphsets/1d3z-model-keyframes.blend` is the local example saved
through the installed 5.1 UI and checked in both versions. Generated examples
and screenshots are ignored by Git; the UI scenario recreates them.
