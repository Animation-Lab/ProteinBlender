# INITIALIZE.md

## Project Overview

We are redesigning the UI layout of the [ProteinBlender](https://github.com/dillonl/ProteinBlender/tree/full-ui-redo) Blender add-on to match a specific mockup layout (ui-development/proteinblender-proposed-layout.png).

## Objective

Transform the current ProteinBlender workspace to match the new UI mockup layout while maintaining core functionality, improving usability, and ensuring tight integration with Blender’s native outliner and undo/redo system. The redesigned workspace should support future extensibility, especially for pose and animation workflows.

## Goals

1. **Remove the left-side layout** (currently using `workspace_layout.py`).
2. **Preserve the existing Importer functionality and appearance**, even though the mockup simplifies it visually.
3. **Add all major components (Protein Outliner, Domain Maker, Group Maker, Protein Pose Library, Animation tools)** as Blender panels stacked vertically **below the Importer**.
4. **Replace the bottom area with the Blender timeline (dopesheet)**.
5. **Implement selection toggles and visibility toggles** for PDBs, chains, and domains — these are the unlabeled boxes in the mockup.
6. **Ensure full two-way binding between ProteinBlender's Outliner and Blender's native outliner/viewport**:

   * Selecting an item in the Protein Outliner should select it in Blender
   * Selecting an item in Blender’s viewport or outliner should update the ProteinBlender UI
   * Show/hide status should sync as well
7. **Fully connect the UI actions to Blender’s undo/redo system**
8. **Clarifying domain rules (most - if not all - of this functionality is already defined and written in the codebase)**:

   * Chains are domains that span an entire chain
   * Domains are sub-segments of chains and must collectively cover the full chain
   * If a domain is added that spans part of a chain, new domains should be auto-generated to cover the rest
   * Auto-name split domains logically (e.g., Domain 1A, 1B, etc.)
9. **Enable collapsing of proteins only** in the Protein Outliner. Chains and domains should remain expanded (when the protein is expanded).
10. **Hierarchical selection rules**:

    * Selecting a protein selects all its chains and domains
    * Selecting a chain selects all its domains
11. **Visual Setup Panel** should apply color and visual styles based on selection context:

    * If a protein is selected, changes apply to the protein and all child chains/domains
    * If a chain is selected, changes apply to the chain and its domains
    * If a domain is selected, changes apply only to it
12. **Domain Maker** should only activate if a single chain or domain is selected.
13. **Pose and Animation panels** should be included as placeholders in this version (mockup only, implementation will follow later).
14. **Support for multiple proteins**: The UI and logic must accommodate multiple imported proteins in a scene. To avoid name collisions and ensure correct linkage, all references to proteins, chains, and domains should be internally tracked using unique identifiers (e.g., IDs) rather than relying solely on names.

## Scope

This PRP focuses exclusively on the redesign of the UI layout and workspace behaviors. The back-end functionality for pose management and animation keyframing will be addressed in a future phase. This scope includes ensuring:

* Seamless workspace setup for the new layout
* Updated and refactored panel registration logic
* Outliner interaction logic
* Domain splitting logic with auto-naming
* MCP-assisted integration for Blender API via the `blender-api` MCP server

## Integration Tools

We have access to a **Blender API MCP Server** (see `documentation/FULL_DESCRIPTION.md`) that provides:

* Semantic API search
* Documentation examples
* Property/operator relationships
* Support for generating Blender UI code (e.g., `bpy.types.Panel`, `bpy.props.*`, `bpy.ops.*`)

The MCP server will be used throughout the PRP phase to:

* Guide the correct use of Blender panels and properties
* Ensure tight integration with Blender's data model
* Generate supporting operator and panel code accurately

## Deliverables for PRP

The output of this PRP phase will be:

* A complete visual and functional redesign of the workspace to match the mockup
* Synced Outliner behavior (two-way selection/show-hide)
* Domain splitting and naming behavior
* Refactored panel layout code
* Placeholder panels for Pose and Animation sections

## Miscellaneous

* MCP Server: `blender-api`
* Blender Version Target: 4.4+
* Timeline: This phase targets foundational refactor and UI relayout — animation-specific work to follow
