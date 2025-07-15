# Protein Outliner TODO

This file tracks the implementation of the Protein Outliner panel.

- [x] **1. Data Model (`PropertyGroup`)**
  - [x] Define `OutlinerListItem` PropertyGroup for individual outliner items.
    - [x] `name`: `StringProperty`
    - [x] `identifier`: `StringProperty` (links to MoleculeWrapper/Domain)
    - [x] `type`: `EnumProperty` ('PROTEIN', 'CHAIN', 'DOMAIN', 'GROUP')
    - [x] `is_selected`: `BoolProperty`
    - [x] `is_visible`: `BoolProperty`
    - [x] `is_expanded`: `BoolProperty`
    - [x] `depth`: `IntProperty`
  - [x] Define `ProteinOutlinerState` PropertyGroup to hold a `CollectionProperty` of `OutlinerListItem`s.
  - [x] Register these properties on `bpy.types.Scene`.

- [x] **2. UI Panel (`Panel`)**
  - [x] Create `PROTEIN_PB_PT_outliner` in a new file (`proteinblender/panels/outliner_panel.py`).
  - [x] Use a custom UI loop to draw the items from the `ProteinOutlinerState.items` collection.
  - [x] Implement layout with name, selection checkbox, and visibility icon.
  - [x] Handle indentation based on the `depth` property.

- [x] **3. Synchronization Logic (`depsgraph_update_post`)**
  - [x] Create a new handler function for synchronization.
  - [x] Implement Blender -> Addon sync: Update `is_selected` and `is_visible` in `ProteinOutlinerState` from Blender's object state.
  - [x] Implement Addon -> Blender sync: Use `update` functions on `BoolProperty`s to set object `select_set()` and `hide_set()` from UI interactions.

- [x] **4. Registration**
  - [x] Register the new panel and properties in the addon's registration files. 