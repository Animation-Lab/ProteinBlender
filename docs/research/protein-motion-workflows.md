# Protein motion workflows and atom sculpting

## Recommended direction

ProteinBlender should organize motion around named conformations and independent morph objects. Imported structures, captured puppet poses, and eventually edited atom coordinates can all supply conformations. Alignment determines the coordinate frame; interpolation determines the path; playback determines timing. Those three choices should remain visible and independently controllable.

The best near-term order is to improve the existing morph workflow, capture conformations from posed proteins, and then expose trajectory playback through the existing MolecularNodes integration. Atom sculpting is feasible, but a reliable molecular editor needs topology preservation and geometric restraints. Markov models are useful when a kinetic model or sampled trajectory already exists; they cannot supply evidence-based motion rates from a single PDB structure.

The recommendations below distinguish existing repository behavior from proposed extensions. External documentation was checked on September 13, 2026. Software documentation describes capabilities, not an independent performance benchmark on the ProteinBlender environment.

## What the existing morph actually does

At the starting revision, `alpha` commit `7ca96f0`, `core/structural_alignment.py` reads imported atom identities and coordinates. Residues require a recognized amino-acid name and a carbon alpha atom. Water, ligands, and nucleic acids are excluded from protein matching. Atom identities are persisted with the imported mesh; an old file without recoverable identities requires re-import.

For identical sequences, residue correspondence is positional. Otherwise, Biotite performs a global protein alignment using BLOSUM62, affine gap penalties of −10 and −1, and unpenalized terminal gaps. Residue numbers and insertion codes identify residues but do not force correspondence, so renumbered structures can still match. Interactive work is bounded by a 16-million-cell sequence-alignment limit and a limit of 1,024 chain-pair comparisons.

Whole-protein matching scores every possible chain pair using the number of sequence matches, with matching chain names used only as a tiny tie-breaker. SciPy's linear assignment chooses a one-to-one chain mapping. A selected chain pair bypasses this assignment. Symmetric homomers can have several equally plausible mappings: the automatic result is a suggestion to inspect, not a uniquely correct biological correspondence.

The **30% threshold** is the fraction of aligned, nongap residue pairs with identical amino-acid letters, evaluated separately for each chain pair. It is not 30% structural overlap, allowed displacement, or confidence. The **three-residue threshold** means at least three paired residues. A separate geometric condition requires at least three non-collinear Cα positions for a proper rigid fit. A collinear three-residue match can therefore pass sequence screening and still fail superposition.

Alignment uses a proper Kabsch rotation and translation; it does not scale or reflect the structure. All-pair fitting uses every paired Cα. Stable-core fitting repeatedly removes distant pairs above 2 Å while retaining at least half of the original paired residues and at least three points. The implementation limits this process to 30 iterations and refits after pruning. It reports both the RMSD of the retained fit pairs and the RMSD of all paired Cα atoms after that same transformation. These values answer different questions.

Morph geometry retains shared atom names and elements within paired residues. At amino-acid substitutions, only shared backbone atoms survive. Bonds survive only when their vertices survive. Unmatched atoms are omitted from the morph copy while remaining intact in the original structures. A point-to-point Cartesian interpolation then moves retained atoms between the starting coordinates and the aligned target coordinates. Blender shape keys store the endpoints; easing changes the time course, not the spatial route.

This path can shorten bonds, create clashes, or pass through an implausible intermediate. A good endpoint alignment does not validate the intermediate states. The original workflow also ignores puppet/domain poses when computing the match, parents the result to the start protein, and stores duration in seconds. Its popup already provides a forward/backward preview, but that preview alone does not create a persistent breathing animation in the scene.

## Chimera and ChimeraX: useful distinctions

ChimeraX Matchmaker separates chain pairing, sequence alignment, and fitting. It supports explicit chain choices, selected-residue fitting, iterative exclusion of distant pairs, and reporting both final-fit and all-pair RMSD. This supports a ProteinBlender interface that exposes the paired regions and the stationary reference region, rather than presenting alignment as an invisible preprocessing step.[^1]

The documented ChimeraX morph API accepts multiple structures and exposes frame count, wrapping, rate, Cartesian interpolation, rigid-group/core options, a playback slider, and optional coloring of segments or core. The retrieved API documentation is explicitly version 1.8; its signature should not be treated as a guarantee for every current release. Its default algorithm and options are more sophisticated than ProteinBlender's two-endpoint shape-key interpolation.[^2]

Classic Chimera's morph command can append multiple segments, generate a trajectory, and open MD Movie. It also documents optional minimization of interpolated conformations, with extra computational cost and limitations. Minimization should therefore be an explicit quality operation, not something silently equated with physical validation.[^3]

For appearance, ChimeraX's Graphics toolbar describes Flat as ambient illumination without shadows plus silhouettes. Its graphics command defines silhouettes through image-depth discontinuities, with configurable width and depth threshold. Equalizing directional lights cannot reproduce that flat look; color shading and outlines must be addressed separately.[^4][^5]

## A practical alignment and morph interface

The proposed creation flow has four sections: Structures, Regions, Alignment, and Playback. Structures chooses two named conformations. Regions chooses whole proteins, chain pairs, or residue intervals. Alignment chooses stable core, all paired residues, a specified anchor region, or the current placement. Playback chooses start/end frames, easing, and return behavior.

A compact match report should always display actual chain assignments, matched-residue coverage, shared-atom count, and both RMSDs. The active morph region should be colored distinctly. The remaining context should be ghosted without changing source materials or their saved visibility. The anchor region needs a distinct indication from the moving region; otherwise a highlighted selection can ambiguously mean either “this moves” or “fit on this.”

The output should be a top-level PB Outliner row with its own selection, visibility, edit, and delete controls. A morph should retain its copied endpoint data when either original protein is deleted. Multiple morphs can share source proteins without owning or deleting each other. Hiding originals requires reference-counted ownership so removing one morph cannot unexpectedly reveal originals still hidden by another.

A return animation should persist in ordinary Blender animation and rendering. Start and end define the forward leg; a return frame defines the backward leg. A repeat option can repeat the resulting cycle. The preview must use the same timing contract, including what happens when playback begins halfway through a cycle. The interface should distinguish “preview repeatedly” from “repeat in the rendered animation.”

For several independently moving chunks, separate morph objects offer useful independent colors and timing. For a sequential A→B→C path, use an ordered conformation list with one transition per adjacent pair. These are different operations. They should not share an ambiguous “multiple morphs” checkbox. Sequential paths also require a stable common atom set across all states or an explicit policy for changing topology.

## Capturing a new conformation from a puppet

A captured conformation should be an immutable atom-coordinate snapshot, with a name and source provenance. “Capture Conformation” records the displayed protein at the current frame; it should not modify the puppet, its poses, or its source meshes. The resulting conformation can then be chosen as a morph endpoint.

The difficult part is coordinate correspondence. ProteinBlender domains may share the parent's full atom mesh while geometry nodes display only their selected residues. Their visible mapping includes object transforms and a geometry-node pivot subtraction. Copying the raw mesh or only the object origin would silently ignore the pose. Capture must identify each displayed atom, apply the domain's actual transform, and write exactly one coordinate for each retained atom.

A safe initial scope is native protein chains/domains transformed by the existing puppet workflow, without topology edits or arbitrary modifiers. Duplicate chain copies, overlapping domain assignments, generated symmetry instances, missing atoms, and nonlinear deformers need explicit handling. If capture cannot determine a unique source atom for a displayed point, it should give a specific error instead of producing a deceptively plausible snapshot.

Validation should compare a captured snapshot with independently observed evaluated atoms. A nontrivial rotated domain is a stronger test than an unchanged protein. Saving and reopening must preserve atom names, residue/insertion identity, chain mapping, coordinates, and endpoint provenance. Capturing the same pose twice should not alter the live scene.

## Atom sculpting: feasibility and implementation options

Direct molecular manipulation is established. ISOLDE combines interactive molecular dynamics with direct atom tugging and adjustable restraints, maintaining a physically informed model during editing. Its original paper demonstrates structural model rebuilding, not arbitrary artistic animation. This is evidence that restrained atom manipulation is feasible, but not that a general Blender sculpt brush can preserve molecular geometry.[^6]

ISOLDE's documented preparation requirements include hydrogens and restrictions on unsupported or incomplete chemistry. These requirements matter because ProteinBlender routinely visualizes structures that are adequate for rendering but incomplete for simulation. A force engine cannot safely assume that every imported PDB is simulation-ready.[^7]

Narupa demonstrates an architecture in which interactive visualization/manipulation communicates with a molecular simulation backend. Its virtual-reality interface is not necessary for ProteinBlender, but separating the simulation process from the drawing process is useful: expensive force calculations need not block Blender's event loop.[^8]

Three implementation levels are worth distinguishing:

| Approach | Suitable first use | Principal limitation |
|---|---|---|
| Topology-preserving atom or residue handles | Artistic endpoint editing and local corrections | Unrestrained motion can damage bonds or create clashes |
| Rigid fragments plus torsion/linker controls | Domain rearrangements, breathing, coarse conformational editing | Requires well-defined hinges and loop closure |
| Restrained molecular dynamics or minimization | Physically informed local remodeling | Chemistry preparation, native dependencies, runtime cost, and validation |

The first prototype should edit a copied conformation using an atom/residue handle and a falloff neighborhood. It should preserve vertex count, atom identity, bonds, chain labels, residue numbers, and insertion codes. Dynamic topology, remeshing, smoothing across disconnected chains, and surface-only sculpting should be excluded: a rendered molecular surface is not the molecular atom graph.

For a constrained editor, use rigid domain handles first and torsional degrees of freedom second. A dragged atom can become a restraint target while nearby atoms relax under bonded and nonbonded terms. OpenMM supplies custom external forces for positional targets and custom bond, angle, torsion, and centroid forces for constraints or restraints. These are building blocks; the application must still choose suitable parameters and handle unsupported chemistry.[^9]

A suitable proposed dragging energy is a bounded positional restraint around a moving target, together with the molecular energy and optional fixed-region restraints. A simple harmonic target is easy to prototype, but its force grows with displacement. Adaptive/top-out restraints offer a researched alternative. Published ISOLDE work describes adaptive distance and torsional restraints and their implementation using OpenMM custom force classes.[^10]

Run the solver in a separate worker process. Blender sends selected atom IDs, target coordinates, restraint settings, and a revision counter; the worker returns coordinates and validation summaries tagged with that revision. Blender discards stale results, updates geometry on its main thread, and keeps Cancel responsive. Undo should restore an accepted coordinate snapshot, rather than replaying every solver iteration.

Before accepting an edited conformation, report changes in bond lengths, angles, chirality, steric clashes, and relevant torsion outliers. Preserve disulfides and explicit cross-links. Large domain motions need interface and loop checks, not merely a low final energy. Minimized intermediates are still model-generated, and they do not establish transition kinetics or a measured biological pathway.

A useful sculpting acceptance suite includes unchanged topology, fixed-anchor invariance, correct angstrom/Blender-unit conversion, cancellation without source mutation, undo/redo of accepted edits, failure isolation when the worker exits, and portable save/reopen. Test a small complete protein before adding ligands, metal coordination, membrane proteins, or large complexes.

## Markov-model movements

A Markov state model represents transition probabilities between discrete states at a specified lag time. Deeptime provides transition counting, model estimation, and analysis, including validation against longer lag times. Such a model requires observed or otherwise justified transition data; a collection of endpoint PDB files alone does not determine the probability matrix.[^11][^12]

A viable ProteinBlender feature would import named states, a transition matrix, its lag-time units, and optionally actual transition-path clips. A seeded sampler could choose a reproducible sequence of states. The animation system would then render that sequence using supplied trajectories or clearly labeled illustrative transitions. A Markov state sequence supplies visits and dwell behavior; it does not supply atom coordinates between those states.

For a purely artistic feature, a state graph with user-defined weights is useful too. It should be described as authored state animation, with editable dwell times and a random seed. Calling invented weights a molecular kinetic prediction would obscure their provenance. Keep the authored state graph and scientifically estimated model as distinct import modes.

Model validation should reject negative or nonfinite probabilities, rows that do not sum to one, inconsistent dimensions, missing state conformations, and ambiguous time units. Statistical tests should use deterministic seeds and enough samples to check expected transition frequencies within confidence bounds. Reducible chains and absorbing states are legitimate; the UI should explain their effect rather than rejecting them indiscriminately.

## MolecularNodes trajectory shortcut

Brady Johnston's documented trajectory workflow loads topology and trajectory files through MDAnalysis, updates coordinates on Blender frame changes, and offers subframes and interpolation. It also documents a companion `.MNSession` file needed on reopen. This is a viable route to playback of existing motion data, rather than a way to infer a trajectory from an isolated PDB.[^13]

The repository already vendors `entities/trajectory/ui.py`, `trajectory.py`, and `session.py`, and already declares MDAnalysis as a dependency. The local loader creates an MDAnalysis Universe and a MolecularNodes Trajectory object. Its existing import operator changes the scene frame range, while session code pickles companion state. A PB-facing wrapper should make timing ownership explicit and integrate the object into the PB Outliner.

The exact “shortcut Brady uses” was not identified as a specific video or keystroke. The documented topology-plus-trajectory workflow is verified. If the intended example is a different demonstration, that source would be needed before claiming equivalence.

A first import feature should expose topology, trajectory, atom selection, first/last sample, stride, and scene start/end frames. It should report physical trajectory time separately from presentation time. Scrubbing backwards, missing files, renamed paths, and saving/reopening must work. For periodic simulations, wrapping can produce apparent jumps; periodic correction must respect the cell shape and available topology.

Do not make a mandatory in-memory copy of every trajectory. An array of 100,000 atoms over 1,000 frames with three float32 coordinates already occupies about 1.2 GB, before object and analysis overhead. Streaming with a small frame cache is a practical default. Baking a bounded selected interval can provide a portable sharing option when external-file dependencies are undesirable.

## Additional motion generators

Normal-mode exploration is a better fit than a Markov model when the input is a single structure and the goal is plausible small-amplitude collective motion. ProDy documents sampling combinations of modes and traversing a mode in both directions. This can support an explicitly labeled exploratory breathing tool; it does not establish realistic amplitudes or kinetics without further evidence.[^14]

FRODA explores protein flexibility using rigidity and geometric constraints. Its original paper and subsequent work support considering constrained geometric pathways for larger rearrangements. It is not a ready-made drop-in replacement for the existing Blender shape keys, and a plugin integration would need dependency, licensing, reproducibility, and validation work.[^15]

The practical research priority is therefore: trajectory import for externally generated motion; restrained conformation editing for new endpoints; then normal-mode exploration. Markov-state playback becomes valuable when actual state and transition data are available. Full physically informed sculpting deserves a dedicated project milestone after endpoint capture and validation are dependable.

## Sources

[^1]: UCSF RBVI. [Matchmaker](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/matchmaker.html). Online user documentation, accessed September 13, 2026.
[^2]: UCSF ChimeraX. [Python functions implementing user commands: morph](https://chimerax.readthedocs.io/en/release-v1.8/modules/core/commands/user_commands.html). Version 1.8 API documentation; accessed September 13, 2026.
[^3]: UCSF Chimera. [Morph command](https://www.cgl.ucsf.edu/chimera/docs/UsersGuide/midas/morph.html). Classic Chimera documentation, accessed September 13, 2026.
[^4]: UCSF RBVI. [Graphics toolbar](https://www.cgl.ucsf.edu/chimerax/docs/user/tools/graphics.html). Accessed September 13, 2026.
[^5]: UCSF RBVI. [Graphics command: silhouettes](https://rbvi.ucsf.edu/chimerax/docs/user/commands/graphics.html). Accessed September 13, 2026.
[^6]: Croll, T. I. [ISOLDE: a physically realistic environment for model building into low-resolution electron-density maps](https://pubmed.ncbi.nlm.nih.gov/29872003/). Acta Crystallographica D 74, 519–530 (2018). DOI: 10.1107/S2059798318002425.
[^7]: ISOLDE. [Introduction to cryo-EM model rebuilding](https://tristanic.github.io/isolde/static/isolde/doc/tutorials/intro/cryo_intro/cryo_intro.html). Online version 1.12.0 documentation, accessed September 13, 2026.
[^8]: O'Connor et al. [Interactive molecular dynamics in virtual reality from quantum chemistry to drug binding: an open-source multi-person framework](https://arxiv.org/abs/1902.01827). 2019 preprint describing Narupa.
[^9]: OpenMM. [Custom forces](https://docs.openmm.org/latest/userguide/theory/03_custom_forces.html). User Guide 8.6, accessed September 13, 2026.
[^10]: Croll and colleagues. [Adaptive Cartesian and torsional restraints for interactive model rebuilding](https://pmc.ncbi.nlm.nih.gov/articles/PMC8025879/). Acta Crystallographica D (2021).
[^11]: Deeptime developers. [Markov state models](https://deeptime-ml.github.io/latest/index_msm.html). Version 0.4.5 documentation, accessed September 13, 2026.
[^12]: Deeptime developers. [MarkovStateModel API](https://deeptime-ml.github.io/latest/api/generated/deeptime.markov.msm.MarkovStateModel.html). Accessed September 13, 2026.
[^13]: Johnston, B. [Trajectories](https://bradyajohnston.github.io/MolecularNodes/tutorials/trajectories.html). MolecularNodes tutorial, accessed September 13, 2026; checked against the locally vendored implementation.
[^14]: ProDy developers. [Dynamics analysis](https://www.bahargroup.org/prody/manual/reference/dynamics/index.html). Sampling and mode-traversal documentation, accessed September 13, 2026.
[^15]: Wells, S., Menor, S., Hespenheide, B., and Thorpe, M. F. [Constrained geometric simulation of diffusive motion in proteins](https://users.cs.duke.edu/~brd/Teaching/Bio/asmb/current/Papers/NMA/wells-PhysBiol2005.pdf). Physical Biology 2, S127–S136 (2005). DOI: 10.1088/1478-3975/2/4/S07.
