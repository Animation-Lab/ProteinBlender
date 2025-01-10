import bpy
from mathutils import Vector
from .base import ProteinVisualizer, RenderStyle
from .constants import GLOBAL_SCALE, ATOM_RELATIVE_SIZES, ELEMENT_INDICES
from .materials import get_or_create_materials, ATOM_MATERIALS, BOND_MATERIALS

class ProteinPointCloud(ProteinVisualizer):
    def __init__(self):
        super().__init__()
        self.main_object = None
        self.node_group = None
        self.selected_atoms = set()  # Track selected atoms for highlighting
        
        # Initialize materials
        get_or_create_materials()
        
        # Create the geometry nodes setup if it doesn't exist
        self.ensure_node_group_exists()
    
    def ensure_node_group_exists(self):
        """Create or get the geometry nodes setup for protein visualization."""
        GROUP_NAME = "ProteinPointCloud"
        
        if GROUP_NAME not in bpy.data.node_groups:
            self.create_geometry_nodes_group(GROUP_NAME)
        
        self.node_group = bpy.data.node_groups[GROUP_NAME]
    
    def create_geometry_nodes_group(self, name):
        """Create the geometry nodes setup for protein visualization."""
        # Create a new node group
        node_group = bpy.data.node_groups.new(name=name, type='GeometryNodeTree')
        
        # Create input and output sockets
        group_input = node_group.nodes.new('NodeGroupInput')
        group_input.location = (-400, 0)
        
        group_output = node_group.nodes.new('NodeGroupOutput')
        group_output.location = (400, 0)
        
        # Add required sockets
        node_group.interface.new_socket(
            name="Geometry",
            in_out='INPUT',
            socket_type='NodeSocketGeometry'
        )
        node_group.interface.new_socket(
            name="Scale",
            in_out='INPUT',
            socket_type='NodeSocketFloat'
        )
        
        # Add output socket
        node_group.interface.new_socket(
            name="Geometry",
            in_out='OUTPUT',
            socket_type='NodeSocketGeometry'
        )
        
        # Create UV Sphere for atoms
        sphere = node_group.nodes.new('GeometryNodeMeshUVSphere')
        sphere.location = (-200, 0)
        sphere.inputs["Segments"].default_value = 32
        sphere.inputs["Rings"].default_value = 16
        sphere.inputs["Radius"].default_value = 1.0  # Increased radius to make it more visible
        
        # Create instance on points node
        instance = node_group.nodes.new('GeometryNodeInstanceOnPoints')
        instance.location = (0, 0)
        
        # Link nodes
        links = node_group.links
        
        # Basic connections
        links.new(group_input.outputs["Geometry"], instance.inputs["Points"])
        links.new(sphere.outputs["Mesh"], instance.inputs["Instance"])
        links.new(instance.outputs["Instances"], group_output.inputs[0])
        
        return node_group

    def create_model(self, protein, style=None, position=None, scale=None, rotation=None):
        """Create or recreate the 3D model with given parameters."""
        # Remove existing model if any
        self.remove_model()
        
        # Store reference to protein for selection methods
        self.protein = protein
        
        # Update parameters if provided
        if style: self.style = style
        if position: self.center_of_mass = position
        if scale: self.scale = scale
        if rotation: self.rotation = rotation
        
        # Create base point cloud
        self.main_object = self.create_point_cloud(protein)
        
        # Add geometry nodes modifier
        geo_mod = self.main_object.modifiers.new(name="ProteinGeometry", type='NODES')
        geo_mod.node_group = self.node_group
        
        # Set up the modifier inputs
        if "Scale" in geo_mod:
            geo_mod["Input_2"] = GLOBAL_SCALE
            print(f"Set global scale to {GLOBAL_SCALE}")
        
        print(f"Created geometry nodes modifier: {geo_mod.name}")
        print(f"Node group: {geo_mod.node_group.name}")

    def remove_model(self):
        """Remove all objects associated with this model."""
        if self.main_object:
            # Remove all bond objects (children)
            for child in self.main_object.children:
                if child.type == 'CURVE':  # Bond objects are curves
                    bpy.data.objects.remove(child, do_unlink=True)
            
            # Remove the main object
            bpy.data.objects.remove(self.main_object, do_unlink=True)
            self.main_object = None
    
    def select_chain(self, chain_id):
        """Select all atoms in a specific chain."""
        if not self.main_object:
            return
            
        # Get the selection vertex group
        selection_group = self.main_object.vertex_groups.get("Selection")
        if not selection_group:
            return
            
        # Update selection weights
        for i, atom in enumerate(self.protein.atoms):
            weight = 1.0 if atom['chain'] == chain_id else 0.0
            selection_group.add([i], weight, 'REPLACE')
            
        # Update the selected atoms set
        self.selected_atoms = {i for i, atom in enumerate(self.protein.atoms) 
                             if atom['chain'] == chain_id}
    
    def select_residue(self, chain_id, residue_name, residue_num):
        """Select all atoms in a specific residue."""
        if not self.main_object:
            return
            
        # Get the selection vertex group
        selection_group = self.main_object.vertex_groups.get("Selection")
        if not selection_group:
            return
            
        # Update selection weights
        for i, atom in enumerate(self.protein.atoms):
            is_selected = (atom['chain'] == chain_id and 
                         atom['residue'] == residue_name and 
                         atom['residue_num'] == residue_num)
            weight = 1.0 if is_selected else 0.0
            selection_group.add([i], weight, 'REPLACE')
            
        # Update the selected atoms set
        self.selected_atoms = {i for i, atom in enumerate(self.protein.atoms) 
                             if (atom['chain'] == chain_id and 
                                 atom['residue'] == residue_name and 
                                 atom['residue_num'] == residue_num)} 

    def create_point_cloud(self, protein):
        """Create a basic point cloud from protein atom positions."""
        # Calculate center of mass
        com = self._calculate_center_of_mass(protein)
        
        # Create the main object that will hold our geometry nodes
        mesh = bpy.data.meshes.new(name=f"protein_{protein.identifier}")
        self.main_object = bpy.data.objects.new(f"protein_{protein.identifier}", mesh)
        bpy.context.scene.collection.objects.link(self.main_object)
        
        # Prepare atom data
        positions = []
        atom_types = []
        scales = []
        selection_weights = []
        
        for i, atom in enumerate(protein.atoms):
            # Get atom position relative to center of mass
            pos = Vector(atom['position']) - com
            positions.append(pos)
            
            # Get atom type index for instancing
            atom_symbol = atom['symbol'].strip().upper()
            atom_type_idx = ELEMENT_INDICES.get(atom_symbol, 0)
            atom_types.append(atom_type_idx)
            
            # Get atom scale based on relative size
            relative_size = ATOM_RELATIVE_SIZES.get(atom_symbol, 1.0)
            scales.append(relative_size)
            
            # Initialize selection weight
            selection_weights.append(0.0)
        
        # Create vertices for each atom position
        mesh.from_pydata(positions, [], [])
        mesh.update()
        
        # Store atom type and scale as vertex attributes
        atom_type_layer = mesh.attributes.new(name="atom_type", type='INT', domain='POINT')
        atom_type_layer.data.foreach_set("value", atom_types)
        
        scale_layer = mesh.attributes.new(name="scale", type='FLOAT', domain='POINT')
        scale_layer.data.foreach_set("value", scales)
        
        # Create vertex group for selection
        selection_group = self.main_object.vertex_groups.new(name="Selection")
        for i, weight in enumerate(selection_weights):
            selection_group.add([i], weight, 'REPLACE')
        
        # Apply transformations
        self.main_object.location = self.center_of_mass
        self.main_object.rotation_euler = self.rotation
        self.main_object.scale = (GLOBAL_SCALE, GLOBAL_SCALE, GLOBAL_SCALE)
        
        # Assign materials to the object
        for symbol, material in ATOM_MATERIALS.items():
            self.main_object.data.materials.append(material)
        
        print(f"Created point cloud with {len(positions)} atoms")
        print(f"Vertex attributes: {[attr.name for attr in mesh.attributes]}")
        print(f"Number of materials: {len(self.main_object.data.materials)}")
        
        return self.main_object

    def _calculate_center_of_mass(self, protein):
        """Calculate the center of mass of the protein."""
        if not protein.atoms:
            return Vector((0, 0, 0))
            
        # Sum up all positions
        total_pos = Vector((0, 0, 0))
        for atom in protein.atoms:
            pos = Vector(atom['position'])
            total_pos += pos
            
        # Divide by number of atoms to get center of mass
        return total_pos / len(protein.atoms) 