# Visual Set-up TODO

This file tracks the implementation of the Visual Set-up panel.

- [ ] **1. UI Panel (`Panel`)**
  - [ ] Create `PROTEIN_PB_PT_visual_setup` in `proteinblender/panels/visual_setup_panel.py`.
  - [ ] Ensure the panel's drawing logic is connected to the selections made in the Protein Outliner.

- [ ] **2. Panel Logic**
  - [ ] The `draw()` method should identify all selected items in the `ProteinOutlinerState`.
  - [ ] **Color Property**:
    - [ ] Add a `FloatVectorProperty` for color selection.
    - [ ] Implement an operator (`MOLECULE_PB_OT_set_color`) to apply the color to all selected protein/domain objects.
  - [ ] **Representation Property**:
    - [ ] Add an `EnumProperty` for selecting different visual styles (e.g., 'Ribbon', 'Surface').
    - [ ] Implement an operator (`MOLECULE_PB_OT_set_style`) to apply the selected style to all selected objects by swapping geometry nodes.

- [ ] **3. Undo/Redo**
  - [ ] Ensure that the new operators (`_set_color`, `_set_style`) are registered with undo support (`'REGISTER', 'UNDO'`).
  - [ ] Test undo/redo functionality for color and style changes. 