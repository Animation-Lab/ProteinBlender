# Chain Deletion in ProteinBlender

## Overview

This document provides a comprehensive guide to how chain deletion is implemented in ProteinBlender, including the architecture, node network management, and cleanup procedures. Chain deletion is a multi-step process that involves removing all domains belonging to a chain, cleaning up the parent molecule's node network, and maintaining data integrity.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Key Components](#key-components)
3. [Parent Node Network Structure](#parent-node-network-structure)
4. [Chain Deletion Flow](#chain-deletion-flow)
5. [Domain Deletion Mechanisms](#domain-deletion-mechanisms)
6. [Node Network Cleanup](#node-network-cleanup)
7. [Edge Cases and Special Handling](#edge-cases-and-special-handling)
8. [Code Examples](#code-examples)

---

## Architecture Overview

ProteinBlender uses a domain-based system where each protein chain can be divided into multiple domains. Each domain has:

- A logical definition (`DomainDefinition` class)
- A Blender object with geometry
- A geometry nodes network for visualization
- Mask nodes in the parent molecule's node group

When a chain is deleted, all domains belonging to that chain must be removed, along with their associated nodes in the parent molecule's geometry nodes network.

### Core Classes

| Class | File | Purpose |
|-------|------|---------|
| `MoleculeWrapper` | [molecule_wrapper.py](../proteinblender/core/molecule_wrapper.py) | Manages domains and parent molecule node network |
| `DomainDefinition` | [domain.py](../proteinblender/core/domain.py) | Defines domain properties and cleanup methods |
| `MOLECULE_PB_OT_delete_chain` | [molecule_operators.py](../proteinblender/operators/molecule_operators.py) | Operator for chain deletion |

---

## Key Components

### 1. MoleculeWrapper

The `MoleculeWrapper` class (located in [molecule_wrapper.py](../proteinblender/core/molecule_wrapper.py:12)) wraps a MolecularNodes molecule and provides ProteinBlender-specific functionality:

```python
class MoleculeWrapper:
    def __init__(self, molecule: Molecule, identifier: str):
        self.molecule = molecule
        self.identifier = identifier
        self.domains: Dict[str, DomainDefinition] = {}
        self.domain_mask_nodes = {}  # Maps domain_id to (chain_select_node, res_select_node)
        self.domain_join_node = None  # Multi-Boolean OR node for combining domain masks
        self.join_nodes = []  # List of all join nodes (for overflow handling)
        self.final_not = None  # NOT node that inverts the domain mask
```

**Key responsibilities:**
- Maintains a dictionary of all domains (`self.domains`)
- Tracks mask nodes for each domain in the parent network (`self.domain_mask_nodes`)
- Manages the domain infrastructure nodes (join nodes, NOT node)
- Provides deletion and cleanup methods

### 2. DomainDefinition

The `DomainDefinition` class (located in [domain.py](../proteinblender/core/domain.py:49)) represents a single domain:

```python
class DomainDefinition:
    def __init__(self, chain_id: str, start: int, end: int, name: Optional[str] = None):
        self.chain_id = chain_id
        self.start = start
        self.end = end
        self.object = None  # Blender object reference
        self.node_group = None  # Geometry nodes network
        self.parent_domain_id = None  # For hierarchy tracking
```

**Key responsibilities:**
- Stores domain parameters (chain, residue range)
- Holds references to Blender object and node group
- Provides `cleanup()` method for removing geometry and nodes

---

## Parent Node Network Structure

### Infrastructure Setup

When a `MoleculeWrapper` is initialized, it sets up a node infrastructure in the parent molecule's geometry nodes network to handle domain masking. This infrastructure is created by `_setup_protein_domain_infrastructure()` ([molecule_wrapper.py](../proteinblender/core/molecule_wrapper.py:85)).

### Node Network Architecture

```
[Domain 1 Chain Select] ──┐
[Domain 1 Res Select] ─────┼──> [Multi-Boolean OR (Join)] ──> [NOT] ──> [Main Style Node]
                           │
[Domain 2 Chain Select] ──┤
[Domain 2 Res Select] ─────┤
                           │
[Domain 3 Chain Select] ──┤
[Domain 3 Res Select] ─────┘
```

**Infrastructure Nodes:**

1. **Domain_Boolean_Join** - A `Multi_Boolean_OR` node group that combines all domain selections
   - Has 8 input slots (Input_1 through Input_8)
   - When all slots are full, overflow join nodes are created and chained
   - Located at: `self.domain_join_node` (primary) and `self.join_nodes` (all join nodes including overflow)

2. **Domain_Final_Not** - A Boolean NOT node
   - Inverts the combined domain selection
   - This ensures the parent molecule displays everything EXCEPT the domains
   - Located at: `self.final_not`

3. **Per-Domain Mask Nodes** (created for each domain):
   - **Domain_Chain_Select_{domain_id}** - Selects atoms by chain ID
   - **Domain_Res_Select_{domain_id}** - Filters by residue range
   - These are tracked in `self.domain_mask_nodes[domain_id]`

### Example Node Setup

Here's what the infrastructure looks like in code ([molecule_wrapper.py:85-157](../proteinblender/core/molecule_wrapper.py#L85-L157)):

```python
def _setup_protein_domain_infrastructure(self):
    """Set up the Multi_Boolean_OR and NOT node infrastructure for domains."""
    parent_node_group = self.molecule.object.modifiers["MolecularNodes"].node_group

    # Create multi-input OR node group
    multi_or_group = nodes.create_multi_boolean_or()

    # Create the join node using our custom group
    self.domain_join_node = parent_node_group.nodes.new("GeometryNodeGroup")
    self.domain_join_node.node_tree = multi_or_group
    self.domain_join_node.name = "Domain_Boolean_Join"

    # Create final NOT node after the join node
    final_not = parent_node_group.nodes.new("FunctionNodeBooleanMath")
    final_not.operation = 'NOT'
    final_not.name = "Domain_Final_Not"

    # Connect OR output to NOT input
    parent_node_group.links.new(self.domain_join_node.outputs["Result"], final_not.inputs[0])

    # Connect NOT output to style Selection
    parent_node_group.links.new(final_not.outputs["Boolean"], main_style_node.inputs["Selection"])

    # Track join nodes and final NOT node
    self.join_nodes = [self.domain_join_node]
    self.final_not = final_not
```

### Domain Mask Node Creation

When a domain is created, mask nodes are added to the parent network ([molecule_wrapper.py:2102-2249](../proteinblender/core/molecule_wrapper.py#L2102-L2249)):

```python
def _create_domain_mask_nodes(self, domain_id: str, chain_id: str, start: int, end: int):
    """Create nodes in the parent molecule to mask out the domain region"""
    parent_node_group = self.molecule.object.modifiers["MolecularNodes"].node_group

    # Create chain selection node
    chain_select = nodes.add_custom(parent_node_group, chain_select_group.name)
    chain_select.name = f"Domain_Chain_Select_{domain_id}"

    # Configure chain selection
    blender_chain_id = self.get_blender_chain_id(chain_id)
    for input_socket in chain_select.inputs:
        if input_socket.name == blender_chain_id:
            input_socket.default_value = True

    # Create residue range selection node
    res_select = nodes.add_custom(parent_node_group, "Select Res ID Range")
    res_select.name = f"Domain_Res_Select_{domain_id}"
    res_select.inputs["Min"].default_value = start
    res_select.inputs["Max"].default_value = end

    # Connect chain select to res select
    parent_node_group.links.new(chain_select.outputs["Selection"], res_select.inputs["And"])

    # Find next available input on the join node
    last_join = self.join_nodes[-1]
    available_input = None
    for i in range(1, 9):
        input_name = f"Input_{i}"
        if input_name in last_join.inputs and not last_join.inputs[input_name].is_linked:
            available_input = input_name
            break

    # Handle overflow if all slots are filled
    if available_input is None:
        # Create a new multi-boolean OR for overflow
        overflow_join = parent_node_group.nodes.new("GeometryNodeGroup")
        overflow_join.node_tree = overflow_group
        parent_node_group.links.new(last_join.outputs["Result"], overflow_join.inputs["Input_1"])
        self.join_nodes.append(overflow_join)
        last_join = overflow_join

    # Connect residue selection to the join input
    parent_node_group.links.new(res_select.outputs["Selection"], last_join.inputs[available_input])

    # Store the nodes for future reference
    self.domain_mask_nodes[domain_id] = (chain_select, res_select)
```

---

## Chain Deletion Flow

### High-Level Process

```
User clicks "Delete Chain" in UI
    ↓
MOLECULE_PB_OT_delete_chain.invoke() - Show confirmation dialog
    ↓
MOLECULE_PB_OT_delete_chain.execute()
    ↓
Capture molecule state for undo
    ↓
Find all domains belonging to chain
    ↓
For each domain:
    │
    ├─> DomainDefinition.cleanup()
    │   ├─> Remove domain Blender object
    │   ├─> Remove domain node group
    │   └─> Remove custom node trees
    │
    └─> Delete from molecule.domains dictionary
    ↓
Remove chain from puppet group memberships
    ↓
Rebuild outliner hierarchy
    ↓
Report success to user
```

### Detailed Operator Implementation

The chain deletion operator is defined in [molecule_operators.py:740-829](../proteinblender/operators/molecule_operators.py#L740-L829):

```python
class MOLECULE_PB_OT_delete_chain(Operator):
    """Delete a chain and all its domains from a protein"""
    bl_idname = "molecule.delete_chain"
    bl_label = "Delete Chain"
    bl_description = "Delete this chain and all its domains"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: StringProperty()
    molecule_id: StringProperty()

    def invoke(self, context, event):
        # Show confirmation dialog
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Capture state for undo
        scene_manager._capture_molecule_state(self.molecule_id)

        # Find all domains belonging to this chain
        domains_to_delete = []
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(self.chain_id):
                domains_to_delete.append(domain_id)

        if not domains_to_delete:
            self.report({'WARNING'}, f"No domains found for chain {self.chain_id}")
            return {'CANCELLED'}

        # Delete each domain using cleanup
        for domain_id in domains_to_delete:
            domain = molecule.domains[domain_id]
            # Call cleanup to remove object and node groups
            domain.cleanup()
            # Remove from molecule's domains dictionary
            del molecule.domains[domain_id]

        # Remove chain from puppet memberships
        self._remove_chain_from_puppets(context, self.molecule_id, self.chain_id)

        # Rebuild outliner
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)

        self.report({'INFO'}, f"Deleted chain {self.chain_id} and {len(domains_to_delete)} domain(s)")
        return {'FINISHED'}
```

### Puppet Membership Cleanup

When a chain is deleted, it must also be removed from any puppet groups that reference it ([molecule_operators.py:793-828](../proteinblender/operators/molecule_operators.py#L793-L828)):

```python
def _remove_chain_from_puppets(self, context, molecule_id, chain_id):
    """Remove chain from any puppet group memberships"""
    chain_outliner_id = f"{molecule_id}_chain_{chain_id}"

    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(molecule_id)

    # Collect all domain IDs for this chain
    domain_ids_in_chain = []
    for domain_id, domain in molecule.domains.items():
        if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(chain_id):
            domain_ids_in_chain.append(domain_id)

    # Remove from puppet memberships
    for item in context.scene.outliner_items:
        if item.item_type == 'PUPPET' and item.puppet_memberships:
            members = set(item.puppet_memberships.split(','))
            modified = False

            # Remove chain outliner ID
            if chain_outliner_id in members:
                members.remove(chain_outliner_id)
                modified = True

            # Remove any domain IDs from this chain
            for domain_id in domain_ids_in_chain:
                if domain_id in members:
                    members.remove(domain_id)
                    modified = True

            if modified:
                item.puppet_memberships = ','.join(members) if members else ""
```

---

## Domain Deletion Mechanisms

### Two Types of Domain Deletion

ProteinBlender supports two modes of domain deletion:

1. **Normal Deletion** - Interactive deletion with merging logic
2. **Cleanup Deletion** - Direct deletion during molecule cleanup

### Normal Domain Deletion

The `delete_domain()` method ([molecule_wrapper.py:1421-1565](../proteinblender/core/molecule_wrapper.py#L1421-L1565)) handles interactive domain deletion with intelligent merging:

```python
def delete_domain(self, domain_id: str, is_cleanup_call: bool = False) -> Optional[str]:
    """Delete a domain and its object.

    If the domain is the only one on its chain, deletion is prevented.
    If multiple domains exist on the chain, deleting one will cause an adjacent
    domain to expand and fill the gap.

    Args:
        domain_id: The ID of the domain to delete.
        is_cleanup_call: True if called during full molecule cleanup.

    Returns:
        The ID of the domain that filled the gap, if any.
    """
    if domain_id not in self.domains:
        return None

    # During cleanup, just delete directly without merging
    if is_cleanup_call:
        self._delete_domain_direct(domain_id)
        return None

    # Normal deletion logic with merging...
    domain_to_delete = self.domains[domain_id]
    chain_id = domain_to_delete.chain_id

    # Count domains on the same chain
    domains_on_this_chain = []
    for d_id, d_obj in self.domains.items():
        if d_obj.chain_id == chain_id:
            domains_on_this_chain.append((d_id, d_obj))

    # Prevent deleting the last domain on a chain
    if len(domains_on_this_chain) <= 1:
        print(f"Cannot delete the last domain on chain {chain_id}")
        return None

    # Find adjacent domains for merging
    domain_before = None  # Domain ending at start - 1
    domain_after = None   # Domain starting at end + 1

    for adj_id, adj_domain in domains_on_this_chain:
        if adj_id == domain_id:
            continue
        if adj_domain.end == domain_to_delete.start - 1:
            domain_before = (adj_id, adj_domain)
        elif adj_domain.start == domain_to_delete.end + 1:
            domain_after = (adj_id, adj_domain)

    # Determine merge strategy
    if domain_before and domain_after:
        # A - B(delete) - C: Expand A to cover B, C remains
        update_target_id = domain_before[0]
        new_end = domain_to_delete.end
    elif domain_before:
        # A - B(delete): Expand A to cover B
        update_target_id = domain_before[0]
        new_end = domain_to_delete.end
    elif domain_after:
        # B(delete) - C: Expand C to cover B
        update_target_id = domain_after[0]
        new_start = domain_to_delete.start

    # Delete the domain
    self._delete_domain_direct(domain_id)

    # Expand adjacent domain if found
    if update_target_id and update_target_id in self.domains:
        self.update_domain(update_target_id, chain_id, new_start, new_end)

    # Reparent child domains
    self._reparent_child_domains(children_to_reparent, update_target_id)

    return update_target_id
```

### Direct Domain Deletion

The `_delete_domain_direct()` method ([molecule_wrapper.py:2465-2474](../proteinblender/core/molecule_wrapper.py#L2465-L2474)) performs the actual deletion:

```python
def _delete_domain_direct(self, domain_id: str):
    """Internal method to delete a domain without adjusting adjacent domains"""
    # Delete domain mask nodes in parent molecule
    self._delete_domain_mask_nodes(domain_id)

    # Clean up domain object and node group
    self.domains[domain_id].cleanup()

    # Remove from domains dictionary
    del self.domains[domain_id]
```

### DomainDefinition Cleanup

The `DomainDefinition.cleanup()` method ([domain.py:241-302](../proteinblender/core/domain.py#L241-L302)) handles geometry and node removal:

```python
def cleanup(self):
    """Remove domain object and node group"""
    try:
        # Clean up object
        if self.object:
            # Clean up node groups first
            if self.object.modifiers:
                for modifier in self.object.modifiers:
                    if modifier.type == 'NODES' and modifier.node_group:
                        try:
                            node_group = modifier.node_group
                            if node_group and node_group.name in bpy.data.node_groups:
                                bpy.data.node_groups.remove(node_group, do_unlink=True)
                        except ReferenceError:
                            pass

            # Store object data
            obj_data = self.object.data

            # Remove object
            if self.object.name in bpy.data.objects:
                bpy.data.objects.remove(self.object, do_unlink=True)

            # Clean up object data if no other users
            if obj_data and obj_data.users == 0:
                if isinstance(obj_data, bpy.types.Mesh):
                    bpy.data.meshes.remove(obj_data, do_unlink=True)

            self.object = None

        # Clean up node group
        if self.node_group:
            try:
                if self.node_group.name in bpy.data.node_groups:
                    bpy.data.node_groups.remove(self.node_group, do_unlink=True)
            except ReferenceError:
                pass
            self.node_group = None

        # Clean up any custom node trees
        for node_group in list(bpy.data.node_groups):
            try:
                if node_group.name.startswith(f"Color Common_{self.domain_id}"):
                    bpy.data.node_groups.remove(node_group, do_unlink=True)
            except ReferenceError:
                pass

        # Reset properties
        self._setup_complete = False
        self.object_name = ""
        self.node_group_name = ""

    except Exception as e:
        print(f"Error during domain cleanup: {str(e)}")
        import traceback
        traceback.print_exc()
```

---

## Node Network Cleanup

### Mask Node Deletion

The `_delete_domain_mask_nodes()` method ([molecule_wrapper.py:1380-1419](../proteinblender/core/molecule_wrapper.py#L1380-L1419)) removes domain-specific mask nodes from the parent network:

```python
def _delete_domain_mask_nodes(self, domain_id: str):
    """Delete mask nodes for a domain in the parent molecule's node group"""
    if domain_id not in self.domain_mask_nodes:
        return

    nodes_to_remove = self.domain_mask_nodes[domain_id]

    # Get the parent molecule's node group
    parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
    if not parent_modifier or not parent_modifier.node_group:
        return

    parent_node_group = parent_modifier.node_group

    # Remove only the links connected to these specific nodes
    for link in list(parent_node_group.links):
        for node in nodes_to_remove:
            try:
                if node and (link.from_node == node or link.to_node == node):
                    parent_node_group.links.remove(link)
                    break
            except ReferenceError:
                continue

    # Remove the nodes safely
    for node in nodes_to_remove:
        try:
            if node:
                if node.name in parent_node_group.nodes:
                    parent_node_group.nodes.remove(parent_node_group.nodes[node.name])
        except ReferenceError:
            pass

    # Remove from tracking dictionary
    del self.domain_mask_nodes[domain_id]

    # Note: Infrastructure nodes (join node and NOT node) persist for future domain creations
```

**Important Note:** The infrastructure nodes (Domain_Boolean_Join and Domain_Final_Not) are NOT removed when individual domains are deleted. They persist to support future domain creation without needing to rebuild the infrastructure.

### Full Molecule Cleanup

When an entire molecule is deleted, the `cleanup()` method ([molecule_wrapper.py:1647-1677](../proteinblender/core/molecule_wrapper.py#L1647-L1677)) removes all domains and infrastructure:

```python
def cleanup(self):
    """Remove all domains and clean up resources"""
    # First clean up all domains
    for domain_id in list(self.domains.keys()):
        self.delete_domain(domain_id, is_cleanup_call=True)

    # Clean up domain infrastructure nodes in parent molecule
    if self.molecule and self.molecule.object:
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if parent_modifier and parent_modifier.node_group:
            parent_node_group = parent_modifier.node_group

            # List of infrastructure node instances to remove
            infra_node_instances_to_remove = []

            # Gather all join nodes (primary and overflows)
            if hasattr(self, 'join_nodes'):
                for node_instance in self.join_nodes:
                    if node_instance and node_instance.name in parent_node_group.nodes:
                        if node_instance not in infra_node_instances_to_remove:
                            infra_node_instances_to_remove.append(node_instance)

            # Gather the final_not node
            if hasattr(self, 'final_not') and self.final_not:
                if self.final_not.name in parent_node_group.nodes:
                    if self.final_not not in infra_node_instances_to_remove:
                        infra_node_instances_to_remove.append(self.final_not)

            # Remove infrastructure nodes
            for node_instance in infra_node_instances_to_remove:
                try:
                    parent_node_group.nodes.remove(node_instance)
                except (ReferenceError, KeyError):
                    pass
```

---

## Edge Cases and Special Handling

### 1. Last Domain on Chain

**Problem:** Deleting the last domain on a chain would leave the chain with no representation.

**Solution:** The UI prevents this action, but `delete_domain()` also checks and blocks deletion:

```python
if len(domains_on_this_chain) <= 1 and not is_cleanup_call:
    print(f"Cannot delete the last domain on chain {chain_id}")
    bpy.ops.wm.call_message_box(
        message=f"Cannot delete the last domain ({domain_name}) on chain {chain_id}.",
        title="Deletion Prevented",
        icon='ERROR'
    )
    return None
```

### 2. Child Domain Reparenting

**Problem:** When a parent domain is deleted, its child domains need a new parent.

**Solution:** Children inherit the deleted domain's parent ([molecule_wrapper.py:1567-1578](../proteinblender/core/molecule_wrapper.py#L1567-L1578)):

```python
def _reparent_child_domains(self, child_domain_ids: List[str], new_parent_id: Optional[str]):
    """Reparent child domains to a new parent

    When a parent domain is deleted, its children inherit the parent's parent.
    If no parent exists in the hierarchy, children are parented to the original protein.
    """
    if not child_domain_ids:
        return

    for child_id in child_domain_ids:
        if child_id in self.domains:
            self.domains[child_id].parent_domain_id = new_parent_id
```

### 3. Domain Name Normalization

**Problem:** After deletion, remaining domains may need name updates (e.g., "Domain_A" instead of "Domain_A_1").

**Solution:** After deletion, names of all domains on the affected chain are normalized:

```python
# Re-normalize names of all remaining domains on the affected chain
for d_id, d_obj in self.domains.items():
    if d_obj.chain_id == affected_chain_id:
        self._normalize_domain_name(d_id)
```

### 4. Overflow Join Node Handling

**Problem:** When domains fill all 8 input slots of a join node, additional domains require overflow nodes.

**Solution:** Overflow join nodes are created dynamically and chained:

```python
if available_input is None:
    # Create a new multi-boolean OR for overflow
    overflow_join = parent_node_group.nodes.new("GeometryNodeGroup")
    overflow_join.node_tree = overflow_group
    # Chain previous join result into new join's first input
    parent_node_group.links.new(last_join.outputs["Result"], overflow_join.inputs["Input_1"])
    # Reconnect final_not to take input from the new join
    parent_node_group.links.new(overflow_join.outputs["Result"], self.final_not.inputs[0])
    self.join_nodes.append(overflow_join)
```

### 5. Reference Errors

**Problem:** Blender nodes can become invalid (freed) during deletion, causing `ReferenceError`.

**Solution:** All node removal code wraps operations in try-except blocks:

```python
try:
    if node and node.name in parent_node_group.nodes:
        parent_node_group.nodes.remove(node)
except ReferenceError:
    # Node already freed, skip
    pass
```

---

## Code Examples

### Example 1: Deleting a Chain from the UI

In the Protein Outliner panel ([protein_outliner_panel.py](../proteinblender/panels/protein_outliner_panel.py)):

```python
# In the UI layout, display a delete button for chains
if item.item_type == 'CHAIN':
    op = row.operator("molecule.delete_chain", text="", icon='TRASH')
    op.chain_id = item.chain_id
    op.molecule_id = item.molecule_id
```

### Example 2: Programmatic Chain Deletion

```python
import bpy
from proteinblender.utils.scene_manager import ProteinBlenderScene

# Get the scene manager
scene_manager = ProteinBlenderScene.get_instance()

# Get the molecule
molecule = scene_manager.molecules.get("my_protein_id")

# Find all domains on chain A
domains_to_delete = []
for domain_id, domain in molecule.domains.items():
    if domain.chain_id == "A":
        domains_to_delete.append(domain_id)

# Delete each domain
for domain_id in domains_to_delete:
    domain = molecule.domains[domain_id]
    domain.cleanup()
    del molecule.domains[domain_id]

# Rebuild the outliner
from proteinblender.utils.scene_manager import build_outliner_hierarchy
build_outliner_hierarchy(bpy.context)
```

### Example 3: Creating a Custom Deletion Operator

```python
import bpy
from bpy.types import Operator
from bpy.props import StringProperty

class MY_OT_delete_chain_silent(Operator):
    """Delete a chain without confirmation dialog"""
    bl_idname = "my.delete_chain_silent"
    bl_label = "Delete Chain (No Confirm)"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: StringProperty()
    molecule_id: StringProperty()

    def execute(self, context):
        from proteinblender.utils.scene_manager import ProteinBlenderScene

        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Capture state for undo
        scene_manager._capture_molecule_state(self.molecule_id)

        # Find and delete all domains on this chain
        domains_to_delete = [
            domain_id for domain_id, domain in molecule.domains.items()
            if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(self.chain_id)
        ]

        for domain_id in domains_to_delete:
            molecule.domains[domain_id].cleanup()
            del molecule.domains[domain_id]

        # Rebuild outliner
        from proteinblender.utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)

        self.report({'INFO'}, f"Deleted {len(domains_to_delete)} domains")
        return {'FINISHED'}
```

### Example 4: Querying Node Network State

```python
def inspect_domain_mask_nodes(molecule_wrapper):
    """Print information about domain mask nodes"""
    print(f"Domain mask nodes for {molecule_wrapper.identifier}:")

    for domain_id, (chain_node, res_node) in molecule_wrapper.domain_mask_nodes.items():
        print(f"  Domain {domain_id}:")
        print(f"    Chain Select: {chain_node.name}")
        print(f"    Res Select: {res_node.name}")
        print(f"    Residue Range: {res_node.inputs['Min'].default_value} - {res_node.inputs['Max'].default_value}")

    print(f"\nJoin nodes: {len(molecule_wrapper.join_nodes)}")
    for i, join_node in enumerate(molecule_wrapper.join_nodes):
        print(f"  Join {i+1}: {join_node.name}")

    if molecule_wrapper.final_not:
        print(f"\nFinal NOT node: {molecule_wrapper.final_not.name}")
```

---

## Summary

Chain deletion in ProteinBlender is a coordinated process that:

1. **Identifies** all domains belonging to the chain
2. **Cleans up** each domain's Blender object and node group
3. **Removes** domain-specific mask nodes from the parent molecule's network
4. **Preserves** the infrastructure nodes for future domain creation
5. **Updates** puppet memberships to remove deleted entities
6. **Rebuilds** the outliner hierarchy for UI consistency
7. **Supports** undo/redo through state capture

The system is designed to handle edge cases gracefully, including:
- Preventing deletion of the last domain on a chain
- Reparenting child domains when parents are deleted
- Handling node reference errors during cleanup
- Managing overflow join nodes for large numbers of domains
- Normalizing domain names after deletions

This architecture ensures that chain deletions are safe, reversible, and maintain the integrity of the parent molecule's node network.
