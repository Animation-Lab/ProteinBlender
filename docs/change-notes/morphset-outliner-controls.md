# Morphset Outliner controls

Morphset child chains/domains have Edit, Select and eye controls. Edit opens
name, color and representation settings and applies appearance changes to the
animated output as well as the source. Appearance persists when keys regenerate
that output. Select targets the animated output.

The eye overrides visibility across the timeline in both viewport and render.
It retains the visibility stored in the keyframes; showing the member restores
those choices. The override survives save/reopen and key edits. Removing the
Morphset releases the override while retaining the current manual visibility,
so ordinary chain controls work again.

The Morphset row's right-click menu supplies only Edit, targeting the hovered
Morphset even when another row is active. A read-only UIList cursor suppresses
Blender's generic property editing commands. Blender retains its native Online
Manual link. Other PB row actions remain available.

## Validation

- New/legacy Morphset integration and save/reopen: 35 checks each in Blender
  5.1 and 5.2. Final cleanup changes also passed the 11 model-Morphset tests on
  5.1 and the focused visibility regression on 5.2.
- Unit and new/legacy Morphset integration suite: 165 passed on 5.2.
- Real foreground menus and live appearance callbacks: 22 focused UI steps
  passed in a fresh installed 5.1 profile and in a source-backed 5.2 window.
- The broader UI suite passed all 151 steps in a fresh installed 5.2 profile,
  including the new Outliner checks and existing selection, color, keyframe,
  membership, Undo, style and temperature-motion workflows.
- All 151 product Python files verified against all six installed copies.

Run the focused UI checks with:

```sh
python tests/run_ui_tests.py --normal-profile --scenario morph-outliner --blender '<blender>'
```

## Chain color and pivot follow-up

The child row also has its original color swatch and Edit Pivot button. The
swatch updates both source and animated geometry, and stays synchronized with
the parent protein and member editor. The pivot tool targets the displayed
chain, preserves its atom positions, and keeps the chosen origin through key
edits, member reordering, and save/reopen. First/Center/Last presets read the
current interpolated model. Source pivots stay synchronized for returning the
chain to its protein.

The missing controls were reproduced before product changes: the swatch test
failed, and both keyed/unkeyed pivot operations returned CANCELLED. After the
fix, 86 related integration tests passed on Blender 5.2, and the four focused
cases also passed on 5.0 and 5.1. Save/reopen passed on 5.1 and 5.2; the latter
also covered legacy Morphsets with temperature motion. The snapshot comparison
now refreshes Blender's cached transforms for hidden animated outputs through
the dependency graph, restoring visibility before sampling. No persistent
fields or transform differences were excluded.

All 152 product Python files were verified in all six installed copies.
Fresh installed-profile UI verification passed 36 focused steps on Blender 5.1
and 165 broader steps on Blender 5.2, including actual swatch/pivot clicks and
geometry checks after adding another key. Both runs exited without Python
tracebacks or draw errors.
