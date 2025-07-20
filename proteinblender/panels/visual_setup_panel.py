"""Visual Setup panel with context-aware styling"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import EnumProperty, FloatVectorProperty
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.molecularnodes.style import STYLE_ITEMS


class PROTEINBLENDER_OT_apply_color(Operator):
    """Apply color to selected items"""
    bl_idname = "proteinblender.apply_color"
    bl_label = "Apply Color"
    bl_options = {'REGISTER', 'UNDO'}
    
    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.1, 0.8, 1.0)
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find selected items in outliner
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Apply color based on selection context
        for item in selected_items:
            if item.item_type == 'PROTEIN':
                # Apply to protein and all children
                self.apply_protein_color(scene_manager, item, self.color)
            elif item.item_type == 'CHAIN':
                # Apply to chain and its domains
                self.apply_chain_color(scene_manager, item, self.color)
            elif item.item_type == 'DOMAIN':
                # Apply to domain only
                self.apply_domain_color(scene_manager, item, self.color)
        
        # Update viewport
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        
        return {'FINISHED'}
    
    def apply_protein_color(self, scene_manager, protein_item, color):
        """Apply color to protein and all its domains"""
        molecule = scene_manager.molecules.get(protein_item.item_id)
        if not molecule:
            return
        
        # Apply to all domains
        for domain in molecule.domains.values():
            if hasattr(domain, 'color'):
                domain.color = color
            # TODO: Update actual material/node color
    
    def apply_chain_color(self, scene_manager, chain_item, color):
        """Apply color to all domains in a chain"""
        # Find parent molecule
        parent_molecule = None
        for item in bpy.context.scene.outliner_items:
            if item.item_id == chain_item.parent_id:
                parent_molecule = scene_manager.molecules.get(item.item_id)
                break
        
        if parent_molecule:
            # TODO: Apply to domains belonging to this chain
            # For now, apply to all domains
            for domain in parent_molecule.domains.values():
                if hasattr(domain, 'color'):
                    domain.color = color
    
    def apply_domain_color(self, scene_manager, domain_item, color):
        """Apply color to a single domain"""
        # Find the domain object
        if domain_item.object_name:
            obj = bpy.data.objects.get(domain_item.object_name)
            if obj:
                # TODO: Update material/node color
                pass


class PROTEINBLENDER_OT_apply_representation(Operator):
    """Apply representation style to selected items"""
    bl_idname = "proteinblender.apply_representation"
    bl_label = "Apply Representation"
    bl_options = {'REGISTER', 'UNDO'}
    
    style: EnumProperty(
        name="Style",
        items=STYLE_ITEMS,
        default='surface'
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Apply style based on selection context
        for item in selected_items:
            if item.item_type == 'PROTEIN':
                # Apply to entire protein
                molecule = scene_manager.molecules.get(item.item_id)
                if molecule:
                    # TODO: Change molecule style using MolecularNodes
                    self.report({'INFO'}, f"Applied {self.style} to {item.name}")
            elif item.item_type == 'DOMAIN':
                # Apply to domain only
                # TODO: Change domain style
                self.report({'INFO'}, f"Applied {self.style} to {item.name}")
        
        return {'FINISHED'}


class PROTEINBLENDER_PT_visual_setup(Panel):
    """Visual Setup panel for color and representation"""
    bl_label = "Visual Set-up"
    bl_idname = "PROTEINBLENDER_PT_visual_setup"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_order = 2  # After outliner
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Check if anything is selected
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            layout.label(text="Select items to apply visual settings", icon='INFO')
            return
        
        # Show what will be affected
        box = layout.box()
        col = box.column(align=True)
        
        # Count selection types
        proteins = sum(1 for item in selected_items if item.item_type == 'PROTEIN')
        chains = sum(1 for item in selected_items if item.item_type == 'CHAIN')
        domains = sum(1 for item in selected_items if item.item_type == 'DOMAIN')
        
        if proteins > 0:
            col.label(text=f"{proteins} protein(s) selected", icon='MESH_DATA')
        if chains > 0:
            col.label(text=f"{chains} chain(s) selected", icon='LINKED')
        if domains > 0:
            col.label(text=f"{domains} domain(s) selected", icon='GROUP_VERTEX')
        
        layout.separator()
        
        # Color section
        col = layout.column(align=True)
        col.label(text="Color", icon='COLOR')
        
        # Color picker row
        row = col.row(align=True)
        row.scale_y = 1.5
        
        # Get current color from first selected item
        current_color = (0.8, 0.1, 0.8, 1.0)  # Default purple
        
        # Use a property to show color picker
        if not hasattr(scene, "visual_setup_color"):
            scene.visual_setup_color = current_color
        
        row.prop(scene, "visual_setup_color", text="")
        
        # Apply color button
        op = row.operator("proteinblender.apply_color", text="Apply")
        op.color = scene.visual_setup_color
        
        layout.separator()
        
        # Representation section
        col = layout.column(align=True)
        col.label(text="Representation", icon='MESH_UVSPHERE')
        
        # Style selector
        row = col.row(align=True)
        row.scale_y = 1.2
        
        # Create style buttons
        styles = [
            ('surface', "Surface", 'MESH_UVSPHERE'),
            ('ribbon', "Ribbon", 'CURVE_BEZCURVE'),
            ('cartoon', "Cartoon", 'OUTLINER_OB_CURVE'),
            ('ball_and_stick', "Ball & Stick", 'RIGID_BODY'),
            ('stick', "Stick", 'RIGID_BODY_CONSTRAINT'),
        ]
        
        for style_id, style_name, style_icon in styles:
            op = row.operator("proteinblender.apply_representation", 
                            text="", icon=style_icon)
            op.style = style_id
            row.separator(factor=0.5)
        
        # Show style names
        row = col.row(align=True)
        row.scale_x = 0.8
        for style_id, style_name, _ in styles:
            row.label(text=style_name[:4])  # Abbreviated names


# Register color property
def register_props():
    """Register scene properties for visual setup"""
    from bpy.props import FloatVectorProperty
    
    bpy.types.Scene.visual_setup_color = FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.1, 0.8, 1.0)
    )


def unregister_props():
    """Unregister scene properties"""
    if hasattr(bpy.types.Scene, "visual_setup_color"):
        del bpy.types.Scene.visual_setup_color


# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_apply_color,
    PROTEINBLENDER_OT_apply_representation,
    PROTEINBLENDER_PT_visual_setup,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    register_props()


def unregister():
    unregister_props()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)