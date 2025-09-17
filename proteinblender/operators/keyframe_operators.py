"""Keyframe operators for animation functionality"""

import bpy
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, IntProperty, CollectionProperty, StringProperty
from ..utils.scene_manager import ProteinBlenderScene


class PuppetKeyframeSettings(PropertyGroup):
    """Property group for puppet keyframe settings"""
    puppet_id: StringProperty(name="Puppet ID")
    puppet_name: StringProperty(name="Puppet Name")
    controller_object_name: StringProperty(name="Controller Object")
    
    # Main checkbox to enable/disable this puppet
    use_puppet: BoolProperty(
        name="Use Puppet",
        description="Include this puppet in keyframing",
        default=False
    )
    
    # Transform checkboxes - all default to True
    keyframe_location: BoolProperty(
        name="Location",
        description="Keyframe puppet location (controller Empty)",
        default=True
    )
    keyframe_rotation: BoolProperty(
        name="Rotation", 
        description="Keyframe puppet rotation (controller Empty)",
        default=True
    )
    keyframe_scale: BoolProperty(
        name="Scale",
        description="Keyframe puppet scale (controller Empty)",
        default=True
    )
    keyframe_color: BoolProperty(
        name="Color",
        description="Keyframe domain colors",
        default=True
    )
    keyframe_pose: BoolProperty(
        name="Pose",
        description="Keyframe domain poses (relative positions within puppet)",
        default=True
    )


class PROTEINBLENDER_OT_create_keyframe(Operator):
    """Create keyframes for puppet animations"""
    bl_idname = "proteinblender.create_keyframe"
    bl_label = "Create Keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    frame_number: IntProperty(
        name="Frame",
        description="Frame number for keyframe",
        default=1,
        min=1
    )
    
    puppet_items: CollectionProperty(
        type=PuppetKeyframeSettings,
        name="Puppet Items",
        description="Collection of puppets to keyframe"
    )
    
    def remove_geometry_node_color_keyframes(self, obj, frame):
        """Remove color keyframes from the geometry nodes modifier and alpha from material"""
        # Find the MolecularNodes modifier
        mod = None
        for modifier in obj.modifiers:
            if modifier.type == 'NODES':
                mod = modifier
                break

        if not mod or not mod.node_group:
            return False

        node_tree = mod.node_group
        removed_rgb = False
        removed_alpha = False

        # Look for the Custom Combine Color node
        for node in node_tree.nodes:
            if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                # Remove keyframes from the RGB input values
                try:
                    node.inputs['Red'].keyframe_delete("default_value", frame=frame)
                    node.inputs['Green'].keyframe_delete("default_value", frame=frame)
                    node.inputs['Blue'].keyframe_delete("default_value", frame=frame)
                    removed_rgb = True
                except:
                    pass  # No keyframes to remove
                break

        # Remove alpha keyframe from the Style node's material
        style_node = None
        for node in node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                style_node = node
                break

        if style_node:
            material_input = style_node.inputs.get("Material")
            if material_input and material_input.default_value:
                mat = material_input.default_value
                if mat.use_nodes and mat.node_tree:
                    for mat_node in mat.node_tree.nodes:
                        if mat_node.type == 'BSDF_PRINCIPLED':
                            try:
                                # Remove keyframe from alpha value
                                mat_node.inputs['Alpha'].keyframe_delete("default_value", frame=frame)
                                removed_alpha = True
                            except:
                                pass  # No keyframe to remove
                            break

        if removed_rgb or removed_alpha:
            print(f"  ✗ Removed domain '{obj.name}' color keyframes")
            return True

        return False

    def keyframe_geometry_node_color(self, obj, frame):
        """Keyframe the color inputs in the geometry nodes modifier and alpha in material"""
        # Find the MolecularNodes modifier
        mod = None
        for modifier in obj.modifiers:
            if modifier.type == 'NODES':
                mod = modifier
                break

        if not mod or not mod.node_group:
            print(f"  Warning: No geometry nodes modifier found on {obj.name}")
            return False

        node_tree = mod.node_group
        keyframed_rgb = False
        keyframed_alpha = False

        # Look for the Custom Combine Color node that holds our color values
        for node in node_tree.nodes:
            if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                # Keyframe the RGB input values
                try:
                    # These are the actual properties that need to be keyframed
                    node.inputs['Red'].keyframe_insert("default_value", frame=frame)
                    node.inputs['Green'].keyframe_insert("default_value", frame=frame)
                    node.inputs['Blue'].keyframe_insert("default_value", frame=frame)
                    keyframed_rgb = True
                except Exception as e:
                    print(f"  Error keyframing RGB nodes for {obj.name}: {e}")
                break

        # If no Custom Combine Color node exists, try to get and store the color
        if not keyframed_rgb:
            from ..panels.visual_setup_panel import get_object_color, apply_color_to_object
            color = get_object_color(obj)
            if color:
                # Apply the color (this creates the Custom Combine Color node)
                apply_color_to_object(obj, color)
                # Now try to keyframe again
                for node in node_tree.nodes:
                    if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                        try:
                            node.inputs['Red'].keyframe_insert("default_value", frame=frame)
                            node.inputs['Green'].keyframe_insert("default_value", frame=frame)
                            node.inputs['Blue'].keyframe_insert("default_value", frame=frame)
                            keyframed_rgb = True
                        except Exception as e:
                            print(f"  Error keyframing RGB nodes for {obj.name}: {e}")
                        break

        # Now keyframe the alpha value in the Style node's material
        style_node = None
        for node in node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                style_node = node
                break

        if style_node:
            material_input = style_node.inputs.get("Material")
            if material_input and material_input.default_value:
                mat = material_input.default_value
                if mat.use_nodes and mat.node_tree:
                    for mat_node in mat.node_tree.nodes:
                        if mat_node.type == 'BSDF_PRINCIPLED':
                            try:
                                # Keyframe the alpha value
                                mat_node.inputs['Alpha'].keyframe_insert("default_value", frame=frame)
                                keyframed_alpha = True
                            except Exception as e:
                                print(f"  Error keyframing alpha for {obj.name}: {e}")
                            break

        if keyframed_rgb and keyframed_alpha:
            print(f"  ✓ Keyframed domain '{obj.name}' color (RGBA)")
        elif keyframed_rgb:
            print(f"  ✓ Keyframed domain '{obj.name}' color (RGB only)")
        elif keyframed_alpha:
            print(f"  ✓ Keyframed domain '{obj.name}' alpha only")
        else:
            print(f"  Warning: Could not keyframe color for {obj.name}")
            return False

        return True

    def get_puppet_objects(self, context, puppet_id):
        """Get all Blender objects that belong to a puppet group"""
        objects = []
        
        # Find puppet item
        puppet_item = None
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_id == puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    break
        
        if not puppet_item or not hasattr(puppet_item, 'puppet_memberships'):
            print(f"Debug: No puppet found or no memberships for puppet {puppet_id}")
            return objects
        
        if not puppet_item.puppet_memberships:
            print(f"Debug: Empty memberships for puppet {puppet_id}")
            return objects
        
        # Parse member IDs and find corresponding objects
        member_ids = puppet_item.puppet_memberships.split(',')
        print(f"Debug: Puppet '{puppet_item.name}' has members: {member_ids}")
        
        # Import scene manager to access molecules
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        for member_id in member_ids:
            # Member IDs are in format: molecule_id_domain_id
            if '_' in member_id:
                # Try to intelligently parse the member_id
                # First, check if it contains '_chain_'
                if '_chain_' in member_id:
                    # Split at '_chain_' to separate molecule_id from chain identifier
                    parts = member_id.rsplit('_chain_', 1)
                    mol_id = parts[0]
                    domain_id = 'chain_' + parts[1]
                else:
                    # For custom domains, find where molecule_id ends
                    import re
                    match = re.match(r'^(.+?_\d+)_(.+)$', member_id)
                    if match:
                        mol_id = match.group(1)
                        domain_id = match.group(2)
                    else:
                        # Fallback to splitting on last underscore
                        parts = member_id.rsplit('_', 1)
                        if len(parts) == 2:
                            mol_id = parts[0]
                            domain_id = parts[1]
                        else:
                            print(f"Debug: Could not parse member_id '{member_id}'")
                            continue
                
                print(f"Debug: Looking for mol_id='{mol_id}', domain_id='{domain_id}'")
                
                # Try to find the domain object
                if mol_id in scene_manager.molecules:
                    molecule = scene_manager.molecules[mol_id]
                    
                    # First try direct lookup
                    if domain_id in molecule.domains:
                        domain = molecule.domains[domain_id]
                        if domain.object:
                            objects.append(domain.object)
                            print(f"Debug: Found domain object '{domain.object.name}' for {member_id}")
                    else:
                        # If domain_id is like 'chain_4', try to find the matching domain
                        if domain_id.startswith('chain_'):
                            chain_index = domain_id.replace('chain_', '')
                            # Find domain that starts with mol_id_chainindex_
                            for dom_id, dom in molecule.domains.items():
                                if dom_id.startswith(f"{mol_id}_{chain_index}_"):
                                    if dom.object:
                                        objects.append(dom.object)
                                        print(f"Debug: Found chain object '{dom.object.name}' for {member_id}")
                                    break
            
            # Always check outliner items as fallback
            for item in context.scene.outliner_items:
                if item.item_id == member_id:
                    if item.object_name:
                        obj = bpy.data.objects.get(item.object_name)
                        if obj and obj not in objects:
                            objects.append(obj)
                            print(f"Debug: Found object via outliner '{obj.name}' for {member_id}")
                    break
        
        print(f"Debug: Total objects found for puppet: {len(objects)}")
        return objects
    
    def invoke(self, context, event):
        scene = context.scene
        
        # Clear previous items
        self.puppet_items.clear()
        
        # Set frame to current frame
        self.frame_number = scene.frame_current
        
        # Add all puppets from the outliner
        if hasattr(scene, 'outliner_items'):
            for item in scene.outliner_items:
                # Only include actual puppets (not separator)
                if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
                    # Only include puppets with a controller object
                    if item.controller_object_name:
                        puppet_item = self.puppet_items.add()
                        puppet_item.puppet_id = item.item_id
                        puppet_item.puppet_name = item.name
                        puppet_item.controller_object_name = item.controller_object_name
                        puppet_item.use_puppet = False  # Unchecked by default
                        puppet_item.keyframe_location = True
                        puppet_item.keyframe_rotation = True
                        puppet_item.keyframe_scale = True
                        puppet_item.keyframe_color = True
                        puppet_item.keyframe_pose = True
        
        # Show popup dialog
        return context.window_manager.invoke_props_dialog(self, width=500)
    
    def draw(self, context):
        layout = self.layout
        
        # Frame number input
        row = layout.row()
        row.label(text="Frame:")
        row.prop(self, "frame_number", text="")
        
        layout.separator()
        
        # Puppet rows
        box = layout.box()
        
        if not self.puppet_items:
            box.label(text="No puppets available", icon='INFO')
            box.label(text="Create puppets using the Puppet Maker first")
        else:
            # Create a subtle header with icons
            header_row = box.row(align=False)
            header_row.scale_y = 0.8
            header_row.label(text="")  # Empty space for checkbox column
            
            # Puppet name label - left aligned to match actual puppet names
            header_row.label(text="Puppet Name")
            
            # Spacer to push transform icons to the right
            header_row.separator(factor=2.0)
            
            # Transform type icons - Pose first (leftmost)
            header_row.label(text="", icon='ARMATURE_DATA')  # Pose icon
            header_row.label(text="", icon='CON_LOCLIKE')  # Location icon
            header_row.label(text="", icon='CON_ROTLIKE')  # Rotation icon
            header_row.label(text="", icon='CON_SIZELIKE')  # Scale icon
            header_row.label(text="", icon='COLOR')  # Color icon
            
            box.separator(factor=0.5)
            
            for item in self.puppet_items:
                row = box.row(align=False)
                row.scale_y = 1.2  # Make rows slightly taller for better readability
                
                # Checkbox for selecting the puppet
                row.prop(item, "use_puppet", text="")
                
                # Puppet name with icon
                name_col = row.column()
                name_col.alignment = 'LEFT'
                name_row = name_col.row(align=True)
                name_row.label(text=item.puppet_name, icon='GROUP')
                
                # Add spacer to push transform checkboxes to the right
                row.separator(factor=2.0)

                # Transform checkboxes - enabled only when puppet is selected
                # Pose first (leftmost)
                pose_row = row.row()
                pose_row.enabled = item.use_puppet
                pose_row.prop(item, "keyframe_pose", text="")

                loc_row = row.row()
                loc_row.enabled = item.use_puppet
                loc_row.prop(item, "keyframe_location", text="")

                rot_row = row.row()
                rot_row.enabled = item.use_puppet
                rot_row.prop(item, "keyframe_rotation", text="")

                scale_row = row.row()
                scale_row.enabled = item.use_puppet
                scale_row.prop(item, "keyframe_scale", text="")

                color_row = row.row()
                color_row.enabled = item.use_puppet
                color_row.prop(item, "keyframe_color", text="")
        
        layout.separator()
        
        # Select all/none buttons
        row = layout.row(align=True)
        row.operator("proteinblender.keyframe_select_all_puppets", text="Select All")
        row.operator("proteinblender.keyframe_select_none_puppets", text="Select None")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get selected puppets
        selected_puppets = [item for item in self.puppet_items if item.use_puppet]
        
        if not selected_puppets:
            self.report({'WARNING'}, "No puppets selected")
            return {'CANCELLED'}
        
        # Store current frame
        original_frame = scene.frame_current
        
        # Only change frame if necessary
        if original_frame != self.frame_number:
            scene.frame_set(self.frame_number)
        
        keyframed_puppets = []
        total_keyframed = 0
        
        for puppet_item in selected_puppets:
            puppet_name = puppet_item.puppet_name
            puppet_id = puppet_item.puppet_id
            
            print(f"\nProcessing puppet: {puppet_name}")
            
            # Get the Empty controller object
            controller_obj = None
            if puppet_item.controller_object_name:
                controller_obj = bpy.data.objects.get(puppet_item.controller_object_name)
                if not controller_obj:
                    print(f"  Warning: Controller object '{puppet_item.controller_object_name}' not found")
            
            # Get all domain objects belonging to this puppet
            domain_objects = self.get_puppet_objects(context, puppet_id)
            
            if not domain_objects and not controller_obj:
                print(f"  Warning: No objects found for puppet '{puppet_name}'")
                continue
            
            # Apply any active poses for the puppet's domains
            # This preserves domain arrangements
            for item in scene.molecule_list_items:
                if hasattr(item, 'active_pose_index') and hasattr(item, 'poses'):
                    if item.active_pose_index >= 0 and item.active_pose_index < len(item.poses):
                        active_pose = item.poses[item.active_pose_index]
                        
                        # Apply pose transforms to matching domains
                        for transform in active_pose.domain_transforms:
                            for domain_obj in domain_objects:
                                if domain_obj.name == transform.domain_id or \
                                   domain_obj.name.endswith(f"_{transform.domain_id}"):
                                    print(f"  Applying pose transform to {domain_obj.name}")
                                    domain_obj.location = transform.location
                                    domain_obj.rotation_euler = transform.rotation
                                    domain_obj.scale = transform.scale
            
            # Keyframe the Empty controller based on checkboxes
            # Only process if puppet is selected
            if controller_obj and puppet_item.use_puppet:
                keyframed_properties = []

                # Location
                if puppet_item.keyframe_location:
                    controller_obj.keyframe_insert(data_path="location", frame=self.frame_number)
                    keyframed_properties.append("location")
                    print(f"  ✓ Keyframed controller location at frame {self.frame_number}")
                else:
                    # Remove existing keyframe if checkbox is unchecked
                    try:
                        controller_obj.keyframe_delete(data_path="location", frame=self.frame_number)
                        print(f"  ✗ Removed controller location keyframe at frame {self.frame_number}")
                    except:
                        pass  # No keyframe exists to remove

                # Rotation
                if puppet_item.keyframe_rotation:
                    controller_obj.keyframe_insert(data_path="rotation_euler", frame=self.frame_number)
                    keyframed_properties.append("rotation")
                    print(f"  ✓ Keyframed controller rotation at frame {self.frame_number}")
                else:
                    # Remove existing keyframe if checkbox is unchecked
                    try:
                        controller_obj.keyframe_delete(data_path="rotation_euler", frame=self.frame_number)
                        print(f"  ✗ Removed controller rotation keyframe at frame {self.frame_number}")
                    except:
                        pass  # No keyframe exists to remove

                # Scale
                if puppet_item.keyframe_scale:
                    controller_obj.keyframe_insert(data_path="scale", frame=self.frame_number)
                    keyframed_properties.append("scale")
                    print(f"  ✓ Keyframed controller scale at frame {self.frame_number}")
                else:
                    # Remove existing keyframe if checkbox is unchecked
                    try:
                        controller_obj.keyframe_delete(data_path="scale", frame=self.frame_number)
                        print(f"  ✗ Removed controller scale keyframe at frame {self.frame_number}")
                    except:
                        pass  # No keyframe exists to remove

                if keyframed_properties:
                    print(f"  Controller: Keyframed {', '.join(keyframed_properties)}")
                    total_keyframed += 1
            
            # Keyframe domain relative transforms (local space) based on pose checkbox
            for domain_obj in domain_objects:
                if puppet_item.keyframe_pose:
                    # Keyframe local transforms when pose checkbox is checked
                    domain_obj.keyframe_insert(data_path="location", frame=self.frame_number)
                    domain_obj.keyframe_insert(data_path="rotation_euler", frame=self.frame_number)
                    domain_obj.keyframe_insert(data_path="scale", frame=self.frame_number)
                    print(f"  ✓ Keyframed domain '{domain_obj.name}' pose (local transforms)")
                else:
                    # Remove existing keyframes if pose checkbox is unchecked
                    try:
                        domain_obj.keyframe_delete(data_path="location", frame=self.frame_number)
                        domain_obj.keyframe_delete(data_path="rotation_euler", frame=self.frame_number)
                        domain_obj.keyframe_delete(data_path="scale", frame=self.frame_number)
                        print(f"  ✗ Removed domain '{domain_obj.name}' pose keyframes")
                    except:
                        pass  # No keyframes exist to remove
                
                # Keyframe color if requested
                if puppet_item.keyframe_color:
                    # Keyframe the actual geometry node color inputs
                    self.keyframe_geometry_node_color(domain_obj, self.frame_number)
                else:
                    # Remove color keyframes if checkbox is unchecked
                    self.remove_geometry_node_color_keyframes(domain_obj, self.frame_number)
                
                total_keyframed += 1
            
            keyframed_puppets.append(puppet_name)
        
        # Restore original frame
        if original_frame != self.frame_number:
            scene.frame_set(original_frame)
        
        if keyframed_puppets:
            puppet_names = ", ".join(keyframed_puppets)
            self.report({'INFO'}, f"Keyframed {total_keyframed} objects from puppets: {puppet_names} at frame {self.frame_number}")
        else:
            self.report({'WARNING'}, "No objects were keyframed")
        
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_all_puppets(Operator):
    """Select all puppets for keyframing"""
    bl_idname = "proteinblender.keyframe_select_all_puppets"
    bl_label = "Select All"
    
    def execute(self, context):
        # Get the active operator
        wm = context.window_manager
        if hasattr(wm, 'operators') and len(wm.operators) > 0:
            for op in reversed(wm.operators):
                if hasattr(op, 'bl_idname') and op.bl_idname == 'proteinblender.create_keyframe':
                    if hasattr(op, 'puppet_items'):
                        for item in op.puppet_items:
                            item.use_puppet = True
                            # Keep default transform settings
                        # Force a redraw
                        context.area.tag_redraw()
                    break
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_none_puppets(Operator):
    """Deselect all puppets"""
    bl_idname = "proteinblender.keyframe_select_none_puppets"
    bl_label = "Select None"
    
    def execute(self, context):
        # Get the active operator
        wm = context.window_manager
        if hasattr(wm, 'operators') and len(wm.operators) > 0:
            for op in reversed(wm.operators):
                if hasattr(op, 'bl_idname') and op.bl_idname == 'proteinblender.create_keyframe':
                    if hasattr(op, 'puppet_items'):
                        for item in op.puppet_items:
                            item.use_puppet = False
                        # Force a redraw
                        context.area.tag_redraw()
                    break
        return {'FINISHED'}


# Keep old operators for backwards compatibility but deprecated
class PROTEINBLENDER_OT_keyframe_select_all(Operator):
    """Deprecated - use keyframe_select_all_poses"""
    bl_idname = "proteinblender.keyframe_select_all"
    bl_label = "Select All (Deprecated)"
    
    def execute(self, context):
        return bpy.ops.proteinblender.keyframe_select_all_poses()


class PROTEINBLENDER_OT_keyframe_select_none(Operator):
    """Deprecated - use keyframe_select_none_poses"""
    bl_idname = "proteinblender.keyframe_select_none"
    bl_label = "Select None (Deprecated)"
    
    def execute(self, context):
        return bpy.ops.proteinblender.keyframe_select_none_poses()


def register():
    """Register keyframe operators and properties"""
    # PoseKeyframeSettings is now registered with the main CLASSES in __init__.py
    pass


def unregister():
    """Unregister keyframe operators and properties"""
    # PoseKeyframeSettings is now unregistered with the main CLASSES in __init__.py
    pass