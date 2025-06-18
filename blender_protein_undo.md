# PRD: Robust Undo/Redo System for Blender Protein Visualization Addon

## Background & Current State
The protein visualization addon currently stores most of its state in Python-side data structures (e.g. dictionaries/lists in `ProteinBlenderScene.molecules`, `MoleculeWrapper` instances, etc.). Only some metadata is saved as Blender **ID Custom Properties** on objects (e.g. object’s custom properties for chain identifiers or domain info), and UI selections are managed with Blender `PropertyGroup` fields on the scene. Keyframes and transforms are handled by Blender’s native animation system. This design leads to **undo/redo inconsistencies**: because crucial protein state lives outside Blender’s undo-aware data, an undo can revert Blender objects without reverting the corresponding Python-side state. The result is the UI panel getting out of sync or empty (e.g. a protein “disappearing” from the panel despite still existing, or vice versa).

### Current Pain Points
- **Non-persistent state:** Important data (protein type, chain list, poses, etc.) isn’t fully stored in Blender’s data blocks. On undo, Blender restores objects but the addon’s Python caches remain stale.
- **Global references invalidated:** The addon keeps direct Python references to Blender objects. When an object is removed or changed by undo, those references become invalid, causing errors or mismatches.
- **UI desynchronization:** The custom UI (panels, lists) relies on Python-managed state that doesn’t track Blender’s undo stack, leading to incorrect panel content after undo/redo.
- **Undo grouping issues:** If multiple scene operations occur in one addon action, they might not be bundled into a single undo step properly, forcing multiple Ctrl+Z presses or leaving partial changes.

## Key Requirement: Integrate Addon State with Blender’s Undo
All essential protein state must be integrated into Blender’s own data and undo system. The undo/redo should reliably restore **both** the visible objects and all associated metadata/UI state for proteins. The system must be robust to multiple undo/redo steps and even user actions outside the addon (like manual object deletion or file save/load). It should follow Blender’s conventions for undo so that maintenance is easier and future Blender updates remain compatible.

## Proposed Solution Overview

1. **Use Blender Data for State:** Migrate all critical addon state (protein info, chain data, pose parameters, etc.) into Blender’s ID data (via custom properties and `PropertyGroup` containers).
2. **Replace Global References with Pointer Properties:** Use Blender’s `PointerProperty` to reference objects. Store a collection of these entries on `bpy.types.Scene`.
3. **Leverage Blender’s Native Undo Stack:** Continue using Blender’s built-in undo system. Operators that change the scene or addon state must be an Operator with `bl_options = {'REGISTER', 'UNDO'}`.
4. **Handlers for Sync (if needed):** Use `bpy.app.handlers.undo_post` and `redo_post` to refresh Python-only caches or UI after an undo/redo.
5. **UI Panel Linking:** Rework the UI panel to rely on new Blender-based data structures. Use `PropertyGroup`, `PointerProperty`, and Blender UI widgets that reference undo-aware data.
6. **Object Lifecycle Management:** All object creation/deletion and corresponding metadata changes should happen in a single operator execution.
7. **Animation Data Handling:** Keyframes should remain managed by Blender’s native animation system. If custom pose data exists, store it as custom properties.
8. **Performance & Maintenance Considerations:** Storing data in Blender properties yields robust undo and easier debugging. Follow Blender conventions to reduce maintenance burden.

## Implementation Plan (Detailed Steps)

### Data Structure Changes
- Define a `ProteinPropertyGroup` (`bpy.types.PropertyGroup`) with fields for `name`, `protein_type`, `chains`, `object_ptr`, etc.
- Register a `CollectionProperty(type=ProteinPropertyGroup)` on `bpy.types.Scene` (e.g. `scene.proteins`).
- Add an `IntProperty` for selected index: `scene.proteins_index`.

### Migrating Addon Operations

#### Add Protein
- Create Blender object(s), assign custom properties.
- Append a new entry to `scene.proteins` with metadata and pointer to the object.
- Set `scene.proteins_index` to the new index.
- Mark operator with `bl_options = {'UNDO'}`.

#### Remove Protein
- Delete object and remove entry from `scene.proteins` in the same operator.
- Adjust index to a valid value.

#### Update Protein Properties
- Use operators or direct property edits to update data.
- For style toggles, update object custom properties and/or `ProteinPropertyGroup` fields.

### Handlers for Undo
- Register a `@persistent` handler on `bpy.app.handlers.undo_post` and `redo_post`.
- Rebuild Python-side caches or validate object pointers in `scene.proteins`.

### UI Panel Updates
- UI lists and controls should reference `scene.proteins` and associated properties directly.
- For deletions outside addon, handlers should detect `None` pointers and clean stale entries.

### Saving and Loading
- Test that blend files save/load all protein metadata and maintain state correctly.

## Summary of Changes

| Data Type               | Where Stored Now                | Proposed Storage (Undo-friendly)                       |
|------------------------|----------------------------------|--------------------------------------------------------|
| Protein metadata       | Python objects/dicts (volatile) | Blender custom properties / PropertyGroup              |
| Chain identifiers      | Python, some custom props       | Blender object custom properties                       |
| Positions/transforms   | Blender object data             | No change                                              |
| Keyframes/animation    | Blender F-Curves                | No change                                              |
| UI state (selections)  | Scene PropertyGroup             | No change                                              |

## Benefits
- Undo/redo becomes reliable and intuitive for users.
- UI panels remain synchronized with the scene.
- Protein state survives undo, redo, file saves, and reloads.
- Reduced risk of bugs from stale global data.
- Easier long-term maintenance and debugging.

---

This PRD reflects Blender best practices and aligns the addon’s architecture with Blender’s undo-aware design. Following this plan will create a maintainable and robust experience for users working with proteins in Blender.

