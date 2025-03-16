from typing import Optional, Dict, Tuple, List
import bpy
from bpy.types import PropertyGroup
from bpy.props import (BoolProperty, StringProperty, IntProperty, PointerProperty, 
                      FloatVectorProperty, FloatProperty, EnumProperty)
from ..utils.molecularnodes.blender import nodes
from ..utils.molecularnodes.style import STYLE_ITEMS

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
    
    # Style property
    style: EnumProperty(name="Style",
                      description="Visualization style for this domain",
                      items=STYLE_ITEMS,
                      default="ribbon")
    
    # Display properties
    color: FloatVectorProperty(name="Color", 
                             description="Color for domain visualization",
                             subtype='COLOR', size=4, 
                             min=0.0, max=1.0, 
                             default=(0.8, 0.1, 0.8, 1.0))  # Default to purple
    
    # Internal references
    parent_molecule_id: StringProperty(description="ID of parent molecule")
    parent_domain_id: StringProperty(description="ID of parent domain")
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
        self.parent_domain_id = None  # Link to parent domain
        self.object = None  # Blender object reference
        self.node_group = None  # Geometry nodes network
        self._setup_complete = False
        self.color = (0.8, 0.1, 0.8, 1.0)  # Default purple color
        self.domain_id = f"{chain_id}_{start}_{end}"
        self.style = "ribbon"  # Default style

    def to_properties(self) -> Dict:
        """Convert domain definition to property dictionary for storing in PropertyGroup"""
        props = {
            'domain_id': self.domain_id,
            'name': self.name,
            'chain_id': self.chain_id,
            'start': self.start,
            'end': self.end,
            'parent_molecule_id': self.parent_molecule_id,
            'parent_domain_id': self.parent_domain_id,
            'object_name': self.object.name if self.object else "",
            'node_group_name': self.node_group.name if self.node_group else "",
            'color': self.color,
            'style': self.style,
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
        domain.parent_domain_id = props.parent_domain_id
        domain.domain_id = props.domain_id
        
        # Find object and node group by name
        if props.object_name and props.object_name in bpy.data.objects:
            domain.object = bpy.data.objects[props.object_name]
        
        if props.node_group_name and props.node_group_name in bpy.data.node_groups:
            domain.node_group = bpy.data.node_groups[props.node_group_name]
            
        # Set color
        domain.color = props.color
        
        # Set style
        if hasattr(props, 'style'):
            domain.style = props.style
        
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
            
            # Instead of linking directly to scene, link to the same collection as the parent
            # and make it a child of the parent object in Blender's hierarchy
            if parent_obj.users_collection:
                # Link to the first collection the parent is in
                parent_obj.users_collection[0].objects.link(self.object)
            else:
                # Fallback to scene collection if parent isn't in any collection
                bpy.context.scene.collection.objects.link(self.object)

            # Set the domain object's matrix to match the parent object's matrix
            self.object.matrix_world = parent_obj.matrix_world.copy()

            # Set the parent in Blender's hierarchy
            self.object.parent = parent_obj
            
            # Set up the parent inverse matrix to handle parent's transformation
            self.object.matrix_parent_inverse = parent_obj.matrix_world.inverted()
            
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
        try:
            # Clean up object
            if self.object:
                # Clean up node groups first
                if self.object.modifiers:
                    for modifier in self.object.modifiers:
                        if modifier.type == 'NODES' and modifier.node_group:
                            try:
                                node_group = modifier.node_group
                                if node_group and node_group.name in bpy.data.node_groups:
                                    bpy.data.node_groups.remove(node_group, do_unlink=True)
                            except ReferenceError:
                                # Node group already removed, skip
                                pass
                
                # Store object data
                obj_data = self.object.data
                
                # Remove object
                if self.object.name in bpy.data.objects:
                    bpy.data.objects.remove(self.object, do_unlink=True)
                
                # Clean up object data if no other users
                if obj_data and obj_data.users == 0:
                    if isinstance(obj_data, bpy.types.Mesh):
                        bpy.data.meshes.remove(obj_data, do_unlink=True)
                
                # Clear reference
                self.object = None
            
            # Clean up node group
            if self.node_group:
                try:
                    if self.node_group.name in bpy.data.node_groups:
                        bpy.data.node_groups.remove(self.node_group, do_unlink=True)
                except ReferenceError:
                    # Node group already removed, skip
                    pass
                self.node_group = None
            
            # Clean up any custom node trees
            for node_group in list(bpy.data.node_groups):  # Create a copy of the list to avoid modification during iteration
                try:
                    if node_group.name.startswith(f"Color Common_{self.domain_id}"):
                        bpy.data.node_groups.remove(node_group, do_unlink=True)
                except ReferenceError:
                    # Node group already removed, skip
                    pass
            
            # Reset properties
            self._setup_complete = False
            self.color = (0.8, 0.1, 0.8, 1.0)  # Reset to default color
            
        except Exception as e:
            print(f"Error during domain cleanup: {str(e)}")
            import traceback
            traceback.print_exc()

# The old Domain class is kept for backward compatibility
class Domain(PropertyGroup):
    """Blender Property Group for UI integration - kept for compatibility"""
    is_expanded: BoolProperty(default=False)
    chain_id: StringProperty()
    start: IntProperty()
    end: IntProperty()
    name: StringProperty()
    object: PointerProperty(type=bpy.types.Object)  # Reference to the domain object

def ensure_domain_properties_registered():
    """Make sure all domain-related properties are registered on Object class"""
    if not hasattr(bpy.types.Object, 'domain_expanded'):
        bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
    
    if not hasattr(bpy.types.Object, 'domain_color'):
        bpy.types.Object.domain_color = bpy.props.FloatVectorProperty(
            name="Domain Color",
            subtype='COLOR',
            size=4,
            min=0.0, max=1.0,
            default=(0.8, 0.1, 0.8, 1.0)
        )
    
    if not hasattr(bpy.types.Object, 'domain_style'):
        bpy.types.Object.domain_style = bpy.props.EnumProperty(
            name="Domain Style",
            description="Visualization style for this domain",
            items=STYLE_ITEMS,
            default="ribbon",
            update=lambda self, context: domain_style_update(self, context)
        )

def register():
    """Register property classes"""
    from bpy.utils import register_class
    register_class(DomainProperties)
    register_class(Domain)
    
    # Register custom object properties - these directly call the ensure function
    ensure_domain_properties_registered()

def unregister():
    try:
        bpy.utils.unregister_class(DomainProperties)
    except:
        pass
    try:
        bpy.utils.unregister_class(Domain)
    except:
        pass

def domain_style_update(obj, context):
    """Callback when domain style is changed"""
    # Get domain_id and parent_molecule_id from the object's custom properties
    try:
        if "domain_id" not in obj or "parent_molecule_id" not in obj:
            return
            
        domain_id = obj["domain_id"]
        parent_molecule_id = obj["parent_molecule_id"]
        
        # Get scene manager and molecule
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(parent_molecule_id)
        
        if not molecule:
            return
            
        # Get the current style value (handle both property and custom property)
        style = None
        try:
            style = obj.domain_style
        except (AttributeError, TypeError):
            # Fall back to custom property if property isn't accessible
            if "domain_style" in obj:
                style = obj["domain_style"]
                
        if not style:
            return
        
        # Get the domain
        domain = molecule.domains.get(domain_id)
        if not domain or not domain.object:
            return
            
        # Update the style directly (instead of calling the operator)
        try:
            print(f"Directly updating domain style for {domain_id} to {style}")
            
            # Update the domain's style property
            domain.style = style
            
            # Find and update the style node if the domain has a node group
            if domain.node_group:
                # Find style node
                style_node = None
                for node in domain.node_group.nodes:
                    if (node.bl_idname == 'GeometryNodeGroup' and 
                        node.node_tree and 
                        "Style" in node.node_tree.name):
                        style_node = node
                        break
                
                if style_node:
                    # Get the style node name from the style value
                    from ..utils.molecularnodes.blender.nodes import styles_mapping, append, swap
                    if style in styles_mapping:
                        style_node_name = styles_mapping[style]
                        # Swap the style node
                        swap(style_node, append(style_node_name))
        except Exception as e:
            print(f"Error in direct style update: {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"Error in domain_style_update: {e}")
        import traceback
        traceback.print_exc()

def try_deferred_style_update(domain_id, style, max_tries=3, current_try=0):
    """Try to run the style update operator if it's available, with retry logic"""
    import bpy
    
    # If we've exhausted our retries, give up
    if current_try >= max_tries:
        print(f"Gave up on operator-based style update after {max_tries} tries")
        return
        
    try:
        # Check if the operator exists now
        if hasattr(bpy.ops.molecule, "update_domain_style"):
            # Try to call it
            bpy.ops.molecule.update_domain_style(domain_id=domain_id, style=style)
            print(f"Successfully called style update operator on try {current_try+1}")
        else:
            # Schedule a retry using a timer
            print(f"Operator not available yet, scheduling retry {current_try+1}/{max_tries}")
            bpy.app.timers.register(
                lambda: try_deferred_style_update(domain_id, style, max_tries, current_try+1),
                first_interval=0.5  # Wait half a second before retry
            )
    except Exception as e:
        print(f"Error in deferred style update (try {current_try+1}): {e}")
        # Schedule a retry
        if current_try < max_tries - 1:
            bpy.app.timers.register(
                lambda: try_deferred_style_update(domain_id, style, max_tries, current_try+1),
                first_interval=0.5  # Wait half a second before retry
            )
