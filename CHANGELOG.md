# Changelog

All notable changes to ProteinBlender are documented in this file.

---

## [1.0.4] - 2026-05-19

### Added
- **DNA/RNA Builder** — generate nucleic acid structures from a sequence
  - Build double- or single-stranded DNA or RNA from a typed or randomly generated sequence
  - Helix and Ladder winding modes, with per-base (A/T/G/C/U) and backbone colouring
  - In Ladder mode, realistic 3D backbone atoms are applied automatically for atom-based styles (Ball & Stick, Spheres, Sticks)
  - Bend editing via a Bezier curve with draggable control nodes
  - Swap-to-Complement to quickly build the antisense strand
  - Selecting an existing DNA/RNA molecule turns the builder panel into an editor for it
- **Membrane Builder** — Geometry Nodes-driven lipid bilayer
  - Deformable bilayer with realistic lipid density and even Poisson-disk packing
  - Holes that redistribute lipids instead of deleting them, with spherical cross-sections
  - Per-lipid procedural motion

### Changed
- Flexible linker controls consolidated into a single inline editor in the builder panel

### Fixed
- Protein outliner now self-heals when molecule objects are deleted outside the addon
- Per-chain visibility toggle in the protein outliner

---

## [1.0.3] - 2026-03-31

### Added
- **Blender 5.1 support** — bundled Python 3.13 (cp313) wheels for all platforms, enabling compatibility with Blender 5.1 while maintaining support for Blender 4.2+ (Python 3.11)
- **Flexible linker system** — connect protein chains within a puppet using physically-based catenary curves
  - Two visual styles: TUBE (smooth tube) and BEADS (instanced spheres with size variance, overlap, and jitter)
  - Rigid binding zones at each endpoint that align with backbone direction
  - Hard distance constraint that prevents domains from exceeding linker max reach
  - Dual rendering modes: QUICK (viewport) and DETAILED (publication-quality via MN Peptide to Curve)
  - Dedicated linker panel with per-linker expand/collapse
  - Help popup [?] on Binding Zone parameter
- **Brownian motion** — baked thermal jitter keyframes for realistic molecular animation, replacing the previous F-Curve Noise approach for better determinism and undo/redo stability

### Changed
- Linker panel now appears above the animation panel in the properties sidebar
- Tube radius default increased to 0.015 with soft_max slider (0.001-0.03 range) for easier fine-tuning; hard max clamped to 0.1
- Bead radius variance now produces up to 4x size difference at maximum (previously 1.5x)
- Build system downloads wheels for both Python 3.11 and 3.13 by default

### Fixed
- Animation rotations now take the shortest path (quaternion interpolation fix)
- Checkbox and icon positioning in the animation timeline
- Puppet creation in certain selection states
- Selection mechanism updated for Blender 5.0 compatibility
- Single-domain puppet selection no longer registers as two items
- Object references refactored to string-based names for undo/redo stability (prevents stale pointer crashes)
- Animation update issues when linkers are present
- Puppet deletion now cascades to clean up associated linkers

---

## [1.0.0] - 2024-12-15

Initial release of ProteinBlender.

### Features
- Import protein structures from PDB codes or local files
- Multiple visual representations (Surface, Cartoon, Ribbon, Ball & Stick, etc.) powered by MolecularNodes
- Domain maker for splitting chains into manageable domains
- Puppet system for grouping chains/domains under a shared controller
- Pose library for saving and recalling molecular arrangements
- Keyframe animation system for animating between poses
- Multi-platform support (Windows x64, Linux x64, macOS ARM64, macOS x64)
