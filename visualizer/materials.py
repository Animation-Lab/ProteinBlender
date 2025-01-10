import bpy

# Global materials dictionary
ATOM_MATERIALS = {}
BOND_MATERIALS = {}

def create_atom_materials():
    """Create global materials for all atom types."""
    colors = {
        # Base atomic elements
        'C': (0.2, 0.2, 0.2, 1.0),     # Grey
        'H': (1.0, 1.0, 1.0, 1.0),     # White
        'O': (1.0, 0.0, 0.0, 1.0),     # Red
        'N': (0.0, 0.0, 1.0, 1.0),     # Blue
        'S': (1.0, 0.8, 0.0, 1.0),     # Yellow
        'P': (1.0, 0.5, 0.0, 1.0),     # Orange
        'FE': (0.7, 0.3, 0.0, 1.0),    # Brown
        'CA': (0.5, 0.5, 0.5, 1.0),    # Light grey
        'MG': (0.0, 1.0, 0.0, 1.0),    # Green
        'ZN': (0.6, 0.6, 0.8, 1.0),    # Blue-grey
        'CL': (0.0, 0.8, 0.0, 1.0),    # Green
        'NA': (0.6, 0.6, 1.0, 1.0),    # Light blue
        'K': (0.6, 0.0, 0.6, 1.0),     # Purple
        'CU': (0.8, 0.4, 0.0, 1.0),    # Copper brown
        'NI': (0.5, 0.5, 0.0, 1.0),    # Olive
        'CO': (0.6, 0.4, 0.6, 1.0),    # Purple-grey
        'MN': (0.6, 0.0, 0.2, 1.0),    # Dark red
        'CD': (0.4, 0.4, 0.6, 1.0),    # Blue-grey
        'HG': (0.7, 0.7, 0.7, 1.0),    # Silver
        'I': (0.5, 0.0, 0.5, 1.0),     # Dark purple
        'BR': (0.6, 0.2, 0.0, 1.0),    # Dark orange
        'F': (0.7, 1.0, 0.7, 1.0),     # Light green
        'BA': (0.0, 0.8, 0.4, 1.0),    # Sea green
        'SR': (0.0, 0.8, 0.6, 1.0),    # Turquoise
        'CS': (0.3, 0.6, 0.8, 1.0),    # Sky blue
        'RB': (0.4, 0.0, 0.4, 1.0),    # Dark purple
    }

    for atom_symbol, color in colors.items():
        mat_name = f"atom_{atom_symbol}"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True

        # Access the Principled BSDF node
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")

        # Modify BSDF properties
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = 0.7
            bsdf.inputs["Metallic"].default_value = 0.2
        else:
            mat.diffuse_color = color
        ATOM_MATERIALS[atom_symbol] = mat

def create_bond_materials():
    """Create global materials for all bond types."""
    colors = {
        'single': (0.8, 0.8, 0.8, 1.0),    # Light grey
        'double': (0.6, 0.6, 0.6, 1.0),    # Medium grey
        'triple': (0.4, 0.4, 0.4, 1.0),    # Dark grey
        'aromatic': (0.7, 0.7, 0.9, 1.0),  # Light blue-grey
        'polar': (0.9, 0.7, 0.7, 1.0),     # Light red
        'nonpolar': (0.7, 0.7, 0.7, 1.0),  # Grey
        'hydrogen': (0.9, 0.9, 0.9, 1.0),   # Very light grey
    }

    for bond_type, color in colors.items():
        mat_name = f"bond_{bond_type}"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True

        # Access the Principled BSDF node
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")

        # Modify BSDF properties
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = 0.5
            bsdf.inputs["Metallic"].default_value = 0.0
        else:
            mat.diffuse_color = color
        BOND_MATERIALS[bond_type] = mat

def get_or_create_materials():
    """Ensure all materials exist and return them."""
    if not ATOM_MATERIALS:
        create_atom_materials()
    if not BOND_MATERIALS:
        create_bond_materials()
    return ATOM_MATERIALS, BOND_MATERIALS 