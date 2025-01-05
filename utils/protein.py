import json
import os
from datetime import datetime
import uuid
from enum import Enum
import bpy
from mathutils import Vector

# Global materials dictionary
ATOM_MATERIALS = {}
BOND_MATERIALS = {}
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



def create_bond_materials():
    BOND_COLORS = {
        'single': (0.8, 0.8, 0.8, 1.0),  # Gray
        'double': (0.4, 0.4, 0.4, 1.0),  # Dark gray
        'triple': (0.2, 0.2, 0.2, 1.0),  # Black
        'polar': (0.3, 0.7, 1.0, 1.0),   # Light blue
        'nonpolar': (0.4, 1.0, 0.4, 1.0),  # Pale green
        'hydrogen': (1.0, 1.0, 0.0, 1.0)  # Yellow
    }
    """Create or retrieve a material for the given bond type."""
    for bond_type in BOND_COLORS:
        mat = bpy.data.materials.new(name=f"bond_{bond_type}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = BOND_COLORS[bond_type]
        else:
            mat.diffuse_color = BOND_COLORS[bond_type]
        BOND_MATERIALS[bond_type] = mat

def determine_bond_type(atom1, atom2, distance):
    """
    Determine the bond type between two atoms based on their symbols and distance.
    
    Parameters:
    - atom1 (dict): First atom, with keys 'symbol' and 'position'.
    - atom2 (dict): Second atom, with keys 'symbol' and 'position'.
    - distance (float): Distance between the two atoms.

    Returns:
    - str: Bond type ('single', 'double', 'triple', 'hydrogen', 'polar', 'nonpolar').
    """
    # Define bond distance thresholds (in angstroms)
    bond_thresholds = {
        'single': 1.6,
        'double': 1.3,
        'triple': 1.2,
        'hydrogen': 2.0  # Longer threshold for hydrogen bonds
    }

    # Get atomic symbols
    symbol1 = atom1['symbol']
    symbol2 = atom2['symbol']

    # Identify hydrogen bonds
    if 'H' in (symbol1, symbol2) and distance <= bond_thresholds['hydrogen']:
        return 'hydrogen'

    # Classify by bond distance
    if distance <= bond_thresholds['triple']:
        return 'triple'
    elif distance <= bond_thresholds['double']:
        return 'double'
    elif distance <= bond_thresholds['single']:
        return 'single'

    # Classify as polar or nonpolar based on electronegativity difference
    electronegativity = {
        'H': 2.20, 'C': 2.55, 'N': 3.04, 'O': 3.44, 'S': 2.58, 'P': 2.19, 'Cl': 3.16, 'Fe': 1.83
    }
    if symbol1 in electronegativity and symbol2 in electronegativity:
        delta_en = abs(electronegativity[symbol1] - electronegativity[symbol2])
        if delta_en > 0.4:  # Polar bond threshold
            return 'polar'
        else:
            return 'nonpolar'

    # Default to single bond if no other criteria are met
    return 'single'

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
    # Class-level dictionaries to store base meshes
    BASE_ATOM_MESHES = {}
    BASE_BOND_MESHES = {}
    
    @classmethod
    def initialize_base_meshes(cls):
        """Create and store base meshes for atoms and bonds."""
        # Clear existing base meshes
        cls.BASE_ATOM_MESHES.clear()
        cls.BASE_BOND_MESHES.clear()
        
        # Create base sphere for atoms
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=12, ring_count=6)
        base_sphere = bpy.context.active_object
        base_sphere_mesh = base_sphere.data
        
        # Set smooth shading
        for polygon in base_sphere_mesh.polygons:
            polygon.use_smooth = True
            
        # Create atom meshes for each element
        for atom_symbol in ATOM_RELATIVE_SIZES.keys():
            atom_mesh = base_sphere_mesh.copy()
            atom_mesh.materials.clear()
            atom_mesh.materials.append(ATOM_MATERIALS.get(atom_symbol, ATOM_MATERIALS['C']))
            cls.BASE_ATOM_MESHES[atom_symbol] = atom_mesh
            
        # Remove the base sphere
        bpy.data.objects.remove(base_sphere, do_unlink=True)
        
        # Create base cylinder for bonds
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=1.0, vertices=6)
        base_cylinder = bpy.context.active_object
        base_cylinder_mesh = base_cylinder.data
        
        # Set smooth shading
        for polygon in base_cylinder_mesh.polygons:
            polygon.use_smooth = True
            
        # Create bond meshes for each type
        for bond_type in BOND_MATERIALS.keys():
            bond_mesh = base_cylinder_mesh.copy()
            bond_mesh.materials.clear()
            bond_mesh.materials.append(BOND_MATERIALS[bond_type])
            cls.BASE_BOND_MESHES[bond_type] = bond_mesh
            
        # Remove the base cylinder
        bpy.data.objects.remove(base_cylinder, do_unlink=True)

    def __init__(self):
        self.objects = []
        self.scale = Vector((1.0, 1.0, 1.0))
        self.center_of_mass = Vector((0.0, 0.0, 0.0))
        self.rotation = Vector((0.0, 0.0, 0.0))
        self.style = RenderStyle.BALL_AND_STICK
        
        self.structure = {
            'chains': {},
            'all_objects': []
        }
        
        # Ensure materials and base meshes exist
        if not ATOM_MATERIALS:
            create_atom_materials()
            create_bond_materials()
        if not self.BASE_ATOM_MESHES:
            self.initialize_base_meshes()

    def create_model(self, protein, style=None, position=None, scale=None, rotation=None):
        """Create or recreate the 3D model with given parameters."""
        # Remove existing model if any
        self.remove_model()
        
        # Initialize structure for this protein
        for chain_id in protein.chains:
            self.structure['chains'][chain_id] = {
                'residues': {}
            }
            chain_residues = [r for r in protein.residues if r[0] == chain_id]
            for _, residue_name, residue_num in chain_residues:
                self.structure['chains'][chain_id]['residues'][(residue_name, residue_num)] = []

        # Update parameters if provided
        if style: self.style = style
        if position: self.center_of_mass = position
        if scale: self.scale = scale
        if rotation: self.rotation = rotation
        
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
        
        atom_objects = []
        atom_positions = {}
        counter = 0
        
        # Create atoms using pre-made meshes
        for atom in protein.atoms:
            atom_symbol = atom['symbol'].strip().upper()
            # Use existing mesh with material
            obj = bpy.data.objects.new(
                name=f"atom_{protein.identifier}_{atom_symbol}_{counter}",
                object_data=self.BASE_ATOM_MESHES[atom_symbol]
            )
            
            # Calculate position relative to center of mass
            pos = Vector(atom['position']) - com
            obj.location = pos * GLOBAL_SCALE
            
            # Apply relative size
            relative_size = ATOM_RELATIVE_SIZES.get(atom_symbol, 1.0)
            base_size = GLOBAL_SCALE * relative_size
            obj.scale = Vector((base_size, base_size, base_size))
            
            # Add to scene collection
            bpy.context.scene.collection.objects.link(obj)
            
            # Add to internal structure
            self.add_object_to_structure(
                obj,
                atom['chain'],
                atom['residue'],
                atom['residue_num']
            )
            
            atom_objects.append(obj)
            atom_positions[counter] = pos
            counter += 1

        # Create bonds using pre-made meshes
        bond_objects = []
        processed_pairs = set()
        
        for i, atom1 in enumerate(protein.atoms):
            pos1 = atom_positions[i]
            
            for j, atom2 in enumerate(protein.atoms):
                if i >= j or (i, j) in processed_pairs:
                    continue
                    
                pos2 = atom_positions[j]
                distance = (pos2 - pos1).length
                
                if distance < 2.0:
                    # Determine bond type and use corresponding mesh
                    bond_type = determine_bond_type(atom1, atom2, distance)
                    bond_obj = bpy.data.objects.new(
                        name=f"bond_{protein.identifier}_{i}_{j}",
                        object_data=self.BASE_BOND_MESHES[bond_type]
                    )
                    
                    mid_point = (pos1 + pos2) / 2
                    bond_obj.location = mid_point * GLOBAL_SCALE
                    
                    direction = pos2 - pos1
                    if direction.length > 0:
                        rot_quat = direction.to_track_quat('-Z', 'Y')
                        bond_obj.rotation_mode = 'QUATERNION'
                        bond_obj.rotation_quaternion = rot_quat
                        bond_length = direction.length
                        bond_obj.scale = Vector((0.9, 0.9, bond_length / 2)) * GLOBAL_SCALE
                    
                    # Store connection information
                    bond_obj['chain1'] = atom1['chain']
                    bond_obj['residue1_name'] = atom1['residue']
                    bond_obj['residue1_num'] = atom1['residue_num']
                    bond_obj['chain2'] = atom2['chain']
                    bond_obj['residue2_name'] = atom2['residue']
                    bond_obj['residue2_num'] = atom2['residue_num']
                    
                    # Add to scene collection
                    bpy.context.scene.collection.objects.link(bond_obj)
                    
                    # Add to internal structure
                    self.add_object_to_structure(
                        bond_obj,
                        atom1['chain'],
                        atom1['residue'],
                        atom1['residue_num']
                    )
                    
                    if (atom2['chain'] != atom1['chain'] or 
                        atom2['residue'] != atom1['residue'] or 
                        atom2['residue_num'] != atom1['residue_num']):
                        self.add_object_to_structure(
                            bond_obj,
                            atom2['chain'],
                            atom2['residue'],
                            atom2['residue_num']
                        )
                    
                    bond_objects.append(bond_obj)
                    processed_pairs.add((i, j))
                    processed_pairs.add((j, i))

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
        # Remove all objects
        for obj in self.structure['all_objects']:
            if obj and obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        
        # Clear internal structure
        self.structure = {
            'chains': {},
            'all_objects': []
        }

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
        if obj not in self.objects:
            self.objects.append(obj)

    def select_chain(self, chain_id):
        """Select all objects in a specific chain."""
        bpy.ops.object.select_all(action='DESELECT')
        if chain_id in self.structure['chains']:
            for residue_objects in self.structure['chains'][chain_id]['residues'].values():
                for obj in residue_objects:
                    if obj and obj.name in bpy.data.objects:
                        obj.select_set(True)

    def select_residue(self, chain_id, residue_name, residue_num):
        """Select all objects in a specific residue."""
        bpy.ops.object.select_all(action='DESELECT')
        residue_key = (residue_name, residue_num)
        if (chain_id in self.structure['chains'] and 
            residue_key in self.structure['chains'][chain_id]['residues']):
            for obj in self.structure['chains'][chain_id]['residues'][residue_key]:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True) 

    def add_object_to_structure(self, obj, chain_id, residue_name, residue_num):
        """Add an object to the internal structure."""
        # Initialize chain if it doesn't exist
        if chain_id not in self.structure['chains']:
            self.structure['chains'][chain_id] = {'residues': {}}
        
        # Initialize residue if it doesn't exist
        residue_key = (residue_name, residue_num)
        if residue_key not in self.structure['chains'][chain_id]['residues']:
            self.structure['chains'][chain_id]['residues'][residue_key] = []
        
        # Add object to residue list
        self.structure['chains'][chain_id]['residues'][residue_key].append(obj)
        
        # Add to all_objects list if not already there
        if obj not in self.structure['all_objects']:
            self.structure['all_objects'].append(obj)
            self.objects.append(obj)  # Also add to legacy objects list 