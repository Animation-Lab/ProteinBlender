"""Ligands, ions and water: the non-polymer atoms of an imported structure.

Chains and domains are made of amino acids (or nucleotides). Everything else a
structure file carries - bound ligands and cofactors, metal and halide ions,
crystallographic water - is kept, but it is *not* part of any chain's residue
range and never lands inside a domain. Splitting a chain only ever deals with
its polymer residues.

Why this matters: PDB/mmCIF files usually number a chain's hetero residues after
its polymer, often from a round number (4BV3 numbers its protein 122-391, its
ligands 1392-1400 and its waters 2001-2124, all in chain A). Counting those as
chain residues stretched chain A to 122-2124 and pulled every ligand and water
into whichever domain covered the chain's end.

Instead, each kind gets one object of its own, parented to the protein so it
moves with it, drawn in a style that suits it, and listed under the protein in
the PB Outliner with its own eye:

    4BV3
    |- Chain A
    |- Ligands    (ball and stick)
    |- Ions       (spheres)
    '- Water      (spheres, small)

How the atoms are routed:

* Every atom gets an integer ``pb_group`` attribute on the shared mesh:
  ``POLYMER`` (0), ``LIGAND`` (1), ``ION`` (2) or ``WATER`` (3).
* Domain objects only draw atoms whose ``pb_group`` is ``POLYMER``
  (:func:`add_polymer_gate`, used by ``MoleculeWrapper._setup_domain_network``).
* The protein object draws whatever no domain claims. A mask node here feeds
  its domain Boolean join, so it never draws non-polymer atoms either.
* Each group object draws only atoms of its own kind.

Files saved before this existed have no ``pb_group`` attribute. A Named
Attribute node reads a missing attribute as 0 (``POLYMER``), so the gates pass
everything and those files render exactly as they did.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import bpy
import numpy as np

logger = logging.getLogger(__name__)

ATTRIBUTE = "pb_group"

POLYMER, LIGAND, ION, WATER = 0, 1, 2, 3

# Custom properties on a group object.
GROUP_PROP = "pb_hetero_group"       # "LIGAND" / "ION" / "WATER"
OWNER_PROP = "pb_hetero_owner"       # the protein's molecule identifier

# Node names in the protein's own MolecularNodes tree.
PARENT_MASK_NODE = "PB_Hetero_Mask"
PARENT_MASK_ATTR_NODE = "PB_Hetero_Mask_Attr"

# Node names in a domain tree.
GATE_ATTR_NODE = "PB_Polymer_Gate_Attr"
GATE_COMPARE_NODE = "PB_Polymer_Gate_Compare"
GATE_AND_NODE = "PB_Polymer_Gate_And"

# kind -> (key, outliner label, style node, carbon color, icon)
KINDS = {
    LIGAND: ("LIGAND", "Ligands", "Style Ball and Stick", (0.20, 0.78, 0.35, 1.0), 'PHYSICS'),
    ION:    ("ION", "Ions", "Style Spheres", (0.60, 0.40, 0.85, 1.0), 'SHADING_SOLID'),
    WATER:  ("WATER", "Water", "Style Spheres", (0.35, 0.65, 1.00, 1.0), 'MOD_FLUIDSIM'),
}
KIND_BY_KEY = {spec[0]: kind for kind, spec in KINDS.items()}

# Water drawn at full van der Waals size buries the protein under a shell of
# spheres; a crystal's waters read better as small beads.
_WATER_SPHERE_SCALE = 0.4

# Polyatomic residues that are ions, not ligands. Single-atom residues (Zn, Na,
# Cl, Mg, ...) are recognised by size, so only multi-atom ions are listed.
POLYATOMIC_IONS = frozenset({
    "SO4", "PO4", "NO3", "NH4", "CO3", "SCN", "CYN", "OH", "PER",
    "PI", "2HP", "IOD", "BR", "AZI", "NO2", "SO3", "MOO", "WO4", "VO4",
})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def polymer_mask(array) -> np.ndarray:
    """Boolean mask of atoms that belong to amino-acid or nucleotide residues."""
    import biotite.structure as struc
    try:
        return struc.filter_amino_acids(array) | struc.filter_nucleotides(array)
    except Exception:
        logger.exception("Could not classify polymer atoms; treating all as polymer")
        return np.ones(len(array), dtype=bool)


def classify(array) -> np.ndarray:
    """Per-atom group code (POLYMER / LIGAND / ION / WATER) for an AtomArray."""
    import biotite.structure as struc

    n = len(array)
    groups = np.full(n, LIGAND, dtype=np.int32)
    if n == 0:
        return groups

    polymer = polymer_mask(array)
    try:
        water = struc.filter_solvent(array) & ~polymer
    except Exception:
        water = np.isin(array.res_name, ("HOH", "WAT", "DOD", "H2O")) & ~polymer

    # Ions: residues of a single atom, or a known polyatomic ion.
    starts = struc.get_residue_starts(array)
    sizes = np.diff(np.append(starts, n))
    per_residue_single = np.repeat(sizes == 1, sizes)
    named_ion = np.isin(np.char.upper(array.res_name.astype(str)), list(POLYATOMIC_IONS))
    ion = (per_residue_single | named_ion) & ~polymer & ~water

    groups[polymer] = POLYMER
    groups[water] = WATER
    groups[ion] = ION
    return groups


def _classify_from_mesh(mesh) -> Optional[np.ndarray]:
    """Fallback when the atom array does not line up with the mesh: classify
    from the attributes MolecularNodes writes on import."""
    attrs = mesh.attributes
    n = len(mesh.vertices)
    if n == 0 or "is_peptide" not in attrs:
        return None

    def read(name, dtype):
        if name not in attrs:
            return np.zeros(n, dtype=dtype)
        values = np.zeros(n, dtype=dtype)
        attrs[name].data.foreach_get("value", values)
        return values

    polymer = read("is_peptide", bool) | read("is_nucleic", bool)
    water = read("is_solvent", bool) & ~polymer
    chain = read("chain_id", np.int32)
    res = read("res_id", np.int32)

    groups = np.full(n, LIGAND, dtype=np.int32)
    keys = chain.astype(np.int64) * 10_000_000 + res
    _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    ion = (counts[inverse] == 1) & ~polymer & ~water
    groups[polymer] = POLYMER
    groups[water] = WATER
    groups[ion] = ION
    return groups


def write_attribute(wrapper) -> Optional[np.ndarray]:
    """Classify the molecule's atoms and store them as ``pb_group`` on its mesh."""
    obj = wrapper.molecule.object
    if obj is None or obj.type != 'MESH':
        return None
    mesh = obj.data
    n = len(mesh.vertices)

    groups = None
    array = getattr(wrapper, "working_array", None)
    if array is not None:
        if len(array) != n:
            # MolecularNodes drops solvent on import by default, so the mesh
            # can be the array minus its waters.
            try:
                import biotite.structure as struc
                dry = array[~struc.filter_solvent(array)]
                array = dry if len(dry) == n else None
            except Exception:
                array = None
        if array is not None:
            groups = classify(array)
    if groups is None:
        groups = _classify_from_mesh(mesh)
    if groups is None:
        return None

    attr = mesh.attributes.get(ATTRIBUTE)
    if not np.any(groups == POLYMER):
        # Nothing here is a chain (a lone ligand file): leave the atoms
        # unclassified, so every domain gate reads POLYMER and they draw as
        # they always have.
        if attr is not None:
            mesh.attributes.remove(attr)
        return groups
    if attr is not None and (attr.data_type != 'INT' or attr.domain != 'POINT'):
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(ATTRIBUTE, 'INT', 'POINT')
    attr.data.foreach_set("value", groups.astype(np.int32))
    mesh.update()
    return groups


def mesh_groups(obj) -> Optional[np.ndarray]:
    """The ``pb_group`` values stored on *obj*'s mesh, or None if it has none."""
    if obj is None or obj.type != 'MESH':
        return None
    attr = obj.data.attributes.get(ATTRIBUTE)
    if attr is None:
        return None
    values = np.zeros(len(obj.data.vertices), dtype=np.int32)
    attr.data.foreach_get("value", values)
    return values


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _named_int(tree, name):
    node = tree.nodes.get(name)
    if node is None:
        node = tree.nodes.new("GeometryNodeInputNamedAttribute")
        node.name = name
    node = tree.nodes[name]
    node.data_type = 'INT'
    node.inputs["Name"].default_value = ATTRIBUTE
    return node


def _compare_int(tree, name, operation, value):
    node = tree.nodes.get(name)
    if node is None:
        node = tree.nodes.new("FunctionNodeCompare")
        node.name = name
    node = tree.nodes[name]
    node.data_type = 'INT'
    node.operation = operation
    _int_compare_input(node, "B").default_value = value
    return node


def _attribute_socket(node):
    # Named Attribute exposes one "Attribute" output per data type; the INT one
    # is the one enabled for data_type == 'INT'.
    for socket in node.outputs:
        if socket.name == "Attribute" and socket.enabled:
            return socket
    return node.outputs[0]


def _int_compare_input(node, name="A"):
    """The Compare node's INT socket *name* ("A" or "B").

    Older Blenders keep one hidden A/B pair per data type (index by type);
    newer ones expose only the active pair. Match on name + type + enabled so
    both work.
    """
    for socket in node.inputs:
        if socket.name == name and socket.type == 'INT' and socket.enabled:
            return socket
    for socket in node.inputs:
        if socket.name == name and socket.enabled:
            return socket
    return node.inputs[name]


def add_polymer_gate(tree, chain_selection_socket_name: str, chain_node_name: str):
    """Return a Boolean output = (chain selection) AND (pb_group == POLYMER).

    Used by a domain's tree so the domain never draws ligands, ions or water,
    even when their residue numbers fall inside its range. All nodes are
    resolved by name, never held across ``nodes.new`` (see
    ``domain_space.ensure_pivot_input`` for why that matters).
    """
    _named_int(tree, GATE_ATTR_NODE)
    _compare_int(tree, GATE_COMPARE_NODE, 'EQUAL', POLYMER)
    if tree.nodes.get(GATE_AND_NODE) is None:
        node = tree.nodes.new("FunctionNodeBooleanMath")
        node.name = GATE_AND_NODE
    and_node = tree.nodes[GATE_AND_NODE]
    and_node.operation = 'AND'
    attr = tree.nodes[GATE_ATTR_NODE]
    compare = tree.nodes[GATE_COMPARE_NODE]
    chain_node = tree.nodes[chain_node_name]

    attr.location = (chain_node.location.x, chain_node.location.y - 220)
    compare.location = (chain_node.location.x + 180, chain_node.location.y - 220)
    and_node.location = (chain_node.location.x + 180, chain_node.location.y - 60)

    for socket in list(and_node.inputs[0].links) + list(and_node.inputs[1].links):
        tree.links.remove(socket)
    tree.links.new(_attribute_socket(attr), _int_compare_input(compare))
    tree.links.new(chain_node.outputs[chain_selection_socket_name], and_node.inputs[0])
    tree.links.new(compare.outputs["Result"], and_node.inputs[1])
    return and_node.outputs["Boolean"]


def install_parent_mask(wrapper) -> bool:
    """Make the protein object stop drawing non-polymer atoms.

    The protein draws NOT(any domain mask); feeding "pb_group != POLYMER" into
    the same Boolean join adds the hetero atoms to what it skips. Idempotent.
    """
    obj = wrapper.molecule.object
    mod = obj.modifiers.get("MolecularNodes") if obj is not None else None
    tree = mod.node_group if mod is not None else None
    if tree is None or tree.nodes.get("Domain_Boolean_Join") is None:
        return False

    _named_int(tree, PARENT_MASK_ATTR_NODE)
    _compare_int(tree, PARENT_MASK_NODE, 'NOT_EQUAL', POLYMER)
    attr = tree.nodes[PARENT_MASK_ATTR_NODE]
    mask = tree.nodes[PARENT_MASK_NODE]
    join = tree.nodes["Domain_Boolean_Join"]
    attr.location = (join.location.x - 420, join.location.y + 260)
    mask.location = (join.location.x - 220, join.location.y + 260)
    if not _int_compare_input(mask).is_linked:
        tree.links.new(_attribute_socket(attr), _int_compare_input(mask))

    if mask.outputs["Result"].is_linked:
        return True

    # Find a free slot on the join chain (same rule the domain masks use).
    if not wrapper._refresh_domain_node_refs(tree):
        return False
    for join_node in wrapper.join_nodes:
        for i in range(1, 9):
            name = f"Input_{i}"
            if name in join_node.inputs and not join_node.inputs[name].is_linked:
                tree.links.new(mask.outputs["Result"], join_node.inputs[name])
                return True
    logger.warning("No free domain-join slot for the hetero mask on %s", obj.name)
    return False


# ---------------------------------------------------------------------------
# Group objects
# ---------------------------------------------------------------------------

def group_objects(wrapper) -> Dict[int, bpy.types.Object]:
    """The existing group objects of a protein, keyed by kind."""
    parent = wrapper.molecule.object if wrapper.molecule else None
    found = {}
    if parent is None:
        return found
    for child in parent.children:
        key = child.get(GROUP_PROP)
        if key in KIND_BY_KEY and child.get(OWNER_PROP, wrapper.identifier) == wrapper.identifier:
            found[KIND_BY_KEY[key]] = child
    return found


def _parent_material(wrapper):
    try:
        style = wrapper.get_main_style_node()
    except Exception:
        style = None
    if style is not None and "Material" in style.inputs:
        return style.inputs["Material"].default_value
    return None


def _build_group_tree(tree, kind, material):
    from ..utils.molecularnodes.blender import nodes
    from . import domain_space

    _key, label, style_name, carbon, _icon = KINDS[kind]

    for node in list(tree.nodes):
        if node.bl_idname not in ('NodeGroupInput', 'NodeGroupOutput'):
            tree.nodes.remove(node)
    tree.links.clear()

    group_in = nodes.get_input(tree)
    group_out = nodes.get_output(tree)
    group_in.location = (-900, 0)
    group_out.location = (500, 0)

    color = nodes.add_custom(tree, "Color Common", location=[-700, -200])
    color.node_tree = color.node_tree.copy()
    color.node_tree.name = f"Color Common_{tree.name}"
    if "Carbon" in color.inputs:
        color.inputs["Carbon"].default_value = carbon
    color.name = "PB Group Color"

    set_color = nodes.add_custom(tree, "Set Color", location=[-450, 0])
    set_color.name = "PB Group Set Color"

    style = nodes.add_custom(tree, style_name, location=[100, 0])
    style.name = "PB Group Style"

    _named_int(tree, "PB Group Attr")
    _compare_int(tree, "PB Group Select", 'EQUAL', kind)

    # Re-resolve everything by name now that all nodes exist.
    group_in = nodes.get_input(tree)
    group_out = nodes.get_output(tree)
    color = tree.nodes["PB Group Color"]
    set_color = tree.nodes["PB Group Set Color"]
    style = tree.nodes["PB Group Style"]
    attr = tree.nodes["PB Group Attr"]
    select = tree.nodes["PB Group Select"]
    attr.location = (-250, -260)
    select.location = (-80, -260)

    link = tree.links.new
    link(group_in.outputs["Atoms"], set_color.inputs["Atoms"])
    link(color.outputs["Color"], set_color.inputs["Color"])
    link(set_color.outputs["Atoms"], style.inputs["Atoms"])
    link(_attribute_socket(attr), _int_compare_input(select))
    link(select.outputs["Result"], style.inputs["Selection"])
    link(style.outputs[0], group_out.inputs["Geometry"])

    if material is not None and "Material" in style.inputs:
        style.inputs["Material"].default_value = material
    _tune_style(style)

    size = tree.nodes.new('ShaderNodeValue')
    size.name = SIZE_NODE
    size.label = "Size"
    size.location = (-250, 260)
    tree.nodes[SIZE_NODE].outputs[0].default_value = 1.0
    _wire_size(tree, kind)

    domain_space.ensure_pivot_input(tree)


def _create_group_object(wrapper, kind, material):
    from . import domain_space

    parent = wrapper.molecule.object
    parent_mod = parent.modifiers.get("MolecularNodes")
    if parent_mod is None or parent_mod.node_group is None:
        return None
    key, label, _style, _carbon, _icon = KINDS[kind]

    # Share the protein's mesh, like a domain does: positions written to the
    # protein (conformations, morphs) move the ligands with it for free.
    obj = parent.copy()
    if hasattr(obj, 'pb_conformations'):
        obj.pb_conformations.states.clear()
    for prop in list(obj.keys()):
        if prop.startswith("pb_") and prop not in (GROUP_PROP, OWNER_PROP):
            del obj[prop]
    obj.name = f"{parent.name} {label}"
    obj[GROUP_PROP] = key
    obj[OWNER_PROP] = wrapper.identifier

    collection = parent.users_collection[0] if parent.users_collection else bpy.context.scene.collection
    collection.objects.link(obj)

    for mod in list(obj.modifiers):
        obj.modifiers.remove(mod)
    tree = parent_mod.node_group.copy()
    tree.name = f"{obj.name}_nodes"
    mod = obj.modifiers.new(name="DomainNodes", type='NODES')
    mod.node_group = tree
    _build_group_tree(tree, kind, material)

    obj.matrix_world = parent.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    domain_space.copy_pivot(parent, obj)
    obj.select_set(False)
    return obj


# ---------------------------------------------------------------------------
# Appearance: representation, color, size
#
# Edited from the pencil on a group's outliner row (operators/hetero_edit.py)
# and keyed from Create Keyframe. Everything lives on the group's own node
# tree, under fixed node names, so a key's data path stays valid whatever
# style is swapped in later.
# ---------------------------------------------------------------------------

STYLE_NODE = "PB Group Style"
COLOR_NODE = "PB Group Color"          # Color Common: colors by element
SET_COLOR_NODE = "PB Group Set Color"
SOLID_NODE = "PB Group Solid"          # Combine Color: one color for all atoms
SIZE_NODE = "PB Group Size"            # Value: 1.0 = the style's own size
_SIZE_PREFIX = "PB Group Size x "

# Which representations make sense for each kind. Cartoon and Ribbon follow a
# protein backbone a ligand does not have, and draw nothing; a single-atom ion
# has no bonds for Sticks to draw. Water is mostly single oxygens too.
STYLES_FOR_KIND = {
    LIGAND: ('ball_and_stick', 'sticks', 'spheres', 'surface'),
    ION: ('spheres',),
    WATER: ('spheres',),
}

# The style inputs that set how big a style draws, scaled together by Size.
_SIZE_SOCKETS = {
    "Style Spheres": ("Sphere Radii",),
    "Style Ball and Stick": ("Sphere Radii", "Bond Radius"),
    "Style Sticks": ("Radius",),
    "Style Surface": ("Scale Radii",),
}


def kind_of(obj) -> Optional[int]:
    """LIGAND / ION / WATER for a group object, None for anything else."""
    if obj is None:
        return None
    return KIND_BY_KEY.get(obj.get(GROUP_PROP))


def _tree(obj):
    mod = obj.modifiers.get("DomainNodes") if obj is not None else None
    return mod.node_group if mod is not None else None


def _style_tree_name(style_node) -> Optional[str]:
    tree = getattr(style_node, "node_tree", None)
    if tree is None:
        return None
    return next((name for name in _SIZE_SOCKETS if name in tree.name), tree.name)


def _tune_style(style_node):
    """Settings every group style gets, whichever style was swapped in.

    Point-cloud spheres render as faceted diamonds in EEVEE at the few atoms an
    ion group has; real mesh spheres cost nothing at that size.
    """
    inputs = style_node.inputs
    if "Sphere As Mesh" in inputs:
        inputs["Sphere As Mesh"].default_value = True
    if "Sphere Subdivisions" in inputs:
        inputs["Sphere Subdivisions"].default_value = 3


def _base_size(style_node, socket_name, kind) -> float:
    """What a size socket would be at Size 1.0: the style's own default.

    Water drawn at full van der Waals size buries the protein under a shell of
    spheres, so its spheres start at a crystal-bead size instead.
    """
    if kind == WATER and socket_name == "Sphere Radii":
        return _WATER_SPHERE_SCALE
    for item in style_node.node_tree.interface.items_tree:
        if (item.item_type == 'SOCKET' and item.in_out == 'INPUT'
                and item.name == socket_name):
            return float(item.default_value)
    return 1.0


def _wire_size(tree, kind):
    """Feed the Size value, times each size input's default, into the style.

    Rebuilt after every style swap: the inputs that set a style's size differ
    from style to style, but the Size node (and any keys on it) stays put.
    """
    for node in [n for n in tree.nodes if n.name.startswith(_SIZE_PREFIX)]:
        tree.nodes.remove(node)
    style = tree.nodes.get(STYLE_NODE)
    if style is None or tree.nodes.get(SIZE_NODE) is None:
        return
    names = [name for name in _SIZE_SOCKETS.get(_style_tree_name(style), ())
             if name in style.inputs]
    bases = {name: _base_size(style, name, kind) for name in names}
    for index, name in enumerate(names):
        node = tree.nodes.new('ShaderNodeMath')
        node.name = _SIZE_PREFIX + name
        node.operation = 'MULTIPLY'
        node.location = (-80, 300 + 120 * index)
    # nodes.new() can leave earlier node pointers stale: resolve by name.
    style = tree.nodes[STYLE_NODE]
    size = tree.nodes[SIZE_NODE]
    for name in names:
        node = tree.nodes[_SIZE_PREFIX + name]
        node.inputs[0].default_value = bases[name]
        tree.links.new(size.outputs[0], node.inputs[1])
        tree.links.new(node.outputs[0], style.inputs[name])


def get_style(obj) -> Optional[str]:
    from .visual_style import get_object_style
    return get_object_style(obj)


def set_style(obj, style) -> bool:
    """Draw a group object in ``style`` (one of :data:`STYLES_FOR_KIND`)."""
    from . import visual_style
    from ..utils.molecularnodes.blender import nodes

    kind = kind_of(obj)
    tree = _tree(obj)
    if kind is None or tree is None or style not in STYLES_FOR_KIND[kind]:
        return False
    node = tree.nodes.get(STYLE_NODE)
    if node is None:
        return False
    if get_style(obj) == style:
        return True
    material = (node.inputs["Material"].default_value
                if "Material" in node.inputs else None)
    visual_style.style_tree(style)
    nodes.swap(node, visual_style.STYLE_TREES[style])

    # swap() puts a new node in the old one's place, under a new name.
    node = tree.nodes.get(STYLE_NODE) or next(
        n for n in tree.nodes
        if n.type == 'GROUP' and n.node_tree is not None
        and n.node_tree.name.startswith("Style "))
    node.name = STYLE_NODE
    node = tree.nodes[STYLE_NODE]
    select = tree.nodes.get("PB Group Select")
    if select is not None and not node.inputs["Selection"].is_linked:
        tree.links.new(select.outputs["Result"], node.inputs["Selection"])
    if material is not None and "Material" in node.inputs:
        node.inputs["Material"].default_value = material
    _tune_style(node)
    _wire_size(tree, kind)
    obj.data.update_tag()
    return True


def _solid_node(tree, create=False):
    node = tree.nodes.get(SOLID_NODE)
    if node is None and create:
        node = tree.nodes.new('FunctionNodeCombineColor')
        node.name = SOLID_NODE
        node.mode = 'RGB'
        node.location = (-700, 120)
        node = tree.nodes[SOLID_NODE]
    return node


def _set_color_input(tree):
    set_color = tree.nodes.get(SET_COLOR_NODE)
    if set_color is None:
        return None
    return next((s for s in set_color.inputs if s.name == "Color"), None)


def by_element(obj) -> bool:
    """True while the group is colored by element (carbon in its own color)."""
    tree = _tree(obj)
    socket = _set_color_input(tree) if tree is not None else None
    if socket is None or not socket.is_linked:
        return True
    return socket.links[0].from_node.name != SOLID_NODE


def get_color(obj):
    """The group's color: its carbon color by element, or its solid color."""
    tree = _tree(obj)
    if tree is None:
        return None
    if by_element(obj):
        node = tree.nodes.get(COLOR_NODE)
        if node is None or "Carbon" not in node.inputs:
            return None
        return tuple(node.inputs["Carbon"].default_value)
    solid = _solid_node(tree)
    return tuple(solid.inputs[c].default_value for c in ("Red", "Green", "Blue")) + (1.0,)


def color_sockets(obj):
    """The sockets that hold the color the group is drawn in now - the ones a
    color keyframe goes on."""
    tree = _tree(obj)
    if tree is None:
        return []
    if by_element(obj):
        node = tree.nodes.get(COLOR_NODE)
        return [node.inputs["Carbon"]] if node is not None and "Carbon" in node.inputs else []
    solid = _solid_node(tree)
    return [solid.inputs[c] for c in ("Red", "Green", "Blue")] if solid is not None else []


def set_color(obj, color, element: Optional[bool] = None) -> bool:
    """Color a group object.

    By element, ``color`` becomes the carbon color and every other element keeps
    its own (nitrogen blue, oxygen red, ...), the usual way to show a ligand.
    Otherwise every atom is drawn in ``color``. ``element=None`` keeps the
    current mode.
    """
    tree = _tree(obj)
    if tree is None:
        return False
    if element is None:
        element = by_element(obj)
    socket = _set_color_input(tree)
    if socket is None:
        return False
    rgba = tuple(color) + (1.0,) * (4 - len(color))
    if element:
        node = tree.nodes.get(COLOR_NODE)
        if node is None:
            return False
        if "Carbon" in node.inputs:
            node.inputs["Carbon"].default_value = rgba[:4]
        source = node.outputs["Color"]
    else:
        solid = _solid_node(tree, create=True)
        for channel, value in zip(("Red", "Green", "Blue"), rgba):
            solid.inputs[channel].default_value = value
        source = solid.outputs["Color"]
    socket = _set_color_input(tree)
    if not socket.is_linked or socket.links[0].from_socket != source:
        for link in list(socket.links):
            tree.links.remove(link)
        tree.links.new(source, socket)
    obj.data.update_tag()
    return True


def get_size(obj) -> float:
    tree = _tree(obj)
    node = tree.nodes.get(SIZE_NODE) if tree is not None else None
    return float(node.outputs[0].default_value) if node is not None else 1.0


def set_size(obj, factor) -> bool:
    """Scale the group's spheres and bonds; 1.0 is the style's own size."""
    tree = _tree(obj)
    node = tree.nodes.get(SIZE_NODE) if tree is not None else None
    if node is None:
        return False
    node.outputs[0].default_value = max(0.0, float(factor))
    obj.data.update_tag()
    return True


# ---------------------------------------------------------------------------
# Visibility and keyframes
#
# The outliner eye normally hides an object for the view layer (hide_set),
# which Blender cannot animate. A group also sets ``hide_viewport`` and
# ``hide_render``, which it can, so whatever the eye shows is what a
# visibility key records. Keying hands the state over to hide_viewport alone,
# so scrubbing back to a visible key shows the group again.
# ---------------------------------------------------------------------------

def is_visible(obj, view_layer=None) -> bool:
    try:
        hidden = obj.hide_get(view_layer=view_layer) if view_layer else obj.hide_get()
    except RuntimeError:
        hidden = False
    return not (hidden or obj.hide_viewport)


def set_visible(obj, visible, view_layer=None) -> None:
    try:
        if view_layer is not None:
            obj.hide_set(not visible, view_layer=view_layer)
        else:
            obj.hide_set(not visible)
    except RuntimeError:
        pass
    obj.hide_viewport = not visible
    obj.hide_render = not visible


def _size_socket(obj):
    tree = _tree(obj)
    node = tree.nodes.get(SIZE_NODE) if tree is not None else None
    return node.outputs[0] if node is not None else None


def keyframe(obj, frame, *, visibility=False, color=False, size=False) -> int:
    """Key the chosen channels of a group object at ``frame``; returns how
    many channels were keyed."""
    keyed = 0
    if visibility:
        hidden = not is_visible(obj)
        try:
            obj.hide_set(False)
        except RuntimeError:
            pass
        obj.hide_viewport = obj.hide_render = hidden
        obj.keyframe_insert("hide_viewport", frame=frame)
        obj.keyframe_insert("hide_render", frame=frame)
        keyed += 1
    if color:
        sockets = color_sockets(obj)
        for socket in sockets:
            socket.keyframe_insert("default_value", frame=frame)
        keyed += bool(sockets)
    if size:
        socket = _size_socket(obj)
        if socket is not None:
            socket.keyframe_insert("default_value", frame=frame)
            keyed += 1
    return keyed


def delete_keyframes(obj, frame, *, visibility=True, color=True, size=True) -> None:
    """Remove a group's visibility / color / size keys at ``frame``."""
    targets = []
    if visibility:
        targets += [(obj, "hide_viewport"), (obj, "hide_render")]
    tree = _tree(obj)
    if color and tree is not None:
        node = tree.nodes.get(COLOR_NODE)
        if node is not None and "Carbon" in node.inputs:
            targets.append((node.inputs["Carbon"], "default_value"))
        solid = _solid_node(tree)
        if solid is not None:
            targets += [(solid.inputs[c], "default_value") for c in ("Red", "Green", "Blue")]
    if size:
        socket = _size_socket(obj)
        if socket is not None:
            targets.append((socket, "default_value"))
    for owner, path in targets:
        try:
            owner.keyframe_delete(path, frame=frame)
        except RuntimeError:
            pass   # nothing keyed there


def keyed_frames(obj) -> set:
    """Frames with a visibility, color, size or transform key on the group."""
    from ..utils.animation import get_fcurves_from_action
    frames = set()
    tree = _tree(obj)
    for owner in (obj, tree):
        ad = getattr(owner, "animation_data", None) if owner is not None else None
        if not ad or not ad.action:
            continue
        for fcurve in get_fcurves_from_action(ad.action, ad):
            if owner != obj and "PB Group" not in fcurve.data_path:
                continue
            frames.update(int(round(k.co[0])) for k in fcurve.keyframe_points
                          if k.type != 'JITTER')
    return frames


def create(wrapper) -> List[bpy.types.Object]:
    """Classify the protein's atoms and give each non-polymer kind its object.

    Call after the protein's domain infrastructure exists. Does nothing for a
    structure with no polymer at all (a lone ligand keeps its current look),
    and nothing for kinds the structure doesn't have.
    """
    groups = write_attribute(wrapper)
    if groups is None or not np.any(groups == POLYMER):
        return []
    present = [kind for kind in KINDS if np.any(groups == kind)]
    if not present:
        return []

    install_parent_mask(wrapper)
    existing = group_objects(wrapper)
    material = _parent_material(wrapper)
    created = []
    for kind in present:
        if kind in existing:
            continue
        obj = _create_group_object(wrapper, kind, material)
        if obj is not None:
            created.append(obj)
    return created


def remove(wrapper) -> None:
    """Delete a protein's group objects and their node trees."""
    for obj in group_objects(wrapper).values():
        trees = [m.node_group for m in obj.modifiers if m.type == 'NODES' and m.node_group]
        bpy.data.objects.remove(obj, do_unlink=True)
        for tree in trees:
            for node in tree.nodes:
                sub = getattr(node, "node_tree", None)
                if sub is not None and sub.name.startswith("Color Common_") and sub.users <= 1:
                    tree.nodes.remove(node)
                    bpy.data.node_groups.remove(sub)
                    break
            if tree.users == 0:
                bpy.data.node_groups.remove(tree)


def counts(wrapper) -> Dict[int, int]:
    """Number of residues of each non-polymer kind (for outliner labels)."""
    obj = wrapper.molecule.object if wrapper.molecule else None
    groups = mesh_groups(obj)
    if groups is None:
        return {}
    attrs = obj.data.attributes
    n = len(groups)
    chain = np.zeros(n, dtype=np.int32)
    res = np.zeros(n, dtype=np.int32)
    if "chain_id" in attrs:
        attrs["chain_id"].data.foreach_get("value", chain)
    if "res_id" in attrs:
        attrs["res_id"].data.foreach_get("value", res)
    keys = chain.astype(np.int64) * 10_000_000 + res
    result = {}
    for kind in KINDS:
        mask = groups == kind
        if mask.any():
            result[kind] = int(len(np.unique(keys[mask])))
    return result


def polymer_chain_ids(obj) -> Optional[set]:
    """Integer chain ids that contain polymer atoms, or None without pb_group."""
    groups = mesh_groups(obj)
    if groups is None or "chain_id" not in obj.data.attributes:
        return None
    chain = np.zeros(len(groups), dtype=np.int32)
    obj.data.attributes["chain_id"].data.foreach_get("value", chain)
    return set(int(c) for c in np.unique(chain[groups == POLYMER]))
