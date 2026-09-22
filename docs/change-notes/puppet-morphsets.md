# Morphsets as puppet components

Morphsets can join new or existing puppets alongside ordinary chains and
domains. The puppet moves the whole Morphset; each Morphset still chooses its
model independently in Create/Edit Keyframe.

## What changed

- Create Puppet accepts whole Morphsets. Edit Puppet has a pencil in the PB
  Outliner and lists actual component IDs, including Morphsets. Occupied items
  show which puppet owns them.
- Membership changes update object parenting while preserving world positions.
  A Morphset's pose curves keep their local coordinates when its parent changes,
  so scrubbing or rebuilding model animation does not undo that placement.
- Outliner rebuilds retain Morphset membership. Puppet references expand to
  show member chains/domains, and their controls target the original entries.
- Puppet visibility reaches animated members and persists through model-key
  rebuilds. Hidden source geometry remains hidden.
- Removing a puppet preserves its Morphsets and model keys. Removing a Morphset
  releases surviving chains/domains into the puppet.
- Selecting a partially morphed chain cannot detach its controlled domains.
  Existing combined selections of ordinary chains and their domains remain
  supported.

## Verification

Automated regressions use real Blender operators and evaluated atom geometry.
They cover 1D3Z before and after animation, mixed domain/chain membership, two
independent Morphsets in one puppet, movement/rotation/scale with model keys,
appearance and B-factor controls, visibility, exclusivity, deletion, and pose
keys surviving removal and reparenting. Save/load tests reopen in a fresh
Blender process and edit model keys after loading.

The installed add-on passed 18 real UI steps on each of Blender 5.1 and 5.2:
Create/Edit Puppet, independent model and puppet keyframes, nested reference
controls, Undo/Redo, Morphset editing, visibility, and pose capture/apply after
regenerating model output. Separate normal-profile processes reopened those
saved files, changed a destination model, and verified the movement of 1,231
evaluated atoms. All 153 Python files were byte-verified in six local installs;
saved preferences remained unchanged.

Full-suite results on the final source:

| Blender | Passed | Skipped | Expected failures |
| --- | ---: | ---: | ---: |
| 5.0 | 795 | 7 | 1 |
| 5.1 | 795 | 7 | 1 |
| 5.2 | 795 | 7 | 1 |

The skips and expected failure predate this change. The latter is the
headless pose-creation wrapper; real pose creation is covered by the UI run.

### Test environment

Blender 5.0's normal dependency paths reported DLL import failures before test
collection. Its suite uses the previously verified isolated wheel environment;
the normal dependency installation was not changed.

An earlier Blender 5.1 run printed native cleanup diagnostics during Cycles
rendering. The unchanged alpha commit reproduced native diagnostics while all
19 illustration rendering tests passed. These diagnostics are separate from
the Morphset/puppet checks.

The full 5.0/5.1 runs also printed native diagnostics during rendering, saving,
or pytest environment cleanup, then continued. These logs should not be
described as diagnostic-free; the assertion results and installed UI/reopen
checks are reported separately above.
