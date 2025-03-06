from typing import Optional, Dict, Tuple, List
import bpy
from bpy.types import PropertyGroup
from bpy.props import (BoolProperty, StringProperty, IntProperty, PointerProperty, 
                      FloatVectorProperty, FloatProperty, EnumProperty)
from ..utils.molecularnodes.blender import nodes

class DomainProperties(PropertyGroup):
    """Complete domain properties class to encapsulate all domain data"""
    # Basic properties
    is_expanded: BoolProperty(default=False, 
                              description="Whether domain settings are expanded in UI")
    
    # Identifier and name
    domain_id: StringProperty(name="Domain ID", 
                            description="Unique identifier for this domain")
    name: StringProperty(name="Name", 
                       description="Display name for this domain")
    
    # Chain and residue range
    chain_id: StringProperty(name="Chain", 
                           description="Chain ID for this domain")
    start: IntProperty(name="Start", 
                      description="Starting residue number", 
                      min=1, default=1)
    end: IntProperty(name="End", 
                    description="Ending residue number", 
                    min=1, default=9999)
    
    # Display properties
    color: FloatVectorProperty(name="Color", 
                             description="Color for domain visualization",
                             subtype='COLOR', size=4, 
                             min=0.0, max=1.0, 
                             default=(0.8, 0.1, 0.8, 1.0))  # Default to purple
    
    # Internal references
    parent_molecule_id: StringProperty(description="ID of parent molecule")
    object_name: StringProperty(description="Name of the Blender object for this domain")
    node_group_name: StringProperty(description="Name of the node group for this domain")

class DomainDefinition:
    """Represents the logical definition of a domain with its own geometry nodes network"""
    def __init__(self, chain_id: str, start: int, end: int, name: Optional[str] = None):
        self.chain_id = chain_id
        self.start = start
        self.end = end
        self.name = name or f"Domain_{chain_id}_{start}_{end}"
        self.parent_molecule_id = None  # Link to parent molecule
        self.object = None  # Blender object reference
        self.node_group = None  # Geometry nodes network
        self._setup_complete = False
        self.color = (0.8, 0.1, 0.8, 1.0)  # Default purple color
        self.domain_id = f"{chain_id}_{start}_{end}"

    def to_properties(self) -> Dict:
        """Convert domain definition to property dictionary for storing in PropertyGroup"""
        props = {
            'domain_id': self.domain_id,
            'name': self.name,
            'chain_id': self.chain_id,
            'start': self.start,
            'end': self.end,
            'parent_molecule_id': self.parent_molecule_id,
            'object_name': self.object.name if self.object else "",
            'node_group_name': self.node_group.name if self.node_group else "",
            'color': self.color,
            'is_expanded': False
        }
        return props
        
    @classmethod
    def from_properties(cls, props) -> 'DomainDefinition':
        """Create a domain definition from properties"""
        domain = cls(
            chain_id=props.chain_id,
            start=props.start,
            end=props.end,
            name=props.name
        )
        domain.parent_molecule_id = props.parent_molecule_id
        domain.domain_id = props.domain_id
        
        # Find object and node group by name
        if props.object_name and props.object_name in bpy.data.objects:
            domain.object = bpy.data.objects[props.object_name]
        
        if props.node_group_name and props.node_group_name in bpy.data.node_groups:
            domain.node_group = bpy.data.node_groups[props.node_group_name]
            
        # Set color
        domain.color = props.color
        
        # Set setup state based on whether object and node group exist
        domain._setup_complete = bool(domain.object and domain.node_group)
        
        return domain

    def create_object_from_parent(self, parent_obj: bpy.types.Object) -> bool:
        """Create a new Blender object for the domain by copying parent"""
        try:
            # First verify parent has required modifier
            parent_modifier = parent_obj.modifiers.get("MolecularNodes")
            if not parent_modifier or not parent_modifier.node_group:
                print("Parent object does not have a valid MolecularNodes modifier")
                return False

            # Copy parent molecule object with data
            self.object = parent_obj.copy()
            self.object.data = parent_obj.data.copy()
            self.object.name = f"{self.name}_{self.chain_id}_{self.start}_{self.end}"
            
            # Copy all modifiers except MolecularNodes
            for mod in parent_obj.modifiers:
                if mod.name != "MolecularNodes":
                    new_mod = self.object.modifiers.new(name=mod.name, type=mod.type)
                    # Copy modifier properties
                    for prop in mod.bl_rna.properties:
                        if not prop.is_readonly:
                            setattr(new_mod, prop.identifier, getattr(mod, prop.identifier))
            
            # Link to scene
            bpy.context.scene.collection.objects.link(self.object)
            
            # Set up initial node group
            if not self._setup_node_group():
                # Clean up if node group setup failed
                bpy.data.objects.remove(self.object, do_unlink=True)
                self.object = None
                return False
            
            return True
        except Exception as e:
            print(f"Error creating domain object: {str(e)}")
            # Clean up if object creation failed
            if self.object:
                bpy.data.objects.remove(self.object, do_unlink=True)
                self.object = None
            return False

    def _setup_node_group(self):
        """Set up the geometry nodes network for the domain by copying parent network"""
        if not self.object:
            return False

        try:
            # Get the parent molecule's node group
            parent_modifier = self.object.modifiers.get("MolecularNodes")
            if not parent_modifier or not parent_modifier.node_group:
                print("Parent molecule has no valid node group")
                return False

            # Copy the parent node group
            parent_node_group = parent_modifier.node_group
            self.node_group = parent_node_group.copy()
            self.node_group.name = f"{self.name}_nodes"

            # Remove the old MolecularNodes modifier and create our new one
            self.object.modifiers.remove(parent_modifier)
            modifier = self.object.modifiers.new(name="DomainNodes", type='NODES')
            modifier.node_group = self.node_group

            # The detailed node setup will be handled by MoleculeWrapper._setup_domain_network
            # We just need to ensure we have a valid node group at this point

            self._setup_complete = True
            return True

        except Exception as e:
            print(f"Error setting up node group: {str(e)}")
            # Clean up if setup failed
            if self.node_group:
                bpy.data.node_groups.remove(self.node_group)
            return False

    def cleanup(self):
        """Remove domain object and node group"""
        if self.object:
            bpy.data.objects.remove(self.object, do_unlink=True)
        if self.node_group:
            bpy.data.node_groups.remove(self.node_group)

# The old Domain class is kept for backward compatibility
class Domain(PropertyGroup):
    """Blender Property Group for UI integration - kept for compatibility"""
    is_expanded: BoolProperty(default=False)
    chain_id: StringProperty()
    start: IntProperty()
    end: IntProperty()
    name: StringProperty()
    object: PointerProperty(type=bpy.types.Object)  # Reference to the domain object

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
            '''
            self.node_group.links.new(original_select_node.outputs["Selection"], style_node.inputs["Selection"])
            self.node_group.links.new(style_node.outputs[0], join_node.inputs[0])
            self.node_group.links.new(join_node.outputs[0], group_output.inputs[0])
            '''
        
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
        '''
        self.node_group.links.new(color_emit.outputs["Color"], set_color.inputs["Color"])
        self.node_group.links.new(group_input.outputs["Atoms"], set_color.inputs["Atoms"])
        self.node_group.links.new(set_color.outputs["Atoms"], style_surface.inputs["Atoms"])
        self.node_group.links.new(select_res_id_range_node.outputs["Selection"], style_surface.inputs["Selection"])
        self.node_group.links.new(style_surface.outputs[0], join_node.inputs[0])
        '''
        
        # Connect Select Res ID Range Inverted output to original Select Res ID Range And input
        '''
        if original_select_node:
            self.node_group.links.new(select_res_id_range_node.outputs["Inverted"], original_select_node.inputs["And"])
        '''
        
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

def register():
    bpy.utils.register_class(Domain)
    bpy.utils.register_class(DomainProperties)
    
def unregister():
    try:
        bpy.utils.unregister_class(DomainProperties)
    except:
        pass
    try:
        bpy.utils.unregister_class(Domain)
    except:
        pass
