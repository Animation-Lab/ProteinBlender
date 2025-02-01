import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.molecularnodes.style import STYLE_ITEMS

class MOLECULE_PB_OT_select(Operator):
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
            # Set the edit identifier when selecting
            context.scene.edit_molecule_identifier = molecule.identifier
            
            # Deselect all objects first
            bpy.ops.object.select_all(action='DESELECT')
            # Select the molecule's object
            molecule.object.select_set(True)
            context.view_layer.objects.active = molecule.object
            
            # Get unique chain IDs from the molecule's object
            if molecule.object:
                # Get the geometry nodes modifier
                gn_mod = molecule.object.modifiers.get("MolecularNodes")
                if gn_mod and gn_mod.node_group:
                    # Create chain enum items
                    chain_items = []
                    # Get chain IDs from the molecule's attributes
                    chain_ids = set()  # Using a set to get unique chain IDs
                    if "chain_id" in molecule.object.data.attributes:
                        chain_attr = molecule.object.data.attributes["chain_id"]
                        for value in chain_attr.data:
                            chain_ids.add(value.value)
                    
                    # Create enum items for each chain
                    chain_items = [("NONE", "None", "None")]
                    chain_items.extend([(str(chain), f"Chain {chain}", f"Chain {chain}") 
                                      for chain in sorted(chain_ids)])
                    
                    # Update the enum property
                    bpy.types.Scene.selected_chain = EnumProperty(
                        name="Chain",
                        description="Selects the protein's chain",
                        items=chain_items,
                        default="NONE"
                    )
                    # Force a property update
                    context.scene.selected_chain = "NONE"
            
        return {'FINISHED'}

class MOLECULE_PB_OT_edit(Operator):
    bl_idname = "molecule.edit"
    bl_label = "Edit Molecule"
    bl_description = "Edit this molecule"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        context.scene.show_molecule_edit_panel = True
        context.scene.selected_molecule_id = self.molecule_id
        return {'FINISHED'}

class MOLECULE_PB_OT_delete(Operator):
    bl_idname = "molecule.delete"
    bl_label = "Delete Molecule"
    bl_description = "Delete this molecule"
    bl_options = {'REGISTER', 'UNDO'}
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        scene_manager.delete_molecule(self.molecule_id)
        return {'FINISHED'}

class MOLECULE_PB_OT_update_identifier(Operator):
    bl_idname = "molecule.update_identifier"
    bl_label = "Update Identifier"
    bl_description = "Update the molecule's identifier"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        old_id = scene.selected_molecule_id
        new_id = scene.edit_molecule_identifier
        
        if old_id == new_id or not new_id:
            return {'CANCELLED'}
            
        # Update molecule identifier
        molecule = scene_manager.molecules[old_id]
        molecule.identifier = new_id
        scene_manager.molecules[new_id] = scene_manager.molecules.pop(old_id)
        
        # Update UI list
        for item in scene.molecule_list_items:
            if item.identifier == old_id:
                item.identifier = new_id
                break
                
        # Update selected molecule id
        scene.selected_molecule_id = new_id
        
        return {'FINISHED'}

class MOLECULE_PB_OT_change_style(Operator):
    bl_idname = "molecule.change_style"
    bl_label = "Change Style"
    bl_description = "Change the molecule's visualization style"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        
        if molecule and molecule.object:
            from ..utils.molecularnodes.blender.nodes import change_style_node
            change_style_node(molecule.object, context.scene.molecule_style)
            
        return {'FINISHED'}

class MOLECULE_PB_OT_select_protein_chain(Operator):
    bl_idname = "molecule.select_protein_chain"
    bl_label = "Select Chain"
    bl_description = "Selects the molecule's chain"


    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        molecule.select_protein_chain = context.scene.selected_chain

        

        '''
        if molecule and molecule.object:
            from ..utils.molecularnodes.blender.nodes import change_style_node
            change_style_node(molecule.object, context.scene.molecule_style)
        '''

        return {'FINISHED'}

