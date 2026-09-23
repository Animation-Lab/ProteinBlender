# Stable B-factor cartoons and motion intensity

- Rename the lighting option to **Turn Off Other Lights**.
- Add **Motion Intensity** beneath the protein's B-factor checkbox. The default
  is 1; 0 stops the jiggle, 0.25 gives quarter amplitude, and 2 doubles it.
  The slider offers 0–2, with typed values up to 5. This is an illustrative
  amplitude control, not a calibrated temperature.
- Preserve cartoon ribbon connections during motion. MolecularNodes uses
  distance thresholds both when building the backbone and when splitting
  sheet, helix and loop splines. Thermal displacement could cross those
  thresholds and repeatedly remove sections. The motion modifier now carries
  the unjiggled positions into those decisions; the geometry itself follows
  the moving atoms. Original structural gaps stay open. Ribbon orientation
  corrections use the same stable reference mechanism as Morphsets.
- Apply intensity to the protein, its chains/domains and existing Morphset
  outputs without rebuilding animation on each slider edit. New domains and
  rebuilt Morphset outputs inherit it. Saved settings persist; older enabled
  motion is upgraded on load.

Validation includes the reproduced 1UBQ failure, four-chain hemoglobin,
an imported backbone gap, independently measured atom displacement, domain
splits, imported-model Morphsets, saved-file migration, save/reopen, and the
real Blender edit/lighting dialogs. See `tests/integration/test_thermal_motion.py`
and the `thermal-motion` UI scenario.

## Validation results

- Final full Windows Blender 5.2 suite: **803 passed, 7 skipped, 1 xfailed**.
  Skips and the modal-pose expected failure are pre-existing.
- Final thermal regressions: **8 passed** in each of Blender **5.0, 5.1, 5.2**.
- Fresh normal installations of 5.1 and 5.2: **28 UI steps passed** each.
- New and previous-release `.blend` scenes reopened in separate installed 5.1
  and 5.2 processes. All four checks preserved the cartoon's 3,466 vertices
  during playback, retained motion/intensity, and accepted subsequent edits.
- All 153 product Python files byte-verified in each normal installation;
  normal preferences remained unchanged.

Blender 5.0 used an isolated profile with compatible bundled wheels because
the machine's normal Python dependencies have existing DLL import failures.
The broader 5.1/5.2 runs printed native diagnostics in render/save tests, as
seen in earlier validation, but completed successfully. The final targeted
thermal and installed UI/reopen checks passed without Python/draw errors.
