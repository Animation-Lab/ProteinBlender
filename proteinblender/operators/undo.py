import bpy
import os
from bpy.props import PointerProperty, StringProperty, CollectionProperty
from bpy.types import Operator, PropertyGroup

from ..utils.molecularnodes.entities.molecule.ui import load_local

# Define PropertyGroups first
class AssociatedDataItem(PropertyGroup):
    """A single item of associated data, storing its name and type."""
    name: StringProperty()
    type: StringProperty()

class ProteinImportMetadata(PropertyGroup):
    """A manifest to track all data blocks associated with a single protein import."""
    created_object_name: StringProperty(
        name="Object Name",
        description="The name of the primary Blender object created for the protein."
    )
    associated_data: CollectionProperty(
        type=AssociatedDataItem,
        name="Associated Data",
        description="A list of all data blocks (meshes, materials, etc.) created for this import."
    )

# Define Operators
class PB_OT_import_protein_undoable(Operator):
    """Imports a protein and creates a single undo step"""
    bl_idname = "pb.import_protein_undoable"
    bl_label = "Import Protein (Undoable)"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.pdb;*.cif;*.mmcif;*.bcif;*.pdbx", options={'HIDDEN'})

    def execute(self, context):
        data_before = {
            'objects': {o.name for o in bpy.data.objects},
            'meshes': {m.name for m in bpy.data.meshes},
            'materials': {m.name for m in bpy.data.materials},
            'node_groups': {ng.name for ng in bpy.data.node_groups},
            'collections': {c.name for c in bpy.data.collections}
        }
        try:
            object_name = os.path.basename(self.filepath).split('.')[0]
            mol_object_wrapper = load_local(filepath=self.filepath, name=object_name)
            if not mol_object_wrapper or not mol_object_wrapper.object:
                self.report({'WARNING'}, "Import failed. Molecular Nodes did not return a valid object.")
                return {'CANCELLED'}
            new_object = mol_object_wrapper.object
        except Exception as e:
            self.report({'ERROR'}, f"An error occurred during import: {e}")
            return {'CANCELLED'}

        data_after = {
            'objects': {o.name for o in bpy.data.objects},
            'meshes': {m.name for m in bpy.data.meshes},
            'materials': {m.name for m in bpy.data.materials},
            'node_groups': {ng.name for ng in bpy.data.node_groups},
            'collections': {c.name for c in bpy.data.collections}
        }
        new_data = {
            'OBJECT': data_after['objects'] - data_before['objects'],
            'MESH': data_after['meshes'] - data_before['meshes'],
            'MATERIAL': data_after['materials'] - data_before['materials'],
            'GEOMETRY': data_after['node_groups'] - data_before['node_groups'],
            'COLLECTION': data_after['collections'] - data_before['collections']
        }

        if new_object.name not in new_data['OBJECT']:
            self.report({'WARNING'}, "The object returned by the importer was not identified as new.")

        new_object.protein_import_metadata.created_object_name = new_object.name
        meta_props = new_object.protein_import_metadata
        meta_props.associated_data.clear()
        for data_type, names in new_data.items():
            for name in names:
                item = meta_props.associated_data.add()
                item.name = name
                item.type = data_type
        
        is_main_object_in_list = any(d.name == new_object.name and d.type == 'OBJECT' for d in meta_props.associated_data)
        if not is_main_object_in_list:
            item = meta_props.associated_data.add()
            item.name = new_object.name
            item.type = 'OBJECT'
            
        self.report({'INFO'}, f"Successfully imported '{new_object.name}' with undo tracking.")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
        
class PB_OT_delete_protein_undoable(Operator):
    """Deletes a protein model and all associated data"""
    bl_idname = "pb.delete_protein_undoable"
    bl_label = "Delete Protein (Undoable)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and hasattr(obj, "protein_import_metadata") and obj.protein_import_metadata.created_object_name

    def execute(self, context):
        DATA_TYPE_TO_COLLECTION = {
            'OBJECT': bpy.data.objects,
            'MESH': bpy.data.meshes,
            'MATERIAL': bpy.data.materials,
            'GEOMETRY': bpy.data.node_groups,
            'COLLECTION': bpy.data.collections,
        }
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        meta = obj.protein_import_metadata
        if not meta.created_object_name:
            self.report({'WARNING'}, "No import metadata found on this object.")
            return {'CANCELLED'}
        data_to_remove = {'OBJECT': []}
        for item in meta.associated_data:
            if item.type not in data_to_remove:
                data_to_remove[item.type] = []
            collection = DATA_TYPE_TO_COLLECTION.get(item.type)
            if collection and item.name in collection:
                data_to_remove[item.type].append(collection[item.name])

        if 'OBJECT' in data_to_remove:
            for obj_to_del in data_to_remove['OBJECT']:
                for coll in bpy.data.collections:
                    if obj_to_del.name in coll.objects:
                        coll.objects.unlink(obj_to_del)
        for data_type, blocks in data_to_remove.items():
            if data_type == 'OBJECT': continue
            collection = DATA_TYPE_TO_COLLECTION.get(data_type)
            if not collection: continue
            for block in blocks:
                try:
                    collection.remove(block)
                except:
                    self.report({'WARNING'}, f"Could not remove '{block.name}' of type '{data_type}'. It may still be in use.")
        if 'OBJECT' in data_to_remove:
            for obj_to_del in data_to_remove['OBJECT']:
                try:
                    bpy.data.objects.remove(obj_to_del, do_unlink=True)
                except:
                    pass
        self.report({'INFO'}, f"Removed protein and associated data for '{obj.name}'.")
        return {'FINISHED'}

# Group all classes for registration by the main addon registration loop
CLASSES = (
    AssociatedDataItem,
    ProteinImportMetadata,
    PB_OT_import_protein_undoable,
    PB_OT_delete_protein_undoable,
)

# Define functions to handle the PointerProperty separately, as it's not a class
def register_properties():
    bpy.types.Object.protein_import_metadata = PointerProperty(type=ProteinImportMetadata)

def unregister_properties():
    try:
        del bpy.types.Object.protein_import_metadata
    except AttributeError:
        # Fails silently if the property was never registered
        pass 