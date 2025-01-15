"""
This file is taken from MolecularNodes
@https://github.com/BradyAJohnston/MolecularNodes/tree/main
"""

import bpy
import numpy as np

from . import mn_coll
from . import mn_nodes
from databpy.attribute import AttributeTypes
from databpy.object import create_bob


def evaluate_using_mesh(obj: bpy.types.Object) -> bpy.types.Object:
    """
    Evaluate the object using a debug object. Some objects can't currently have their
    Geometry Node trees evaluated (such as volumes), so we source the geometry they create
    into a mesh object, which can be evaluated and tested.

    Parameters
    ----------
    object : bpy.types.Object
        The object to be evaluated.

    Returns
    -------
    bpy.types.Object

    Notes
    -----
    Intended for debugging only.
    """
    # create an empty mesh object. It's modifiers can be evaluated but some other
    # object types can't be currently through the API
    bob = create_bob()
    mod = mn_nodes.get_mod(bob.object)
    mod.node_group = mn_nodes.create_debug_group()
    mod.node_group.nodes["Object Info"].inputs["Object"].default_value = obj

    # need to use 'evaluate' otherwise the modifiers won't be taken into account
    return bob.evaluate()

def create_data_object(
    array: np.ndarray,
    name: str = "DataObject",
    collection: str | bpy.types.Collection | None = None,
    world_scale: float = 0.01,
) -> bpy.types.Object:
    print("Debug: Array type:", type(array))
    
    # Extract first model if it's an AtomArrayStack
    if hasattr(array, 'get_array'):
        array = array.get_array(0)  # Get first model
        print("Debug: Converted to single array")
    
    print("Debug: Array attributes:", dir(array))
    
    try:
        print("Debug: Array shape:", array.shape if hasattr(array, 'shape') else "No shape")
        # Use coord directly from biotite array
        locations = array.coord * world_scale
        print("Debug: Locations shape:", locations.shape)
    except Exception as e:
        print("Debug: Error accessing array data:", str(e))
        raise

    if not collection:
        collection = mn_coll.data()

    try:
        bob = create_bob(locations, collection=collection, name=name)

        # Modified attributes to match biotite's structure
        attributes = [
            ("chain_id", AttributeTypes.INT),
            ("res_id", AttributeTypes.INT),
            ("atom_id", AttributeTypes.INT),
        ]

        for column, attr_type in attributes:
            try:
                data = getattr(array, column)
                print(f"Debug: Processing attribute {column}, type: {attr_type}")
                
                # Handle string data
                if isinstance(data[0], str):
                    data = np.unique(data, return_inverse=True)[1]
                
                bob.store_named_attribute(data=data, name=column, atype=attr_type)
                
            except (ValueError, AttributeError) as e:
                print(f"Debug: Skipping attribute {column}: {str(e)}")
                continue

        return bob.object
    except Exception as e:
        print("Debug: Error in create_data_object:", str(e))
        raise

def create_data_object2(
    array: np.ndarray,
    name: str = "DataObject",
    collection: str | bpy.types.Collection | None = None,
    world_scale: float = 0.01,
) -> bpy.types.Object:
    # still requires a unique call TODO: figure out why
    # I think this has to do with the bcif instancing extraction
    # array = np.unique(array)
    locations = array["translation"] * world_scale

    if not collection:
        collection = mn_coll.data()

    bob = create_bob(locations, collection=collection, name=name)

    attributes = [
        ("rotation", AttributeTypes.QUATERNION),
        ("assembly_id", AttributeTypes.INT),
        ("chain_id", AttributeTypes.INT),
        ("transform_id", AttributeTypes.INT),
        ("pdb_model_num", AttributeTypes.INT),
    ]

    for column, type in attributes:
        try:
            data = array[column]
        except ValueError:
            continue
        # us the unique sorted integer encoding version of the non-numeric
        # attribute, as GN doesn't support strings currently
        if np.issubdtype(data.dtype, str):
            data = np.unique(data, return_inverse=True)[1]

        bob.store_named_attribute(data=data, name=column, atype=type)

    return bob.object
