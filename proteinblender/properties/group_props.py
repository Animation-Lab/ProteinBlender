"""Group properties for ProteinBlender.

This module defines the properties for managing groups of proteins, chains, and domains.
"""

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, CollectionProperty, IntProperty
from bpy.types import PropertyGroup


class GroupMember(PropertyGroup):
    """A member of a protein group."""
    identifier: StringProperty(
        name="Identifier",
        description="Unique identifier of the group member"
    )
    type: EnumProperty(
        name="Type",
        items=[
            ('PROTEIN', 'Protein', 'A protein/molecule'),
            ('CHAIN', 'Chain', 'A chain within a protein'),
            ('DOMAIN', 'Domain', 'A domain within a chain')
        ]
    )
    name: StringProperty(
        name="Name",
        description="Display name of the member"
    )
    parent_id: StringProperty(
        name="Parent ID",
        description="Identifier of the parent (for chains and domains)"
    )


class ProteinGroup(PropertyGroup):
    """A group containing proteins, chains, or domains."""
    name: StringProperty(
        name="Group Name",
        default="Group",
        description="Name of the group"
    )
    members: CollectionProperty(
        type=GroupMember,
        name="Members",
        description="Members of this group"
    )
    is_expanded: BoolProperty(
        name="Expanded",
        default=True,
        description="Whether the group is expanded in the outliner"
    )
    group_id: StringProperty(
        name="Group ID",
        description="Unique identifier for the group"
    )
    
    def add_member(self, identifier, member_type, name, parent_id=""):
        """Add a member to the group."""
        member = self.members.add()
        member.identifier = identifier
        member.type = member_type
        member.name = name
        member.parent_id = parent_id
        return member
    
    def remove_member(self, identifier):
        """Remove a member from the group by identifier."""
        for i, member in enumerate(self.members):
            if member.identifier == identifier:
                self.members.remove(i)
                return True
        return False
    
    def has_member(self, identifier):
        """Check if a member with the given identifier exists in the group."""
        for member in self.members:
            if member.identifier == identifier:
                return True
        return False
    
    def clear_members(self):
        """Remove all members from the group."""
        self.members.clear()


def generate_group_id():
    """Generate a unique group ID."""
    import uuid
    return f"group_{uuid.uuid4().hex[:8]}"


def create_new_group(context, name="New Group"):
    """Create a new protein group."""
    scene = context.scene
    if not hasattr(scene, 'pb_groups'):
        return None
    
    group = scene.pb_groups.add()
    group.name = name
    group.group_id = generate_group_id()
    group.is_expanded = True
    
    return group


def get_group_by_id(context, group_id):
    """Get a group by its ID."""
    scene = context.scene
    if not hasattr(scene, 'pb_groups'):
        return None
    
    for group in scene.pb_groups:
        if group.group_id == group_id:
            return group
    
    return None


def get_group_by_name(context, name):
    """Get a group by its name."""
    scene = context.scene
    if not hasattr(scene, 'pb_groups'):
        return None
    
    for group in scene.pb_groups:
        if group.name == name:
            return group
    
    return None


def update_outliner_for_groups(context):
    """Update the outliner to include groups."""
    scene = context.scene
    outliner_state = scene.protein_outliner_state
    
    if not hasattr(scene, 'pb_groups'):
        return
    
    # Remove old groups from outliner
    items_to_remove = []
    for i, item in enumerate(outliner_state.items):
        if item.type == 'GROUP':
            # Check if this group still exists
            group_exists = False
            for group in scene.pb_groups:
                if group.group_id == item.identifier:
                    group_exists = True
                    break
            if not group_exists:
                items_to_remove.append(i)
    
    # Remove in reverse order to maintain indices
    for i in reversed(items_to_remove):
        outliner_state.items.remove(i)
    
    # Add or update groups in the outliner
    for group in scene.pb_groups:
        # Check if group already exists in outliner
        group_exists = False
        group_index = -1
        
        for i, item in enumerate(outliner_state.items):
            if item.type == 'GROUP' and item.identifier == group.group_id:
                group_exists = True
                group_index = i
                # Update name if changed
                item.name = group.name
                item.is_expanded = group.is_expanded
                break
        
        if not group_exists:
            # Add new group to outliner at the end
            item = outliner_state.items.add()
            item.name = group.name
            item.identifier = group.group_id
            item.type = 'GROUP'
            item.is_expanded = group.is_expanded
            item.depth = 0
            item.is_selected = False
            item.is_visible = True
            group_index = len(outliner_state.items) - 1
        
        # Add group members as children in the outliner (if expanded)
        if group.is_expanded and len(group.members) > 0:
            # First, remove any existing child entries for this group
            children_to_remove = []
            for i in range(group_index + 1, len(outliner_state.items)):
                item = outliner_state.items[i]
                if item.depth == 0:  # Hit next top-level item
                    break
                if f"_group_{group.group_id}" in item.identifier:
                    children_to_remove.append(i)
            
            for i in reversed(children_to_remove):
                outliner_state.items.remove(i)
            
            # Add members as children
            insert_index = group_index + 1
            for member in group.members:
                # Create a group-specific entry
                child_item = outliner_state.items.add()
                child_item.name = member.name
                child_item.identifier = f"{member.identifier}_group_{group.group_id}"
                child_item.type = member.type
                child_item.depth = 1 if member.type in ['PROTEIN', 'CHAIN'] else 2
                child_item.is_selected = False
                child_item.is_visible = True
                
                # Move to correct position
                outliner_state.items.move(len(outliner_state.items) - 1, insert_index)
                insert_index += 1


# Classes to register
CLASSES = [
    GroupMember,
    ProteinGroup,
]


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except:
            pass  # Already registered
    
    if not hasattr(bpy.types.Scene, "pb_groups"):
        bpy.types.Scene.pb_groups = CollectionProperty(type=ProteinGroup)
    
    # Add current group index for UI
    if not hasattr(bpy.types.Scene, "pb_group_index"):
        bpy.types.Scene.pb_group_index = IntProperty(
            name="Group Index",
            default=0,
            min=0
        )


def unregister():
    if hasattr(bpy.types.Scene, "pb_group_index"):
        del bpy.types.Scene.pb_group_index
    
    if hasattr(bpy.types.Scene, "pb_groups"):
        del bpy.types.Scene.pb_groups
    
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass