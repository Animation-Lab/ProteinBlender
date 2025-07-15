# Outliner Population TODO

This file tracks the implementation of populating the Protein Outliner when proteins are imported.

## **1. Integration with Import Process**
- [x] Hook into `scene_manager._finalize_imported_molecule()` to trigger outliner population
- [x] Ensure outliner population happens after molecule is fully loaded and added to scene
- [x] Add outliner refresh call to both `create_molecule_from_id()` and local import methods

## **2. Outliner Population Logic**
- [x] Create `populate_outliner_from_molecules()` function in `outliner_handler.py`
- [x] Implement hierarchy creation:
  - [x] Add top-level protein/molecule entries
  - [x] Add chain entries as children (if domains exist)
  - [x] Add domain entries as children of chains
- [x] Set proper `depth` values for indentation (0 for proteins, 1 for chains, 2 for domains)
- [x] Set proper `type` values ('PROTEIN', 'CHAIN', 'DOMAIN')

## **3. Data Synchronization**
- [x] Enhance `sync_outliner_state()` to handle hierarchical data
- [x] Implement selection/visibility sync for domains and chains, not just top-level proteins
- [x] Handle domain object references properly
- [x] Ensure sync works when domains are created after initial import
- [x] Add dedicated selection change handler for 2-way connectivity

## **4. UI Enhancements**
- [ ] Add expand/collapse functionality for hierarchical items
- [ ] Implement proper indentation for child items
- [ ] Add visual indicators for item types (icons for proteins vs domains)
- [ ] Handle empty outliner state gracefully

## **5. Testing & Edge Cases**
- [ ] Test with proteins that have no domains
- [ ] Test with proteins that have multiple chains
- [ ] Test outliner population after domain creation/deletion
- [ ] Verify undo/redo works with outliner state 