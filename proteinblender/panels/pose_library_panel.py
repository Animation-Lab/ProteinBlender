"""Pose Library Panel for ProteinBlender - Simplified Group-Based System"""

import json

import bpy
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, IntProperty, BoolProperty
from datetime import datetime


def get_puppet_protein_object(context, puppet_id):
    """The protein object a puppet was built from (its members' molecule).

    A puppet's controller is positioned relative to this protein so a pose can
    restore where the controller sits ON the protein, not only the chains
    around the controller. Resolves via the molecule of the puppet's first
    member chain. Returns None if it can't be determined (e.g. orphaned puppet)."""
    from ..utils.scene_manager import ProteinBlenderScene
    scene_manager = ProteinBlenderScene.get_instance()
    puppet = next((it for it in context.scene.outliner_items
                   if it.item_id == puppet_id and it.item_type == 'PUPPET'), None)
    if not puppet or not puppet.puppet_memberships:
        return None
    by_id = {it.item_id: it for it in context.scene.outliner_items}
    for member_id in puppet.puppet_memberships.split(','):
        member = by_id.get(member_id)
        mol_id = (member.parent_id if member and member.parent_id
                  else member_id.split('_chain_')[0])
        molecule = scene_manager.molecules.get(mol_id)
        if molecule and molecule.object:
            return molecule.object
    return None


def capture_controller_transform(context, pose, puppet_id, controller_obj):
    """Append a pose entry storing the puppet controller RELATIVE TO its parent
    protein, so applying the pose restores where the controller sits on the
    protein (the missing half of a pose — the chains relative to the controller
    are captured separately). No-op if the controller or protein can't be found."""
    if not controller_obj:
        return
    protein_obj = get_puppet_protein_object(context, puppet_id)
    if not protein_obj:
        return
    relative_matrix = protein_obj.matrix_world.inverted() @ controller_obj.matrix_world
    puppet_name = next((it.name for it in context.scene.outliner_items
                        if it.item_id == puppet_id and it.item_type == 'PUPPET'), puppet_id)
    t = pose.transforms.add()
    t.puppet_id = puppet_id
    t.puppet_name = puppet_name
    t.object_name = controller_obj.name
    t.is_controller = True
    t.protein_object_name = protein_obj.name
    t.location = relative_matrix.to_translation()
    t.rotation_euler = relative_matrix.to_euler()
    t.scale = relative_matrix.to_scale()


# ---------------------------------------------------------------------------
# Shared puppet/pose helpers
#
# These were previously duplicated as methods on the pose operators: three
# copies of get_puppet_objects (two byte-identical 118-line copies carrying ~45
# debug prints, plus this print-free variant) and two byte-identical copies of
# capture_pose_preview. None of them ever touched self. Keeping one copy means
# a pose is captured and applied through exactly the same resolution rules.
# ---------------------------------------------------------------------------

def get_puppet_objects(context, puppet_id):
    """Get all objects that belong to a puppet (for pose capture/validation).

    Delegates to the canonical :func:`get_puppet_member_objects` so pose
    capture resolves membership through exactly the same rules as keyframing
    and selection sync. Crucially, that helper resolves a CHAIN member via
    ``get_chain_objects``, which collects EVERY domain object of a chain that
    has been split into pieces - so a chain split AFTER the puppet was built
    still contributes all of its chunks to the pose. The previous local
    resolver matched split-domain keys (chain LETTER) against the member's
    chain INDEX and captured at most one piece, silently dropping the rest.
    """
    from ..utils.scene_manager import ProteinBlenderScene
    from ..utils.chain_utils import get_puppet_member_objects

    puppet_item = None
    if hasattr(context.scene, 'outliner_items'):
        for item in context.scene.outliner_items:
            if item.item_id == puppet_id and item.item_type == 'PUPPET':
                puppet_item = item
                break

    if not puppet_item or not puppet_item.puppet_memberships:
        return []

    scene_manager = ProteinBlenderScene.get_instance()
    return get_puppet_member_objects(context.scene, scene_manager, puppet_item)

def _puppet_item(context, puppet_id):
    return next((it for it in context.scene.outliner_items
                 if it.item_id == puppet_id and it.item_type == 'PUPPET'), None)


def _scene_puppets(context):
    """Every puppet in the scene, as ``{'id', 'name'}`` rows."""
    return [{'id': it.item_id, 'name': it.name}
            for it in getattr(context.scene, 'outliner_items', ())
            if it.item_type == 'PUPPET' and it.item_id != "puppets_separator"]


def capture_puppet(context, pose, puppet_id):
    """Record one puppet in ``pose``.

    Each member object is stored relative to the puppet's controller (or as
    its own transform when there is no controller), with its colour, and the
    controller itself relative to its protein.
    """
    from ..core.visual_style import get_object_color

    item = _puppet_item(context, puppet_id)
    puppet_name = item.name if item else puppet_id
    controller_obj = (bpy.data.objects.get(item.controller_object_name)
                      if item and item.controller_object_name else None)
    for obj in get_puppet_objects(context, puppet_id):
        transform = pose.transforms.add()
        transform.puppet_id = puppet_id
        transform.puppet_name = puppet_name
        transform.object_name = obj.name
        if controller_obj:
            relative_matrix = controller_obj.matrix_world.inverted() @ obj.matrix_world
            transform.location = relative_matrix.to_translation()
            transform.rotation_euler = relative_matrix.to_euler()
            transform.scale = relative_matrix.to_scale()
        else:
            transform.location = obj.location.copy()
            transform.rotation_euler = obj.rotation_euler.copy()
            transform.scale = obj.scale.copy()
        color = get_object_color(obj)
        transform.has_color = bool(color)
        if color:
            transform.color = color
    capture_controller_transform(context, pose, puppet_id, controller_obj)


def capture_filaments(context, pose):
    """Record the shape of every filament the pose's puppets hold.

    A filament's bend and its subunit count are not chain transforms, so
    without this a pose of a filament puppet kept neither.
    """
    from ..core import filament_animation

    objects = []
    for puppet_id in filter(None, pose.puppet_ids.split(',')):
        objects.extend(get_puppet_objects(context, puppet_id))
    states = {}
    for molecule in filament_animation.filaments_drawn_by(objects):
        state = filament_animation.capture_state(molecule)
        if state:
            states[molecule.identifier] = state
    pose.filament_states = json.dumps(states) if states else ""


def apply_filaments(pose) -> int:
    """Put back the filament shapes a pose recorded. Returns how many."""
    if not pose.filament_states:
        return 0
    from ..core import filament_animation
    from ..utils.scene_manager import ProteinBlenderScene

    try:
        states = json.loads(pose.filament_states)
    except ValueError:
        return 0
    molecules = ProteinBlenderScene.get_instance().molecules
    applied = 0
    for molecule_id, state in states.items():
        molecule = molecules.get(molecule_id)
        if molecule is not None and filament_animation.apply_state(molecule, state):
            applied += 1
    return applied


def capture_pose_preview(context, pose):
    """Capture a preview image for the pose"""
    try:
        import tempfile
        from pathlib import Path
        
        # Create temp directory for pose previews if it doesn't exist
        temp_dir = Path(tempfile.gettempdir()) / "proteinblender_poses"
        temp_dir.mkdir(exist_ok=True)
        
        # Generate filename based on pose name and timestamp
        import time
        timestamp = str(int(time.time()))
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in pose.name)
        preview_file = temp_dir / f"pose_{safe_name}_{timestamp}.png"
        
        # Store current render settings
        old_path = context.scene.render.filepath
        old_format = context.scene.render.image_settings.file_format
        old_res_x = context.scene.render.resolution_x
        old_res_y = context.scene.render.resolution_y
        old_percentage = context.scene.render.resolution_percentage
        
        # Configure render for thumbnail
        context.scene.render.filepath = str(preview_file)
        context.scene.render.image_settings.file_format = 'PNG'
        context.scene.render.resolution_x = 256
        context.scene.render.resolution_y = 256
        context.scene.render.resolution_percentage = 100
        
        # Render viewport preview
        bpy.ops.render.opengl(write_still=True, view_context=True)
        
        # Restore render settings
        context.scene.render.filepath = old_path
        context.scene.render.image_settings.file_format = old_format
        context.scene.render.resolution_x = old_res_x
        context.scene.render.resolution_y = old_res_y
        context.scene.render.resolution_percentage = old_percentage
        
        # Store the preview path in the pose
        pose.preview_path = str(preview_file)
        
        # Load the image into Blender's data so it's available for display
        # This must be done here, not during drawing
        try:
            # Check if image already exists and remove it
            img_name = f"pose_preview_{safe_name}"
            if img_name in bpy.data.images:
                old_img = bpy.data.images[img_name]
                bpy.data.images.remove(old_img)
            
            # Load the new image
            img = bpy.data.images.load(str(preview_file))
            img.name = img_name
            # Generate preview for UI display
            img.preview_ensure()
        except Exception as e:
            print(f"Warning: Could not load preview into Blender: {e}")
        
    except Exception as e:
        print(f"Warning: Could not capture pose preview: {e}")

class GroupSelectionItem(PropertyGroup):
    """Helper class to store puppet selection state"""
    puppet_id: StringProperty(name="Puppet ID")
    puppet_name: StringProperty(name="Puppet Name")
    selected: BoolProperty(name="Selected", default=False)


class PROTEINBLENDER_OT_create_pose(Operator):
    """Create a new pose from selected puppets"""
    bl_idname = "proteinblender.create_pose"
    bl_label = "Create Pose"
    bl_description = "Save current positions of selected puppets as a new pose"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_name: StringProperty(
        name="Pose Name",
        description="Name for the new pose",
        default="New Pose"
    )
    # Run without the dialog (scripts, tests): the puppets to include,
    # comma-separated. Empty includes every puppet.
    puppet_ids: StringProperty(name="Puppet IDs", default="",
                               options={'SKIP_SAVE', 'HIDDEN'})

    def invoke(self, context, event):
        # Set default pose name based on count
        pose_count = 0
        if hasattr(context.scene, 'pose_library'):
            pose_count = len(context.scene.pose_library)
        self.pose_name = f"Pose {pose_count + 1}"
        
        # Store available puppets as a simple list for this operator instance
        self.available_puppets = _scene_puppets(context)
        # Every puppet starts ticked.
        self.selected_puppets = {p['id']: True for p in self.available_puppets}
        
        if not self.available_puppets:
            self.report({'WARNING'}, "No puppets available. Create puppets first.")
            return {'CANCELLED'}
        
        # Store this instance for the toggle operator
        if not hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            PROTEINBLENDER_OT_create_pose._active_instances = {}
        PROTEINBLENDER_OT_create_pose._active_instances[str(id(self))] = self
        
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def draw(self, context):
        layout = self.layout
        
        # Pose name
        layout.prop(self, "pose_name")
        
        # Group selection with checkboxes
        layout.separator()
        layout.label(text="Select Groups to Include:", icon='GROUP')
        
        # Create a box for the puppet list
        box = layout.box()
        col = box.column(align=True)
        
        # Display each puppet as a checkbox using operator button toggles
        for puppet in self.available_puppets:
            row = col.row(align=True)
            # Use toggle buttons to simulate checkboxes
            icon = 'CHECKBOX_HLT' if self.selected_puppets.get(puppet['id'], False) else 'CHECKBOX_DEHLT'
            op = row.operator('proteinblender.toggle_puppet_selection', text=puppet['name'], icon=icon, emboss=False)
            op.puppet_id = puppet['id']
            op.operator_instance_id = str(id(self))  # Pass operator instance ID
        
        if not self.available_puppets:
            col.label(text="No puppets available", icon='INFO')
    
    def check(self, context):
        # This method is called when properties change
        return True
    
    def execute(self, context):
        scene = context.scene
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}

        available = getattr(self, 'available_puppets', None)
        if available is None:
            # Run without the dialog: tick what puppet_ids names, or all.
            available = _scene_puppets(context)
            wanted = set(filter(None, self.puppet_ids.split(',')))
            ticked = {p['id']: not wanted or p['id'] in wanted for p in available}
        else:
            ticked = self.selected_puppets
        chosen = [p for p in available if ticked.get(p['id'], False)]
        if not chosen:
            self.report({'WARNING'}, "No puppets selected. Please select at least one puppet.")
            return {'CANCELLED'}

        instances = getattr(PROTEINBLENDER_OT_create_pose, '_active_instances', {})
        instances.pop(str(id(self)), None)

        pose = scene.pose_library.add()
        pose.name = self.pose_name
        pose.puppet_ids = ','.join(p['id'] for p in chosen)
        pose.puppet_names = ', '.join(p['name'] for p in chosen)
        pose.created_timestamp = datetime.now().isoformat()
        pose.modified_timestamp = pose.created_timestamp
        for puppet in chosen:
            capture_puppet(context, pose, puppet['id'])
        capture_filaments(context, pose)
        capture_pose_preview(context, pose)

        if hasattr(scene, 'active_pose_index'):
            scene.active_pose_index = len(scene.pose_library) - 1
        self.report({'INFO'}, f"Created pose '{self.pose_name}' with {len(chosen)} puppet(s)")
        return {'FINISHED'}


class PROTEINBLENDER_OT_apply_pose(Operator):
    """Apply a saved pose to restore puppet positions"""
    bl_idname = "proteinblender.apply_pose"
    bl_label = "Apply Pose"
    bl_description = "Restore puppets to their saved positions in this pose"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_index: IntProperty(name="Pose Index", default=0)
    
    def execute(self, context):
        scene = context.scene

        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}

        if self.pose_index < 0 or self.pose_index >= len(scene.pose_library):
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}

        pose = scene.pose_library[self.pose_index]
        applied_count = 0
        not_found = []

        # Group transforms by puppet to find their controllers
        puppets = {}
        for transform in pose.transforms:
            puppets.setdefault(transform.puppet_id,
                               {'controller': None, 'transforms': []})
            puppets[transform.puppet_id]['transforms'].append(transform)

        # Find controller for each puppet
        for puppet_id in puppets:
            for item in scene.outliner_items:
                if item.item_id == puppet_id and item.item_type == 'PUPPET':
                    if item.controller_object_name:
                        controller_obj = bpy.data.objects.get(item.controller_object_name)
                        if controller_obj:
                            puppets[puppet_id]['controller'] = controller_obj
                            print(f"Debug: Found controller '{controller_obj.name}' for puppet {puppet_id}")
                    break

        # Restore each puppet CONTROLLER first, relative to its parent protein,
        # so the whole puppet returns to where it sat on the protein. The member
        # chains are then restored relative to the controller below. (Older poses
        # have no controller entry, so this pass is a no-op for them.)
        from mathutils import Matrix, Vector, Euler
        for puppet_id, puppet_data in puppets.items():
            controller_obj = puppet_data['controller']
            if not controller_obj:
                continue
            for transform in puppet_data['transforms']:
                if not transform.is_controller:
                    continue
                protein_obj = (bpy.data.objects.get(transform.protein_object_name)
                               if transform.protein_object_name else None)
                if protein_obj is None:
                    print(f"Debug: controller protein '{transform.protein_object_name}' "
                          f"not found; leaving controller in place")
                    continue
                relative_matrix = Matrix.Translation(Vector(transform.location))
                relative_matrix @= Euler(transform.rotation_euler).to_matrix().to_4x4()
                scale_matrix = Matrix()
                for i in range(3):
                    scale_matrix[i][i] = transform.scale[i]
                relative_matrix @= scale_matrix
                controller_obj.matrix_world = protein_obj.matrix_world @ relative_matrix
                print(f"Debug: Restored controller '{controller_obj.name}' relative to "
                      f"protein '{protein_obj.name}'")
        # Push the controller moves through so children read the NEW controller
        # world matrix when we restore them below.
        context.view_layer.update()

        # Apply transforms
        for puppet_id, puppet_data in puppets.items():
            controller_obj = puppet_data['controller']

            for transform in puppet_data['transforms']:
                if transform.is_controller:
                    continue  # already restored above (relative to the protein)
                print(f"Debug: Looking for object '{transform.object_name}'")
                obj = bpy.data.objects.get(transform.object_name)
                if obj:
                    print(f"Debug: Found object '{obj.name}'")

                    if controller_obj:
                        # Apply transforms RELATIVE to the puppet controller
                        from mathutils import Matrix, Vector, Euler, Quaternion

                        # Store the previous quaternion BEFORE applying the new pose
                        # This is needed to ensure shortest-path interpolation
                        prev_quat = None
                        if obj.rotation_mode == 'QUATERNION':
                            prev_quat = obj.rotation_quaternion.copy()

                        # Build the relative transformation matrix
                        relative_matrix = Matrix()
                        relative_matrix = Matrix.Translation(Vector(transform.location))
                        relative_matrix @= Euler(transform.rotation_euler).to_matrix().to_4x4()

                        # Apply scale
                        scale_matrix = Matrix()
                        for i in range(3):
                            scale_matrix[i][i] = transform.scale[i]
                        relative_matrix @= scale_matrix

                        # Apply relative to controller's current world position
                        world_matrix = controller_obj.matrix_world @ relative_matrix
                        obj.matrix_world = world_matrix
                        
                        # Ensure quaternion mode
                        if obj.rotation_mode != 'QUATERNION':
                            obj.rotation_mode = 'QUATERNION'
                        
                        # Ensure shortest path: if we have a previous quaternion,
                        # make sure the new one is on the same hemisphere
                        new_quat = obj.rotation_quaternion.copy()
                        if prev_quat is not None:
                            dot = prev_quat.dot(new_quat)
                            if dot < 0:
                                # Flip to same hemisphere as previous
                                obj.rotation_quaternion = Quaternion((-new_quat.w, -new_quat.x, -new_quat.y, -new_quat.z))
                    else:
                        # Fallback to absolute positioning if no controller
                        from mathutils import Quaternion, Euler
                        print(f"  WARNING: No controller found, applying absolute transform")
                        obj.location = transform.location
                        
                        # Convert to quaternion for consistent animation
                        if obj.rotation_mode != 'QUATERNION':
                            obj.rotation_mode = 'QUATERNION'
                        obj.rotation_quaternion = Euler(transform.rotation_euler).to_quaternion()
                        
                        # Normalize to positive W hemisphere
                        if obj.rotation_quaternion.w < 0:
                            q = obj.rotation_quaternion
                            obj.rotation_quaternion = Quaternion((-q.w, -q.x, -q.y, -q.z))
                        
                        obj.scale = transform.scale
                        print(f"  Applied absolute transform - new location: {list(obj.location)}")

                    # Apply color if available
                    if transform.has_color:
                        from ..core.visual_style import apply_color_to_object
                        apply_color_to_object(obj, transform.color)

                    applied_count += 1
                else:
                    print(f"Debug: Object '{transform.object_name}' NOT FOUND")
                    not_found.append(transform.object_name)

        if not_found:
            print(f"Apply Pose: objects no longer in the scene: {not_found}")

        # Filaments last: their copies are placed along a bend rig that hangs
        # off the molecule, so the chains must already stand where they will.
        context.view_layer.update()
        filaments = apply_filaments(pose)
        message = f"Applied pose '{pose.name}' ({applied_count}/{len(pose.transforms)} objects"
        if filaments:
            message += f", {filaments} filament shape{'s' if filaments > 1 else ''}"
        self.report({'INFO'}, message + ")")
        return {'FINISHED'}


class PROTEINBLENDER_OT_capture_pose(Operator):
    """Update pose with current puppet positions"""
    bl_idname = "proteinblender.capture_pose"
    bl_label = "Capture Pose"
    bl_description = "Update this pose with the current positions of its puppets"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_index: IntProperty(name="Pose Index", default=0)
    
    def execute(self, context):
        scene = context.scene
        
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        if self.pose_index < 0 or self.pose_index >= len(scene.pose_library):
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}
        
        pose = scene.pose_library[self.pose_index]
        
        pose.transforms.clear()
        for puppet_id in filter(None, pose.puppet_ids.split(',')):
            capture_puppet(context, pose, puppet_id)
        capture_filaments(context, pose)

        # Update timestamp
        pose.modified_timestamp = datetime.now().isoformat()
        
        # Update screenshot preview
        capture_pose_preview(context, pose)
        
        self.report({'INFO'}, f"Captured current positions for pose '{pose.name}'")
        return {'FINISHED'}
    
class PROTEINBLENDER_OT_delete_pose(Operator):
    """Delete a saved pose"""
    bl_idname = "proteinblender.delete_pose"
    bl_label = "Delete Pose"
    bl_description = "Remove this pose from the library"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_index: IntProperty(name="Pose Index", default=0)
    
    def invoke(self, context, event):
        # Show confirmation dialog
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        scene = context.scene
        
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        if self.pose_index < 0 or self.pose_index >= len(scene.pose_library):
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}
        
        pose_name = scene.pose_library[self.pose_index].name
        
        # Remove the pose
        scene.pose_library.remove(self.pose_index)
        
        # Adjust active index if needed
        if hasattr(scene, 'active_pose_index'):
            if scene.active_pose_index >= len(scene.pose_library):
                scene.active_pose_index = max(0, len(scene.pose_library) - 1)
        
        self.report({'INFO'}, f"Deleted pose '{pose_name}'")
        return {'FINISHED'}


# Placeholder operator to fix animation panel errors


class PROTEINBLENDER_PT_pose_library(Panel):
    """Panel for managing puppet poses"""
    bl_label = "Protein Pose Library"
    bl_idname = "PROTEINBLENDER_PT_pose_library"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 5  # Position after Group Maker
    
    # NO POLL METHOD - ALWAYS SHOW THE PANEL
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create a box for the entire panel content (matching other panels)
        main_box = layout.box()

        # Add panel title inside the box
        main_box.label(text="Protein Pose Library", icon='ARMATURE_DATA')
        main_box.separator()
        
        # ALWAYS SHOW THE CREATE BUTTON - NO CONDITIONS
        header_row = main_box.row()
        header_row.scale_y = 1.2
        header_row.operator("proteinblender.create_pose", text="Create Pose", icon='ADD')
        
        # Check if pose_library exists
        if not hasattr(scene, 'pose_library'):
            error_box = main_box.box()
            error_box.label(text="Pose system not initialized", icon='ERROR')
            return
        
        # Check if there are poses
        if not scene.pose_library or len(scene.pose_library) == 0:
            info_box = main_box.box()
            info_box.label(text="No poses saved yet", icon='INFO')
            info_box.label(text="Click 'Create Pose' to save puppet positions")
            return
        
        main_box.separator()
        
        # Grid layout for pose cards
        grid = main_box.grid_flow(
            row_major=True,
            columns=2,  # 2 columns for better fit
            even_columns=True,
            even_rows=False,
            align=True
        )
        
        # Display each pose as a card
        for idx, pose in enumerate(scene.pose_library):
            # Create a box for each pose
            pose_box = grid.box()
            pose_col = pose_box.column()
            
            # Header with pose name
            header = pose_col.row()
            active_idx = getattr(scene, 'active_pose_index', 0)
            header.label(text=pose.name, icon='LAYER_ACTIVE' if idx == active_idx else 'LAYER_USED')
            
            # Puppets label
            if pose.puppet_names:
                puppets_box = pose_col.box()
                puppets_box.scale_y = 0.8
                puppets_box.label(text="Puppets:", icon='ARMATURE_DATA')
                # Split long puppet lists into multiple lines
                puppet_names = pose.puppet_names.split(', ')
                for i in range(0, len(puppet_names), 2):
                    row = puppets_box.row()
                    row.scale_y = 0.8
                    row.label(text=', '.join(puppet_names[i:i+2]))
            
            # Screenshot preview
            screenshot_box = pose_col.box()
            
            # Try to display the preview image
            preview_shown = False
            
            # Look for the image in Blender's loaded images
            # The image should have been loaded when the pose was created
            if pose.preview_path:
                import os
                # Normalize the preview path for comparison
                preview_path_normalized = os.path.normpath(pose.preview_path)
                
                # Find image by comparing normalized paths
                for img in bpy.data.images:
                    # Skip images without filepath
                    if not img.filepath:
                        continue
                    
                    # Compare normalized paths
                    img_path_normalized = os.path.normpath(img.filepath)
                    
                    if preview_path_normalized == img_path_normalized:
                        # Found the image!
                        if img.preview and img.preview.icon_id > 0:
                            # Use template_icon for a single large preview
                            # This method is designed specifically for displaying large icons
                            screenshot_box.template_icon(icon_value=img.preview.icon_id, scale=5.0)
                            
                            preview_shown = True
                            break
            
            # If no preview shown, display placeholder with proper scaling
            if not preview_shown:
                # Use a centered layout with a large placeholder icon
                col = screenshot_box.column()
                col.alignment = 'CENTER'
                row = col.row()
                row.alignment = 'CENTER'
                row.scale_x = 3.0
                row.scale_y = 3.0
                row.label(text="", icon='IMAGE_DATA')
            
            # Action buttons
            button_row = pose_col.row(align=True)
            
            # Apply button
            apply_op = button_row.operator(
                "proteinblender.apply_pose",
                text="Apply"
            )
            apply_op.pose_index = idx
            
            # Update button (formerly Capture)
            capture_op = button_row.operator(
                "proteinblender.capture_pose",
                text="Update"
            )
            capture_op.pose_index = idx
            
            # Delete button with only trash icon
            delete_op = button_row.operator(
                "proteinblender.delete_pose",
                text="",
                icon='TRASH'
            )
            delete_op.pose_index = idx
            
            # Timestamp info
            if pose.modified_timestamp:
                info_row = pose_col.row()
                info_row.scale_y = 0.6
                info_row.label(text=f"Modified: {pose.modified_timestamp[:10]}")


class PROTEINBLENDER_OT_toggle_puppet_selection(Operator):
    """Toggle puppet selection in pose creation dialog"""
    bl_idname = "proteinblender.toggle_puppet_selection"
    bl_label = "Toggle Puppet Selection"
    bl_options = {'INTERNAL'}
    
    puppet_id: StringProperty()
    operator_instance_id: StringProperty()
    
    def execute(self, context):
        # Find the create_pose operator instance by ID
        if hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            instances = PROTEINBLENDER_OT_create_pose._active_instances
            if self.operator_instance_id in instances:
                instance = instances[self.operator_instance_id]
                # Toggle the selection state
                current = instance.selected_puppets.get(self.puppet_id, False)
                instance.selected_puppets[self.puppet_id] = not current
                # Force redraw
                for area in context.screen.areas:
                    area.tag_redraw()
                return {'FINISHED'}
        
        return {'CANCELLED'}


# Register classes

