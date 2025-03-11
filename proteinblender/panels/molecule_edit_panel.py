import bpy
from bpy.types import Panel

class MOLECULE_PB_PT_edit(Panel):
    bl_label = "Molecule Settings"
    bl_idname = "MOLECULE_PB_PT_edit"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        # Check if property exists before accessing it
        return hasattr(context.scene, "show_molecule_edit_panel") and context.scene.show_molecule_edit_panel
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            return
            
        # Create settings UI
        box = layout.box()
        
        # Identifier editor
        row = box.row(align=True)
        if scene.edit_molecule_identifier == "":
            scene.edit_molecule_identifier = molecule.identifier
        row.prop(scene, "edit_molecule_identifier", text="Identifier")
        row.operator("molecule.update_identifier", text="", icon='CHECKMARK')
        
        box.separator()
        
        # Style selector
        row = box.row()
        row.prop(molecule.object.mn, "import_style", text="Style")
        
        # Visibility toggle
        row = box.row()
        row.prop(molecule.object, "hide_viewport", text="Visible", icon='HIDE_OFF' if not molecule.object.hide_viewport else 'HIDE_OFF')
        
        # Add more molecule-specific settings here 