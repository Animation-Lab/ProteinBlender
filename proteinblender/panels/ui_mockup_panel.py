import bpy
from bpy.types import Panel
from bpy.props import BoolProperty, EnumProperty, StringProperty, IntProperty

class PROTEIN_PB_PT_ui_mockup(Panel):
    bl_label = "ProteinBlender UI Mockup"
    bl_idname = "PROTEIN_PB_PT_ui_mockup"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = -100
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Add workspace creation button at the top
        workspace_box = layout.box()
        workspace_row = workspace_box.row()
        workspace_row.scale_y = 1.2
        workspace_row.operator("workspace.create_proteinblender_alt", text="Create ProteinBlenderAlt Workspace", icon='WORKSPACE')
        
        layout.separator()
        
        # ===== PROTEIN OUTLINER SECTION =====
        outliner_box = layout.box()
        outliner_header = outliner_box.row()
        outliner_header.label(text="Protein outliner", icon='OUTLINER')
        
        # Mock hierarchical structure
        outliner_content = outliner_box.column(align=True)
        
        # PDB #1
        pdb1_row = outliner_content.row(align=True)
        pdb1_row.prop(scene, "pdb1_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'pdb1_expanded', True) else 'TRIA_RIGHT', emboss=False)
        pdb1_row.label(text="PDB #1")
        pdb1_row.prop(scene, "pdb1_visible", text="", icon='HIDE_OFF')
        pdb1_row.prop(scene, "pdb1_selected", text="", icon='CHECKBOX_HLT')
        
        if getattr(scene, 'pdb1_expanded', True):
            # Chain A
            chain_a_row = outliner_content.row(align=True)
            chain_a_row.separator()
            chain_a_row.prop(scene, "chain_a_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'chain_a_expanded', True) else 'TRIA_RIGHT', emboss=False)
            chain_a_row.label(text="Chain A")
            chain_a_row.prop(scene, "chain_a_visible", text="", icon='HIDE_OFF')
            chain_a_row.prop(scene, "chain_a_selected", text="", icon='CHECKBOX_HLT')
            
            # Chain B
            chain_b_row = outliner_content.row(align=True)
            chain_b_row.separator()
            chain_b_row.prop(scene, "chain_b_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'chain_b_expanded', True) else 'TRIA_RIGHT', emboss=False)
            chain_b_row.label(text="Chain B")
            chain_b_row.prop(scene, "chain_b_visible", text="", icon='HIDE_OFF')
            chain_b_row.prop(scene, "chain_b_selected", text="", icon='CHECKBOX_HLT')
            
            if getattr(scene, 'chain_b_expanded', True):
                # Domains under Chain B
                for i, domain_name in enumerate(["Domain 1", "Domain 2", "Domain 3"]):
                    domain_row = outliner_content.row(align=True)
                    # Create indentation by adding empty space
                    domain_row.label(text="", icon='BLANK1')
                    domain_row.label(text="", icon='BLANK1')
                    domain_row.label(text=domain_name)
                    domain_row.prop(scene, f"domain_{i}_visible", text="", icon='HIDE_OFF')
                    domain_row.prop(scene, f"domain_{i}_selected", text="", icon='CHECKBOX_HLT')
        
        # PDB #2
        pdb2_row = outliner_content.row(align=True)
        pdb2_row.prop(scene, "pdb2_expanded", text="", icon='TRIA_RIGHT', emboss=False)
        pdb2_row.label(text="PDB #2")
        pdb2_row.prop(scene, "pdb2_visible", text="", icon='HIDE_OFF')
        pdb2_row.prop(scene, "pdb2_selected", text="", icon='CHECKBOX_DEHLT')
        
        layout.separator()
        
        # ===== VISUAL SET-UP SECTION =====
        visual_box = layout.box()
        visual_header = visual_box.row()
        visual_header.label(text="Visual Set-up", icon='MATERIAL')
        
        visual_content = visual_box.column(align=True)
        visual_row = visual_content.row(align=True)
        visual_row.prop(scene, "mockup_color_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'mockup_color_expanded', True) else 'TRIA_RIGHT', emboss=False)
        visual_row.label(text="Color")
        visual_row.prop(scene, "mockup_representation_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'mockup_representation_expanded', True) else 'TRIA_RIGHT', emboss=False)
        visual_row.label(text="Representation")
        
        layout.separator()
        
        # ===== DOMAIN MAKER SECTION =====
        domain_box = layout.box()
        domain_header = domain_box.row()
        domain_header.label(text="Domain Maker", icon='MOD_ARRAY')
        
        domain_content = domain_box.column(align=True)
        
        # Chain A selection
        chain_row = domain_content.row(align=True)
        chain_row.prop(scene, "chain_a_domain_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'chain_a_domain_expanded', True) else 'TRIA_RIGHT', emboss=False)
        chain_row.label(text="Chain A")
        
        if getattr(scene, 'chain_a_domain_expanded', True):
            # Split Chain controls
            split_row = domain_content.row(align=True)
            split_row.separator()
            split_row.prop(scene, "split_chain_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'split_chain_expanded', True) else 'TRIA_RIGHT', emboss=False)
            split_row.label(text="Split Chain")
            split_row.operator("mockup.split_chain", text="Split Chain", emboss=True)
            
            if getattr(scene, 'split_chain_expanded', True):
                # Amino Acids range
                amino_row = domain_content.row(align=True)
                amino_row.separator()
                amino_row.separator()
                amino_row.label(text="Amino Acids")
                amino_row.prop(scene, "amino_start", text="")
                amino_row.label(text="To")
                amino_row.prop(scene, "amino_end", text="")
                
                # Name Domain
                name_row = domain_content.row(align=True)
                name_row.separator()
                name_row.prop(scene, "name_domain_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'name_domain_expanded', True) else 'TRIA_RIGHT', emboss=False)
                name_row.label(text="Name Domain")
                name_row.prop(scene, "domain_name", text="")
        
        layout.separator()
        
        # ===== ANIMATION SET-UP SECTION =====
        anim_box = layout.box()
        anim_header = anim_box.row()
        anim_header.label(text="Animation Set-up", icon='ANIM')
        
        anim_content = anim_box.column(align=True)
        
        # Pivot controls
        pivot_row = anim_content.row(align=True)
        pivot_row.prop(scene, "pivot_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'pivot_expanded', True) else 'TRIA_RIGHT', emboss=False)
        pivot_row.label(text="Pivot")
        pivot_controls = pivot_row.row(align=True)
        pivot_controls.operator("mockup.move_pivot", text="Move Pivot")
        pivot_controls.operator("mockup.snap_to_center", text="Snap to Center")
        
        # Add Keyframe
        keyframe_row = anim_content.row(align=True)
        keyframe_row.prop(scene, "keyframe_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'keyframe_expanded', True) else 'TRIA_RIGHT', emboss=False)
        keyframe_row.label(text="Add Keyframe")
        
        # Brownian Motion checkbox - this was checked in the mockup
        brownian_row = anim_content.row(align=True)
        brownian_row.separator()
        brownian_row.prop(scene, "brownian_motion", text="Brownian Motion")
        
        # Create Pose section
        pose_row = anim_content.row(align=True)
        pose_row.prop(scene, "create_pose_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'create_pose_expanded', True) else 'TRIA_RIGHT', emboss=False)
        pose_row.label(text="Create Pose")
        
        if getattr(scene, 'create_pose_expanded', True):
            pose_content = anim_content.column(align=True)
            pose_content.separator()
            
            # Pose 1
            pose1_row = pose_content.row(align=True)
            pose1_row.separator()
            pose1_row.prop(scene, "pose1_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'pose1_expanded', True) else 'TRIA_RIGHT', emboss=False)
            pose1_row.label(text="Pose 1")
            
            # Pose 2
            pose2_row = pose_content.row(align=True)
            pose2_row.separator()
            pose2_row.prop(scene, "pose2_expanded", text="", icon='TRIA_DOWN' if getattr(scene, 'pose2_expanded', True) else 'TRIA_RIGHT', emboss=False)
            pose2_row.label(text="Pose 2")

        '''
        layout.separator()
    
        # ===== TIMELINE PLACEHOLDER =====
        timeline_box = layout.box()
        timeline_header = timeline_box.row()
        timeline_header.label(text="Timeline", icon='TIME')
        timeline_content = timeline_box.column()
        timeline_content.label(text="(Timeline visualization would go here)")
        timeline_content.label(text="• Summary")
        timeline_content.label(text="• PDB #1, PDB #2")
        timeline_content.label(text="• Chain A tracks")
        '''


# Mock operators for the buttons
class MOCKUP_OT_split_chain(bpy.types.Operator):
    bl_idname = "mockup.split_chain"
    bl_label = "Split Chain"
    bl_description = "Mock operator for splitting chain"
    
    def execute(self, context):
        self.report({'INFO'}, "Split Chain (mockup)")
        return {'FINISHED'}

class MOCKUP_OT_move_pivot(bpy.types.Operator):
    bl_idname = "mockup.move_pivot"
    bl_label = "Move Pivot"
    bl_description = "Mock operator for moving pivot"
    
    def execute(self, context):
        self.report({'INFO'}, "Move Pivot (mockup)")
        return {'FINISHED'}

class MOCKUP_OT_snap_to_center(bpy.types.Operator):
    bl_idname = "mockup.snap_to_center"
    bl_label = "Snap to Center"
    bl_description = "Mock operator for snapping to center"
    
    def execute(self, context):
        self.report({'INFO'}, "Snap to Center (mockup)")
        return {'FINISHED'}


def register_mockup_properties():
    """Register properties for the mockup panel"""
    # Protein outliner properties
    bpy.types.Scene.pdb1_expanded = BoolProperty(default=True)
    bpy.types.Scene.pdb1_visible = BoolProperty(default=True)
    bpy.types.Scene.pdb1_selected = BoolProperty(default=True)
    
    bpy.types.Scene.pdb2_expanded = BoolProperty(default=False)
    bpy.types.Scene.pdb2_visible = BoolProperty(default=True)
    bpy.types.Scene.pdb2_selected = BoolProperty(default=False)
    
    bpy.types.Scene.chain_a_expanded = BoolProperty(default=True)
    bpy.types.Scene.chain_a_visible = BoolProperty(default=True)
    bpy.types.Scene.chain_a_selected = BoolProperty(default=True)
    
    bpy.types.Scene.chain_b_expanded = BoolProperty(default=True)
    bpy.types.Scene.chain_b_visible = BoolProperty(default=True)
    bpy.types.Scene.chain_b_selected = BoolProperty(default=True)
    
    # Domain properties
    for i in range(3):
        setattr(bpy.types.Scene, f"domain_{i}_visible", BoolProperty(default=True))
        setattr(bpy.types.Scene, f"domain_{i}_selected", BoolProperty(default=False))
    
    # Visual setup properties
    bpy.types.Scene.mockup_color_expanded = BoolProperty(default=True)
    bpy.types.Scene.mockup_representation_expanded = BoolProperty(default=True)
    
    # Domain maker properties
    bpy.types.Scene.chain_a_domain_expanded = BoolProperty(default=True)
    bpy.types.Scene.split_chain_expanded = BoolProperty(default=True)
    bpy.types.Scene.name_domain_expanded = BoolProperty(default=True)
    bpy.types.Scene.amino_start = IntProperty(default=27, min=1)
    bpy.types.Scene.amino_end = IntProperty(default=98, min=1)
    bpy.types.Scene.domain_name = StringProperty(default="Domain 1")
    
    # Animation setup properties
    bpy.types.Scene.pivot_expanded = BoolProperty(default=True)
    bpy.types.Scene.keyframe_expanded = BoolProperty(default=True)
    bpy.types.Scene.brownian_motion = BoolProperty(default=True)  # Checked in mockup
    bpy.types.Scene.create_pose_expanded = BoolProperty(default=True)
    bpy.types.Scene.pose1_expanded = BoolProperty(default=True)
    bpy.types.Scene.pose2_expanded = BoolProperty(default=True)


def unregister_mockup_properties():
    """Unregister mockup properties"""
    props_to_remove = [
        'pdb1_expanded', 'pdb1_visible', 'pdb1_selected',
        'pdb2_expanded', 'pdb2_visible', 'pdb2_selected',
        'chain_a_expanded', 'chain_a_visible', 'chain_a_selected',
        'chain_b_expanded', 'chain_b_visible', 'chain_b_selected',
        'mockup_color_expanded', 'mockup_representation_expanded',
        'chain_a_domain_expanded', 'split_chain_expanded', 'name_domain_expanded',
        'amino_start', 'amino_end', 'domain_name',
        'pivot_expanded', 'keyframe_expanded', 'brownian_motion',
        'create_pose_expanded', 'pose1_expanded', 'pose2_expanded'
    ]
    
    for prop in props_to_remove:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    
    # Remove domain properties
    for i in range(3):
        for suffix in ['_visible', '_selected']:
            prop_name = f"domain_{i}{suffix}"
            if hasattr(bpy.types.Scene, prop_name):
                delattr(bpy.types.Scene, prop_name)


# Register the mockup properties when the module loads
register_mockup_properties()

CLASSES = [
    PROTEIN_PB_PT_ui_mockup,
    MOCKUP_OT_split_chain,
    MOCKUP_OT_move_pivot,
    MOCKUP_OT_snap_to_center,
] 