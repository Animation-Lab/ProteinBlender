# ProteinBlender TODO List

This document provides detailed specifications for upcoming features and bug fixes in ProteinBlender. Each task includes context, implementation guidance, and acceptance criteria.

**Code Quality Guidelines:**
- **Reuse existing functionality** - Always check if a function or pattern already exists before creating new code
- **Extend, don't duplicate** - If similar functionality exists, extend or refactor it rather than duplicating
- **Keep it DRY** - Don't Repeat Yourself - extract common patterns into reusable functions
- **Follow existing patterns** - Match the coding style and architectural patterns already in the codebase
- **Clean and maintainable** - Write code that is easy to understand and modify

---

## 1. Fix - 2-Way Selection Sync (3D Viewer ↔ Protein Outliner)

### Problem
Currently, selection only works in one direction. When users select items in the Protein Outliner, the corresponding objects are selected in the 3D viewport. However, when users select objects directly in the 3D viewport, the Protein Outliner does not update to reflect this selection.

### Current Behavior
- **Protein Outliner → 3D Viewport**: ✅ Works (via `sync_outliner_to_blender_selection` in `handlers/selection_sync.py`)
- **3D Viewport → Protein Outliner**: ❌ Does not work

### Implementation Location
- **Primary file**: `proteinblender/handlers/selection_sync.py`
- **Secondary files**:
  - `proteinblender/panels/protein_outliner_panel.py` (for selection operator)
  - Possibly need to register a scene update handler in `proteinblender/__init__.py`

### Implementation Details

1. **Reuse Existing Selection Sync Logic**
   - Review `sync_outliner_to_blender_selection()` function in `selection_sync.py`
   - This function already maps outliner items to Blender objects
   - Create a complementary `sync_blender_to_outliner_selection()` function that reverses the logic

2. **Create a Blender Scene Update Handler**
   - Add a `@persistent` handler function that runs when the selection changes in the 3D viewport
   - This handler should detect when `bpy.context.selected_objects` changes
   - Use Blender's `depsgraph_update_post` or `bpy.msgbus.subscribe_rna()` for object selection changes
   - **Reuse pattern**: Look at how other handlers are registered in `__init__.py`

3. **Map 3D Objects to Outliner Items**
   - When an object is selected in 3D viewport, determine which outliner item it corresponds to
   - **Check existing functions**: See if there's already a reverse lookup function for objects → outliner items
   - Use the object's name and custom properties to find the matching molecule/chain/domain
   - Objects are linked via:
     - Molecules: `molecule.object`
     - Domains: `domain.object` (stored in `molecule.domains` dict)
     - Chains: typically represented by domain objects that span the full chain

4. **Update Outliner Selection States**
   - Update the `is_selected` property of the corresponding outliner item
   - **Reuse hierarchical logic**: The `update_parent_chain_selection()` method in `PROTEINBLENDER_OT_outliner_select` (line 432) already handles parent updates
   - Extract this logic into a reusable utility function if it's not already separate
   - Handle hierarchical selection logic:
     - If all domains in a chain are selected, mark the chain as selected
     - If all chains in a protein are selected, mark the protein as selected
   - Update any reference items (for puppets/groups) to maintain consistency

5. **Prevent Infinite Loops**
   - Add a module-level flag to prevent recursive updates between outliner and 3D viewport
   - Example: `_updating_selection = False` flag that's checked before triggering updates
   - Pattern:
     ```python
     _updating_selection = False

     def sync_outliner_to_blender_selection(context, item_id):
         global _updating_selection
         if _updating_selection:
             return
         _updating_selection = True
         try:
             # ... sync logic ...
         finally:
             _updating_selection = False
     ```

6. **Handle Edge Cases**
   - Multiple objects selected
   - Puppet controller Empty objects (should sync to puppet checkbox)
   - Objects that are part of multiple groups/puppets
   - Deselection (when objects are deselected in viewport)

### Code Reuse Opportunities
- `sync_outliner_to_blender_selection()` - Study and reverse its logic
- `PROTEINBLENDER_OT_outliner_select.update_parent_chain_selection()` - Extract into utility function
- `PROTEINBLENDER_OT_outliner_select.select_children()` - Already handles recursive selection, reuse pattern
- Scene manager's molecule/domain lookup methods - Reuse for object → outliner item mapping

### Files to Reference
- `proteinblender/handlers/selection_sync.py` - Current one-way sync implementation
- `proteinblender/panels/protein_outliner_panel.py:289-495` - `PROTEINBLENDER_OT_outliner_select` operator
- `proteinblender/panels/protein_outliner_panel.py:432-460` - Parent chain selection update logic
- Blender API: `bpy.msgbus` for subscribing to selection changes

---

## 2. Add Snap/Copy/Delete Buttons to Individual Proteins in Outliner

### Problem
The Protein Outliner currently has action buttons for chains and domains (copy, delete) but proteins themselves only have a delete button. Users need quick access to snap (reset transform) and copy functionality at the protein level.

### Current Behavior
- **Chains/Domains**: Have reset transform (OBJECT_ORIGIN icon), copy (ADD icon), and delete (TRASH icon) buttons
- **Proteins**: Only have delete button
- **Puppets**: Only have delete button

### Implementation Location
- **Primary file**: `proteinblender/panels/protein_outliner_panel.py`
- **Specific method**: `PROTEINBLENDER_UL_outliner.draw_item()` around line 220-231

### Implementation Details

1. **Update the `draw_item` Method**
   - Locate the section that handles `item.item_type == 'PROTEIN'` (around line 221)
   - Add three buttons matching the same pattern as chains/domains:
     - **Snap/Reset Transform Button** (OBJECT_ORIGIN icon)
     - **Copy Button** (ADD icon)
     - **Delete Button** (TRASH icon) - already exists

2. **Reuse Existing Operator Patterns**

   **A. Check for Existing Reset Transform Operators**
   - Look in `proteinblender/operators/molecule_operators.py` for any existing reset/transform operators
   - Check `proteinblender/operators/pivot_operators.py` - there may be reset functionality there
   - The operator `molecule.reset_domain_transform` exists for domains (line 165 in protein_outliner_panel.py)
   - **Extend or create similar**: Create `MOLECULE_OT_reset_protein_transform` following the same pattern

   **B. Check for Existing Copy Operators**
   - The operator `molecule.copy_domain` exists (line 177, 209 in protein_outliner_panel.py)
   - Review its implementation in `molecule_operators.py`
   - **Create similar**: `MOLECULE_OT_copy_protein` following the domain copy pattern
   - Should duplicate the entire molecule with all its domains and chains

3. **Create Reset Protein Transform Operator**
   - File: `proteinblender/operators/molecule_operators.py`
   - Operator ID: `molecule.reset_protein_transform`
   - Class name: `MOLECULE_OT_reset_protein_transform`
   - Should reset the protein's root object location, rotation, and scale to defaults
   - Set location to (0, 0, 0), rotation to (0, 0, 0), scale to (1, 1, 1)
   - Should also reset all child chain/domain transforms to maintain relative positions

4. **Create Copy Protein Operator**
   - File: `proteinblender/operators/molecule_operators.py`
   - Operator ID: `molecule.copy_protein`
   - Class name: `MOLECULE_OT_copy_protein`
   - **Study**: Look at how `copy_domain` works and apply similar logic
   - Should create a duplicate of the entire protein molecule including:
     - Copy of the molecule object and all its data
     - Copies of all domains with their geometry nodes (reuse domain copy logic)
     - New unique ID for the copied molecule
     - Suffix like "_copy_1", "_copy_2" to the name
   - After copying, call `build_outliner_hierarchy(context)` to update UI

5. **Button Layout in Outliner**
   - Order should match chains/domains: Reset → Copy → Delete
   - Use same emboss=False style for consistency
   - Icons: 'OBJECT_ORIGIN', 'ADD', 'TRASH'
   - Code structure at line 221:
   ```python
   elif item.item_type == 'PROTEIN':
       # Reset transform button
       reset_op = row.operator("molecule.reset_protein_transform", text="", icon='OBJECT_ORIGIN', emboss=False)
       if reset_op:
           reset_op.molecule_id = item.item_id

       # Copy button
       copy_op = row.operator("molecule.copy_protein", text="", icon='ADD', emboss=False)
       if copy_op:
           copy_op.molecule_id = item.item_id

       # Delete button (already exists)
       delete_op = row.operator("molecule.delete", text="", icon='TRASH', emboss=False)
       if delete_op:
           delete_op.molecule_id = item.item_id
   ```

### Code Reuse Opportunities
- `molecule.reset_domain_transform` - Use as template for protein reset
- `molecule.copy_domain` - Use as template for protein copy, but loop through all domains
- `molecule.delete` - Already exists and works for proteins
- `build_outliner_hierarchy()` - Already called after structural changes

### Files to Reference
- `proteinblender/panels/protein_outliner_panel.py:162-218` - Chain/domain button implementation
- `proteinblender/operators/molecule_operators.py` - For copy_domain and delete operators
- `proteinblender/operators/pivot_operators.py` - May contain reset transform code
- `proteinblender/utils/scene_manager.py` - For molecule creation/management

---

## 3. Implement Delete Chain Functionality

### Problem
Users cannot delete individual chains from a protein. Chains are currently displayed in the outliner but lack a delete button. This is needed to allow users to remove unwanted chains while keeping the rest of the protein intact.

### Current Behavior
- Chains are displayed in the outliner
- Chains can have domains split from them
- Chains cannot be deleted individually
- Only entire proteins can be deleted

### Implementation Location
- **Primary file**: `proteinblender/operators/molecule_operators.py` (create new operator)
- **Secondary file**: `proteinblender/panels/protein_outliner_panel.py` (add delete button for chains)

### Implementation Details

1. **Add Delete Button to Chain Items in Outliner**
   - Modify `PROTEINBLENDER_UL_outliner.draw_item()` method
   - In the `item.item_type == 'CHAIN'` section (around line 130)
   - **Follow existing pattern**: Domains already have delete buttons (line 215)
   - Add delete button after the copy button:
   ```python
   # After copy button for chains
   delete_op = row.operator("molecule.delete_chain", text="", icon='TRASH', emboss=False)
   if delete_op:
       delete_op.chain_id = item.chain_id
       delete_op.molecule_id = item.parent_id
   ```

2. **Create Chain Delete Operator**
   - File: `proteinblender/operators/molecule_operators.py`
   - Operator ID: `molecule.delete_chain`
   - Class name: `MOLECULE_OT_delete_chain`
   - **Study existing delete operators**: Look at `molecule.delete` and `molecule.delete_domain` for patterns

3. **Operator Implementation Logic**

   **A. Reuse Domain Deletion Logic**
   - The operator `molecule.delete_domain` likely already exists
   - A chain is essentially a collection of domains with the same `chain_id`
   - Loop through domains and call existing domain deletion logic for each

   **B. Find and Delete All Domains Belonging to the Chain**
   - Get the molecule from scene_manager: `scene_manager.molecules.get(self.molecule_id)`
   - Iterate through `molecule.domains` to find all domains where `domain.chain_id == target_chain_id`
   - For each domain:
     - **Reuse cleanup**: Call `domain.cleanup()` (already exists in `core/domain.py:241-303`)
     - Remove from `molecule.domains` dictionary

   **C. Update Puppet Memberships**
   - **Look for existing puppet update functions**: Check if there's already a utility for updating puppet memberships
   - Remove the chain from puppet membership lists
   - Pattern likely exists in `domain_ops.py` around lines 616-631 (group membership handling)
   - Extract and reuse this logic

   **D. Rebuild Outliner**
   - Call `build_outliner_hierarchy(context)` - already used throughout codebase
   - This will remove the chain and its domains from the display

   **E. Capture State for Undo/Redo**
   - Call `scene_manager._capture_molecule_state(molecule_id)` before making changes
   - This pattern is used in `domain_ops.py:552` and elsewhere

4. **Handle Edge Cases**
   - Prevent deletion if it's the last chain in a protein (optional: could delete entire protein instead)
   - Clean up any references in the pose library
   - Remove chain from any puppet/group memberships
   - If chain has no domains (full-chain domain), ensure that's handled

### Code Reuse Opportunities
- `domain.cleanup()` (core/domain.py:241) - Already handles domain object removal
- `scene_manager._capture_molecule_state()` - Already used for undo support
- `build_outliner_hierarchy()` - Already used after structural changes
- Puppet membership update logic from `domain_ops.py:616-631` - Extract into utility function if not already separate
- Domain deletion loop pattern from any existing multi-delete operations

### Implementation Pattern
```python
class MOLECULE_OT_delete_chain(Operator):
    """Delete a chain from a protein"""
    bl_idname = "molecule.delete_chain"
    bl_label = "Delete Chain"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: StringProperty()
    molecule_id: StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Capture state for undo (reuse existing pattern)
        scene_manager._capture_molecule_state(self.molecule_id)

        # Find and delete all domains belonging to this chain
        domains_to_delete = [
            domain_id for domain_id, domain in molecule.domains.items()
            if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(self.chain_id)
        ]

        # Delete domains (reuse domain.cleanup())
        for domain_id in domains_to_delete:
            domain = molecule.domains[domain_id]
            domain.cleanup()  # Reuse existing cleanup method
            del molecule.domains[domain_id]

        # Remove from puppet memberships (extract existing logic into utility)
        self._remove_chain_from_puppets(context, self.molecule_id, self.chain_id)

        # Rebuild outliner (reuse existing function)
        build_outliner_hierarchy(context)

        self.report({'INFO'}, f"Deleted chain {self.chain_id}")
        return {'FINISHED'}

    def _remove_chain_from_puppets(self, context, molecule_id, chain_id):
        """Remove chain from any puppet group memberships"""
        # Check if this logic already exists elsewhere and reuse it
        chain_outliner_id = f"{molecule_id}_chain_{chain_id}"
        for item in context.scene.outliner_items:
            if item.item_type == 'PUPPET' and item.puppet_memberships:
                members = set(item.puppet_memberships.split(','))
                if chain_outliner_id in members:
                    members.remove(chain_outliner_id)
                    item.puppet_memberships = ','.join(members)
```

### Files to Reference
- `proteinblender/operators/domain_ops.py:616-631` - Puppet membership handling pattern
- `proteinblender/operators/molecule_operators.py` - For existing delete operators
- `proteinblender/core/domain.py:241-303` - Domain cleanup method to reuse
- `proteinblender/panels/protein_outliner_panel.py:215` - Existing domain delete button

---

## 4. Minor Bug Fix - Inherit Style When Splitting Domains

### Problem
When splitting a chain into domains, the newly created domains do not inherit the visual style (ribbon, surface, cartoon, etc.) from the parent chain. This results in domains reverting to the default "ribbon" style instead of maintaining the chain's current style.

### Current Behavior
- Parent chain has a style (e.g., "surface", "cartoon", "ball_and_stick")
- User splits the chain into domains
- New domains are created with default "ribbon" style
- User must manually set the style for each new domain

### Expected Behavior
- New domains should inherit the parent's style automatically
- If splitting a domain (not a chain), the new sub-domains should inherit the parent domain's style

### Implementation Location
- **Primary file**: `proteinblender/operators/domain_ops.py`
- **Specific method**: `PROTEINBLENDER_OT_split_domain.execute()` around line 636-675
- **Secondary location**: `proteinblender/core/molecule_wrapper.py` in the `_create_domain_with_params` method

### Implementation Details

1. **Identify Parent Style Before Splitting**
   - Before creating new domains, determine the parent's current style
   - For chain splits: Find the domain that represents the full chain
   - For domain splits: Use the domain being split as the parent
   - Get the style from `domain.style` property (defined in `core/domain.py:31-34`)

2. **Check if Style Parameter Already Exists**
   - Review the signature of `molecule._create_domain_with_params()` in `molecule_wrapper.py`
   - Check if there's already a style parameter or a way to pass initial properties
   - **If it exists**: Use it directly
   - **If it doesn't exist**: Add it as an optional parameter with default="ribbon"

3. **Pass Style to Domain Creation**
   - Modify the call to `molecule._create_domain_with_params()` in `domain_ops.py` around line 658
   - Pass the parent's style as a parameter:
   ```python
   created_domain_ids = molecule._create_domain_with_params(
       self.chain_id,
       start,
       end,
       domain_name,
       False,  # auto_fill_chain
       None,   # parent_domain_id
       style=parent_style  # NEW: Pass parent style
   )
   ```

4. **Apply Style During Domain Creation**
   - In `molecule_wrapper.py`, update `_create_domain_with_params` to accept optional `style` parameter
   - When creating the domain definition, set `domain.style = style` if provided
   - **Check for existing style application code**: Look for how styles are currently applied
   - **Reuse style application logic**: The `domain_style_update()` function in `core/domain.py:370-437` already handles style changes
   - Apply the style using existing mechanisms after domain creation

5. **Extract Parent Style Detection Logic**
   - Create a reusable helper function to find the parent domain/chain and get its style:
   ```python
   def get_parent_style(molecule, chain_id, split_start, split_end):
       """Get the style of the parent domain/chain being split"""
       for domain_id, domain in molecule.domains.items():
           if (hasattr(domain, 'chain_id') and
               str(domain.chain_id) == str(chain_id) and
               domain.start <= split_start and
               domain.end >= split_end):
               return getattr(domain, 'style', 'ribbon')
       return 'ribbon'  # Default fallback
   ```

### Code Reuse Opportunities
- `domain.style` property (core/domain.py:31-34) - Already defined
- `domain_style_update()` callback (core/domain.py:370-437) - Already handles style application
- Style application through geometry nodes - Check if there's a utility function for this
- STYLE_ITEMS from `utils/molecularnodes/style.py` - Validation of style names

### Implementation Pattern

**In `domain_ops.py` around line 543:**
```python
def execute(self, context):
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(self.molecule_id)

    # ... existing validation code ...

    # NEW: Get parent style before splitting (extract into utility function)
    parent_style = self._get_parent_style(molecule, self.chain_id, self.split_start, self.split_end)

    # ... existing domain generation code ...

    # MODIFIED: Pass parent_style to domain creation
    for i, (start, end) in enumerate(domains):
        domain_name = f"Residues {start}-{end}"

        created_domain_ids = molecule._create_domain_with_params(
            self.chain_id,
            start,
            end,
            domain_name,
            False,
            None,
            style=parent_style  # Pass style
        )

def _get_parent_style(self, molecule, chain_id, split_start, split_end):
    """Extract parent style detection into reusable method"""
    for domain_id, domain in molecule.domains.items():
        if (hasattr(domain, 'chain_id') and
            str(domain.chain_id) == str(chain_id) and
            domain.start <= split_start and
            domain.end >= split_end):
            return getattr(domain, 'style', 'ribbon')
    return 'ribbon'
```

**In `molecule_wrapper.py` - extend `_create_domain_with_params`:**
```python
def _create_domain_with_params(self, chain_id_int_str, start, end, name,
                               auto_fill_chain, parent_domain_id, style=None):
    """Create domain with parameters, optionally specifying style"""

    # ... existing domain creation code ...

    # Apply style if provided (reuse existing style application mechanism)
    if style and new_domain:
        new_domain.style = style
        # Check if there's an existing function to apply style to domain
        # If so, call it here instead of duplicating logic
```

### Files to Reference
- `proteinblender/core/domain.py:31-34` - Style property definition
- `proteinblender/core/domain.py:370-437` - Domain style update callback (reuse this logic)
- `proteinblender/operators/domain_ops.py:543-699` - Split domain execute method
- `proteinblender/utils/molecularnodes/style.py` - Style definitions and STYLE_ITEMS

---

## 5. Calculate and Set Pivots for Proteins and Chains

### Problem
When importing proteins, pivots are not set intelligently based on the molecule's geometry. This makes rotation and manipulation less intuitive. Pivots should be set to the center of mass for proteins and chains, and to appropriate boundaries for split domains.

### Current Behavior
- Protein objects are imported with default pivot at an rbitrary location
- No automatic centering of proteins at world origin

### Expected Behavior
**For Proteins (on import or copy):**
1. Calculate center of mass for the entire protein
2. Set the protein's pivot point to this center of mass
3. Move the protein so this pivot is at world origin (0, 0, 0)

**For Chains (on import or create):**
1. Calculate center of mass for each chain
2. Set each chain's pivot to its center of mass

**For Split Domains:**
1. When splitting into 2 domains: Set pivots at the boundary between domains
2. When splitting into 3+ domains:
   - First domain: Pivot at end
   - Middle domains: Pivot at beginning
   - Last domain: Pivot at center of mass 

### Implementation Location
- **Primary file**: `proteinblender/core/molecule_wrapper.py` (molecule creation and setup)
- **Secondary file**: `proteinblender/operators/domain_ops.py` (domain split pivots)
- **Check first**: `proteinblender/operators/pivot_operators.py` - May already have pivot utilities

### Implementation Details

#### Part A: Check for Existing Pivot Functionality

1. **Review pivot_operators.py**
   - Check if there are already functions for:
     - Setting object origin/pivot
     - Calculating center of mass
     - Moving objects while maintaining transforms
   - **Reuse existing functions** if they exist

2. **Check MolecularNodes Integration**
   - The `utils/molecularnodes/` directory may have utilities for:
     - Accessing molecular geometry
     - Getting residue positions
     - Working with atom coordinates
   - **Reuse MolecularNodes utilities** instead of reimplementing

#### Part B: Protein Import - Center of Mass Calculation

1. **Add Post-Processing Hook**
   - In `molecule_wrapper.py`, after molecule object creation
   - Check if there's already a post-processing method that can be extended
   - Add center-of-mass pivot setting as part of molecule setup

2. **Use Blender's Built-in Center of Mass**
   - Blender already has: `bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')`
   - Or: `bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS_VOLUME')`
   - **Prefer built-in** over custom calculation for reliability

3. **Implementation Pattern**
   ```python
   def _set_protein_pivot_and_center(self, obj):
       """Set pivot to center of mass and move to world origin"""
       # Check if this functionality already exists elsewhere
       # Reuse if possible

       # Select object (required for operators)
       bpy.context.view_layer.objects.active = obj
       obj.select_set(True)

       # Use Blender's built-in center of mass calculation
       bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')

       # Move to world origin
       obj.location = (0, 0, 0)

       obj.select_set(False)
   ```

#### Part C: Chain Pivots

1. **Chains as Domain Objects**
   - Chains are represented as domain objects that span the full chain
   - When creating full-chain domains, set their pivots using the same logic

2. **Reuse Protein Pivot Logic**
   - Extract the protein pivot function into a generic utility
   - Call it for chain domain objects with optional parameters for residue filtering

3. **Check for Existing Residue Filtering**
   - MolecularNodes likely has functions to work with specific residue ranges
   - Use these to calculate center of mass for just the chain's residues

#### Part D: Domain Split Pivots

1. **Determine Pivot Position Based on Split**
   - **2 domains**: Boundary between them (end of first / start of second)
   - **3+ domains**: Start of each domain

2. **Check for Existing Residue Position Functions**
   - Look in MolecularNodes utilities for getting atom positions by residue number
   - Common pattern: Get C-alpha atom position for a residue

3. **Create Reusable Pivot Setting Utility**
   ```python
   def set_domain_pivot_at_residue(domain_obj, residue_number):
       """Set domain object's pivot at a specific residue position"""
       # Check if this already exists in pivot_operators.py
       # If so, use that instead

       # Get residue position (C-alpha atom)
       residue_pos = get_residue_position(domain_obj, residue_number)

       # Set object origin to that position
       set_object_origin(domain_obj, residue_pos)
   ```

4. **Apply Pivots After Domain Split**
   - In `domain_ops.py`, after creating domains (around line 670)
   - Calculate appropriate pivot residue for each domain
   - Apply using the utility function

#### Part E: Extract Common Utilities

If these don't already exist, create them in a utility module:

```python
# In proteinblender/utils/geometry_utils.py (or similar)

def set_object_origin(obj, position):
    """Set object's origin/pivot to a specific 3D position"""
    # Check if this exists in pivot_operators.py first
    pass

def get_residue_position(obj, residue_number, chain_id=None):
    """Get 3D position of a specific residue (C-alpha atom)"""
    # Check if MolecularNodes has this functionality
    pass

def calculate_object_center_of_mass(obj, vertex_filter=None):
    """Calculate center of mass for object or subset of vertices"""
    # Use Blender's built-in if possible
    pass
```

### Code Reuse Opportunities
- `pivot_operators.py` - May already have pivot manipulation functions
- `bpy.ops.object.origin_set()` - Blender's built-in center of mass
- MolecularNodes utilities for residue positions and atom coordinates
- Existing domain creation hooks for applying pivots

### Files to Reference
- `proteinblender/operators/pivot_operators.py` - Existing pivot functionality to reuse
- `proteinblender/core/molecule_wrapper.py` - Molecule creation and setup
- `proteinblender/operators/domain_ops.py` - Domain splitting (around line 636-699)
- `proteinblender/utils/molecularnodes/` - Molecular geometry utilities
- Blender API: `bpy.ops.object.origin_set()`, `Object.matrix_world`, `Vector` from `mathutils`

---

## 6. Fix Keyframe Bug - Additive Keyframing

### Problem
When adding keyframes with different properties (e.g., pose then color), the system overwrites previous keyframe values instead of being additive. This causes animations to lose data when adding new keyframe properties at the same frame.

### Bug Reproduction Steps
```
1. Change color to green
2. Create keyframe at frame 1 (color is keyframed)
3. Go to frame 20
4. Make new pose (move domains around)
5. Create keyframe at frame 20 (pose is keyframed)
6. Change color to red
7. Create keyframe at frame 20 (color is keyframed)

Result: The pose from steps 4-5 is overwritten/lost. Only the red color remains at frame 20.
Expected: Both pose AND red color should exist at frame 20.
```

### Root Cause
The bug is in `proteinblender/operators/keyframe_operators.py` in the `PROTEINBLENDER_OT_create_keyframe` operator. The operator is likely:
- Resetting transform values before keyframing
- Not preserving existing keyframe values for properties that aren't being keyframed
- Applying poses unconditionally, which overwrites current transforms

### Implementation Location
- **Primary file**: `proteinblender/operators/keyframe_operators.py`
- **Specific method**: `PROTEINBLENDER_OT_create_keyframe.execute()` around lines 414-560
- **Problem areas**:
  - Lines 456-470: Pose application logic (applies poses unconditionally)
  - Lines 522-546: Domain keyframing logic

### Implementation Details

1. **Review Existing Keyframe Logic**
   - The operator has checkboxes for: Location, Rotation, Scale, Color, Pose
   - When checked, that property should be keyframed at current values
   - When unchecked, existing keyframes should be removed
   - **Current bug**: Pose application (lines 456-470) happens regardless of checkbox state

2. **Identify the Exact Problem**
   - Lines 456-470: "Apply any active poses for the puppet's domains"
   - This code runs **before** checking if pose should be keyframed
   - It overwrites current domain transforms with pose data from the library
   - When only keyframing color, this still resets the pose

3. **Fix Strategy - Conditional Pose Application**

   **A. Only Apply Poses When Keyframing Pose**
   ```python
   # CURRENT BUGGY CODE (around line 456):
   # Apply any active poses for the puppet's domains
   for item in scene.molecule_list_items:
       if hasattr(item, 'active_pose_index') and hasattr(item, 'poses'):
           # ... applies pose transforms to domain_objects ...

   # FIXED CODE:
   # Only apply poses if we're actually keyframing the pose checkbox
   if puppet_item.keyframe_pose:
       # Apply any active poses for the puppet's domains
       for item in scene.molecule_list_items:
           if hasattr(item, 'active_pose_index') and hasattr(item, 'poses'):
               # ... applies pose transforms to domain_objects ...
   ```

4. **Additional Safety - Preserve Existing Animation Data**

   **A. Check if Preserve Function Already Exists**
   - Look for any existing utilities that read keyframe values from F-curves
   - Check if there's already a pattern for reading animation data at specific frames

   **B. Create Reusable Keyframe Reading Utility**
   ```python
   def get_keyframe_value_at_frame(obj, data_path, frame):
       """Get the keyframed value of a property at a specific frame"""
       # Check if this utility already exists elsewhere
       if obj.animation_data and obj.animation_data.action:
           for fcurve in obj.animation_data.action.fcurves:
               if fcurve.data_path == data_path:
                   return fcurve.evaluate(frame)
       return None
   ```

   **C. Use Before Keyframing**
   - Only needed as extra safety if the conditional pose application isn't sufficient
   - Before keyframing, read existing values and restore them if not changing that property

5. **Separate Pose and Visual Properties Clearly**
   - Pose keyframes: location, rotation, scale of domains (relative transforms)
   - Visual keyframes: color, alpha (geometry node inputs)
   - Transform keyframes: location, rotation, scale of puppet controller (global transforms)
   - These should be completely independent

6. **Specific Code Change**

   **Primary Fix - Conditional Pose Application (around line 456):**
   ```python
   # BEFORE:
   # Apply any active poses for the puppet's domains
   for item in scene.molecule_list_items:
       if hasattr(item, 'active_pose_index') and hasattr(item, 'poses'):
           if item.active_pose_index >= 0 and item.active_pose_index < len(item.poses):
               active_pose = item.poses[item.active_pose_index]
               # Apply pose transforms to matching domains
               for transform in active_pose.domain_transforms:
                   for domain_obj in domain_objects:
                       if domain_obj.name == transform.domain_id or \
                          domain_obj.name.endswith(f"_{transform.domain_id}"):
                           domain_obj.location = transform.location
                           domain_obj.rotation_euler = transform.rotation
                           domain_obj.scale = transform.scale

   # AFTER (wrap in conditional):
   # Only apply poses if we're keyframing the pose
   if puppet_item.keyframe_pose:
       # Apply any active poses for the puppet's domains
       for item in scene.molecule_list_items:
           if hasattr(item, 'active_pose_index') and hasattr(item, 'poses'):
               if item.active_pose_index >= 0 and item.active_pose_index < len(item.poses):
                   active_pose = item.poses[item.active_pose_index]
                   # Apply pose transforms to matching domains
                   for transform in active_pose.domain_transforms:
                       for domain_obj in domain_objects:
                           if domain_obj.name == transform.domain_id or \
                              domain_obj.name.endswith(f"_{transform.domain_id}"):
                               domain_obj.location = transform.location
                               domain_obj.rotation_euler = transform.rotation
                               domain_obj.scale = transform.scale
   ```

### Code Reuse Opportunities
- Check if animation data reading utilities already exist in the codebase
- Reuse F-curve evaluation patterns if they exist elsewhere
- The checkbox logic (lines 477-546) already works correctly for adding/removing keyframes
- The color keyframing methods (lines 69-208) already work correctly

### Verification Approach
Since there's no automated testing for Blender, verification must be manual:
1. Apply the fix (wrap pose application in conditional)
2. Follow the exact bug reproduction steps
3. Verify that both pose and color are preserved at frame 20
4. Test other combinations (multiple properties at once)
5. Test unchecking boxes removes keyframes without affecting others

### Files to Reference
- `proteinblender/operators/keyframe_operators.py:50-561` - The create_keyframe operator
- `proteinblender/operators/keyframe_operators.py:456-470` - Buggy pose application code
- `proteinblender/panels/animation_panel.py` - Animation panel UI
- Blender API: `FCurve.evaluate()`, `Object.animation_data`, `Action.fcurves`

---

## Summary

This TODO list covers 6 major tasks with emphasis on code reuse and clean implementation:

1. **2-way selection sync** - Reverse existing one-way sync logic, reuse selection update patterns
2. **Protein action buttons** - Follow existing chain/domain button patterns, reuse operators
3. **Delete chain** - Reuse domain deletion logic, extract puppet membership utilities
4. **Inherit style** - Extend domain creation to accept style parameter, reuse existing style application
5. **Pivot points** - Check existing pivot utilities first, use Blender built-ins, reuse MolecularNodes geometry functions
6. **Keyframe bug fix** - Simple conditional fix to prevent pose overwriting, minimal code change

Each task emphasizes:
- **Checking for existing functionality** before writing new code
- **Extracting reusable utilities** from patterns found in the codebase
- **Following established patterns** for consistency
- **Extending existing functions** rather than duplicating logic
- **Clean, maintainable code** that fits the existing architecture
