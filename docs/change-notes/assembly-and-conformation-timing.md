# Assemblies and conformation timing

September 25, 2026. Implements the assembly and Morphset feedback from #mira.

## Changes

- **Create New Assembly** opens on **PDB-defined Assembly** when definitions
  are available. It includes all six 1STM definitions, preserves deposited
  descriptions, and keeps the chosen entry through Apply and dialog reopening.
- Blender invokes the dialog's `check()` before its enum update callback.
  Synchronizing from the old assembly ID during that check was resetting a
  freshly selected entry. The picker value now wins during UI checks.
- Deposited transformations retain their chain lists. Identity-only assemblies
  can select a chain subset, and each chain receives only its own transformations.
  Description and label-to-author chain metadata are stored with the protein.
  Older projects without that metadata need a fresh structure import to acquire
  the deposited descriptions.
- **Assembly progress** and **Copy delay** replace the ambiguous labels. The
  Assembly Controls popup explains the endpoints and why delay changes motion
  between them.
  Maximum delay now completes every placement at progress 1.
- **Realize Copies** preserves each source chain's evaluated placement and pivot,
  including intermediate progress and delay, instead of reusing the first
  chain's placement offsets for every source.
- Morphset key timing follows Blender's editable curves. State and visibility
  records travel with those keys through moves, scaling, duplication and
  deletion; subsequent key edits no longer restore obsolete frame numbers.
  Older saved state curves are upgraded when edited. Unrelated transform
  animation on the Morphset controller is preserved.
- **Cycle through Conformations** creates editable keys using start/end frames,
  spacing, sequential repetition or seeded random selection. Existing keys can
  be kept or replaced within the chosen range. It is available in Animation
  and beside a checked Morphset in Create/Edit Keyframe, and supports undo/redo.

## Verification

The bundled [1STM fixture](../../tests/data/assembly-fixtures.md) supplies an
offline reproduction of the deposited assembly definitions.
`tests/integration/test_feedback_regressions.py` checks chain placements,
realization, animation retiming, cycling, legacy keys, metadata persistence,
and whole-protein assemblies without separate domain objects.

The final Blender 5.2 combined assembly and Morphset run passed **160 tests**.
A separate symmetry dialog/builder/realization/cutaway/bend run passed **84
tests** (with some dialog coverage shared between those runs). The focused
Blender 5.1 regressions also passed, including both updated legacy-retiming cases.

The real-dialog scenario passed **48 steps each in Blender 5.1 and 5.2**,
including mouse selection of assembly entries, Apply, confirm, reopen, Cancel,
assembly sliders, cycling confirmation, and undo/redo. Run it with:

```sh
python tests/run_ui_tests.py --blender /path/to/blender --scenario assembly-conformations
```

Blender 5.0's existing dependency environment fails the harness preflight with
DLL import errors in MDAnalysis and starfile. No result is claimed for 5.0.
The initial checks used the source tree. Following the installed-copy mismatch,
both normal Blender 5.2 add-on locations were updated, with all 154 Python files
verified against the source. The same **48 UI steps passed in a fresh normal
5.2 profile**, loading the installed legacy add-on and showing assemblies 1–6
with deposited descriptions. The previous installed copies were backed up;
preferences and the startup file retained their original hashes. Blender 5.1
and 5.0 installations were not changed during this follow-up.

## Disappearing assemblies when changing source

A second reproduction with `1stm` and `1stm_001` exposed a separate cleanup
bug: changing the first protein from generated to deposited symmetry removed
the second protein's placement objects because both names matched the same
prefix. The second assembly then evaluated to no visible geometry.

Assembly point clouds and node groups now carry an explicit owner reference.
Cleanup follows the assembly's node references, including the Object Info
references in older saved builds, and removes only that assembly's resources.
In-place operator updates also use exact references so bending one assembly
cannot move another similarly named protein's copies.

The regression failed before the fix and passed afterward. The related Blender
5.2 run passed **102 tests**, including switching/clearing assemblies, older
saved-build layouts, three molecular representations, copy realization, and
bend updates. The foreground scenario now starts with two generated 1STM
assemblies, changes the source through the real dropdown, and verifies the
second protein's evaluated atom positions after previews and cancellation.
All **51 UI steps passed in both source and normal installed Blender 5.2**.
Both installed 5.2 copies were updated and verified; preferences and the startup
file were unchanged.

An already affected assembly can be rebuilt by applying its assembly settings
again; the cleanup bug removed placement data, not the imported protein atoms.

Assembly controls now open from the sliders icon beside the assembly row's pencil,
or **Assembly Controls** in that row's drop-down menu. No selection-dependent
panel appears. The popup targets the row directly, including when another protein
is selected, and its live slider edits support Undo.

The installed Blender 5.2 popup workflow passes 35 real UI steps, including
clicking the icon and row-menu entry, editing both sliders, Undo/Redo, reopening,
and helical bend controls. Run with `--scenario assembly-controls --normal-profile`.
