"""Code paths that must not touch API Blender is removing in 6.0.

Blender 5.0 deprecated ``Material.use_nodes``, ``World.use_nodes`` and
``Scene.use_nodes`` (``Light.use_nodes`` followed in 5.1), each warning
"is expected to be removed in Blender 6.0". Nodes are always on: a new material
arrives with a Principled BSDF tree, a new world with Background and World
Output nodes, a write of ``use_nodes = True`` changes nothing and a write of
``False`` is ignored. Code that still touches the property works today and
raises ``AttributeError`` the day it is removed.

The autouse ``_fail_on_api_blender_is_removing`` fixture in conftest.py records
that warning and fails any test that triggers it, naming the file and line. The
tests here drive the sites the rest of the suite does not reach, and check
Blender still emits the warning the guard listens for.
"""

import bpy
import pytest

import helpers as H


def test_blender_still_announces_the_removal_the_guard_listens_for():
    """The guard is only as good as Blender's warning, so check Blender emits it.

    If Blender stops warning (or the property is finally removed in 6.0, which
    turns this into an AttributeError), the guard has gone vacuous: replace
    this probe with another deprecated property rather than deleting it.
    """
    material = bpy.data.materials.new("guard probe")
    with pytest.warns(DeprecationWarning, match="removed in Blender 6.0"):
        material.use_nodes


def test_transparent_material_is_built_without_deprecated_api():
    """The animated-alpha material arrives wired and fully opaque."""
    from proteinblender.core.visual_style import get_or_create_transparent_material

    material = get_or_create_transparent_material("probe")

    nodes = {n.type: n for n in material.node_tree.nodes}
    principled = nodes["BSDF_PRINCIPLED"]
    assert principled.inputs["Alpha"].default_value == 1.0

    # The geometry's Color attribute tints the base colour, and the shader
    # reaches the material output.
    links = {(l.from_node.type, l.from_socket.name, l.to_node.type, l.to_socket.name)
             for l in material.node_tree.links}
    assert ("ATTRIBUTE", "Color", "BSDF_PRINCIPLED", "Base Color") in links
    assert ("BSDF_PRINCIPLED", "BSDF", "OUTPUT_MATERIAL", "Surface") in links
    assert nodes["ATTRIBUTE"].attribute_name == "Color"


def _style_material(obj):
    """The material the style node renders with, read straight off the tree."""
    modifier = next(m for m in obj.modifiers if m.type == "NODES")
    style = next(n for n in modifier.node_group.nodes
                 if n.type == "GROUP" and n.node_tree and "Style" in n.node_tree.name)
    return style.inputs["Material"].default_value


def _alpha(material):
    return next(n.inputs["Alpha"].default_value
                for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def _set_alpha(material, value):
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            node.inputs["Alpha"].default_value = value


def _keyed_domain(sm):
    """A freshly imported domain whose style material is already translucent."""
    from proteinblender.core.visual_style import apply_material_transparency_to_style_node

    mol_id = H.import_local("1ubq.pdb", "1ubq")
    obj = next(iter(sm.molecules[mol_id].domains.values())).object
    assert apply_material_transparency_to_style_node(obj, 0.5)
    return obj


def test_alpha_keyframes_are_inserted_and_removed(scene, sm):
    """Key a domain's alpha at frame 7, then remove it.

    Ground truth is Blender evaluating the animation: with a key of 0.5 at
    frame 7, moving the alpha elsewhere and returning to frame 7 must bring 0.5
    back, and once the key is removed it must not.
    """
    from proteinblender.utils.animation import (
        has_color_keyframe, keyframe_color_properties, remove_color_keyframes)

    obj = _keyed_domain(sm)
    material = _style_material(obj)
    assert _alpha(material) == pytest.approx(0.5)

    assert keyframe_color_properties(obj, 7)

    _set_alpha(material, 1.0)
    scene.frame_set(7)
    assert _alpha(material) == pytest.approx(0.5), "the key at frame 7 was not stored"

    # Called for the material branch it walks, which is where the deprecated
    # property used to be read. Its answer for an alpha key is the xfail below.
    has_color_keyframe(obj, 7)

    assert remove_color_keyframes(obj, 7)

    _set_alpha(material, 0.9)
    scene.frame_set(8)
    scene.frame_set(7)
    assert _alpha(material) == pytest.approx(0.9), "the key at frame 7 survived removal"


@pytest.mark.xfail(strict=True, reason=(
    "has_color_keyframe looks for 'Alpha' in the F-curve data_path, but Blender "
    "addresses node sockets by index (nodes[\"Principled BSDF\"].inputs[4]."
    "default_value), so an alpha key is never found and the keyframe indicator "
    "stays off for a domain keyed only on alpha. Found while covering the "
    "use_nodes cleanup; not fixed there because it changes visible behaviour."))
def test_has_color_keyframe_sees_an_alpha_key(scene, sm):
    from proteinblender.utils.animation import has_color_keyframe, keyframe_color_properties

    obj = _keyed_domain(sm)
    assert keyframe_color_properties(obj, 7)
    assert has_color_keyframe(obj, 7)
