from abc import ABC
from enum import Enum
import bpy
from mathutils import Vector
import uuid
from .base import ProteinVisualizer, RenderStyle
from .constants import ELEMENT_INDICES, ATOM_RELATIVE_SIZES

class ProteinPointCloud(ProteinVisualizer):
    def __init__(self):
        super().__init__()
        self.main_object = None
        self.protein = None
        self.style_node_groups = {}
        self.selected_atoms = set()  # Track selected atoms for highlighting
        
        # Initialize the base node group and style-specific groups
        self.ensure_base_node_group_exists()
        self.ensure_style_node_groups_exist()

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
        geo_mod.node_group = self.base_node_group
        
        # Set up the modifier inputs
        if "Scale" in geo_mod:
            geo_mod["Input_2"] = 1.0  # Base scale
            
        # Set initial style
        style_index = list(RenderStyle).index(self.style)
        if "Style" in geo_mod:
            geo_mod["Input_3"] = style_index

    def remove_model(self):
        """Remove all objects associated with this model."""
        if self.main_object:
            bpy.data.objects.remove(self.main_object, do_unlink=True)
            self.main_object = None
            self.protein = None
            self.selected_atoms.clear()

    def select_chain(self, chain_id):
        """Select all atoms in a specific chain."""
        if not self.main_object or not self.protein:
            return
            
        # Get the selection vertex group
        selection_group = self.main_object.vertex_groups.get("Selection")
        if not selection_group:
            selection_group = self.main_object.vertex_groups.new(name="Selection")
            
        # Update selection weights
        for i, atom in enumerate(self.protein.atoms):
            weight = 1.0 if atom['chain'] == chain_id else 0.0
            selection_group.add([i], weight, 'REPLACE')
            
        # Update the selected atoms set
        self.selected_atoms = {i for i, atom in enumerate(self.protein.atoms) 
                             if atom['chain'] == chain_id}

    def select_residue(self, chain_id, residue_name, residue_num):
        """Select all atoms in a specific residue."""
        if not self.main_object or not self.protein:
            return
            
        # Get the selection vertex group
        selection_group = self.main_object.vertex_groups.get("Selection")
        if not selection_group:
            selection_group = self.main_object.vertex_groups.new(name="Selection")
            
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
        obj = bpy.data.objects.new(f"protein_{protein.identifier}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        
        # Prepare atom data
        positions = []
        atom_types = []
        scales = []
        selection_weights = []
        
        for i, atom in enumerate(protein.atoms):
            # Get atom position relative to center of mass
            pos = Vector(atom['position']) - com
            positions.append(pos)
            
            # Store atom type and scale
            atom_symbol = atom['symbol'].strip().upper()
            atom_types.append(ELEMENT_INDICES.get(atom_symbol, 0))
            scales.append(ATOM_RELATIVE_SIZES.get(atom_symbol, 1.0))
            selection_weights.append(0.0)
        
        # Create vertices for each atom position
        mesh.from_pydata(positions, [], [])
        mesh.update()
        
        # Store attributes
        atom_type_layer = mesh.attributes.new(name="atom_type", type='INT', domain='POINT')
        atom_type_layer.data.foreach_set("value", atom_types)
        
        scale_layer = mesh.attributes.new(name="scale", type='FLOAT', domain='POINT')
        scale_layer.data.foreach_set("value", scales)
        
        # Create selection vertex group
        selection_group = obj.vertex_groups.new(name="Selection")
        for i, weight in enumerate(selection_weights):
            selection_group.add([i], weight, 'REPLACE')
        
        # Apply transformations
        obj.location = self.center_of_mass
        obj.rotation_euler = self.rotation
        obj.scale = self.scale
        
        return obj

    def _calculate_center_of_mass(self, protein):
        """Calculate the center of mass of the protein."""
        if not protein.atoms:
            return Vector((0, 0, 0))
            
        total_pos = Vector((0, 0, 0))
        for atom in protein.atoms:
            total_pos += Vector(atom['position'])
            
        return total_pos / len(protein.atoms) 

    def ensure_base_node_group_exists(self):
        """Create or get the base geometry nodes setup."""
        GROUP_NAME = "ProteinVisualizationBase"
        
        if GROUP_NAME not in bpy.data.node_groups:
            self.create_base_node_group(GROUP_NAME)
        
        self.base_node_group = bpy.data.node_groups[GROUP_NAME]

    def create_base_node_group(self, name):
        """Create the base geometry nodes setup that handles style switching."""
        try:
            node_group = bpy.data.node_groups.new(name=name, type='GeometryNodeTree')
            
            # Create input/output sockets
            group_input = node_group.nodes.new('NodeGroupInput')
            group_output = node_group.nodes.new('NodeGroupOutput')
            
            # Add required interface sockets
            node_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
            node_group.interface.new_socket(name="Scale", in_out='INPUT', socket_type='NodeSocketFloat')
            node_group.interface.new_socket(name="Style", in_out='INPUT', socket_type='NodeSocketInt')
            node_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
            
            # For style switching, we'll use a more appropriate approach:
            # Create separate node groups for each style and use them as inputs to the switch
            switch_setup = self.create_switch_setup(node_group)
            
            # Position nodes
            group_input.location = (-400, 0)
            switch_setup.location = (0, 0)
            group_output.location = (400, 0)
            
            # Link nodes
            links = node_group.links
            links.new(group_input.outputs["Style"], switch_setup.inputs[0])  # Switch control input
            links.new(switch_setup.outputs[0], group_output.inputs[0])  # Output geometry
            
            return node_group
        except Exception as e:
            print(f"Error creating base node group: {str(e)}")
            raise

    def create_switch_setup(self, node_group):
        """Create a switch setup using native Blender nodes."""
        try:
            # Create a Compare node to check the style index
            compare = node_group.nodes.new('FunctionNodeCompare')
            compare.data_type = 'INT'
            compare.operation = 'EQUAL'
            
            # Create Join Geometry node to combine all styles
            join = node_group.nodes.new('GeometryNodeJoinGeometry')
            
            return join
            
        except Exception as e:
            print(f"Error creating switch setup: {str(e)}")
            raise

    def ensure_style_node_groups_exist(self):
        """Create or get all style-specific node groups."""
        for style in RenderStyle:
            group_name = f"ProteinStyle_{style.value}"
            if group_name not in bpy.data.node_groups:
                self.create_style_node_group(style)
            self.style_node_groups[style] = bpy.data.node_groups[group_name]
    
    def create_style_node_group(self, style):
        """Create a node group for a specific visualization style."""
        group_name = f"ProteinStyle_{style.value}"
        node_group = bpy.data.node_groups.new(name=group_name, type='GeometryNodeTree')
        
        # Create basic in/out interface
        group_input = node_group.nodes.new('NodeGroupInput')
        group_output = node_group.nodes.new('NodeGroupOutput')
        
        node_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        node_group.interface.new_socket(name="Scale", in_out='INPUT', socket_type='NodeSocketFloat')
        node_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        
        self.setup_surface_style(node_group, group_input, group_output)
        '''
        # Create style-specific nodes based on visualization type
        if style == RenderStyle.SPHERES:
            self.setup_spheres_style(node_group, group_input, group_output)
        elif style == RenderStyle.BALL_AND_STICK:
            self.setup_ball_and_stick_style(node_group, group_input, group_output)
        elif style == RenderStyle.CARTOON:
            self.setup_cartoon_style(node_group, group_input, group_output)
        elif style == RenderStyle.SURFACE:
            self.setup_surface_style(node_group, group_input, group_output)
        elif style == RenderStyle.RIBBON:
            self.setup_ribbon_style(node_group, group_input, group_output)
        '''
    
    def setup_spheres_style(self, node_group, group_input, group_output):
        """Set up nodes for sphere-style visualization."""
        # Create UV Sphere for atoms
        sphere = node_group.nodes.new('GeometryNodeMeshUVSphere')
        sphere.inputs["Segments"].default_value = 32
        sphere.inputs["Rings"].default_value = 16
        
        # Create instance on points node
        instance = node_group.nodes.new('GeometryNodeInstanceOnPoints')
        
        # Position nodes
        group_input.location = (-400, 0)
        sphere.location = (-200, 0)
        instance.location = (0, 0)
        group_output.location = (200, 0)
        
        # Link nodes
        links = node_group.links
        links.new(group_input.outputs["Geometry"], instance.inputs["Points"])
        links.new(sphere.outputs["Mesh"], instance.inputs["Instance"])
        links.new(instance.outputs["Instances"], group_output.inputs[0])
    
    def change_visualization_style(self, style: RenderStyle):
        """Change the visualization style of the protein."""
        if not self.main_object:
            return
            
        # Get the geometry nodes modifier
        geo_mod = self.main_object.modifiers.get("ProteinGeometry")
        if not geo_mod:
            return
        
        # Update the style input
        style_index = list(RenderStyle).index(style)
        if "Style" in geo_mod:
            geo_mod["Input_3"] = style_index
        
        self.current_style = style

    def setup_ball_and_stick_style(self, node_group, group_input, group_output):
        """Set up nodes for ball-and-stick visualization."""
        try:
            # Create nodes for spheres (atoms)
            sphere = node_group.nodes.new('GeometryNodeMeshUVSphere')
            sphere.inputs["Segments"].default_value = 16
            sphere.inputs["Rings"].default_value = 8
            
            # Instance spheres on points
            instance = node_group.nodes.new('GeometryNodeInstanceOnPoints')
            
            # Transform the instances
            transform = node_group.nodes.new('GeometryNodeTransform')
            transform.inputs["Scale"].default_value = [0.3, 0.3, 0.3]  # Smaller spheres
            
            # For bonds, we'll create cylinders between points
            # First, create a cylinder for bonds
            cylinder = node_group.nodes.new('GeometryNodeMeshCylinder')
            cylinder.inputs["Radius"].default_value = 0.05
            cylinder.inputs["Depth"].default_value = 1.0
            cylinder.inputs["Vertices"].default_value = 8
            
            # Instance cylinders for bonds
            instance_bonds = node_group.nodes.new('GeometryNodeInstanceOnPoints')
            
            # Instead of trying to modify the Join Geometry node, we'll chain two of them
            join1 = node_group.nodes.new('GeometryNodeJoinGeometry')
            join2 = node_group.nodes.new('GeometryNodeJoinGeometry')
            
            # Position nodes
            group_input.location = (-600, 0)
            sphere.location = (-400, 200)
            instance.location = (-200, 200)
            transform.location = (0, 200)
            cylinder.location = (-400, -200)
            instance_bonds.location = (-200, -200)
            join1.location = (200, 100)
            join2.location = (200, -100)
            group_output.location = (400, 0)
            
            # Link nodes
            links = node_group.links
            # Sphere setup (atoms)
            links.new(group_input.outputs["Geometry"], instance.inputs["Points"])
            links.new(sphere.outputs["Mesh"], instance.inputs["Instance"])
            links.new(instance.outputs["Instances"], transform.inputs["Geometry"])
            
            # Bond setup (basic - just cylinder instances)
            links.new(group_input.outputs["Geometry"], instance_bonds.inputs["Points"])
            links.new(cylinder.outputs["Mesh"], instance_bonds.inputs["Instance"])
            
            # Join geometry using two join nodes in sequence
            links.new(transform.outputs[0], join1.inputs[0])  # First join gets atoms
            links.new(instance_bonds.outputs[0], join2.inputs[0])  # Second join gets bonds
            links.new(join1.outputs[0], join2.inputs[0])  # Connect first join to second
            links.new(join2.outputs[0], group_output.inputs[0])  # Output final result
            
        except Exception as e:
            print(f"Error setting up ball and stick style: {str(e)}\n")
            import traceback
            traceback.print_exc()
            raise

    def setup_cartoon_style(self, node_group, group_input, group_output):
        """Set up nodes for cartoon visualization."""
        try:
            # Create nodes
            # Instead of CurveSpline, we'll use a more basic approach with curves
            curve_line = node_group.nodes.new('GeometryNodeCurveToMesh')
            
            # Create profile circle for the tube
            circle = node_group.nodes.new('GeometryNodeCurvePrimitiveCircle')
            circle.inputs["Radius"].default_value = 0.2
            
            # Smooth the result
            smooth = node_group.nodes.new('GeometryNodeSubdivisionSurface')
            smooth.inputs["Level"].default_value = 2
            
            # Position nodes
            group_input.location = (-600, 0)
            circle.location = (-400, -200)
            curve_line.location = (-200, 0)
            smooth.location = (0, 0)
            group_output.location = (200, 0)
            
            # Link nodes
            links = node_group.links
            links.new(circle.outputs["Curve"], curve_line.inputs["Profile Curve"])
            links.new(group_input.outputs["Geometry"], curve_line.inputs["Curve"])
            links.new(curve_line.outputs[0], smooth.inputs[0])
            links.new(smooth.outputs[0], group_output.inputs[0])
            
        except Exception as e:
            print(f"Error setting up cartoon style: {str(e)}\n")
            import traceback
            traceback.print_exc()
            raise
    
    def setup_surface_style(self, node_group, group_input, group_output):
        """Set up nodes for surface visualization."""
        try:
            # Print all inputs for debugging
            mesh_to_vol = node_group.nodes.new('GeometryNodeMeshToVolume')
            print("MeshToVolume inputs:", [input.name for input in mesh_to_vol.inputs])
            
            vol_to_mesh = node_group.nodes.new('GeometryNodeVolumeToMesh')
            print("VolumeToMesh inputs:", [input.name for input in vol_to_mesh.inputs])
            
        except Exception as e:
            print(f"Error setting up surface style: {str(e)}\n")
            import traceback
            traceback.print_exc()
            raise

    def setup_ribbon_style(self, node_group, group_input, group_output):
        """Set up nodes for ribbon visualization."""
        try:
            # Create a rectangular profile for the ribbon
            profile = node_group.nodes.new('GeometryNodeCurvePrimitiveQuadrilateral')
            profile.inputs["Width"].default_value = 0.4
            profile.inputs["Height"].default_value = 0.1
            
            # Convert to mesh along the backbone
            curve_to_mesh = node_group.nodes.new('GeometryNodeCurveToMesh')
            
            # Smooth the result
            smooth = node_group.nodes.new('GeometryNodeSubdivisionSurface')
            smooth.inputs["Level"].default_value = 2
            
            # Position nodes
            group_input.location = (-600, 0)
            profile.location = (-400, -200)
            curve_to_mesh.location = (-200, 0)
            smooth.location = (0, 0)
            group_output.location = (200, 0)
            
            # Link nodes
            links = node_group.links
            links.new(group_input.outputs["Geometry"], curve_to_mesh.inputs["Curve"])
            links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
            links.new(curve_to_mesh.outputs[0], smooth.inputs[0])
            links.new(smooth.outputs[0], group_output.inputs[0])
            
        except Exception as e:
            print(f"Error setting up ribbon style: {str(e)}\n")
            import traceback
            traceback.print_exc()
            raise
        
    def ensure_style_node_groups_exist(self):
        """Create or get all style-specific node groups."""
        try:
            for style in RenderStyle:
                group_name = f"ProteinStyle_{style.value}"
                if group_name not in bpy.data.node_groups:
                    self.create_style_node_group(style)
                self.style_node_groups[style] = bpy.data.node_groups[group_name]
            
            # Connect styles to base node group
            self.connect_style_to_base()
        except Exception as e:
            print(f"Error ensuring style node groups: {str(e)}")
            raise

    def connect_style_to_base(self):
        """Connect style node groups to the base group."""
        try:
            if not self.base_node_group:
                raise ValueError("Base node group not initialized")
            
            # Find the join geometry nodes in the base group
            joins = [node for node in self.base_node_group.nodes 
                    if node.type == 'JOIN_GEOMETRY']
            
            if not joins:
                raise ValueError("Join nodes not found in base group")
            
            # Create and connect all style nodes
            for i, style in enumerate(RenderStyle):
                style_group = self.style_node_groups.get(style)
                if not style_group:
                    continue
                
                # Create a Group node in the base group for this style
                style_node = self.base_node_group.nodes.new('GeometryNodeGroup')
                style_node.node_tree = style_group
                style_node.location = (-200, -200 * i)
                
                # Connect the style group
                links = self.base_node_group.links
                
                # Connect geometry input
                links.new(self.base_node_group.nodes["Group Input"].outputs["Geometry"],
                         style_node.inputs["Geometry"])
                
                # Connect scale input if it exists
                if "Scale" in style_node.inputs:
                    links.new(self.base_node_group.nodes["Group Input"].outputs["Scale"],
                             style_node.inputs["Scale"])
                
                # Connect to last join node
                links.new(style_node.outputs["Geometry"], joins[-1].inputs[0])
                
        except Exception as e:
            print(f"Error connecting styles to base: {str(e)}\n")
            import traceback
            traceback.print_exc()
            raise

    def create_base_node_group(self, name):
        """Create the base geometry nodes setup."""
        try:
            node_group = bpy.data.node_groups.new(name=name, type='GeometryNodeTree')
            
            # Create input/output sockets
            group_input = node_group.nodes.new('NodeGroupInput')
            group_output = node_group.nodes.new('NodeGroupOutput')
            
            # Add required interface sockets
            node_group.interface.new_socket(name="Geometry", in_out='INPUT', 
                                          socket_type='NodeSocketGeometry')
            node_group.interface.new_socket(name="Scale", in_out='INPUT', 
                                          socket_type='NodeSocketFloat')
            node_group.interface.new_socket(name="Style", in_out='INPUT', 
                                          socket_type='NodeSocketInt')
            node_group.interface.new_socket(name="Geometry", in_out='OUTPUT', 
                                          socket_type='NodeSocketGeometry')
            
            # Create join geometry node for combining styles
            join = node_group.nodes.new('GeometryNodeJoinGeometry')
            
            # Position nodes
            group_input.location = (-400, 0)
            join.location = (0, 0)
            group_output.location = (400, 0)
            
            # Link nodes
            links = node_group.links
            links.new(join.outputs[0], group_output.inputs[0])  # Output geometry
            
            return node_group
            
        except Exception as e:
            print(f"Error creating base node group: {str(e)}\n")
            import traceback
            traceback.print_exc()
            raise