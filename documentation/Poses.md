# Pose System

## Overview

A **pose** in ProteinBlender is a saved configuration that captures the spatial arrangement of protein groups (collections of chains and/or domains). Poses are fundamental to the animation workflow, allowing users to save, manage, and transition between different protein conformations.

### What is a Pose?

A pose consists of:
1. **Groups**: Specific collections of protein chains and/or domains
2. **Positions**: Spatial coordinates (location, rotation, scale) of objects in selected groups
3. **Metadata**: Name and list of included groups

### Why Group-Based?

The current implementation uses a **group-based system** rather than molecule-based:
- **Simplicity**: Poses work directly with groups without molecule dependencies
- **Flexibility**: Any groups in the scene can be included in a pose
- **Clarity**: Direct group-to-pose relationship, no complex validation needed

## Current Implementation

### Scene-Level Storage

Poses are stored at the scene level in `bpy.context.scene.pose_library`. Each pose captures transforms for all objects in selected groups.

### User Interface

The **Pose Library Panel** provides a grid-based interface with pose cards showing:
- Pose name
- Groups included
- Screenshot placeholder
- Action buttons (Apply, Capture, Delete)

## Usage Guide

### Creating a Pose

1. **Create groups** using the Group Maker panel
2. **Position groups** as desired in the viewport
3. **Click "Create Pose"** button
4. **Select which groups** to include in the pose
5. **Name the pose** and save

### Applying a Pose

1. **Click "Apply"** button on a pose card
2. Objects are moved to their saved positions
3. Scene updates immediately

### Updating a Pose (Capturing New Positions)

1. **Adjust group positions** in the viewport
2. **Click "Capture"** button on the existing pose
3. Current positions overwrite stored positions

## Technical Implementation

### Files

- **Panel**: `proteinblender/panels/pose_library_panel.py`
- **Properties**: `proteinblender/properties/pose_props.py`
- **Registration**: `proteinblender/panels/__init__.py` and `proteinblender/addon.py`

### Operators

- **`proteinblender.create_pose`**: Select groups and save their positions
- **`proteinblender.apply_pose`**: Restore groups to saved positions
- **`proteinblender.capture_pose`**: Update pose with current positions
- **`proteinblender.delete_pose`**: Remove pose from library

## Implementation History

### Evolution: Domain-Based → Group-Based

**Original Design (deprecated):**
- Poses tied to specific molecules
- Required molecule selection to function
- Complex dual-system architecture
- Alpha carbon relative positioning

**Current Design (simplified):**
- Poses work directly with groups
- No molecule selection required
- Scene-level pose storage
- Direct group-to-pose relationship
- World-space transforms (simpler, more flexible)

## Future Enhancements

1. **Actual Screenshot Thumbnails**: Capture viewport images instead of placeholders
2. **Group Editing**: Modify which groups are included in a pose after creation
3. **Interpolation**: Smooth transitions between poses for animation
4. **Import/Export**: Share pose libraries between projects
5. **Better Object Resolution**: Improve how group members map to Blender objects

## Glossary

- **Pose**: A saved configuration of group positions
- **Group**: A collection of protein chains and/or domains (also called "puppet")
- **Transform**: Location, rotation, and scale of an object
- **Capture**: Save current object positions to a pose
- **Apply**: Restore objects to positions stored in a pose
