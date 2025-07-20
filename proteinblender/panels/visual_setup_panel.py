"""Visual Set-up panel for controlling molecular appearance.

This module implements the Visual Set-up panel with:
- Context-sensitive color wheel
- Representation dropdown
- Live updates based on outliner selection
- Multi-selection support
"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import FloatVectorProperty, EnumProperty
from ..utils.scene_manager import ProteinBlenderScene


def get_selected_outliner_items(context):
    """Get all selected items from the outliner."""
    outliner_state = context.scene.protein_outliner_state
    selected_items = []
    
    for item in outliner_state.items:
        if item.is_selected:
            # Skip items that are in groups (unless they ARE groups)
            if item.type != 'GROUP' and is_item_in_group(item, context):
                continue
            selected_items.append(item)
    
    return selected_items


def is_item_in_group(item, context):
    """Check if an item is part of a group."""
    scene = context.scene
    if not hasattr(scene, 'pb_groups'):
        return False
    
    for group in scene.pb_groups:
        for member in group.members:
            if member.identifier == item.identifier:
                return True
    
    return False


def get_object_for_item(item):
    """Get the Blender object for an outliner item."""
    scene_manager = ProteinBlenderScene.get_instance()
    
    if item.type == 'PROTEIN':
        molecule = scene_manager.molecules.get(item.identifier)
        if molecule and molecule.object:
            return molecule.object
    elif item.type == 'DOMAIN':
        # Find the domain by searching through all molecules
        for mol in scene_manager.molecules.values():
            if hasattr(mol, 'domains') and item.identifier in mol.domains:
                domain = mol.domains[item.identifier]
                if domain and domain.object:
                    return domain.object
                break
    elif item.type == 'CHAIN':
        # Chains might not have direct objects, need to handle differently
        # For now, we'll skip chains
        pass
    
    return None


def get_current_style(obj):
    """Get the current style of a molecule object."""
    if not obj:
        return None
    
    # Check if object has MolecularNodes data
    if hasattr(obj, "mn") and hasattr(obj.mn, "style"):
        return obj.mn.style
    
    # Try to find style from node tree
    if obj.modifiers:
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group:
                # Look for style node in the node tree
                for node in mod.node_group.nodes:
                    if node.name.startswith("Style "):
                        style_name = node.name.replace("Style ", "").lower()
                        # Convert to our enum format
                        style_map = {
                            "spheres": "spheres",
                            "cartoon": "cartoon",
                            "surface": "surface",
                            "ribbon": "ribbon",
                            "sticks": "sticks",
                            "ball and stick": "ball_stick",
                            "ball_and_stick": "ball_stick",
                        }
                        return style_map.get(style_name, "cartoon")
    
    return "cartoon"  # Default


def get_current_color(obj):
    """Get the current color of a molecule object."""
    if not obj:
        return (0.5, 0.5, 0.5)
    
    # Try to get color from object custom properties
    if "molecule_color" in obj:
        return obj["molecule_color"]
    
    # Try to get color from material
    if obj.data and obj.data.materials:
        mat = obj.data.materials[0]
        if mat and mat.use_nodes:
            # Look for color in shader nodes
            for node in mat.node_tree.nodes:
                if node.type == 'RGB':
                    return node.outputs[0].default_value[:3]
    
    # Default gray
    return (0.5, 0.5, 0.5)


def update_visual_color(self, context):
    """Update the color of selected items."""
    selected_items = get_selected_outliner_items(context)
    color = context.scene.pb_visual_color
    
    for item in selected_items:
        obj = get_object_for_item(item)
        if obj:
            # Store color in custom property
            obj["molecule_color"] = color
            
            # Try to update material color
            if obj.data and obj.data.materials:
                for mat in obj.data.materials:
                    if mat and mat.use_nodes:
                        # Look for RGB nodes to update
                        for node in mat.node_tree.nodes:
                            if node.type == 'RGB':
                                node.outputs[0].default_value = (*color, 1.0)
            
            # Update color attribute if it exists
            if hasattr(obj.data, "attributes") and "Color" in obj.data.attributes:
                color_attr = obj.data.attributes["Color"]
                # This would need proper implementation based on MolecularNodes
                pass


def update_visual_representation(self, context):
    """Update the representation style of selected items."""
    selected_items = get_selected_outliner_items(context)
    style = context.scene.pb_visual_representation
    
    # Import MolecularNodes style change function
    try:
        from ..utils.molecularnodes.style import change_style_node
        
        for item in selected_items:
            obj = get_object_for_item(item)
            if obj:
                # Map our style names to MolecularNodes style names
                style_map = {
                    'ribbon': 'ribbon',
                    'cartoon': 'cartoon',
                    'surface': 'surface',
                    'ball_stick': 'ball_and_stick',
                    'spheres': 'spheres',
                    'sticks': 'sticks'
                }
                
                mn_style = style_map.get(style, 'cartoon')
                try:
                    change_style_node(obj, mn_style)
                    # Store the style in object
                    if hasattr(obj, "mn"):
                        obj.mn.style = mn_style
                except Exception as e:
                    print(f"Failed to change style for {obj.name}: {e}")
    except ImportError:
        print("MolecularNodes style module not available")


class VIEW3D_PT_pb_visual_setup(Panel):
    """Visual Set-up panel for molecular appearance."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "Visual Set-up"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Get selected items
        selected_items = get_selected_outliner_items(context)
        
        if not selected_items:
            layout.label(text="Select items in outliner")
            layout.enabled = False
            
            # Still show the controls but disabled
            layout.prop(scene, "pb_visual_color", text="Color")
            layout.prop(scene, "pb_visual_representation", text="Representation")
            return
        
        # Enable the layout
        layout.enabled = True
        
        # Show what's selected
        if len(selected_items) == 1:
            layout.label(text=f"Selected: {selected_items[0].name}")
        else:
            layout.label(text=f"Selected: {len(selected_items)} items")
        
        # Color wheel
        layout.prop(scene, "pb_visual_color", text="Color")
        
        # Representation dropdown
        layout.prop(scene, "pb_visual_representation", text="Representation")
        
        # For single selection, show current values
        if len(selected_items) == 1:
            obj = get_object_for_item(selected_items[0])
            if obj:
                # Show current style
                current_style = get_current_style(obj)
                if current_style and current_style != scene.pb_visual_representation:
                    layout.label(text=f"Current: {current_style}", icon='INFO')


class PROTEIN_PB_OT_sync_visual_selection(Operator):
    """Sync visual properties with current selection."""
    bl_idname = "protein_pb.sync_visual_selection"
    bl_label = "Sync Visual Selection"
    bl_options = {'INTERNAL'}
    
    def execute(self, context):
        selected_items = get_selected_outliner_items(context)
        
        if selected_items:
            # For single selection, update properties to match object
            if len(selected_items) == 1:
                obj = get_object_for_item(selected_items[0])
                if obj:
                    # Update color
                    color = get_current_color(obj)
                    context.scene.pb_visual_color = color
                    
                    # Update style
                    style = get_current_style(obj)
                    if style and style in [item[0] for item in get_representation_items()]:
                        context.scene.pb_visual_representation = style
        
        return {'FINISHED'}


def get_representation_items():
    """Get the representation enum items."""
    return [
        ('ribbon', 'Ribbon', 'Ribbon representation'),
        ('cartoon', 'Cartoon', 'Cartoon representation'),
        ('surface', 'Surface', 'Surface representation'),
        ('ball_stick', 'Ball & Stick', 'Ball and stick representation'),
        ('spheres', 'Spheres', 'Space-filling spheres'),
        ('sticks', 'Sticks', 'Stick representation'),
    ]


# Register properties
def register_properties():
    """Register visual properties if not already registered."""
    if not hasattr(bpy.types.Scene, "pb_visual_color"):
        bpy.types.Scene.pb_visual_color = FloatVectorProperty(
            name="Color",
            subtype='COLOR',
            size=3,
            min=0.0,
            max=1.0,
            default=(0.5, 0.5, 0.5),
            update=update_visual_color
        )
    
    if not hasattr(bpy.types.Scene, "pb_visual_representation"):
        bpy.types.Scene.pb_visual_representation = EnumProperty(
            name="Representation",
            items=get_representation_items(),
            default='cartoon',
            update=update_visual_representation
        )


def unregister_properties():
    """Unregister visual properties."""
    if hasattr(bpy.types.Scene, "pb_visual_color"):
        del bpy.types.Scene.pb_visual_color
    if hasattr(bpy.types.Scene, "pb_visual_representation"):
        del bpy.types.Scene.pb_visual_representation


# Classes to register
CLASSES = [
    VIEW3D_PT_pb_visual_setup,
    PROTEIN_PB_OT_sync_visual_selection,
]


def register():
    register_properties()
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    unregister_properties()