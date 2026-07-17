"""Does an imported molecule actually draw anything?

This lane exists because the suite had a hole big enough to drive a protein
through: 234 tests asserted on raw mesh coordinates, pivot maths and world
positions, and *not one* of them checked that a domain's geometry-nodes tree
emits any geometry at all. A tree whose geometry source was severed passed every
one of them, and 1ATN imported into the outliner while rendering nothing.

Why the obvious check is not enough
-----------------------------------
``bpy.data.meshes.new_from_object`` only captures the mesh component. The default
Style Spheres emits a *point cloud* (Cycles renders those natively), so a
perfectly healthy molecule reads as zero vertices. Measuring that way is how the
breakage stayed invisible - it looked identical before and after.

So this asserts on the tree's topology instead, which is style-independent and is
exactly what broke: the geometry has to be able to get from the Group Input to
the Group Output. If that path is cut, nothing downstream can draw, whatever the
style.
"""

import numpy as np
import pytest
import bpy

import helpers as H


def _render_coverage(tmp_path, resolution=96):
    """Render the scene and return how many pixels geometry actually covered.

    The ground truth, and the only measure here that isn't a proxy. With
    film_transparent on, any pixel with alpha > 0 was hit by geometry, so 0 means
    the viewport is empty no matter what the node tree claims.

    Cycles at 1 sample and 96x96 keeps this to a couple of seconds.
    """
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    out = str(tmp_path / "probe.png")
    scene.render.filepath = out

    cam_data = bpy.data.cameras.new("probe_cam")
    cam = bpy.data.objects.new("probe_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0, -12, 0)
    cam.rotation_euler = (1.5707963, 0, 0)
    scene.camera = cam
    try:
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(out)
        try:
            px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
            return int((px[:, 3] > 0.01).sum())
        finally:
            bpy.data.images.remove(img)
    finally:
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)


def _pb_tree(obj):
    mod = obj.modifiers.get("DomainNodes") or obj.modifiers.get("MolecularNodes")
    assert mod is not None, f"{obj.name} has no ProteinBlender GN modifier"
    assert mod.node_group is not None, f"{obj.name}'s modifier has no node group"
    return mod.node_group


def _nodes_feeding(node_group, start):
    """Every node reachable by walking *backwards* from ``start``'s inputs."""
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for socket in node.inputs:
            for link in socket.links:
                stack.append(link.from_node)
    return seen


def _group_io(node_group):
    gi = next((n for n in node_group.nodes
               if n.bl_idname == "NodeGroupInput"), None)
    go = next((n for n in node_group.nodes
               if n.bl_idname == "NodeGroupOutput"), None)
    return gi, go


def _assert_tree_renders(obj, label):
    ng = _pb_tree(obj)
    gi, go = _group_io(ng)
    assert gi is not None, f"{label}: tree has no Group Input"
    assert go is not None, f"{label}: tree has no Group Output"

    # A node feeding itself is always a wiring bug, and it silently starves the
    # branch: the node has no real source, so it emits nothing.
    #
    # Compare names, not `is`: Blender returns a fresh bpy_struct wrapper per
    # access, so `l.from_node is l.to_node` is False even for a genuine
    # self-link. That identical mistake is what created the bug this guards.
    self_links = [l.from_node.name for l in ng.links
                  if l.from_node.name == l.to_node.name]
    assert not self_links, (
        f"{label}: node(s) linked to themselves: {self_links}. The branch has no "
        f"geometry source and renders nothing.")

    assert go.inputs[0].links, f"{label}: Group Output's geometry is unconnected"

    reachable = _nodes_feeding(ng, go)
    assert gi in reachable, (
        f"{label}: the Group Input is not reachable from the Group Output - the "
        f"molecule's atoms never enter the tree, so nothing is drawn. "
        f"Links: {[(l.from_node.name + '.' + l.from_socket.name, l.to_node.name + '.' + l.to_socket.name) for l in ng.links]}")

    # The atoms specifically (the geometry socket), not just any input.
    geo_out = next((s for s in gi.outputs if s.type == "GEOMETRY"), None)
    assert geo_out is not None, f"{label}: Group Input exposes no geometry socket"
    assert geo_out.links, (
        f"{label}: the Group Input's geometry socket feeds nothing - the atoms "
        f"are never consumed, so the tree renders an empty scene.")


@pytest.mark.integration
@pytest.mark.parametrize("fixture,ident", [
    ("1atn.pdb", "1atn"),   # the structure that surfaced this
    ("1ubq.pdb", "1ubq"),   # single chain
    ("4hhb.pdb", "4hhb"),   # four chains
])
def test_imported_molecule_renders(scene, sm, fixture, ident):
    """Every domain's tree must be able to carry atoms from input to output."""
    mol_id = H.import_local(fixture, ident)
    mol = sm.molecules[mol_id]

    _assert_tree_renders(mol.object, f"{ident} parent")

    assert mol.domains, f"{ident}: import created no domains"
    for domain in mol.domains.values():
        assert domain.object is not None, f"{ident}: domain {domain.name} has no object"
        _assert_tree_renders(domain.object, f"{ident} domain {domain.name}")


@pytest.mark.integration
def test_imported_molecule_actually_puts_pixels_on_screen(scene, sm, tmp_path):
    """The end-to-end check: import a protein, render, see it.

    Everything else in this file reasons about the node graph. This one just
    looks. It is the test that would have caught 1ATN importing into the
    outliner while the viewport stayed empty, and it is immune to how a style
    chooses to emit its geometry.
    """
    H.import_local("1atn.pdb", "1atn")
    bpy.context.view_layer.update()

    covered = _render_coverage(tmp_path)
    assert covered > 0, (
        "the molecule rendered zero pixels - it is in the outliner but the "
        "viewport is empty")


@pytest.mark.integration
def test_pivot_change_does_not_blank_the_render(scene, sm, tmp_path):
    """Setting a pivot must not make the molecule vanish.

    Inserting the pivot's Transform node rewires the geometry path, which is
    exactly where it got severed before.
    """
    H.import_local("1atn.pdb", "1atn")
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    for it in scene.outliner_items:
        it.is_selected = it.item_type == "CHAIN"

    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}
    bpy.context.view_layer.update()

    assert _render_coverage(tmp_path) > 0, (
        "the molecule rendered zero pixels after a pivot change")


@pytest.mark.integration
def test_molecule_renders_after_a_pivot_change(scene, sm):
    """Setting a pivot must not sever the geometry path.

    The pivot inserts a Transform node between the Group Input and the rest of
    the tree, so a mistake there cuts the molecule out of its own node tree.
    """
    mol_id = H.import_local("1atn.pdb", "1atn")
    mol = sm.molecules[mol_id]
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)

    for it in scene.outliner_items:
        it.is_selected = it.item_type == "CHAIN"

    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}
    for domain in mol.domains.values():
        _assert_tree_renders(domain.object, f"after set_pivot_first: {domain.name}")

    assert bpy.ops.proteinblender.set_pivot_center() == {"FINISHED"}
    for domain in mol.domains.values():
        _assert_tree_renders(domain.object, f"after set_pivot_center: {domain.name}")


@pytest.mark.integration
def test_molecule_renders_after_a_style_change(scene, sm):
    """Rebuilding a domain's network for a new style must not sever it either.

    _setup_domain_network rebuilds with links.clear(), and the pivot has to be
    re-inserted afterwards - a rebuild that forgets to is exactly how the
    geometry path gets cut.
    """
    mol_id = H.import_local("1atn.pdb", "1atn")
    mol = sm.molecules[mol_id]
    scene.selected_molecule_id = mol_id

    swapped = False
    for style in ("spheres", "surface", "cartoon"):
        # Re-read the ids each pass: a style swap can rebuild a domain, and the
        # operator raises rather than returning CANCELLED on a stale id.
        for did in list(mol.domains.keys()):
            if did not in mol.domains:
                continue
            try:
                res = bpy.ops.molecule.update_domain_style(
                    domain_id=did, style=style)
            except RuntimeError:
                continue
            swapped = swapped or res == {"FINISHED"}

        for domain in mol.domains.values():
            _assert_tree_renders(domain.object, f"style={style}: {domain.name}")

    if not swapped:
        pytest.skip("update_domain_style could not swap the style node headless")
