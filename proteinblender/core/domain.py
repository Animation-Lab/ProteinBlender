from bpy.types import PropertyGroup
from bpy.props import BoolProperty, StringProperty, IntProperty
from typing import Optional, Dict
import bpy
from ..utils.molecularnodes.blender import nodes

class Domain(PropertyGroup):
    """Represents a continuous segment of amino acids within a chain"""
    is_expanded: BoolProperty(default=False)
    chain_id: StringProperty()
    start: IntProperty()
    end: IntProperty()
    name: StringProperty()

    def __post_init__(self):
        if self.start > self.end:
            self.start, self.end = self.end, self.start 

class ProteinBlenderDomain:
    """Manages domain visualization and node setup in the geometry nodes"""
    
    def __init__(self, node_group: bpy.types.NodeGroup, chain_id: str, start: int, end: int, 
                 domain_index: int = 0, name: Optional[str] = None):
        self.chain_id = chain_id
        self.start = start
        self.end = end
        self.name = name or ""
        self.node_group = node_group
        self.domain_index = domain_index
        self.nodes = {}
        self._setup_domain()
    
    def _setup_domain(self):
        """Set up the domain node structure"""
        # Get existing nodes
        group_input = nodes.get_input(self.node_group)
        group_output = nodes.get_output(self.node_group)
        style_node = nodes.style_node(self.node_group)
        
        # Find existing Join Geometry node and original Select node
        join_node = None
        original_select_node = None
        for node in self.node_group.nodes:
            if node.bl_idname == "GeometryNodeJoinGeometry":
                join_node = node
            elif (node.bl_idname == "GeometryNodeGroup" and 
                  node.node_tree and "Select Res ID Range" in node.node_tree.name):
                original_select_node = node
        
        # If this is the first domain, set up the base structure
        if join_node is None:
            # Create original Select Res ID Range node
            original_select_node = nodes.add_custom(self.node_group, "Select Res ID Range")
            original_select_node.inputs["Min"].default_value = 0
            original_select_node.inputs["Max"].default_value = 9999
            
            # Create Join Geometry node
            join_node = self.node_group.nodes.new("GeometryNodeJoinGeometry")
            
            # Position nodes
            style_pos = style_node.location
            join_node.location = (style_pos[0] + 200, style_pos[1])
            original_select_node.location = (style_pos[0] - 200, style_pos[1] - 200)
            
            # Connect original nodes
            self.node_group.links.new(original_select_node.outputs["Selection"], style_node.inputs["Selection"])
            self.node_group.links.new(style_node.outputs[0], join_node.inputs[0])
            self.node_group.links.new(join_node.outputs[0], group_output.inputs[0])
        
        # Create domain nodes
        color_emit = nodes.add_custom(self.node_group, "Color Common")
        color_emit.outputs["Color"].default_value = (1.0, 1.0, 0.0, 1.0)  # Yellow
        
        set_color = nodes.add_custom(self.node_group, "Set Color")
        select_res_id_range_node = nodes.add_custom(self.node_group, "Select Res ID Range")
        style_surface = nodes.add_custom(self.node_group, "Style Surface")
        
        # Set initial range
        select_res_id_range_node.inputs["Min"].default_value = self.start
        select_res_id_range_node.inputs["Max"].default_value = self.end
        
        # Position nodes
        style_pos = style_node.location
        # We'll need to pass in domain index from outside for proper vertical positioning
        base_y_offset = -300  # This should be adjusted based on domain index
        color_emit.location = (style_pos[0] - 600, style_pos[1] + base_y_offset)
        set_color.location = (style_pos[0] - 400, style_pos[1] + base_y_offset)
        select_res_id_range_node.location = (style_pos[0] - 200, style_pos[1] + base_y_offset)
        style_surface.location = (style_pos[0], style_pos[1] + base_y_offset)
        
        # Connect nodes
        self.node_group.links.new(color_emit.outputs["Color"], set_color.inputs["Color"])
        self.node_group.links.new(group_input.outputs["Atoms"], set_color.inputs["Atoms"])
        self.node_group.links.new(set_color.outputs["Atoms"], style_surface.inputs["Atoms"])
        self.node_group.links.new(select_res_id_range_node.outputs["Selection"], style_surface.inputs["Selection"])
        self.node_group.links.new(style_surface.outputs[0], join_node.inputs[0])
        
        # Connect Select Res ID Range Inverted output to original Select Res ID Range And input
        if original_select_node:
            self.node_group.links.new(select_res_id_range_node.outputs["Inverted"], original_select_node.inputs["And"])
        
        # Store node references
        self.nodes = {
            "select": select_res_id_range_node,
            "style": style_surface,
            "color": color_emit,
            "set_color": set_color,
            "join": join_node,
            "original_select": original_select_node
        }
        
        return self.nodes

    def set_visibility(self, visible: bool):
        """Toggle visibility of the domain"""
        if not self.nodes:
            return
            
        self.nodes["style"].mute = not visible
        self.nodes["color"].mute = not visible
        self.nodes["set_color"].mute = not visible
        self.nodes["select"].mute = not visible

    def update_range(self, start: int, end: int):
        """Update the domain residue range"""
        if not self.nodes:
            return
        
        self.start = start
        self.end = end
        select_node = self.nodes["select"]
        select_node.inputs["Min"].default_value = start
        select_node.inputs["Max"].default_value = end

