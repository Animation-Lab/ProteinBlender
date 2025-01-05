import json
import os
from datetime import datetime
import uuid
from enum import Enum
import bpy
from mathutils import Vector

# Global materials dictionary
ATOM_MATERIALS = {}
GLOBAL_SCALE = 0.1

class RenderStyle(Enum):
    BALL_AND_STICK = 'ball_stick'
    RIBBON = 'ribbon'
    SPHERES = 'spheres'
    CARTOON = 'cartoon'
    SURFACE = 'surface'
    HIDDEN = 'hidden'

ATOM_RELATIVE_SIZES = {
    # Base atomic elements
    'C': 1.0,    # Carbon
    'H': 0.5,    # Hydrogen
    'O': 1.2,    # Oxygen
    'N': 1.1,    # Nitrogen
    'S': 1.8,    # Sulfur
    'P': 1.7,    # Phosphorus
    'FE': 2.0,   # Iron
    'CA': 2.0,   # Calcium
    'MG': 1.8,   # Magnesium
    'ZN': 1.5,   # Zinc
    'CL': 1.6,   # Chlorine
}

def create_atom_materials():
    """Create global materials for all atom types and functional groups."""
    colors = {
        # Base atomic elements
        'C': (0.2, 0.2, 0.2, 1.0),    # Grey
        'H': (1.0, 1.0, 1.0, 1.0),    # White
        'O': (1.0, 0.0, 0.0, 1.0),    # Red
        'N': (0.0, 0.0, 1.0, 1.0),    # Blue
        'S': (1.0, 0.8, 0.0, 1.0),    # Yellow
        'P': (1.0, 0.5, 0.0, 1.0),    # Orange
        'FE': (0.7, 0.3, 0.0, 1.0),   # Brown
        'CA': (0.5, 0.5, 0.5, 1.0),   # Light grey
        'MG': (0.0, 1.0, 0.0, 1.0),   # Green
        'ZN': (0.6, 0.6, 0.8, 1.0),   # Blue-grey
        'CL': (0.0, 0.8, 0.0, 1.0),   # Green
    }

    for atom_symbol, color in colors.items():
        mat_name = f"atom_{atom_symbol}"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True  # Enable the use of nodes

        # Access the Principled BSDF node
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")

        # Modify BSDF properties
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = 0.7  # Make the surface rough
            bsdf.inputs["Metallic"].default_value = 0.2  # Slightly metallic
        else:
            mat.diffuse_color = color
        ATOM_MATERIALS[atom_symbol] = mat


class Protein:
    def __init__(self, identifier, method='PDB'):
        self.identifier = identifier
        self.unique_id = f"{identifier}-{str(uuid.uuid4())[:8]}"  # Using first 8 chars of UUID for brevity
        self.method = method
        self.file_path = None
        self.import_date = datetime.now().isoformat()
        self.atoms = []  # List of atom positions and types
        self.chains = []  # List of chain IDs
        self.residues = []  # List of residue information
        self.model = ProteinModel()  # Add 3D model management


    def create_model(self):
        self.model.create_model(self)
        
    def parse_pdb_string(self, pdb_content):
        """Parse PDB content and store relevant information."""
        for line in pdb_content.splitlines():
            if line.startswith(('ATOM', 'HETATM')):
                atom_info = {
                    'type': line[12:16].strip(),
                    'residue': line[17:20].strip(),
                    'chain': line[21],
                    'residue_num': int(line[22:26]),
                    'position': [
                        float(line[30:38]),
                        float(line[38:46]),
                        float(line[46:54]),
                    ],
                    'symbol': line[76:78].strip().upper()
                }
                self.atoms.append(atom_info)
                if atom_info['chain'] not in self.chains:
                    self.chains.append(atom_info['chain'])
                residue_key = (atom_info['chain'], atom_info['residue'], atom_info['residue_num'])
                if residue_key not in self.residues:
                    self.residues.append(residue_key)

    def get_id(self):
        """Get the unique identifier for this protein instance."""
        return self.unique_id

    def to_json(self):
        """Convert the protein instance to JSON."""
        return json.dumps({
            'identifier': self.identifier,
            'unique_id': self.unique_id,  # Added unique_id to JSON serialization
            'method': self.method,
            'file_path': self.file_path,
            'import_date': self.import_date,
            'atoms': self.atoms,
            'chains': self.chains,
            'residues': self.residues
        })

    @classmethod
    def from_json(cls, json_str):
        """Create a Protein instance from JSON."""
        data = json.loads(json_str)
        protein = cls(data['identifier'], data['method'])
        protein.unique_id = data['unique_id']  # Restore unique_id from JSON
        protein.file_path = data['file_path']
        protein.import_date = data['import_date']
        protein.atoms = data['atoms']
        protein.chains = data['chains']
        protein.residues = data['residues']
        return protein 

class ProteinModel:
    def __init__(self):
        self.objects = []  # List of Blender object references
        self.scale = Vector((1.0, 1.0, 1.0))
        self.center_of_mass = Vector((0.0, 0.0, 0.0))
        self.rotation = Vector((0.0, 0.0, 0.0))
        self.style = RenderStyle.BALL_AND_STICK
        
        # Ensure materials exist
        if not ATOM_MATERIALS:
            create_atom_materials()

    def create_model(self, protein, style=None, position=None, scale=None, rotation=None):
        """Create or recreate the 3D model with given parameters.
        
        Args:
            protein (Protein): The protein instance containing atom data
            style (RenderStyle, optional): Style to render the protein in
            position (Vector, optional): Position for the center of mass
            scale (Vector, optional): Scale factors for x, y, z
            rotation (Vector, optional): Rotation angles in radians
        """
        # Remove existing model if any
        self.remove_model()
        
        # Update parameters if provided
        if style: self.style = style
        if position: self.center_of_mass = position
        if scale: self.scale = scale
        if rotation: self.rotation = rotation
        
        # Find suitable position if none provided
        if not position:
            self.center_of_mass = self.find_available_position()
        
        # Create model based on style
        if self.style == RenderStyle.BALL_AND_STICK:
            self._create_ball_and_stick(protein)
        elif self.style == RenderStyle.RIBBON:
            self._create_ribbon(protein)
        elif self.style == RenderStyle.SPHERES:
            self._create_spheres(protein)
        elif self.style == RenderStyle.CARTOON:
            self._create_cartoon(protein)
        elif self.style == RenderStyle.SURFACE:
            self._create_surface(protein)
        elif self.style == RenderStyle.HIDDEN:
            return
        
        # Apply transformations to all objects
        # self._apply_transformations()

    def calculate_center_of_mass(self, protein):
        """Calculate the center of mass of the protein."""
        if not protein.atoms:
            return Vector((0, 0, 0))
            
        total = Vector((0, 0, 0))
        for atom in protein.atoms:
            total += Vector(atom['position'])
        return total / len(protein.atoms)

    def _create_ball_and_stick(self, protein):
        """Create ball and stick representation efficiently."""
        com = self.calculate_center_of_mass(protein)
        
        # Create a low-resolution base sphere mesh
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=16, ring_count=8)
        base_sphere = bpy.context.active_object
        base_sphere_mesh = base_sphere.data
        bpy.data.objects.remove(base_sphere, do_unlink=True)
        
        # Create base cylinder for bonds
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=1.0, vertices=8)
        base_cylinder = bpy.context.active_object
        base_cylinder_mesh = base_cylinder.data
        bpy.data.objects.remove(base_cylinder, do_unlink=True)
        
        # Set smooth shading for both base meshes
        for mesh in [base_sphere_mesh, base_cylinder_mesh]:
            for polygon in mesh.polygons:
                polygon.use_smooth = True

        # Create bond material if it doesn't exist
        if 'bond_material' not in bpy.data.materials:
            bond_mat = bpy.data.materials.new(name='bond_material')
            bond_mat.use_nodes = True
            nodes = bond_mat.node_tree.nodes
            bsdf = nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1.0)
                bsdf.inputs["Metallic"].default_value = 0.2
                bsdf.inputs["Roughness"].default_value = 0.7

        atom_objects = []
        atom_positions = {}  # Store atom positions for bond creation
        counter = 0
        
        # Create atoms (existing code...)
        for atom in protein.atoms:
            atom_symbol = atom['symbol'].strip().upper()
            # Create a copy of the base mesh for each atom
            atom_mesh = base_sphere_mesh.copy()
            obj = bpy.data.objects.new(
                name=f"atom_{protein.identifier}_{atom_symbol}_{counter}",
                object_data=atom_mesh  # Use the copied mesh instead of the base mesh
            )
            # Get atom size
            relative_size = ATOM_RELATIVE_SIZES.get(atom_symbol, 1.0)

            # Calculate position relative to center of mass
            pos = Vector(atom['position']) - com
            obj.location = pos * GLOBAL_SCALE

            # Apply relative size
            base_size = GLOBAL_SCALE * relative_size
            obj.scale = Vector((base_size, base_size, base_size))
            
            # Assign material (reuse materials to optimize performance)
            obj.data.materials.clear()
            obj.data.materials.append(ATOM_MATERIALS.get(atom_symbol, ATOM_MATERIALS['C']))
            
            atom_objects.append(obj)
            pos = Vector(atom['position']) - com
            atom_positions[counter] = pos
            counter += 1

        # Create bonds
        bond_objects = []
        processed_pairs = set()  # Keep track of processed bonds
        '''
        for i, atom1 in enumerate(protein.atoms):
            pos1 = atom_positions[i]
            
            # Check nearby atoms for bonds
            for j, atom2 in enumerate(protein.atoms):
                if i >= j or (i, j) in processed_pairs:
                    continue
                    
                pos2 = atom_positions[j]
                distance = (pos2 - pos1).length
                
                # Bond distance threshold (adjust as needed)
                if distance < 2.0:  # Typical bond length is ~1.5 Å
                    # Create bond (cylinder)
                    bond_mesh = base_cylinder_mesh.copy()
                    bond_obj = bpy.data.objects.new(
                        name=f"bond_{protein.identifier}_{i}_{j}",
                        object_data=bond_mesh
                    )
                    
                    # Position and orient bond
                    mid_point = (pos1 + pos2) / 2
                    bond_obj.location = mid_point * GLOBAL_SCALE
                    
                    # Calculate rotation to point cylinder between atoms
                    direction = pos2 - pos1
                    rot_quat = direction.to_track_quat('-Z', 'Y')
                    bond_obj.rotation_mode = 'QUATERNION'
                    bond_obj.rotation_quaternion = rot_quat
                    
                    # Scale cylinder to match bond length
                    bond_length = direction.length
                    bond_obj.scale = Vector((0.1, 0.1, bond_length / 2)) * GLOBAL_SCALE
                    
                    # Assign material
                    bond_obj.data.materials.clear()
                    bond_obj.data.materials.append(bpy.data.materials['bond_material'])
                    
                    bond_objects.append(bond_obj)
                    processed_pairs.add((i, j))
        '''
        # Batch link objects to scene
        scene_collection = bpy.context.scene.collection
        for obj in atom_objects + bond_objects:
            scene_collection.objects.link(obj)

        # Offset all objects by available position
        available_pos = self.find_available_position()
        for obj in atom_objects + bond_objects:
            obj.location += available_pos
            self.add_object_to_model(obj)

   
    def _create_ribbon(self, protein):
        """Create ribbon representation efficiently."""
        # Calculate center of mass first
        com = self.calculate_center_of_mass(protein)
        
        # Create curve
        curve = bpy.data.curves.new('protein_ribbon', 'CURVE')
        curve.dimensions = '3D'
        curve.resolution_u = 12
        curve_obj = bpy.data.objects.new('protein_ribbon', curve)
        
        # Create spline from backbone atoms
        spline = curve.splines.new('BEZIER')
        backbone_atoms = [atom for atom in protein.atoms if atom['symbol'] == 'CA']
        
        if backbone_atoms:
            # Pre-allocate points
            spline.bezier_points.add(len(backbone_atoms)-1)
            
            # Batch set point locations
            for idx, atom in enumerate(backbone_atoms):
                point = spline.bezier_points[idx]
                pos = Vector(atom['position']) - com
                point.co = pos * GLOBAL_SCALE
                point.handle_left_type = 'AUTO'
                point.handle_right_type = 'AUTO'
            
            # Find available position and offset
            available_pos = self.find_available_position()
            curve_obj.location = available_pos
        
        # Link to scene
        bpy.context.scene.collection.objects.link(curve_obj)
        self.add_object_to_model(curve_obj)

    def _create_spheres(self, protein):
        """Create space-filling (CPK) representation efficiently."""
        # Similar updates to _create_ball_and_stick but with van der Waals radii
        # ... implementation similar to above but with different radii ...
        pass

    def _create_cartoon(self, protein):
        """Create cartoon representation efficiently."""
        # Similar to ribbon but with additional geometry for secondary structure
        # Implementation will depend on secondary structure detection
        pass

    def _create_surface(self, protein):
        """Create surface representation efficiently."""
        # Will need to implement surface calculation algorithm
        # Could use metaballs for a basic implementation
        pass

    def _apply_transformations(self):
        """Apply scale, rotation, and position to all model objects."""
        for obj in self.objects:
            # Apply scale (multiply with existing scale)
            obj.scale = Vector((
                obj.scale.x * self.scale.x,
                obj.scale.y * self.scale.y,
                obj.scale.z * self.scale.z
            ))
            
            # Apply rotation (relative to center of mass)
            obj.rotation_euler = self.rotation
            
            # Apply position offset (maintaining relative positions)
            obj.location = obj.location + self.center_of_mass

   
    def remove_model(self):
        """Remove all 3D objects associated with this model."""
        for obj in self.objects:
            if obj and obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        self.objects.clear()
    
    def select_model(self):
        """Select all objects associated with this model."""
        # Deselect all objects first
        bpy.ops.object.select_all(action='DESELECT')
        
        # Select our objects
        for obj in self.objects:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
                # Set the last object as active
                bpy.context.view_layer.objects.active = obj
    
    def find_available_position(self, grid_size=5.0):
        """Find an available position for the protein model."""
        occupied_positions = self.get_occupied_positions()
        
        # Start from origin and spiral outward until we find a free spot
        x, y = 0, 0
        dx, dy = 0, -grid_size
        step = 0
        max_steps = 100  # Prevent infinite loops
        
        while step < max_steps:
            current_pos = Vector((x, y, 0))
            
            # Check if position is far enough from all occupied positions
            if self.is_position_available(current_pos, occupied_positions, grid_size):
                return current_pos
            
            # Spiral pattern movement
            if x == y or (x < 0 and x == -y) or (x > 0 and x == 1-y):
                dx, dy = -dy, dx
            
            x += dx
            y += dy
            step += 1
            
        # If no position found, return a default offset position
        return Vector((grid_size * step, 0, 0))
    
    @staticmethod
    def get_occupied_positions():
        """Get list of positions occupied by existing protein models."""
        occupied = []
        for obj in bpy.data.objects:
            if obj.get('is_protein_part', False):  # Check custom property
                occupied.append(obj.location.copy())
        return occupied
    
    @staticmethod
    def is_position_available(pos, occupied_positions, min_distance):
        """Check if a position is far enough from all occupied positions."""
        for occ_pos in occupied_positions:
            if (pos - occ_pos).length < min_distance:
                return False
        return True
    
    def add_object_to_model(self, obj):
        """Add a Blender object to this model and set appropriate properties."""
        obj['is_protein_part'] = True  # Custom property to identify protein objects
        self.objects.append(obj) 