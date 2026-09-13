# Alignment, morphing, and captured conformations

Branch: `feat/weekly-morph-workflow`, based on `alpha` at `7ca96f0`.

## Changes and reasons

- **Align & Morph** replaces the old label. Start/end frames replace seconds in
  the visible controls; legacy scripts using duration remain supported.
- Morphs own endpoint data and appear beside proteins with no children. They
  survive deletion of either endpoint. Old parented morphs are migrated while
  preserving world placement.
- Inclusive residue ranges support multiple chunks and chains. Explicit chain
  pairs and a chosen anchor region supplement automatic stable-core/all-residue
  fitting. Current placement allows authored motion without a new superposition.
- The creation dialog previews selected regions. Blue moving geometry and gray,
  translucent surrounding source regions make scope visible. Context visibility
  and opacity are adjustable. Cancel removes the preview and restores visibility,
  the frame, and the scene range.
- A return frame and repeat option create saved breathing animation. Playback
  respects forward-only, return, and repeat choices. Invalid frame order leaves
  an existing animation intact.
- **Capture Conformation** records the current native chain/domain pose as a
  named independent endpoint. Source transforms and mesh coordinates stay intact.
- Multiple independent morphs can share endpoints; visibility restoration is
  reference-counted, and deleting one cleans up only its own data.

## Verification

Blender 5.2: 21 integration tests passed, including independent geometry against
Biotite superposition, evaluated shape-key interpolation, multiple-chain/region
matching, chosen anchors, current placement, breathing samples, deletion and
visibility, real geometry/rendering, capture against Blender's evaluated atom
positions, and a simulated old-file reload. Four fresh-process save/load cases
passed: ordinary, surface, breathing, and captured conformations. The combined
verification record and foreground UI results are in the weekly demo notes.

The old-file regression exposed a node-group dependency stall in surrounding
geometry; each context now owns its cartoon group so migration of the shared
cartoon template cannot invalidate it.

## Demonstration

See [the user guide](../conformations.md) for controls, examples, and exact
algorithm details. Show a partial region preview and cancel it; then create a
10→30→50 breathing cycle. Create a second morph, remove one, and show the remaining
object still works. Pose a split domain, capture it, and use it as a new endpoint.

## Boundaries

The 30% requirement is per-chain sequence identity over nongap residue pairs;
three amino acids means at least three matched residue pairs, with non-collinear
Cα atoms required for a rigid fit. Cartesian interpolation is illustrative and
can distort molecular geometry. Surrounding context remains in the source pose.
Capture rejects duplicate or arbitrarily deformed geometry. An ordered multi-state
editor, atom sculpting, simulation, and trajectory import remain research follow-ups.
