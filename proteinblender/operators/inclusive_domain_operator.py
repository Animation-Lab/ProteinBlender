import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from ..core.scene_manager import ProteinBlenderScene

class MOLECULE_PB_OT_create_inclusive_domains(Operator):
    bl_idname = "molecule.create_inclusive_domains"
    bl_label = "Create Inclusive Domains"
    bl_description = "Create domains for all chains ensuring complete coverage of the molecular structure"
    bl_options = {'REGISTER', 'UNDO'}
    
    clear_existing: BoolProperty(
        name="Clear Existing Domains",
        description="Remove all existing domains before creating inclusive domains",
        default=True
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule_wrapper = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule_wrapper:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        try:
            # Use the inclusive domain creation method
            created_domains = molecule_wrapper.create_inclusive_domains(clear_existing=self.clear_existing)
            
            if created_domains:
                self.report({'INFO'}, f"Successfully created {len(created_domains)} inclusive domains")
                
                # Refresh the UI to show new domains
                scene_manager._refresh_ui()
                
                return {'FINISHED'}
            else:
                self.report({'WARNING'}, "No domains were created")
                return {'CANCELLED'}
                
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create inclusive domains: {str(e)}")
            return {'CANCELLED'}

class MOLECULE_PB_OT_analyze_chain_composition(Operator):
    bl_idname = "molecule.analyze_chain_composition"
    bl_label = "Analyze Chain Composition"
    bl_description = "Analyze the molecular composition of all chains in the selected molecule"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule_wrapper = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule_wrapper:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        try:
            # Get all chains and analyze them
            if hasattr(molecule_wrapper.working_array, 'chain_id'):
                unique_chains = sorted(list(molecule_wrapper.working_array.chain_id.astype(str)))
                
                print("=== Chain Composition Analysis ===")
                for chain_id in unique_chains:
                    composition = molecule_wrapper.analyze_chain_composition(chain_id)
                    print(f"\nChain {chain_id}:")
                    print(f"  Dominant type: {composition['dominant_type']}")
                    print(f"  Residue range: {composition['residue_range']}")
                    print(f"  Unique residues: {composition['unique_residues']}")
                    print(f"  Counts - Protein: {composition['protein_residues']}, "
                          f"Ligand: {composition['ligand_residues']}, "
                          f"Nucleic: {composition['nucleic_residues']}")
                
                # Get domain coverage summary
                summary = molecule_wrapper.get_domain_composition_summary()
                print("\n=== Domain Coverage Summary ===")
                print(f"Total domains: {summary['total_domains']}")
                print(f"By type: {summary['by_type']}")
                print(f"Missing chains: {summary['missing_chains']}")
                
                self.report({'INFO'}, f"Analysis complete for {len(unique_chains)} chains. Check console for details.")
            else:
                self.report({'ERROR'}, "No chain information available")
                return {'CANCELLED'}
                
        except Exception as e:
            self.report({'ERROR'}, f"Failed to analyze composition: {str(e)}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

def register():
    bpy.utils.register_class(MOLECULE_PB_OT_create_inclusive_domains)
    bpy.utils.register_class(MOLECULE_PB_OT_analyze_chain_composition)

def unregister():
    bpy.utils.unregister_class(MOLECULE_PB_OT_create_inclusive_domains)
    bpy.utils.unregister_class(MOLECULE_PB_OT_analyze_chain_composition) 