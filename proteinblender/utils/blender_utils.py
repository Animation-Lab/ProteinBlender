"""Centralized Blender object reference utilities.

This module provides safe wrappers for Blender object references that can
become invalid after undo/redo operations. It centralizes all object
validation and reference healing logic to avoid duplication throughout
the codebase.
"""

import bpy
from typing import Optional, TypeVar, Generic

T = TypeVar('T')


def is_object_valid(obj: Optional[bpy.types.Object]) -> bool:
    """Check if a Blender object reference is still valid.

    Object references can become invalid after undo/redo operations.
    This function safely checks if the reference is still usable.

    Args:
        obj: The Blender object reference to check

    Returns:
        True if the object exists and is accessible, False otherwise
    """
    if obj is None:
        return False
    try:
        # Accessing .name will raise ReferenceError if object was freed
        return obj.name in bpy.data.objects
    except (ReferenceError, AttributeError):
        return False


def is_node_group_valid(ng: Optional[bpy.types.NodeTree]) -> bool:
    """Check if a node group reference is still valid.

    Args:
        ng: The node group reference to check

    Returns:
        True if the node group exists and is accessible, False otherwise
    """
    if ng is None:
        return False
    try:
        return ng.name in bpy.data.node_groups
    except (ReferenceError, AttributeError):
        return False


def get_object_safe(
    obj: Optional[bpy.types.Object],
    stored_name: str = ""
) -> Optional[bpy.types.Object]:
    """Get a valid object reference, healing from stored name if needed.

    This function first checks if the existing reference is valid.
    If not, it attempts to recover the object by looking up its stored name.

    Args:
        obj: The potentially stale object reference
        stored_name: The object's name to use for recovery

    Returns:
        A valid object reference, or None if recovery failed
    """
    if is_object_valid(obj):
        return obj
    if stored_name and stored_name in bpy.data.objects:
        return bpy.data.objects[stored_name]
    return None


def get_node_group_safe(
    ng: Optional[bpy.types.NodeTree],
    stored_name: str = ""
) -> Optional[bpy.types.NodeTree]:
    """Get a valid node group reference, healing from stored name if needed.

    Args:
        ng: The potentially stale node group reference
        stored_name: The node group's name to use for recovery

    Returns:
        A valid node group reference, or None if recovery failed
    """
    if is_node_group_valid(ng):
        return ng
    if stored_name and stored_name in bpy.data.node_groups:
        return bpy.data.node_groups[stored_name]
    return None


class ObjectRef:
    """Safe wrapper for Blender object references with automatic healing.

    This class wraps a Blender object reference and stores the object's name.
    When the reference becomes invalid (e.g., after undo/redo), it can
    automatically recover the object by looking it up by name.

    Example:
        ref = ObjectRef(my_object)
        # ... undo/redo happens ...
        obj = ref.get()  # Returns valid object or None

    Attributes:
        name: The stored object name for recovery
    """

    __slots__ = ('_name', '_cached_obj')

    def __init__(self, obj: Optional[bpy.types.Object] = None, name: str = ""):
        """Initialize ObjectRef with an object and/or name.

        Args:
            obj: Optional Blender object to wrap
            name: Optional name to use (defaults to obj.name if obj provided)
        """
        self._cached_obj: Optional[bpy.types.Object] = obj
        if name:
            self._name = name
        elif obj:
            try:
                self._name = obj.name
            except (ReferenceError, AttributeError):
                self._name = ""
        else:
            self._name = ""

    @property
    def name(self) -> str:
        """Get the stored object name."""
        return self._name

    @name.setter
    def name(self, value: str):
        """Set the stored object name."""
        self._name = value

    def get(self) -> Optional[bpy.types.Object]:
        """Get a valid object reference, healing if necessary.

        Returns:
            A valid object reference, or None if the object doesn't exist
        """
        if is_object_valid(self._cached_obj):
            return self._cached_obj

        # Attempt to heal from stored name
        if self._name and self._name in bpy.data.objects:
            self._cached_obj = bpy.data.objects[self._name]
            return self._cached_obj

        self._cached_obj = None
        return None

    def set(self, obj: Optional[bpy.types.Object]):
        """Set the object reference and update stored name.

        Args:
            obj: The new object to reference
        """
        self._cached_obj = obj
        if obj:
            try:
                self._name = obj.name
            except (ReferenceError, AttributeError):
                pass

    def is_valid(self) -> bool:
        """Check if this reference points to a valid object.

        Returns:
            True if get() would return a valid object
        """
        return self.get() is not None

    def heal(self) -> bool:
        """Attempt to heal the reference from stored name.

        This forces a refresh of the cached object from bpy.data.objects.

        Returns:
            True if a valid object was found, False otherwise
        """
        self._cached_obj = None  # Force refresh
        return self.get() is not None

    def update_name(self):
        """Update stored name from current object.

        Call this after renaming an object to keep the stored name in sync.
        """
        obj = self.get()
        if obj:
            try:
                self._name = obj.name
            except (ReferenceError, AttributeError):
                pass

    def __bool__(self) -> bool:
        """Allow truthiness check on the reference."""
        return self.is_valid()

    def __repr__(self) -> str:
        """String representation for debugging."""
        valid = self.is_valid()
        return f"ObjectRef(name='{self._name}', valid={valid})"


class NodeGroupRef:
    """Safe wrapper for Blender node group references with automatic healing.

    Similar to ObjectRef but for node groups (bpy.types.NodeTree).
    """

    __slots__ = ('_name', '_cached_ng')

    def __init__(self, ng: Optional[bpy.types.NodeTree] = None, name: str = ""):
        """Initialize NodeGroupRef with a node group and/or name.

        Args:
            ng: Optional node group to wrap
            name: Optional name to use (defaults to ng.name if ng provided)
        """
        self._cached_ng: Optional[bpy.types.NodeTree] = ng
        if name:
            self._name = name
        elif ng:
            try:
                self._name = ng.name
            except (ReferenceError, AttributeError):
                self._name = ""
        else:
            self._name = ""

    @property
    def name(self) -> str:
        """Get the stored node group name."""
        return self._name

    @name.setter
    def name(self, value: str):
        """Set the stored node group name."""
        self._name = value

    def get(self) -> Optional[bpy.types.NodeTree]:
        """Get a valid node group reference, healing if necessary."""
        if is_node_group_valid(self._cached_ng):
            return self._cached_ng

        if self._name and self._name in bpy.data.node_groups:
            self._cached_ng = bpy.data.node_groups[self._name]
            return self._cached_ng

        self._cached_ng = None
        return None

    def set(self, ng: Optional[bpy.types.NodeTree]):
        """Set the node group reference and update stored name."""
        self._cached_ng = ng
        if ng:
            try:
                self._name = ng.name
            except (ReferenceError, AttributeError):
                pass

    def is_valid(self) -> bool:
        """Check if this reference points to a valid node group."""
        return self.get() is not None

    def heal(self) -> bool:
        """Attempt to heal the reference from stored name."""
        self._cached_ng = None
        return self.get() is not None

    def __bool__(self) -> bool:
        return self.is_valid()

    def __repr__(self) -> str:
        valid = self.is_valid()
        return f"NodeGroupRef(name='{self._name}', valid={valid})"


def refresh_ui_areas(area_types: tuple = ('PROPERTIES', 'VIEW_3D')):
    """Force a redraw of specified UI area types.

    Args:
        area_types: Tuple of area type strings to refresh
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in area_types:
                    area.tag_redraw()
    except (AttributeError, RuntimeError):
        # Context may not be available during certain operations
        pass


def safe_remove_object(obj: bpy.types.Object, remove_data: bool = True):
    """Safely remove a Blender object and optionally its data.

    Args:
        obj: The object to remove
        remove_data: If True, also remove the object's mesh/data if unused
    """
    if not is_object_valid(obj):
        return

    try:
        # Store data reference before removing object
        obj_data = obj.data if remove_data else None

        # Remove the object
        bpy.data.objects.remove(obj, do_unlink=True)

        # Remove orphaned data
        if obj_data and obj_data.users == 0:
            if isinstance(obj_data, bpy.types.Mesh):
                bpy.data.meshes.remove(obj_data, do_unlink=True)
    except (ReferenceError, RuntimeError) as e:
        print(f"Warning: Could not fully remove object: {e}")


def safe_remove_node_group(ng: bpy.types.NodeTree):
    """Safely remove a node group.

    Args:
        ng: The node group to remove
    """
    if not is_node_group_valid(ng):
        return

    try:
        bpy.data.node_groups.remove(ng, do_unlink=True)
    except (ReferenceError, RuntimeError) as e:
        print(f"Warning: Could not remove node group: {e}")
