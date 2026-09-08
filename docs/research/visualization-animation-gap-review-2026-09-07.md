ProteinBlender visualization and animation review — 7 September 2026

The largest opportunities are molecular selection and annotation, organizing a
movie into shots, and animating changes between measured structures. ProteinBlender
already has much of the machinery for assembling and animating molecular scenes.
My recommendation is to make those scenes easier to explain and deliver, then
add deeper structural and trajectory workflows.

This comparison uses the current working tree and official documentation for
ChimeraX, PyMOL, VMD, Mol*, and MolecularNodes. It is a source/documentation audit,
not a runtime benchmark of the other applications. A missing PB workflow means
I found no integrated route through ProteinBlender's registered panels and
operators. Blender itself or bundled code may still provide the underlying
capability. Priorities and implementation sizes below are my product judgments,
not measurements of demand or delivery estimates.

ProteinBlender's existing foundation includes PDB/mmCIF/AlphaFold imports; six
representation styles; chain/domain colors and transparency; domain splitting
with focus highlighting; puppets and pose capture; transform, pose, and color
keyframes; Brownian-style motion; flexible linkers; DNA/RNA and membrane builders;
deposited and generated assemblies; assembly animation, filtering, cutaways and
filament bending; and the new fitted lighting presets. These should be extended
and reused. They are not missing features.

| Opportunity | Current ProteinBlender position | Useful addition | Reference and priority |
|---|---|---|---|
| Camera and shot manager | Blender supplies cameras and animation; PB exposes molecular keyframes and lighting orientation, without a dedicated shot workflow. | Save a view, frame a target, orbit or follow a protein, set shot duration and transition, and reorder shots. Include camera, visibility, colors and annotations in scene bookmarks. | PyMOL's documented [Timeline](https://learn.schrodinger.com/public/pymol/current/Content/pymol/Features/timeline.htm) has camera/object tracks; Mol* [snapshots](https://molstar.org/me-docs/snapshot/) capture scene state. **First release; medium scope.** |
| Molecular labels and measurements | Object names and linker-length readouts exist. Blender text and measurement tools are available, but molecular annotations are not integrated. | Labels anchored to proteins, chains, domains and residues; arrows, Å/nm distances, angles, scale bars and legends. Keep them attached through motion and allow visibility keyframes. | [Mol* measurements](https://molstar.org/viewer-docs/tips/measurements/) and [ChimeraX labels](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/label.html). **First release; medium scope, extending to larger scope for atom-level tools.** |
| Sequence viewer and named selections | Outliner selection and contiguous domain ranges are supported. DNA sequence input serves construction, rather than browsing imported protein sequences. | Click a residue in sequence or 3D, select several disjoint ranges, select residue types or secondary structure, and save sets such as “binding site.” Add “within 5 Å of this ligand” with explicit fixed/dynamic membership. | Mol* [sequence navigation](https://molstar.org/viewer-docs/navigating-by-sequence/) and [selection operations](https://molstar.org/viewer-docs/making-selections/). **Foundational priority; large scope.** |
| Multiple representations of the same selection | Each PB appearance target has a representation setting; separate domains can have different styles. Copying objects can approximate layering. | A representation stack: cartoon plus transparent surface, ligand sticks, selected side chains as spheres, each with independent color and opacity. These layers should share one molecular identity. | Mol* [display management](https://molstar.org/viewer-docs/managing-the-display/) provides components and representations. **High priority after selections; medium scope.** |
| Data-driven coloring and legends | Manual colors and mixed-color swatches exist. The AlphaFold import path explicitly requests pLDDT coloring; this audit did not verify whether that coloring survives every downstream operation. | A general Color By menu for confidence, B-factor, secondary structure, hydrophobicity and imported residue values, with ranges, missing-data handling and an exportable legend. Add PAE inspection separately. | ChimeraX [attribute rendering](https://rbvi.ucsf.edu/chimerax/docs/user/tools/render.html) and [AlphaFold tools](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/alphafold.html). **High priority; medium scope for coloring, larger for interactive PAE.** |
| Structural alignment and comparison | Object transforms and pivots exist. No PB sequence-guided superposition/RMSD workflow was found. | Align two structures or selected chains, review the matched residues, report RMSD, and compare aligned structures with consistent views and colors. | [ChimeraX Matchmaker](https://www.cgl.ucsf.edu/chimerax/docs/user/tools/matchmaker.html). **Second release and foundation for morphing; large scope.** |
| Conformational morphs between structures | PB poses capture domain/puppet transforms. These do not establish atom correspondence between two imported conformations. | Select open and closed structures, review chain/residue correspondence, align, then create a scrubbable transition. Handle missing residues, differing sequences and ligands explicitly. | [ChimeraX morph](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/morph.html) creates trajectories between matched models. **High animation value after alignment; large scope.** |
| MD trajectories and structural ensembles | Bundled MolecularNodes contains trajectory import and frame-handling code. PB's visible importer accepts structures, and its wrapper uses the first model for domain bookkeeping. | Import topology plus trajectory, map simulation frames/time to the Blender timeline, choose stride, align playback, manage periodic boundaries, and combine playback with PB camera/annotation animation. | [MolecularNodes trajectories](https://bradyajohnston.github.io/MolecularNodes/tutorials/trajectories.html) and [VMD Movie Maker](https://www.ks.uiuc.edu/Research/vmd/plugins/vmdmovie/). **Second release; substantial integration and validation.** |
| Ligand and binding-site view | Imported atoms can include ligands; PB has chain/domain selection and assembly contact filtering. No dedicated ligand/interactions workflow was found. | Small-molecule entries, “Show Binding Site,” nearby residues, interaction labels and chemically classified contacts. Start with selection/distance views, then add hydrogen-bond and interaction analysis. | Mol* documents [ligand surroundings and non-covalent interactions](https://molstar.org/viewer-docs/faqs-scenarios/). **High explanatory value; medium-to-large scope.** |
| Density-map visualization | Bundled MolecularNodes includes MRC/density import and surface/wire styles. No PB map-import/control workflow was found. | Add cryo-EM/crystallographic maps to the outliner, set contour and opacity, zone around a selection, preserve map/model coordinates and animate visibility. Consider fitting only after display works well. | ChimeraX [map tools](https://www.cgl.ucsf.edu/chimerax/docs/user/tools/densitymaps.html) and [Fit in Map](https://www.cgl.ucsf.edu/chimerax/docs/user/tools/fitmap.html). **Second release; medium scope for basic display, large for fitting/segmentation.** |
| General clipping and capped sections | Assembly cutaways already remove whole copies on one side of a plane. This does not slice individual protein surfaces or volumes. | Movable clipping planes/slabs per target, capped surfaces, and keyframed section reveals. Preserve the existing whole-subunit cutaway as a separate useful mode. | [ChimeraX clipping](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/clip.html). **Second release; medium-to-large scope.** |
| Figure presets and export workflow | Lighting and molecular representations are integrated. Blender handles rendering/export, without a PB-oriented delivery workflow. | Presets for a figure, transparent-background asset, presentation movie and turntable. Expose camera, size, frame range and preview/final quality together; add optional outlines and accessible palettes. | Mol* [Quick Styles](https://molstar.org/viewer-docs/tips/quick-styles/) and [Movie Export](https://molstar.org/viewer-docs/tips/movie-export/). **First release; small-to-medium scope, with advanced outlining larger.** |
| Reusable mechanism actions | Existing assembly factors, puppets, keyframes and linkers already supply many building blocks. | Presets for approach, bind, separate, hinge, focus/reveal and sequential assembly. Expose start/end targets and timing, then generate ordinary editable keyframes. | VMD's [Movie Maker/Userani documentation](https://www.ks.uiuc.edu/Research/vmd/plugins/vmdmovie/) illustrates predefined actions. The PB mechanism presets are a proposed extension. **After shots and selections; medium scope.** |
| Interactive sharing and provenance | Native Blender saving and some structure identifiers/path metadata exist. No PB web-story export or consolidated provenance workflow was found. | Attach source/model/assembly IDs, confidence meaning, units and animation origin to exports. Later investigate a browser-viewable structural story, documenting which Blender effects cannot transfer. | [MolViewSpec animations](https://molstar.org/mol-view-spec-docs/animations/) combine described snapshots and transitions. **Provenance should accompany new data features; browser export is a later, large project.** |

There are three important boundaries in this comparison. First, a PB pose is an
authored arrangement of components; a morph requires matching atoms between
structures, and an MD trajectory supplies sampled coordinates from a simulation.
They deserve distinct import and animation controls. Second, the membrane force
field and Brownian-style motion support scene animation; they should not be
presented as an atomistic dynamics engine. Third, confidence values, B-factors,
hydrophobicity scales and electrostatic potentials have different meanings.
Color legends should name the actual quantity and its source.

Electrostatic surface coloring is a worthwhile later extension of the data-color
workflow. ChimeraX documents [Coulombic potential coloring](https://www.cgl.ucsf.edu/chimerax/).
For PB, importing a potential map would be a sensible first step before taking
responsibility for charge assignment and calculation settings. This would be
separate from the existing membrane force field.

My suggested delivery order is:

1. Build a complete short-movie workflow: save camera views/shots, add labels to
   existing PB targets, and export a preview or final movie from the PB panel.
   Expand the lighting presets into optional figure presets.
2. Add a shared selection model and sequence browser. Use it for residue labels,
   measurements, layered representations, data colors and binding-site views.
3. Add structural superposition, then morphing. Integrate trajectories alongside
   this work while preserving the distinction between authored and sampled motion.
4. Add density maps and general clipping; consider map fitting, richer analysis,
   mechanism templates and interactive sharing according to actual user demand.

If only one next feature is chosen, I recommend **camera views and shots**. It
would make the animation tools already present easier to turn into a finished
movie. The strongest scientific foundation project is **named molecular
selections with a sequence viewer**. The most substantial new animation
capability is **alignment plus conformational morphing**.

Docking, force-field simulation, energy minimization, structure refinement and
chemical editing would broaden PB's responsibilities considerably. I would
initially support importing their results from specialist tools. Likewise,
large-scene performance should be benchmarked before making a particular cache
or level-of-detail strategy a roadmap commitment.

The local evidence behind the classifications is concentrated in these files:

| Evidence | What it establishes |
|---|---|
| [Registration](../../proteinblender/addon.py), [operators](../../proteinblender/operators/__init__.py), [panels](../../proteinblender/panels/__init__.py) | The integrated PB surface, rather than everything present in vendored directories. |
| [Structure importer](../../proteinblender/operators/operator_import_local.py), [remote import](../../proteinblender/utils/scene_manager.py) | Structure-file formats and the AlphaFold path requesting pLDDT coloring. |
| [Visual settings](../../proteinblender/operators/visual_edit.py), [representation inventory](../../proteinblender/core/visual_style.py), [domain editor](../../proteinblender/operators/domain_splitter.py) | Per-target appearance, six style choices and contiguous range-based domains. |
| [Animation panel](../../proteinblender/panels/animation_panel.py), [keyframes](../../proteinblender/operators/keyframe_operators.py), [poses](../../proteinblender/operators/pose_operators.py), [pose library](../../proteinblender/panels/pose_library_panel.py) | Existing molecular keyframes, transform-based poses and pose-preview code; these are not a camera/whole-scene storyboard. |
| [Assembly cutaway](../../proteinblender/core/assembly.py), [lighting](../../proteinblender/core/lighting.py) | Existing copy-removal cutaways and fitted lighting, including camera/view orientation. |
| [Trajectory backend](../../proteinblender/utils/molecularnodes/entities/trajectory/trajectory.py), [trajectory UI code](../../proteinblender/utils/molecularnodes/entities/trajectory/ui.py), [MRC backend](../../proteinblender/utils/molecularnodes/entities/density/mrc.py) | Reusable foundations, whose presence alone does not establish a supported PB workflow. |
| [Molecule wrapper](../../proteinblender/core/molecule_wrapper.py) | First-model use for chain/domain bookkeeping when the imported array is a multi-model stack. |

Every implementation should use the existing Blender harness. Concrete checks
would include labels staying attached after rename/split/undo and through
trajectory playback; distances matching independently parsed atom coordinates;
selection sets preserving scientific identities through domain edits; shot
transitions restoring camera/visibility/color state after save/reopen; and
alignment recovering a known rigid transform with independently computed RMSD.
Morph tests should verify correspondence and exact endpoints, while treating
interpolated frames as illustrative unless a physical method establishes more.
Trajectory fixtures should verify frame/time mapping and periodic-boundary
handling; map fixtures should verify voxel spacing, axes, origin and model
registration. Native popup tests, rendered-image checks and installed-profile
validation should accompany each new user workflow.

The cited PyMOL timeline is the vendor-documented PyMOL 3 workflow; availability
can differ by edition. VMD's Movie Maker page includes historical setup and
encoding instructions, so it is used here as evidence of workflow design, not
as current platform-installation guidance. Upstream MolecularNodes documentation
does not establish that this repository's bundled version supports every current
upstream feature. No addon behavior was changed for this review.
