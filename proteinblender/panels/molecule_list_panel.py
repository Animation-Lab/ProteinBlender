import bpy
from bpy.types import Panel, Operator
from bpy.props import StringProperty
from ..utils.scene_manager import ProteinBlenderScene

class MOLECULE_OT_select(Operator):
    bl_idname = "molecule.select"
    bl_label = "Select Molecule"
    bl_description = "Select this molecule"
    bl_order = 0
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        context.scene.selected_molecule_id = self.molecule_id
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        
        if molecule:
            # Deselect all objects first
            bpy.ops.object.select_all(action='DESELECT')
            # Select the molecule's object
            molecule.object.select_set(True)
            context.view_layer.objects.active = molecule.object
            
        return {'FINISHED'}

class MOLECULE_OT_edit(Operator):
    bl_idname = "molecule.edit"
    bl_label = "Edit Molecule"
    bl_description = "Edit this molecule"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        context.scene.show_molecule_edit_panel = True
        context.scene.selected_molecule_id = self.molecule_id
        return {'FINISHED'}

class MOLECULE_OT_delete(Operator):
    bl_idname = "molecule.delete"
    bl_label = "Delete Molecule"
    bl_description = "Delete this molecule"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        scene_manager.delete_molecule(self.molecule_id)
        return {'FINISHED'}

class MOLECULE_PT_list(Panel):
    bl_label = "Molecules in Scene"
    bl_idname = "MOLECULE_PT_list"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    
    @classmethod
    def poll(cls, context):
        print("MOLECULE_PT_list poll called")
        return True
    
    def draw(self, context):
        print("MOLECULE_PT_list draw called")
        layout = self.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        print(f"Molecules in scene_manager: {list(scene_manager.molecules.keys())}")
        
        # Create box for list
        box = layout.box()
        
        if not scene_manager.molecules:
            print("No molecules found in scene_manager")
            box.label(text="No molecules in scene", icon='INFO')
            return
            
        # Create column for molecule entries
        col = box.column()
        
        # Draw each molecule entry
        for molecule_id, molecule in scene_manager.molecules.items():
            print(f"Drawing molecule: {molecule_id}")
            row = col.row(align=True)
            
            # Create clickable operator for selection
            name_op = row.operator(
                "molecule.select",
                text=molecule.identifier,
                depress=(molecule_id == scene.selected_molecule_id)
            )
            name_op.molecule_id = molecule_id
            
            if molecule.object:
                # Only add style selector if mn property exists
                if hasattr(molecule.object, "mn"):
                    style_row = row.row()
                    style_row.prop(molecule.object.mn, "import_style", text="")
                
                # Visibility toggle
                vis_row = row.row()
                vis_row.prop(molecule.object, "hide_viewport", text="", emboss=False)
                
                # Edit button
                edit_op = row.operator("molecule.edit", text="", icon='PREFERENCES')
                if edit_op:  # Check if operator exists before setting property
                    edit_op.molecule_id = molecule_id
                
                # Delete button
                delete_op = row.operator("molecule.delete", text="", icon='X')
                if delete_op:  # Check if operator exists before setting property
                    delete_op.molecule_id = molecule_id

def register_molecule_list_panel():
    print("Registering molecule list panel...")  # Debug print
    bpy.utils.register_class(MOLECULE_OT_select)
    bpy.utils.register_class(MOLECULE_OT_edit)
    bpy.utils.register_class(MOLECULE_OT_delete)
    bpy.utils.register_class(MOLECULE_PT_list)
    print("Molecule list panel registered")  # Debug print

def unregister_molecule_list_panel():
    print("Unregistering molecule list panel...")  # Debug print
    bpy.utils.unregister_class(MOLECULE_PT_list)
    bpy.utils.unregister_class(MOLECULE_OT_delete)
    bpy.utils.unregister_class(MOLECULE_OT_edit)
    bpy.utils.unregister_class(MOLECULE_OT_select)
    print("Molecule list panel unregistered")  # Debug print 