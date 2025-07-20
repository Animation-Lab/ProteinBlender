from bpy.types import Panel
from ..utils.scene_manager import ProteinBlenderScene

class MOLECULE_PB_PT_poses(Panel):
    bl_label = "Protein Poses"
    bl_idname = "MOLECULE_PB_PT_poses"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        # Show panel only when a molecule is selected
        return hasattr(context.scene, "selected_molecule_id") and context.scene.selected_molecule_id
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            layout.label(text="No molecule selected", icon='INFO')
            return
            
        # Get molecule item
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            layout.label(text="Molecule not found in list", icon='ERROR')
            return
        
        # Create pose management UI
        box = layout.box()
        box.label(text=f"Poses for {molecule.identifier}", icon='ARMATURE_DATA')
        
        # Create New Pose button
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("molecule.create_pose", text="Create Pose From Current State", icon='ADD')
        
        # If no poses, show message and return
        if len(molecule_item.poses) == 0:
            box.label(text="No poses saved", icon='INFO')
            return
        
        # Show pose list with actions
        box.separator()
        row = box.row()
        row.label(text="Saved Poses:")
        
        # List of poses with management options
        for idx, pose in enumerate(molecule_item.poses):
            # Create box for each pose
            pose_box = box.box()
            row = pose_box.row(align=True)
            
            # Pose selection/name
            name_row = row.row()
            name_row.operator(
                "molecule.apply_pose", 
                text=pose.name,
                depress=(idx == molecule_item.active_pose_index)
            ).pose_index = str(idx)
            
            # Make pose active when clicked
            name_row.context_pointer_set("molecule_item", molecule_item)
            
            # If this is the active pose, create action buttons
            if idx == molecule_item.active_pose_index:
                # Buttons for active pose
                action_row = row.row(align=True)
                action_row.operator("molecule.rename_pose", text="", icon='GREASEPENCIL')
                action_row.operator("molecule.delete_pose", text="", icon='X')
                
                # Add "Apply and Keyframe" button
                keyframe_row = pose_box.row()
                keyframe_row.scale_y = 1.1
                keyframe_op = keyframe_row.operator(
                    "molecule.apply_pose_and_keyframe", 
                    text="Apply Pose and Keyframe", 
                    icon='KEYFRAME'
                )
                keyframe_op.pose_index = str(idx)
                
                # Show domain transforms count
                info_row = pose_box.row()
                info_row.label(text=f"Contains transforms for {len(pose.domain_transforms)} domains")

# List of panel classes to be registered
CLASSES = [
    MOLECULE_PB_PT_poses,
] 