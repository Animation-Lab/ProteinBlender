from typing import Dict, List, Tuple, Optional, Any
import bpy
from mathutils import Vector, Matrix
from .domain import DomainDefinition


class MoleculeState:
    """Captures and restores complete molecule state for undo/redo operations"""
    
    def __init__(self, molecule_wrapper):
        """Capture complete state of a molecule and all its domains"""
        self.identifier = molecule_wrapper.identifier
        self.molecule_data = self._capture_molecule_data(molecule_wrapper)
        self.domains_data = self._capture_domains_data(molecule_wrapper)
        
    def _capture_molecule_data(self, molecule):
        """Store basic molecule info needed for recreation"""
        # Safely capture molecule object and its properties to avoid exceptions if object reference is invalid
        try:
            obj = molecule.object
        except Exception:
            obj = None

        # Prepare object-related data
        object_name = None
        object_transform = None
        object_location = None
        object_rotation = None
        object_scale = None
        # Attempt to extract attributes only if the object is fully valid
        if obj:
            try:
                object_name = obj.name
                object_transform = obj.matrix_world.copy()
                object_location = obj.location.copy()
                object_rotation = obj.rotation_euler.copy()
                object_scale = obj.scale.copy()
            except Exception:
                # Object has been removed or is invalid; skip capturing its data
                object_name = None
                object_transform = None
                object_location = None
                object_rotation = None
                object_scale = None

        data = {
            'identifier': molecule.identifier,
            'style': molecule.style,
            'object_name': object_name,
            'object_transform': object_transform,
            'object_location': object_location,
            'object_rotation': object_rotation,
            'object_scale': object_scale,
            'chain_mapping': getattr(molecule, 'chain_mapping', {}),
            'auth_chain_id_map': getattr(molecule, 'auth_chain_id_map', {}),
            'idx_to_label_asym_id_map': getattr(molecule, 'idx_to_label_asym_id_map', {}),
            'chain_residue_ranges': getattr(molecule, 'chain_residue_ranges', {})
        }

        # Store material information if available, safely
        try:
            if obj and hasattr(obj, 'data') and getattr(obj.data, 'materials', None):
                data['materials'] = [mat.name for mat in obj.data.materials if mat]
        except Exception:
            pass

        return data
        
    def _capture_domains_data(self, molecule):
        """Store all domain info including objects, transforms, and node configurations"""
        domains_data = {}
        
        for domain_id, domain in molecule.domains.items():
            # Always record stored names so we can reattach objects/node groups even if pointers die
            obj_name = getattr(domain, 'object_name', None)
            ng_name = getattr(domain, 'node_group_name', None)
            # Safely capture world transform if possible
            try:
                obj_transform = domain.object.matrix_world.copy() if domain.object else None
            except Exception:
                obj_transform = None
            domain_data = {
                'domain_id': domain_id,
                'chain_id': domain.chain_id,
                'start': domain.start,
                'end': domain.end,
                'name': domain.name,
                'color': domain.color,
                'style': getattr(domain, 'style', 'ribbon'),
                'parent_molecule_id': domain.parent_molecule_id,
                'parent_domain_id': domain.parent_domain_id,
                'object_name': obj_name,
                'object_transform': obj_transform,
                'node_group_name': ng_name,
                'setup_complete': getattr(domain, '_setup_complete', False)
            }
            
            # Store parent-child relationships in Blender hierarchy
            if domain.object:
                domain_data['parent_object'] = domain.object.parent.name if domain.object.parent else None
                domain_data['matrix_parent_inverse'] = domain.object.matrix_parent_inverse.copy()
                # Store local transform (relative to parent) instead of world transform
                domain_data['matrix_local'] = domain.object.matrix_local.copy()
                
                # Store collection information
                if domain.object.users_collection:
                    domain_data['collections'] = [col.name for col in domain.object.users_collection]
            
            domains_data[domain_id] = domain_data
            
        return domains_data
        
    def restore_to_scene(self, scene_manager):
        """Recreate the molecule and all domains with proper relationships"""
        try:
            #print(f"Restoring molecule state: {self.identifier}")
            
            # Find the restored Blender object by name
            molecule_obj = None
            if self.molecule_data['object_name']:
                molecule_obj = bpy.data.objects.get(self.molecule_data['object_name'])
                
            if not molecule_obj:
                #print(f"Could not find restored object for molecule {self.identifier}")
                return False
                
            # Recreate molecule using molecule manager
            if not self._restore_molecule(scene_manager, molecule_obj):
                return False
                
            # Restore all domains
            if not self._restore_domains(scene_manager):
                return False
                
            # Add to UI list if not already present
            scene = bpy.context.scene
            found = False
            for item in scene.molecule_list_items:
                if item.identifier == self.identifier:
                    found = True
                    break
            
            if not found:
                item = scene.molecule_list_items.add()
                item.identifier = self.identifier
                #print(f"Added molecule {self.identifier} to UI list")
                
            #print(f"Successfully restored molecule: {self.identifier}")
            return True
            
        except Exception as e:
            print(f"Error restoring molecule {self.identifier}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
            
    def _restore_molecule(self, scene_manager, molecule_obj):
        """Restore the main molecule wrapper"""
        try:
            print(f"Restoring molecule wrapper for object: {molecule_obj.name}")
            
            # Create a minimal Molecule-like object to wrap the restored Blender object
            # We don't need to recreate the full MolecularNodes Molecule since the object already exists
            class MinimalMolecule:
                def __init__(self, obj):
                    self.object = obj
                    self.array = None
                    # Try to get array data from the object's custom properties
                    if hasattr(obj, 'mn'):
                        if hasattr(obj.mn, 'array'):
                            self.array = obj.mn.array
                
            mol = MinimalMolecule(molecule_obj)
            
            # Create wrapper with restored data - bypassing the MoleculeWrapper's initialization
            # that would try to set up the molecule from scratch 
            from .molecule_wrapper import MoleculeWrapper
            
            # Create wrapper but we'll manually set its attributes to avoid re-initialization
            wrapper = object.__new__(MoleculeWrapper)
            
            # Set basic attributes
            wrapper.molecule      = mol
            wrapper.identifier    = self.identifier
            wrapper.style         = self.molecule_data.get('style', 'surface')
            wrapper.domains       = {}
            wrapper.residue_assignments = {}
            
            # Restore wrapper mapping attributes
            wrapper.chain_mapping = self.molecule_data.get('chain_mapping', {})
            wrapper.auth_chain_id_map = self.molecule_data.get('auth_chain_id_map', {})
            wrapper.idx_to_label_asym_id_map = self.molecule_data.get('idx_to_label_asym_id_map', {})
            wrapper.chain_residue_ranges = self.molecule_data.get('chain_residue_ranges', {})
            
            # Set other attributes that MoleculeWrapper expects
            wrapper.working_array = None
            wrapper.preview_nodes = None
            wrapper.domain_mask_nodes = {}
            wrapper.domain_join_node = None
            
            # Set object name
            wrapper.object_name = molecule_obj.name
            
            # Store in scene manager
            scene_manager.molecules[self.identifier] = wrapper
            scene_manager.molecule_manager.molecules[self.identifier] = wrapper
            
            # Don't restore transforms - the undo operation should have restored the object
            # to its correct position already. Overriding transforms can break movability.
            
            #print(f"Successfully restored molecule wrapper for {self.identifier}")
            return True
            
        except Exception as e:
            print(f"Error restoring molecule object: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
            
    def _restore_domains(self, scene_manager):
        """Restore all domain objects and relationships"""
        try:
            molecule = scene_manager.molecules.get(self.identifier)
            if not molecule:
                #print(f"Could not find molecule {self.identifier} for domain restoration")
                return False
                
            # Clear existing domains
            molecule.domains.clear()
            
            # Restore each domain
            for domain_id, domain_data in self.domains_data.items():
                if not self._restore_single_domain(molecule, domain_id, domain_data):
                    #print(f"Failed to restore domain {domain_id}")
                    continue
                    
            return True
            
        except Exception as e:
            print(f"Error restoring domains: {str(e)}")
            return False
            
    def _restore_single_domain(self, molecule, domain_id, domain_data):
        """Restore a single domain object"""
        try:
            # Find the restored domain object
            domain_obj = None
            if domain_data.get('object_name'):
                domain_obj = bpy.data.objects.get(domain_data['object_name'])
                
            # Find the restored node group
            node_group = None
            if domain_data.get('node_group_name'):
                node_group = bpy.data.node_groups.get(domain_data['node_group_name'])
                
            # Create domain definition
            domain = DomainDefinition(
                chain_id=domain_data['chain_id'],
                start=domain_data['start'],
                end=domain_data['end'],
                name=domain_data['name']
            )
            
            # If the Blender domain object is missing, invoke DomainDefinition.create_object_from_parent
            # against the molecule.object to re-generate the domain object and its node group
            if not domain_obj and molecule.object:
                print(f"Domain object missing for {domain_id}, recreating from parent")
                if domain.create_object_from_parent(molecule.object):
                    domain_obj = domain.object
                    node_group = domain.node_group
            
            # Restore domain attributes
            domain.domain_id = domain_id
            domain.color = domain_data.get('color', (0.8, 0.1, 0.8, 1.0))
            domain.style = domain_data.get('style', 'ribbon')
            domain.parent_molecule_id = domain_data.get('parent_molecule_id')
            domain.parent_domain_id = domain_data.get('parent_domain_id')
            domain.object = domain_obj
            domain.node_group = node_group
            domain._setup_complete = domain_data.get('setup_complete', False)
            # Restore stored names for future pointer healing
            domain.object_name     = domain_data.get('object_name')
            domain.node_group_name = domain_data.get('node_group_name')
            
            # Restore object relationships if object exists
            if domain_obj:
                # Check if parent relationship needs to be restored
                parent_name = domain_data.get('parent_object')
                if parent_name:
                    parent_obj = bpy.data.objects.get(parent_name)
                    if parent_obj and domain_obj.parent != parent_obj:
                        # Only set parent if it's not already correct
                        # Store current world transform to maintain position
                        world_matrix = domain_obj.matrix_world.copy()
                        domain_obj.parent = parent_obj
                        # Restore the world position after parenting
                        domain_obj.matrix_world = world_matrix
                        
                # Don't override transforms if the objects are already in correct positions after undo
                # The undo operation should have restored them correctly
                    
            # Add domain to molecule
            molecule.domains[domain_id] = domain
            
            return True
            
        except Exception as e:
            print(f"Error restoring single domain {domain_id}: {str(e)}")
            return False


def _is_object_valid(obj):
    """Check if Blender object reference is still valid"""
    try:
        return obj and obj.name in bpy.data.objects
    except:
        return False


def _has_invalid_domains(molecule):
    """Check if any domains have invalid object references"""
    try:
        for domain in molecule.domains.values():
            if domain.object and not _is_object_valid(domain.object):
                return True
        return False
    except:
        return True 