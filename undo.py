# operators/undo.py

import bpy
import os
from bpy.props import PointerProperty, StringProperty, CollectionProperty
from bpy.types import Operator, PropertyGroup

# It's better to import the specific function we need.
# This avoids cluttering the namespace and makes dependencies clearer.
from proteinblender.utils.molecularnodes.entities.molecule.ui import load_local

class ProteinImportMetadata(PropertyGroup):
    """
    A PropertyGroup to store metadata about imported protein data blocks.
    This acts as a manifest to track all associated data for a single import,
    enabling a clean deletion for the undo/redo system.
    """
    # We store names instead of direct pointers because pointers can become
    # invalid during undo/redo operations or if the data is deleted.
    # Names are a more robust way to look up the data again.
    
    created_object_name: StringProperty(
        name="Object Name",
        description="The name of the primary Blender object created for the protein."
    )
    
    # Using a CollectionProperty for associated data is more flexible than
    # comma-separated strings. Each item will have a 'name' and 'type'.
    class AssociatedDataItem(PropertyGroup):
        name: StringProperty()
        type: StringProperty() # e.g., 'MESH', 'MATERIAL', 'GEOMETRY', 'COLLECTION'
        
    associated_data: CollectionProperty(
        type=AssociatedDataItem,
        name="Associated Data",
        description="A list of all data blocks (meshes, materials, etc.) created for this import."
    )

class PB_OT_import_protein_undoable(Operator):
    """
    Imports a local protein file (.pdb, .cif, etc.) and creates a single,
    robust undo step that can revert the entire operation.
    """
    bl_idname = "pb.import_protein_undoable"
    bl_label = "Import Protein (Undoable)"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype="FILE_PATH")
    
    # Define a filter for the file browser
    filter_glob: StringProperty(
        default="*.pdb;*.cif;*.mmcif;*.bcif;*.pdbx",
        options={'HIDDEN'},
    )

    def execute(self, context):
        # --- 1. Data Tracking: Before ---
        # Get a snapshot of all relevant data block names *before* the import.
        # Using sets for efficient comparison later.
        data_before = {
            'objects': {o.name for o in bpy.data.objects},
            'meshes': {m.name for m in bpy.data.meshes},
            'materials': {m.name for m in bpy.data.materials},
            'node_groups': {ng.name for ng in bpy.data.node_groups},
            'collections': {c.name for c in bpy.data.collections}
        }

        # --- 2. Call the core import function from Molecular Nodes ---
        try:
            # The 'name' argument will be the Blender object's name.
            # We derive it from the filepath.
            object_name = os.path.basename(self.filepath).split('.')[0]
            mol_object_wrapper = load_local(filepath=self.filepath, name=object_name)
            
            if not mol_object_wrapper or not mol_object_wrapper.object:
                self.report({'WARNING'}, "Import failed. Molecular Nodes did not return a valid object.")
                return {'CANCELLED'}
            
            new_object = mol_object_wrapper.object

        except Exception as e:
            self.report({'ERROR'}, f"An error occurred during import: {e}")
            return {'CANCELLED'}

        # --- 3. Data Tracking: After ---
        # Get a snapshot of data *after* the import.
        data_after = {
            'objects': {o.name for o in bpy.data.objects},
            'meshes': {m.name for m in bpy.data.meshes},
            'materials': {m.name for m in bpy.data.materials},
            'node_groups': {ng.name for ng in bpy.data.node_groups},
            'collections': {c.name for c in bpy.data.collections}
        }
        
        # --- 4. Identify new data and store metadata ---
        # Compare the 'before' and 'after' sets to find what was created.
        new_data = {
            'OBJECT': data_after['objects'] - data_before['objects'],
            'MESH': data_after['meshes'] - data_before['meshes'],
            'MATERIAL': data_after['materials'] - data_before['materials'],
            'GEOMETRY': data_after['node_groups'] - data_before['node_groups'],
            'COLLECTION': data_after['collections'] - data_before['collections']
        }
        
        # Check if the primary object we got from the importer is in our new list.
        if new_object.name not in new_data['OBJECT']:
            self.report({'WARNING'}, "The object returned by the importer was not identified as new.")
            # This can happen if an object with the same name was replaced.
            # We'll still proceed to add metadata to the returned object.

        # Attach our custom PropertyGroup to the main object
        new_object.protein_import_metadata = new_object.protein_import_metadata
        meta_props = new_object.protein_import_metadata
        meta_props.created_object_name = new_object.name
        
        # Clear any old data, just in case
        meta_props.associated_data.clear()

        # Populate the metadata with all the new data blocks we found
        for data_type, names in new_data.items():
            for name in names:
                item = meta_props.associated_data.add()
                item.name = name
                item.type = data_type
        
        # Ensure the main object itself is in the list, as it's the entry point.
        is_main_object_in_list = any(d.name == new_object.name and d.type == 'OBJECT' for d in meta_props.associated_data)
        if not is_main_object_in_list:
            item = meta_props.associated_data.add()
            item.name = new_object.name
            item.type = 'OBJECT'

        self.report({'INFO'}, f"Successfully imported '{new_object.name}' with undo tracking.")
        return {'FINISHED'}

    def invoke(self, context, event):
        # Open the file browser, filtering for common molecular file types
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
        
# A dictionary to map metadata types to Blender's data collections
DATA_TYPE_TO_COLLECTION = {
    'OBJECT': bpy.data.objects,
    'MESH': bpy.data.meshes,
    'MATERIAL': bpy.data.materials,
    'GEOMETRY': bpy.data.node_groups,
    'COLLECTION': bpy.data.collections,
}

class PB_OT_delete_protein_undoable(Operator):
    """
    Deletes a protein model and all of its associated data blocks
    (mesh, materials, etc.) using the metadata created on import.
    This entire deletion can be undone in a single step.
    """
    bl_idname = "pb.delete_protein_undoable"
    bl_label = "Delete Protein (Undoable)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # This operator should only be active if the selected object is
        # a protein that was imported with our undoable operator.
        obj = context.active_object
        return (
            obj and 
            hasattr(obj, "protein_import_metadata") and 
            obj.protein_import_metadata.created_object_name
        )

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        
        meta = obj.protein_import_metadata
        if not meta.created_object_name:
            self.report({'WARNING'}, "No import metadata found on this object.")
            return {'CANCELLED'}

        # --- Data Removal Logic ---
        # We build a list of all data blocks to remove based on the metadata.
        # The order of removal can be important to avoid dependency errors.
        # We will remove objects last.
        
        data_to_remove = {'OBJECT': []}
        for item in meta.associated_data:
            if item.type not in data_to_remove:
                data_to_remove[item.type] = []
            
            collection = DATA_TYPE_TO_COLLECTION.get(item.type)
            if collection and item.name in collection:
                data_to_remove[item.type].append(collection[item.name])
        
        # Start by removing objects from their collections to break links.
        # This must be done before removing the object data itself.
        if 'OBJECT' in data_to_remove:
            for obj_to_del in data_to_remove['OBJECT']:
                for coll in bpy.data.collections:
                    if obj_to_del.name in coll.objects:
                        coll.objects.unlink(obj_to_del)
        
        # Now, iterate through and remove the actual data blocks.
        # We skip objects for now and remove them at the very end.
        for data_type, blocks in data_to_remove.items():
            if data_type == 'OBJECT':
                continue
            
            collection = DATA_TYPE_TO_COLLECTION.get(data_type)
            if not collection:
                continue
                
            for block in blocks:
                # Check for users. If a data block (like a material) is used
                # by something else not part of this import, we should be cautious.
                # For a clean import/delete cycle, user count should be low.
                try:
                    collection.remove(block)
                except:
                    # Catch errors if something is still using the data.
                    self.report({'WARNING'}, f"Could not remove '{block.name}' of type '{data_type}'. It may still be in use.")

        # Finally, remove the object data blocks themselves.
        if 'OBJECT' in data_to_remove:
            for obj_to_del in data_to_remove['OBJECT']:
                try:
                    bpy.data.objects.remove(obj_to_del, do_unlink=True)
                except:
                    pass # Already unlinked, so this should be safe.

        self.report({'INFO'}, f"Removed protein and associated data for '{obj.name}'.")
        return {'FINISHED'}


def register():
    # It's good practice to handle potential registration errors.
    try:
        bpy.utils.register_class(ProteinImportMetadata.AssociatedDataItem)
    except ValueError:
        pass # Class is already registered
    bpy.utils.register_class(ProteinImportMetadata)
    bpy.types.Object.protein_import_metadata = PointerProperty(type=ProteinImportMetadata)
    bpy.utils.register_class(PB_OT_import_protein_undoable)
    bpy.utils.register_class(PB_OT_delete_protein_undoable)

def unregister():
    bpy.utils.unregister_class(PB_OT_delete_protein_undoable)
    bpy.utils.unregister_class(PB_OT_import_protein_undoable)
    del bpy.types.Object.protein_import_metadata
    bpy.utils.unregister_class(ProteinImportMetadata)
    # It's good practice to handle potential unregistration errors.
    try:
        bpy.utils.unregister_class(ProteinImportMetadata.AssociatedDataItem)
    except RuntimeError:
        pass # Class is not registered

# The following code block is not provided in the original file or the code block
# to apply changes from. It's assumed to be part of the original file.

# The following code block is not provided in the original file or the code block
# to apply changes from. It's assumed to be part of the original file. 