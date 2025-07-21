"""Visual Setup panel with context-aware styling"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import EnumProperty, FloatVectorProperty
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.molecularnodes.style import STYLE_ITEMS


class PROTEINBLENDER_OT_apply_color(Operator):
    """Apply color to selected items"""
    bl_idname = "proteinblender.apply_color"
    bl_label = "Apply Color"
    bl_options = {'REGISTER', 'UNDO'}
    
    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.1, 0.8, 1.0)
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find selected items in outliner
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Apply color based on selection context
        for item in selected_items:
            if item.item_type == 'PROTEIN':
                # Apply to protein and all children
                self.apply_protein_color(scene_manager, item, self.color)
            elif item.item_type == 'CHAIN':
                # Apply to chain and its domains
                self.apply_chain_color(scene_manager, item, self.color)
            elif item.item_type == 'DOMAIN':
                # Apply to domain only
                self.apply_domain_color(scene_manager, item, self.color)
        
        # Update viewport
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        
        return {'FINISHED'}
    
    def apply_protein_color(self, scene_manager, protein_item, color):
        """Apply color to protein and all its domains"""
        molecule = scene_manager.molecules.get(protein_item.item_id)
        if not molecule:
            return
        
        # Apply to main protein object if it exists
        if molecule.object:
            self._apply_color_to_object(molecule.object, color)
        
        # Apply to all domains
        for domain in molecule.domains.values():
            if domain.object:
                self._apply_color_to_object(domain.object, color)
    
    def apply_chain_color(self, scene_manager, chain_item, color):
        """Apply color to all domains in a chain"""
        # Find parent molecule
        parent_molecule = scene_manager.molecules.get(chain_item.parent_id)
        
        if parent_molecule:
            # Extract chain identifier
            chain_id_str = chain_item.item_id.split('_chain_')[-1]
            try:
                chain_id = int(chain_id_str)
            except:
                chain_id = chain_id_str
            
            # Apply to domains belonging to this chain
            for domain_id, domain in parent_molecule.domains.items():
                # Check if domain belongs to this chain
                domain_chain_id = getattr(domain, 'chain_id', None)
                
                # Extract chain from domain name if needed
                if domain_chain_id is None and hasattr(domain, 'name'):
                    import re
                    match = re.search(r'Chain_([A-Z])', domain.name)
                    if match:
                        domain_chain_id = match.group(1)
                    elif '_' in domain.name:
                        match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                        if match2:
                            domain_chain_id = int(match2.group(1))
                
                # Check if this domain belongs to the chain
                if domain_chain_id is not None:
                    domain_chain_str = str(domain_chain_id)
                    chain_str = str(chain_id)
                    
                    if domain_chain_str == chain_str or domain_chain_id == chain_id:
                        if domain.object:
                            self._apply_color_to_object(domain.object, color)
    
    def apply_domain_color(self, scene_manager, domain_item, color):
        """Apply color to a single domain"""
        # Find the domain object
        if domain_item.object_name:
            obj = bpy.data.objects.get(domain_item.object_name)
            if obj:
                self._apply_color_to_object(obj, color)
    
    def _apply_color_to_object(self, obj, color):
        """Apply color to a molecular object through its geometry nodes"""
        # Find the MolecularNodes modifier
        mod = None
        for modifier in obj.modifiers:
            if modifier.type == 'NODES' and 'MolecularNodes' in modifier.name:
                mod = modifier
                break
        
        if not mod or not mod.node_group:
            return
        
        node_tree = mod.node_group
        
        # Look for a Color RGB node or create one
        rgb_node = None
        for node in node_tree.nodes:
            if node.type == 'RGB':
                rgb_node = node
                break
        
        if not rgb_node:
            # Create new RGB node
            rgb_node = node_tree.nodes.new('ShaderNodeRGB')
            rgb_node.location = (-400, 0)
            rgb_node.name = "Custom Color"
        
        # Set the color
        rgb_node.outputs[0].default_value = color
        
        # Find the Set Color node
        set_color_node = None
        for node in node_tree.nodes:
            if 'Set Color' in node.name or (hasattr(node, 'node_tree') and node.node_tree and 'Set Color' in node.node_tree.name):
                set_color_node = node
                break
        
        if set_color_node:
            # Connect RGB to Set Color
            color_input = None
            for input_socket in set_color_node.inputs:
                if 'Color' in input_socket.name:
                    color_input = input_socket
                    break
            
            if color_input:
                # Remove existing connections to the color input
                for link in node_tree.links:
                    if link.to_socket == color_input:
                        node_tree.links.remove(link)
                
                # Create new connection
                node_tree.links.new(rgb_node.outputs["Color"], color_input)
        
        # Force update
        obj.data.update()


class PROTEINBLENDER_OT_apply_representation(Operator):
    """Apply representation style to selected items"""
    bl_idname = "proteinblender.apply_representation"
    bl_label = "Apply Representation"
    bl_options = {'REGISTER', 'UNDO'}
    
    style: EnumProperty(
        name="Style",
        items=STYLE_ITEMS,
        default='surface'
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Apply style based on selection context
        for item in selected_items:
            if item.item_type == 'PROTEIN':
                # Apply to entire protein
                molecule = scene_manager.molecules.get(item.item_id)
                if molecule:
                    # TODO: Change molecule style using MolecularNodes
                    self.report({'INFO'}, f"Applied {self.style} to {item.name}")
            elif item.item_type == 'DOMAIN':
                # Apply to domain only
                # TODO: Change domain style
                self.report({'INFO'}, f"Applied {self.style} to {item.name}")
        
        return {'FINISHED'}


class PROTEINBLENDER_PT_visual_setup(Panel):
    """Visual Setup panel for color and representation"""
    bl_label = "Visual Set-up"
    bl_idname = "PROTEINBLENDER_PT_visual_setup"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 2  # After outliner
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create a box for the entire panel content
        box = layout.box()
        
        # Add panel title inside the box
        box.label(text="Visual Set-up", icon='SHADING_RENDERED')
        box.separator()
        
        # Check if anything is selected
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            box.label(text="Select items to apply visual settings", icon='INFO')
            layout.separator()  # Add bottom spacing
            return
        
        # Show what will be affected
        info_box = box.box()
        col = info_box.column(align=True)
        
        # Count selection types
        proteins = sum(1 for item in selected_items if item.item_type == 'PROTEIN')
        chains = sum(1 for item in selected_items if item.item_type == 'CHAIN')
        domains = sum(1 for item in selected_items if item.item_type == 'DOMAIN')
        
        if proteins > 0:
            col.label(text=f"{proteins} protein(s) selected", icon='MESH_DATA')
        if chains > 0:
            col.label(text=f"{chains} chain(s) selected", icon='LINKED')
        if domains > 0:
            col.label(text=f"{domains} domain(s) selected", icon='GROUP_VERTEX')
        
        box.separator()
        
        # Create a 2x2 grid layout
        # First row - labels
        row = box.row(align=True)
        row.alignment = 'CENTER'
        
        col_left = row.column(align=True)
        col_left.label(text="Color", icon='COLOR')
        
        col_right = row.column(align=True)
        col_right.label(text="Representation", icon='MESH_UVSPHERE')
        
        # Second row - controls
        row = box.row(align=True)
        row.scale_y = 1.5
        
        # Color picker on the left
        col_left = row.column(align=True)
        col_left.prop(scene, "visual_setup_color", text="")
        
        # Style dropdown on the right
        col_right = row.column(align=True)
        col_right.prop(scene, "visual_setup_style", text="")
        
        # Add bottom spacing
        layout.separator()


# Standalone color application functions (for live updates)
def apply_protein_color_direct(scene_manager, protein_item, color):
    """Apply color to protein and all its domains"""
    molecule = scene_manager.molecules.get(protein_item.item_id)
    if not molecule:
        return
    
    # Apply to main protein object if it exists
    if molecule.object:
        apply_color_to_object(molecule.object, color)
    
    # Apply to all domains
    for domain in molecule.domains.values():
        if domain.object:
            apply_color_to_object(domain.object, color)


def apply_chain_color_direct(scene_manager, chain_item, color):
    """Apply color to all domains in a chain"""
    # Find parent molecule
    parent_molecule = scene_manager.molecules.get(chain_item.parent_id)
    
    if parent_molecule:
        # Extract chain identifier
        chain_id_str = chain_item.item_id.split('_chain_')[-1]
        try:
            chain_id = int(chain_id_str)
        except:
            chain_id = chain_id_str
        
        # Apply to domains belonging to this chain
        for domain_id, domain in parent_molecule.domains.items():
            # Check if domain belongs to this chain
            domain_chain_id = getattr(domain, 'chain_id', None)
            
            # Extract chain from domain name if needed
            if domain_chain_id is None and hasattr(domain, 'name'):
                import re
                match = re.search(r'Chain_([A-Z])', domain.name)
                if match:
                    domain_chain_id = match.group(1)
                elif '_' in domain.name:
                    match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                    if match2:
                        domain_chain_id = int(match2.group(1))
            
            # Check if this domain belongs to the chain
            if domain_chain_id is not None:
                domain_chain_str = str(domain_chain_id)
                chain_str = str(chain_id)
                
                if domain_chain_str == chain_str or domain_chain_id == chain_id:
                    if domain.object:
                        apply_color_to_object(domain.object, color)


def apply_domain_color_direct(scene_manager, domain_item, color):
    """Apply color to a single domain"""
    # Find the domain object
    if domain_item.object_name:
        obj = bpy.data.objects.get(domain_item.object_name)
        if obj:
            apply_color_to_object(obj, color)


def apply_color_to_object(obj, color):
    """Apply color to a molecular object through its geometry nodes"""
    # Find the MolecularNodes modifier
    mod = None
    for modifier in obj.modifiers:
        if modifier.type == 'NODES' and modifier.name == "MolecularNodes":
            mod = modifier
            break
    
    if not mod or not mod.node_group:
        # Try to find any nodes modifier if exact name doesn't match
        for modifier in obj.modifiers:
            if modifier.type == 'NODES':
                mod = modifier
                break
        if not mod or not mod.node_group:
            return
    
    node_tree = mod.node_group
    
    # Debug: print node names to understand structure
    print(f"Applying color to {obj.name}")
    print("Nodes in tree:")
    for node in node_tree.nodes:
        print(f"  - {node.name} (type: {node.type})")
        if node.type == 'GROUP':
            print(f"    Node tree: {node.node_tree.name if node.node_tree else 'None'}")
    
    # Look for existing color nodes
    color_node = None
    set_color_node = None
    
    for node in node_tree.nodes:
        # Look for Set Color node (it's a group node)
        if node.type == 'GROUP' and node.node_tree and 'Set Color' in node.node_tree.name:
            set_color_node = node
        # Look for existing color nodes
        elif 'Color' in node.name and node.type == 'GROUP':
            color_node = node
    
    if not set_color_node:
        print("Warning: Set Color node not found")
        return
    
    # Find what's currently connected to Set Color's Atoms input
    atoms_input = None
    current_atoms_connection = None
    for input_socket in set_color_node.inputs:
        if input_socket.name in ['Atoms', 'Geometry']:  # Could be named either
            atoms_input = input_socket
            # Find what's connected to it
            for link in node_tree.links:
                if link.to_socket == atoms_input:
                    current_atoms_connection = link.from_socket
                    break
            break
    
    # Remove any old Custom Color RGB nodes
    nodes_to_remove = []
    for node in node_tree.nodes:
        if node.name == "Custom Color RGB":
            nodes_to_remove.append(node)
    for node in nodes_to_remove:
        node_tree.nodes.remove(node)
    
    # Create a Combine Color node to ensure proper color format
    combine_color_node = None
    for node in node_tree.nodes:
        if node.name == "Custom Combine Color":
            combine_color_node = node
            break
    
    if not combine_color_node:
        # Create new Combine Color node
        combine_color_node = node_tree.nodes.new('FunctionNodeCombineColor')
        combine_color_node.location = (set_color_node.location[0] - 200, set_color_node.location[1])
        combine_color_node.name = "Custom Combine Color"
        combine_color_node.mode = 'RGB'
    
    # Set the color values
    combine_color_node.inputs["Red"].default_value = color[0]
    combine_color_node.inputs["Green"].default_value = color[1]
    combine_color_node.inputs["Blue"].default_value = color[2]
    
    # Find the Color input on the Set Color node
    color_input = None
    for input_socket in set_color_node.inputs:
        if 'Color' in input_socket.name:
            color_input = input_socket
            break
    
    if color_input:
        # Remove existing connections to the color input
        links_to_remove = []
        for link in node_tree.links:
            if link.to_socket == color_input:
                links_to_remove.append(link)
        
        for link in links_to_remove:
            node_tree.links.remove(link)
        
        # Create new connection
        node_tree.links.new(combine_color_node.outputs["Color"], color_input)
        print(f"Connected Custom Combine Color to {set_color_node.name}")
    
    # Ensure atoms/geometry is still connected
    if atoms_input and current_atoms_connection:
        # Check if connection exists
        connection_exists = False
        for link in node_tree.links:
            if link.from_socket == current_atoms_connection and link.to_socket == atoms_input:
                connection_exists = True
                break
        
        if not connection_exists:
            node_tree.links.new(current_atoms_connection, atoms_input)
            print("Reconnected atoms input")
    
    # Force update by tagging the object
    obj.data.update()
    if hasattr(obj.data, 'update_tag'):
        obj.data.update_tag()
    
    # Ensure object stays selected
    obj.select_set(True)


def update_color(self, context):
    """Live update callback for color property"""
    scene = context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    
    # Store current active object
    active_obj = context.view_layer.objects.active
    
    # Find selected items in outliner
    selected_items = [item for item in scene.outliner_items if item.is_selected]
    
    if not selected_items:
        return
    
    # Apply color based on selection context
    for item in selected_items:
        if item.item_type == 'PROTEIN':
            apply_protein_color_direct(scene_manager, item, scene.visual_setup_color)
        elif item.item_type == 'CHAIN':
            apply_chain_color_direct(scene_manager, item, scene.visual_setup_color)
        elif item.item_type == 'DOMAIN':
            apply_domain_color_direct(scene_manager, item, scene.visual_setup_color)
    
    # Restore active object
    if active_obj:
        context.view_layer.objects.active = active_obj
    
    # Update viewport
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# Standalone style application functions (for live updates)
def apply_protein_style_direct(scene_manager, protein_item, style):
    """Apply style to protein and all its domains"""
    molecule = scene_manager.molecules.get(protein_item.item_id)
    if not molecule:
        return
    
    # Apply to main protein object if it exists
    if molecule.object:
        apply_style_to_object(molecule.object, style)
    
    # Apply to all domains
    for domain in molecule.domains.values():
        if domain.object:
            apply_style_to_object(domain.object, style)


def apply_chain_style_direct(scene_manager, chain_item, style):
    """Apply style to all domains in a chain"""
    # Find parent molecule
    parent_molecule = scene_manager.molecules.get(chain_item.parent_id)
    
    if parent_molecule:
        # Extract chain identifier
        chain_id_str = chain_item.item_id.split('_chain_')[-1]
        try:
            chain_id = int(chain_id_str)
        except:
            chain_id = chain_id_str
        
        # Apply to domains belonging to this chain
        for domain_id, domain in parent_molecule.domains.items():
            # Check if domain belongs to this chain
            domain_chain_id = getattr(domain, 'chain_id', None)
            
            # Extract chain from domain name if needed
            if domain_chain_id is None and hasattr(domain, 'name'):
                import re
                match = re.search(r'Chain_([A-Z])', domain.name)
                if match:
                    domain_chain_id = match.group(1)
                elif '_' in domain.name:
                    match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                    if match2:
                        domain_chain_id = int(match2.group(1))
            
            # Check if this domain belongs to the chain
            if domain_chain_id is not None:
                domain_chain_str = str(domain_chain_id)
                chain_str = str(chain_id)
                
                if domain_chain_str == chain_str or domain_chain_id == chain_id:
                    if domain.object:
                        apply_style_to_object(domain.object, style)


def apply_domain_style_direct(scene_manager, domain_item, style):
    """Apply style to a single domain"""
    # Find the domain object
    if domain_item.object_name:
        obj = bpy.data.objects.get(domain_item.object_name)
        if obj:
            apply_style_to_object(obj, style)


def apply_style_to_object(obj, style):
    """Apply style to a molecular object through its geometry nodes"""
    # Find the MolecularNodes modifier
    mod = None
    for modifier in obj.modifiers:
        if modifier.type == 'NODES' and modifier.name == "MolecularNodes":
            mod = modifier
            break
    
    if not mod or not mod.node_group:
        # Try to find any nodes modifier if exact name doesn't match
        for modifier in obj.modifiers:
            if modifier.type == 'NODES':
                mod = modifier
                break
        if not mod or not mod.node_group:
            return
    
    node_tree = mod.node_group
    
    print(f"Applying style '{style}' to {obj.name}")
    
    # Find the style node
    style_node = None
    for node in node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
            style_node = node
            print(f"Found style node: {node.name} with tree: {node.node_tree.name}")
            break
    
    if not style_node:
        print("Warning: Style node not found")
        return
    
    # Swap to the desired style node
    from ..utils.molecularnodes.blender import nodes
    
    # Map our style names to MolecularNodes style node names
    style_map = {
        'spheres': 'Style Spheres',
        'cartoon': 'Style Cartoon',
        'surface': 'Style Surface',
        'ribbon': 'Style Ribbon',
        'sticks': 'Style Sticks',
        'ball_and_stick': 'Style Ball and Stick'
    }
    
    target_style_name = style_map.get(style)
    if target_style_name:
        try:
            # Use the swap function from MolecularNodes
            nodes.swap(style_node, target_style_name)
            print(f"Swapped to {target_style_name}")
        except Exception as e:
            print(f"Error swapping style: {e}")
    
    # Force update
    obj.data.update()
    if hasattr(obj.data, 'update_tag'):
        obj.data.update_tag()
    
    # Ensure object stays selected
    obj.select_set(True)


def update_style(self, context):
    """Live update callback for style property"""
    scene = context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    
    # Skip if empty value (multiple selections)
    if not scene.visual_setup_style:
        return
    
    # Store current active object
    active_obj = context.view_layer.objects.active
    
    # Find selected items in outliner
    selected_items = [item for item in scene.outliner_items if item.is_selected]
    
    if not selected_items:
        return
    
    # Apply style based on selection context
    for item in selected_items:
        if item.item_type == 'PROTEIN':
            apply_protein_style_direct(scene_manager, item, scene.visual_setup_style)
        elif item.item_type == 'CHAIN':
            apply_chain_style_direct(scene_manager, item, scene.visual_setup_style)
        elif item.item_type == 'DOMAIN':
            apply_domain_style_direct(scene_manager, item, scene.visual_setup_style)
    
    # Restore active object
    if active_obj:
        context.view_layer.objects.active = active_obj
    
    # Update viewport
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# Register color property
def register_props():
    """Register scene properties for visual setup"""
    from bpy.props import FloatVectorProperty, EnumProperty
    
    bpy.types.Scene.visual_setup_color = FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.1, 0.8, 1.0),
        update=update_color  # Live update callback
    )
    
    # Style property with empty option for multiple selections
    style_items = [
        ('', "Multiple", "Multiple styles selected"),
        ('spheres', "Spheres", "Sphere representation"),
        ('cartoon', "Cartoon", "Cartoon representation"),
        ('surface', "Surface", "Surface representation"),
        ('ribbon', "Ribbon", "Ribbon representation"),
        ('sticks', "Sticks", "Stick representation"),
        ('ball_and_stick', "Ball & Stick", "Ball and stick representation"),
    ]
    
    bpy.types.Scene.visual_setup_style = EnumProperty(
        name="Style",
        items=style_items,
        default='surface',
        update=update_style  # Live update callback
    )


def unregister_props():
    """Unregister scene properties"""
    if hasattr(bpy.types.Scene, "visual_setup_color"):
        del bpy.types.Scene.visual_setup_color
    if hasattr(bpy.types.Scene, "visual_setup_style"):
        del bpy.types.Scene.visual_setup_style


# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_apply_color,
    PROTEINBLENDER_OT_apply_representation,
    PROTEINBLENDER_PT_visual_setup,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    register_props()


def unregister():
    unregister_props()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)