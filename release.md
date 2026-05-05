# ProteinBlender v1.0.3 Release Notes

## Blender 5.1 / Python 3.13 Support

- Added Python 3.13 (cp313) wheels alongside existing cp311 wheels, enabling full compatibility with **Blender 5.1**
- Build system updated to download wheels for both Python 3.11 and 3.13 across all platforms (Windows x64, Linux x64, macOS ARM64, macOS x64)
- Continues to support Blender 4.2+ (Python 3.11)

## Flexible Linker System (New Feature)

A complete flexible linker system for connecting protein chains within puppets:

- **Catenary physics**: linkers behave like floppy strings with realistic droop when slack, solved via Newton-Raphson iteration
- **Rigid binding zones**: configurable number of residues at each endpoint that stay rigid and align with the backbone direction, preventing unnatural bending at attachment points
- **Hard distance constraint**: depsgraph handler automatically snaps domains back if the linker's max reach is exceeded
- **Two linker styles**:
  - **TUBE** — smooth tube along the catenary curve (default radius 0.015, soft_max slider for easy fine-tuning, max 0.1)
  - **BEADS** — spherical beads instanced along the curve with adjustable radius, up to 4x size variance, overlap control, and positional jitter
- **Dual rendering modes**: QUICK (styled Bezier curve for fast viewport performance) or DETAILED (MN Peptide to Curve for publication-quality renders)
- **Same-puppet constraint**: linkers connect chains within a single puppet only (no cross-puppet linking)
- **Puppet deletion cascade**: removing a puppet automatically cleans up associated linkers

### Linker UI

- Dedicated linker panel positioned above the animation panel
- Per-linker expand/collapse in the UIList
- Help popup [?] button on Binding Zone explaining what the parameter does
- Tube radius slider uses `soft_max` for a better drag experience — slider focuses on 0.001-0.03 range while still allowing manual entry up to 0.1

## Brownian Motion Animation (New Feature)

- New Brownian motion system for realistic molecular thermal jitter
- Baked jitter keyframes replace F-Curve Noise modifiers for better control, deterministic playback, and reliability across undo/redo

## Undo/Redo Stability

- Refactored all object references to use string-based names instead of Blender pointers, preventing crashes and stale references after undo/redo operations
- Re-entrancy guards on depsgraph handlers to prevent recursive updates
- Cleaned up debug output

## Animation Improvements

- Fixed animation not taking the shortest path for rotations (quaternion linear interpolation fix)
- Fixed checkbox and icon positioning in the animation timeline panel
- Fixed animation update issues when linkers are present

## Puppet System Fixes

- Fixed issues with creating puppets in certain selection states
- Fixed selection mechanism for Blender 5.0 compatibility
- Fixed single-domain puppet selection registering as two items instead of one, which prevented pivot changes

## Documentation & Deployment

- Updated installation guide and all feature documentation
- Added tutorial video links to puppet, keyframe, pose, and import documentation pages
- Fixed GitHub Pages deployment for the extensions hosting site
- Updated publish-extension workflow with correct permissions and gh-pages deployment

## Build & Housekeeping

- `.gitignore` updated to exclude `.claude/skills/`, `.mcp.json`, `docs/plans/`, and `tmp_tests/`
- Build script (`build.py`) now accepts a list of Python versions for wheel downloads (defaults to `["3.11", "3.13"]`)
- Version bumped across `blender_manifest.toml`, `pyproject.toml`, and `__init__.py`

---

## Alpha Testing Guide (v1.0.3)

The goal of this alpha test is to verify the new features introduced since v1.0.0 and identify any bugs before a wider beta release. Testers should work through each section below and report any issues encountered.

### Prerequisites

- Install ProteinBlender v1.0.3 from the provided `.zip` file via **Edit > Preferences > Get Extensions > Install from Disk**
- Tested on **Blender 4.2+** or **Blender 5.1** (this release adds Blender 5.1 support — please test on both if possible)

### 1. Core Workflow (Baseline)

Confirm that the existing core features still work correctly:

- [ ] Import a protein structure using a PDB code (e.g., `1UBQ`, `4HHB`)
- [ ] Change the visual representation (Surface, Cartoon, Ribbon, Ball & Stick)
- [ ] Split individual chains into domains using the Domain Maker
- [ ] Set and adjust pivot points for chains and domains

### 2. Puppet System

- [ ] Select multiple chains/domains and create a Puppet
- [ ] Verify the controller Empty is created and domains are parented to it
- [ ] Move the puppet controller and confirm all member domains move together
- [ ] Move individual domains within a puppet independently
- [ ] Delete a puppet and confirm its associated objects and linkers are cleaned up
- [ ] Verify that a chain/domain can only belong to one puppet at a time

### 3. Flexible Linkers (New)

- [ ] Select a puppet and create a linker between two chains within it
- [ ] Switch between **TUBE** and **BEADS** linker styles
- [ ] For TUBE style:
  - [ ] Adjust the tube radius slider — confirm it is easy to fine-tune (should feel smooth, not jumpy)
  - [ ] Verify the default radius looks reasonable (0.015)
- [ ] For BEADS style:
  - [ ] Adjust bead radius and confirm beads resize
  - [ ] Increase Radius Variance to max — confirm beads show a noticeable range of sizes (up to 4x difference)
  - [ ] Adjust Bead Overlap and Bead Jitter — confirm visual changes
- [ ] Click the **[?]** button next to Binding Zone — confirm the help popup appears with an explanation
- [ ] Adjust the Binding Zone value — confirm the linker endpoints become more/less rigid
- [ ] Move domains apart until the linker reaches its max length — confirm the distance constraint snaps them back
- [ ] Switch between QUICK and DETAILED rendering modes
- [ ] Delete a linker and confirm geometry is cleaned up
- [ ] Verify the Linker panel appears **above** the Animation panel in the properties sidebar

### 4. Pose Library & Animation

- [ ] Create a START pose (save the current arrangement)
- [ ] Move domains/puppets to a new position and create an END pose
- [ ] Create keyframes for START and END poses
- [ ] Play the animation and confirm smooth interpolation between poses
- [ ] Verify rotations take the shortest path (no unexpected 360-degree spins)

### 5. Brownian Motion (New)

- [ ] Enable Brownian motion on a molecule/puppet
- [ ] Play the animation and confirm realistic thermal jitter is visible
- [ ] Undo/redo several times — confirm Brownian motion keyframes remain stable

### 6. Undo/Redo Stability

- [ ] Perform a complex sequence of operations: import protein, create domains, create puppet, add linker, set keyframes
- [ ] Undo all the way back and redo forward — confirm no crashes, no missing objects, no stale references
- [ ] Save the file, close Blender, reopen — confirm everything loads correctly

### 7. Blender 5.1 Compatibility (New)

If testing on Blender 5.1:

- [ ] Confirm the addon installs and enables without errors
- [ ] Run through sections 1-6 above and note any Blender 5.1-specific issues

### Reporting Issues

When reporting a bug, please include:
- Blender version (e.g., 5.1.0, 4.2.3)
- Operating system
- Steps to reproduce
- Any error messages from the Blender system console (Window > Toggle System Console)
