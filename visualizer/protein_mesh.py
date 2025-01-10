import bpy
from mathutils import Vector
from .base import ProteinVisualizer, RenderStyle
from .constants import GLOBAL_SCALE, ATOM_RELATIVE_SIZES
from .materials import get_or_create_materials, ATOM_MATERIALS, BOND_MATERIALS

class ProteinMesh(ProteinVisualizer):
    # Class-level dictionaries to store base meshes
    BASE_ATOM_MESHES = {}
    BASE_BOND_MESHES = {}
    
    def __init__(self):
        super().__init__()
        self.structure = {
            'chains': {},
            'all_objects': []
        }
        self.objects = []  # Legacy support
        
        # Initialize materials
        get_or_create_materials()
        
    @classmethod
    def initialize_base_meshes(cls):
        """Create and store base meshes for atoms and bonds."""
        # Clear existing base meshes
        for mesh in cls.BASE_ATOM_MESHES.values():
            if mesh and hasattr(mesh, 'name') and mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)
        cls.BASE_ATOM_MESHES.clear()
        
        for mesh in cls.BASE_BOND_MESHES.values():
            if mesh and hasattr(mesh, 'name') and mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)
        cls.BASE_BOND_MESHES.clear()
        
        # Create base sphere for atoms
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=12, ring_count=6)
        base_sphere = bpy.context.active_object
        base_sphere_mesh = base_sphere.data
        
        # Set smooth shading
        for polygon in base_sphere_mesh.polygons:
            polygon.use_smooth = True
            
        # Create atom meshes for each element
        for atom_symbol in ATOM_MATERIALS.keys():
            # atom_mesh = bpy.data.meshes.new(name=f"base_atom_{atom_symbol}")
            # atom_mesh.copy_from(base_sphere_mesh)
            atom_mesh = base_sphere_mesh.copy()
            atom_mesh.materials.clear()
            atom_mesh.materials.append(ATOM_MATERIALS[atom_symbol])
            cls.BASE_ATOM_MESHES[atom_symbol] = atom_mesh
            
        # Remove the base sphere
        bpy.data.objects.remove(base_sphere, do_unlink=True)
        bpy.data.meshes.remove(base_sphere_mesh)
        
        # Create base cylinder for bonds
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=1.0, vertices=8)
        base_cylinder = bpy.context.active_object
        base_cylinder_mesh = base_cylinder.data
        
        # Set smooth shading
        for polygon in base_cylinder_mesh.polygons:
            polygon.use_smooth = True
            
        # Create bond meshes for each type
        for bond_type in BOND_MATERIALS.keys():
            # bond_mesh = bpy.data.meshes.new(name=f"base_bond_{bond_type}")
            # bond_mesh.copy_from(base_cylinder_mesh)
            bond_mesh = base_cylinder_mesh.copy()
            bond_mesh.materials.clear()
            bond_mesh.materials.append(BOND_MATERIALS[bond_type])
            cls.BASE_BOND_MESHES[bond_type] = bond_mesh
            
        # Remove the base cylinder
        bpy.data.objects.remove(base_cylinder, do_unlink=True)
        bpy.data.meshes.remove(base_cylinder_mesh)

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

        # Apply any transformations
        self._apply_transformations() 

    def _create_ball_and_stick(self, protein):
        """Create ball and stick representation efficiently."""
        # Calculate center of mass first
        com = self.calculate_center_of_mass(protein)
        
        # Create atom objects
        atom_objects = []
        atom_positions = []
        
        # Initialize base meshes if not already done
        if not self.BASE_ATOM_MESHES:
            self.initialize_base_meshes()
        
        # Create atoms
        for i, atom in enumerate(protein.atoms):
            pos = Vector(atom['position']) - com
            atom_positions.append(pos)
            
            # Get atom symbol and corresponding mesh
            atom_symbol = atom['symbol'].strip().upper()
            if atom_symbol not in self.BASE_ATOM_MESHES:
                continue  # Skip if we don't have a mesh for this atom type
                
            # Create atom object
            atom_obj = bpy.data.objects.new(
                name=f"atom_{protein.identifier}_{i}",
                object_data=self.BASE_ATOM_MESHES[atom_symbol]
            )
            
            # Set position and scale
            atom_obj.location = pos * GLOBAL_SCALE
            relative_size = ATOM_RELATIVE_SIZES.get(atom_symbol, 1.0)
            atom_obj.scale = Vector((relative_size, relative_size, relative_size)) * GLOBAL_SCALE
            
            # Store atom information
            atom_obj['chain'] = atom['chain']
            atom_obj['residue_name'] = atom['residue']
            atom_obj['residue_num'] = atom['residue_num']
            
            # Add to scene collection
            bpy.context.scene.collection.objects.link(atom_obj)
            
            # Add to internal structure
            self.add_object_to_structure(
                atom_obj,
                atom['chain'],
                atom['residue'],
                atom['residue_num']
            )
            
            atom_objects.append(atom_obj)
        
        # Create bonds
        bond_objects = []
        processed_pairs = set()
        
        # Create bonds between atoms
        for i, atom1 in enumerate(protein.atoms):
            pos1 = atom_positions[i]
            
            for j, atom2 in enumerate(protein.atoms):
                if i >= j or (i, j) in processed_pairs:
                    continue
                    
                pos2 = atom_positions[j]
                distance = (pos2 - pos1).length
                
                if distance < 2.0:  # Maximum bond distance
                    # Determine bond type and use corresponding mesh
                    bond_type = protein.determine_bond_type(atom1, atom2, distance)
                    bond_obj = bpy.data.objects.new(
                        name=f"bond_{protein.identifier}_{i}_{j}",
                        object_data=self.BASE_BOND_MESHES[bond_type]
                    )
                    
                    # Set position and orientation
                    mid_point = (pos1 + pos2) / 2
                    bond_obj.location = mid_point * GLOBAL_SCALE
                    
                    direction = pos2 - pos1
                    if direction.length > 0:
                        rot_quat = direction.to_track_quat('-Z', 'Y')
                        bond_obj.rotation_mode = 'QUATERNION'
                        bond_obj.rotation_quaternion = rot_quat
                        bond_length = direction.length
                        bond_obj.scale = Vector((0.9, 0.9, bond_length / 2)) * GLOBAL_SCALE
                    
                    # Store bond information
                    bond_obj['chain1'] = atom1['chain']
                    bond_obj['residue1_name'] = atom1['residue']
                    bond_obj['residue1_num'] = atom1['residue_num']
                    bond_obj['chain2'] = atom2['chain']
                    bond_obj['residue2_name'] = atom2['residue']
                    bond_obj['residue2_num'] = atom2['residue_num']
                    
                    # Add to scene collection
                    bpy.context.scene.collection.objects.link(bond_obj)
                    
                    # Add to internal structure for both residues
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
        backbone_atoms = [atom for atom in protein.atoms if atom['type'].strip() == 'CA']
        
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

    def calculate_center_of_mass(self, protein):
        """Calculate center of mass of the protein."""
        if not protein.atoms:
            return Vector((0, 0, 0))
            
        total_pos = Vector((0, 0, 0))
        for atom in protein.atoms:
            total_pos += Vector(atom['position'])
        return total_pos / len(protein.atoms)

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
        self.objects = []  # Clear legacy support list

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

    def add_object_to_model(self, obj):
        """Add a Blender object to this model and set appropriate properties."""
        obj['is_protein_part'] = True  # Custom property to identify protein objects
        if obj not in self.objects:
            self.objects.append(obj)

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