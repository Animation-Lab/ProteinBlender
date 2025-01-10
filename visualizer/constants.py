GLOBAL_SCALE = 0.1

# Element indices for geometry nodes
ELEMENT_INDICES = {
    'C': 0,    # Carbon
    'H': 1,    # Hydrogen
    'O': 2,    # Oxygen
    'N': 3,    # Nitrogen
    'S': 4,    # Sulfur
    'P': 5,    # Phosphorus
    'FE': 6,   # Iron
    'CA': 7,   # Calcium
    'MG': 8,   # Magnesium
    'ZN': 9,   # Zinc
    'CL': 10,  # Chlorine
    'NA': 11,  # Sodium
    'K': 12,   # Potassium
    'CU': 13,  # Copper
    'NI': 14,  # Nickel
    'CO': 15,  # Cobalt
    'MN': 16,  # Manganese
    'CD': 17,  # Cadmium
    'HG': 18,  # Mercury
    'I': 19,   # Iodine
    'BR': 20,  # Bromine
    'F': 21,   # Fluorine
    'BA': 22,  # Barium
    'SR': 23,  # Strontium
    'CS': 24,  # Cesium
    'RB': 25,  # Rubidium
}

ATOM_RELATIVE_SIZES = {
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
    'NA': 1.9,   # Sodium
    'K': 2.0,    # Potassium
    'CU': 1.6,   # Copper
    'NI': 1.6,   # Nickel
    'CO': 1.6,   # Cobalt
    'MN': 1.6,   # Manganese
    'CD': 1.7,   # Cadmium
    'HG': 1.7,   # Mercury
    'I': 1.8,    # Iodine
    'BR': 1.7,   # Bromine
    'F': 1.0,    # Fluorine
    'BA': 2.2,   # Barium
    'SR': 2.1,   # Strontium
    'CS': 2.2,   # Cesium
    'RB': 2.2,   # Rubidium
}

# Bond type indices for geometry nodes
BOND_TYPE_INDICES = {
    'single': 0,
    'double': 1,
    'triple': 2,
    'aromatic': 3,
    'polar': 4,
    'nonpolar': 5,
    'hydrogen': 6,
} 