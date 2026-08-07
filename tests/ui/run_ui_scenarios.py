"""Foreground Blender UI scenarios, advanced one step per application timer.

Running assertions from timers lets Blender's real window manager process
redraws, popup dialogs, mode switches, and synthetic keyboard events between
steps.  A synchronous pytest call cannot provide that event-loop boundary.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


repo_root, report_path = sys.argv[sys.argv.index("--") + 1:]
repo_root = Path(repo_root)
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "tests"))

import proteinblender
import helpers as H


results = []
EXPECTED_UI_PANELS = {
    "PROTEIN_PB_PT_import_protein",
    "PROTEINBLENDER_PT_outliner",
    "PROTEINBLENDER_PT_puppet_maker",
    "PROTEINBLENDER_PT_pose_library",
    "PROTEINBLENDER_PT_animation",
    "PROTEINBLENDER_PT_builders",
    "PB2_PT_linkers",
}
state = {"molecule_id": None, "puppet_id": None, "puppet_members": set(),
         "pivot_row": None, "pivot_origin_before": None,
         "dna": None, "membrane": None, "undo_domains_before": set(),
         "undo_properties_before": set(), "workspace_area_count": None,
         "workspace_screen": None, "workspace_contexts": None}


def active_window():
    return bpy.context.window or next(iter(bpy.context.window_manager.windows), None)


def record(name, function):
    try:
        detail = function()
        results.append({"name": name, "ok": True, "detail": detail or ""})
    except Exception as exc:
        results.append({
            "name": name,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })


def ui_override(area_type="PROPERTIES"):
    window = active_window()
    assert window is not None and window.screen is not None, "foreground Blender has no window/screen"
    area = next((item for item in window.screen.areas if item.type == area_type), None)
    if area is None:
        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        area.type = area_type
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    assert region is not None, f"{area_type} area has no WINDOW region"
    return bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region)


def protein_workspace_panel_area():
    window = active_window()
    workspace = bpy.data.workspaces.get("Protein Blender")
    assert workspace is not None, "Protein Blender workspace does not exist"
    # Some import operators temporarily restore the previously active
    # workspace. Select the add-on workspace exactly as a user clicking its
    # tab would before inspecting its editors.
    if window.workspace != workspace:
        window.workspace = workspace
    areas = [area for area in window.screen.areas if area.type == "PROPERTIES"]
    assert areas, "Protein Blender workspace contains no Properties editor"
    scene_areas = [area for area in areas
                   if area.spaces.active.context == "SCENE"]
    assert scene_areas, (
        "Protein Blender Properties editor is not showing Scene properties; "
        f"screen={window.screen.name}; "
        f"contexts={[area.spaces.active.context for area in areas]}; "
        f"initial_screen={state.get('workspace_screen')}; "
        f"initial_contexts={state.get('workspace_contexts')}")
    return scene_areas[0]


def protein_workspace_override():
    window = active_window()
    area = protein_workspace_panel_area()
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    assert region is not None, "Protein Blender Properties editor has no WINDOW region"
    return bpy.context.temp_override(
        window=window, screen=window.screen, area=area, region=region)


def setup():
    proteinblender._test_register()
    H.reset_scene()
    from proteinblender.addon import create_workspace_callback
    create_workspace_callback()
    # Exercise the ordinary second-launch path where the named workspace is
    # already present. It must bind and repair the existing layout, not return
    # with uninitialized area references.
    create_workspace_callback()
    state["workspace_area_count"] = len(active_window().screen.areas)
    state["workspace_screen"] = active_window().screen.name
    state["workspace_contexts"] = [
        area.spaces.active.context for area in active_window().screen.areas
        if area.type == "PROPERTIES"]
    fixture = H.data_path("4hhb.pdb")
    # Timer callbacks do not inherit an editor area. MolecularNodes appends
    # bundled node groups through bpy.ops.wm.append, so give it the same real
    # VIEW_3D window context a user-triggered import has.
    with ui_override("VIEW_3D"):
        state["molecule_id"] = H.import_local("4hhb.pdb", "ui_4hhb")
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    chains = [row for row in bpy.context.scene.outliner_items if row.item_type == "CHAIN"]
    assert len(chains) >= 2
    for row in bpy.context.scene.outliner_items:
        row.is_selected = row.item_id in {chains[0].item_id, chains[1].item_id}
    state["puppet_members"] = {chains[0].item_id, chains[1].item_id}
    with ui_override("PROPERTIES"):
        assert bpy.ops.proteinblender.create_puppet(
            "EXEC_DEFAULT", puppet_name="UI Existing Puppet") == {"FINISHED"}
    puppet = next(row for row in bpy.context.scene.outliner_items
                  if row.item_type == "PUPPET" and row.item_id != "puppets_separator")
    state["puppet_id"] = puppet.item_id
    assert Path(fixture).is_file()
    return bpy.app.version_string


def verify_workspace_ui():
    area = protein_workspace_panel_area()
    screen = active_window().screen
    assert len(screen.areas) == state["workspace_area_count"], (
        "deferred/repeated workspace setup duplicated editor areas")
    # The Protein Outliner is a panel inside this Scene Properties editor. The
    # duplicated default workspace ships a Scene-Collection Outliner editor in
    # the right column, directly above Properties. If setup leaves it in place
    # the user sees the stock "Scene Collection" tree stacked above the Protein
    # Outliner. The canonical layout has no Outliner editor at all.
    outliners = [a for a in screen.areas if a.type == "OUTLINER"]
    assert not outliners, (
        "Protein Blender workspace still shows a stock Outliner editor "
        f"({len(outliners)} found) above the Protein Outliner; "
        f"areas={sorted(a.type for a in screen.areas)}")
    # Nothing may sit above the panel editor in its own column: the Protein
    # Outliner must be the top of the right-hand column.
    column = [a for a in screen.areas if abs(a.x - area.x) <= 2]
    above = [a for a in column if a.y > area.y + 2]
    assert not above, (
        "editors stacked above the Protein Blender panel column: "
        f"{[a.type for a in above]}")
    # The panel column must be the intended ~30% of the window, not Blender's
    # narrow ~18% default Properties column (which the setup reused before the
    # layout was rebuilt from a single viewport). Assert clearly wider than that
    # default so a regression to the reused column fails here.
    win_w = active_window().width
    frac = area.width / win_w if win_w else 0
    assert frac >= 0.25, (
        "Protein Blender panel column is too narrow: "
        f"{area.width}px = {frac:.0%} of {win_w}px (expected ~30%)")
    return (f"Scene Properties editor ready ({area.width}x{area.height}, "
            f"{frac:.0%} width)")


def assert_proteinblender_ui_loaded():
    """Prove the user-facing panel surface is loaded in its real workspace."""
    # Put the conditional Domain Maker panel into its documented visible state.
    chain = next(row for row in bpy.context.scene.outliner_items
                 if row.item_type == "CHAIN" and "_ref_" not in row.item_id)
    for row in bpy.context.scene.outliner_items:
        row.is_selected = row.item_id == chain.item_id
    with protein_workspace_override():
        assert bpy.context.area.spaces.active.context == "SCENE"
        missing = sorted(name for name in EXPECTED_UI_PANELS
                         if not hasattr(bpy.types, name))
        assert not missing, f"ProteinBlender UI panels are not loaded: {missing}"

        problems = []
        visible = []
        for name in sorted(EXPECTED_UI_PANELS):
            panel = getattr(bpy.types, name)
            if not getattr(panel, "is_registered", False):
                problems.append(f"{name} is not registered")
            if panel.bl_space_type != "PROPERTIES":
                problems.append(f"{name} space={panel.bl_space_type!r}")
            if panel.bl_region_type != "WINDOW":
                problems.append(f"{name} region={panel.bl_region_type!r}")
            if panel.bl_context != "scene":
                problems.append(f"{name} context={panel.bl_context!r}")
            poll = getattr(panel, "poll", None)
            if poll is None or poll(bpy.context):
                visible.append(name)
            else:
                problems.append(f"{name}.poll rejected the live Scene context")

        assert not problems, "ProteinBlender UI is not usable:\n  " + "\n  ".join(problems)
        assert set(visible) == EXPECTED_UI_PANELS
        bpy.context.area.tag_redraw()
    return f"all {len(visible)} ProteinBlender panels loaded and visible"


def redraw_all_panels():
    with protein_workspace_override():
        area = bpy.context.area
        assert area.spaces.active.context == "SCENE"
        area.tag_redraw()
    expected = [name for name in dir(bpy.types)
                if name.startswith(("PROTEINBLENDER_PT_", "PROTEIN_PB_PT_", "PB2_PT_"))]
    assert len(expected) >= 8, f"expected at least 8 add-on panels, got {expected}"
    return f"requested redraw for {len(expected)} panels"


def invoke_and_cancel_pose_dialog():
    scene = bpy.context.scene
    chains = [row for row in scene.outliner_items if row.item_type == "CHAIN"]
    assert chains
    chains[0].is_selected = True
    with ui_override("PROPERTIES"):
        result = bpy.ops.proteinblender.create_pose("INVOKE_DEFAULT", pose_name="UI Pose")
    assert result == {"RUNNING_MODAL"}, result
    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return "pose dialog invoked and cancelled through window events"


def invoke_and_cancel_puppet_dialog():
    scene = bpy.context.scene
    chains = [row for row in scene.outliner_items if row.item_type == "CHAIN"]
    assert len(chains) >= 4
    available = {row.item_id for row in chains
                 if row.item_id not in state["puppet_members"]}
    for row in scene.outliner_items:
        row.is_selected = row.item_id in available
    with ui_override("PROPERTIES"):
        result = bpy.ops.proteinblender.create_puppet("INVOKE_DEFAULT", puppet_name="UI Puppet")
    assert result == {"RUNNING_MODAL"}, result
    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return "puppet dialog invoked and cancelled through window events"


def invoke_and_cancel_protein_visuals_dialog():
    """The protein row's edit pencil must open and draw in a real window.

    Its Visual Set-up block seeds itself from the protein's objects in
    invoke() and lays out colour, style, pivot and force-field controls in
    draw(). Neither runs headless - background Blender sends INVOKE_DEFAULT
    straight to execute() - so a draw() that raises would go unnoticed by the
    offline lane entirely.
    """
    protein = next(row for row in bpy.context.scene.outliner_items
                   if row.item_type == "PROTEIN")
    with ui_override("PROPERTIES"):
        result = bpy.ops.proteinblender.edit_protein_visuals(
            "INVOKE_DEFAULT", item_id=protein.item_id)
    assert result == {"RUNNING_MODAL"}, result

    from proteinblender.operators import visual_edit
    dialog = visual_edit.active_dialog()
    assert dialog is not None, "the protein dialog did not register as active"
    objects = dialog.visual_objects(bpy.context)
    assert objects, "the protein dialog resolved no objects to style"

    # The fields must arrive seeded from what is on screen. 4hhb imports with a
    # different colour per chain, so the swatch has no single colour to show:
    # it must be the neutral grey placeholder, flagged, with the shared style
    # still reported properly. Only invoke() seeds - headless never runs it -
    # so this wiring exists nowhere but here.
    carbons = {tuple(round(c, 4) for c in _carbon_rgb(obj))
               for obj in dialog.appearance_objects(bpy.context)
               if _carbon_rgb(obj) is not None}
    assert len(carbons) > 1, f"fixture chains must differ in colour: {carbons}"

    seeded = tuple(round(c, 4) for c in dialog.vs_color)
    assert dialog.vs_color_is_mixed, (
        "a protein whose chains differ did not open flagged as mixed")
    assert seeded == visual_edit.MIXED_COLOR, (
        f"the swatch opened on {seeded}, not the grey placeholder "
        f"{visual_edit.MIXED_COLOR}")
    assert dialog.vs_style == "spheres", (
        f"the style dropdown opened on {dialog.vs_style!r}, not the style "
        f"every chain is actually wearing")

    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return (f"protein visuals dialog opened over {len(objects)} object(s), "
            f"seeded grey for {len(carbons)} chain colours, and cancelled")


def _carbon_rgb(obj):
    """An object's Color Common Carbon socket, read straight off the node."""
    for modifier in obj.modifiers:
        if modifier.type != "NODES" or not modifier.node_group:
            continue
        for node in modifier.node_group.nodes:
            if (node.type == "GROUP" and node.node_tree
                    and "Color Common" in node.node_tree.name
                    and "Carbon" in node.inputs):
                return tuple(node.inputs["Carbon"].default_value[:3])
    return None


def edit_pivot_opens_the_move_gizmo():
    """First click on a chain row's Edit Pivot: the mode opens.

    A helper Empty appears on the chain's current pivot, selected, with the
    Move tool and only the translate gizmo active. Starting from the Rotate
    tool proves the mode switches it rather than inheriting whatever was
    active - a rotation gizmo on a pivot helper is meaningless and reads as
    if the pivot could be spun.
    """
    from proteinblender.operators import pivot_operators as P

    scene = bpy.context.scene
    chain = next(row for row in scene.outliner_items if row.item_type == "CHAIN")
    state["pivot_row"] = chain.item_id

    objects = P.row_pivot_objects(bpy.context, chain)
    assert objects, "the chain row resolved to no objects"
    state["pivot_origin_before"] = list(objects[0].matrix_world.translation)

    with ui_override("VIEW_3D"):
        assert bpy.ops.wm.tool_set_by_id(name="builtin.rotate") == {"FINISHED"}
        assert bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False).idname == "builtin.rotate"
        result = bpy.ops.proteinblender.set_pivot_custom(
            "EXEC_DEFAULT", item_id=chain.item_id)
    assert result == {"FINISHED"}, result

    assert P.pivot_edit_key(scene) == chain.item_id, (
        "Edit Pivot did not open a session for the row that was clicked")

    active = bpy.context.workspace.tools.from_space_view3d_mode(
        "OBJECT", create=False)
    assert active.idname == "builtin.move", (
        f"Edit Pivot left the active tool at {active.idname}")
    view = next(area for area in active_window().screen.areas
                if area.type == "VIEW_3D")
    space = view.spaces.active
    assert space.show_gizmo and space.show_gizmo_tool
    assert space.show_gizmo_object_translate
    assert not space.show_gizmo_object_rotate
    assert not space.show_gizmo_object_scale

    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    assert helper is not None, "Edit Pivot created no helper"
    assert helper.select_get(), "the helper is not selected, so it cannot be dragged"
    assert helper.empty_display_type == "ARROWS", (
        f"the pivot helper draws {helper.empty_display_type} geometry; "
        "SPHERE creates rotation-like circles")
    return "Edit Pivot opened with the translate gizmo on a selected helper"


def edit_pivot_second_click_applies_and_closes():
    """Second click: the helper's position becomes the pivot, and it goes away.

    The helper is dragged first, the way a user would, so the applied pivot is
    somewhere the item's pivot demonstrably was not. Ground truth is the
    helper's own world position, read before the click - not anything the
    pivot code derives.
    """
    from proteinblender.operators import pivot_operators as P

    scene = bpy.context.scene
    chain = next(row for row in scene.outliner_items
                 if row.item_id == state["pivot_row"])
    helper = bpy.data.objects.get(P.PIVOT_HELPER)
    assert helper is not None, "the Edit Pivot session did not survive the tick"

    helper.location = helper.location + Vector((1.5, -0.75, 0.5))
    bpy.context.view_layer.update()
    dropped_at = helper.matrix_world.translation.copy()
    assert (dropped_at - Vector(state["pivot_origin_before"])).length > 1e-3, (
        "the helper was not actually moved, so applying it proves nothing")

    with ui_override("VIEW_3D"):
        result = bpy.ops.proteinblender.set_pivot_custom(
            "EXEC_DEFAULT", item_id=chain.item_id)
    assert result == {"FINISHED"}, result

    assert P.pivot_edit_key(scene) == "", "the Edit Pivot session stayed open"
    assert bpy.data.objects.get(P.PIVOT_HELPER) is None, (
        "the pivot helper survived the second click")

    bpy.context.view_layer.update()
    for obj in P.row_pivot_objects(bpy.context, chain):
        offset = (obj.matrix_world.translation - dropped_at).length
        assert offset < 1e-4, (
            f"{obj.name}'s origin is {offset:.6f} from where the helper was "
            f"dropped; the pivot was not applied")
    return "Edit Pivot applied the dropped position and closed"


def parent_and_domain_pivot_edit_roundtrip():
    """The two scripted Edit Pivot entry points, in a real window.

    ``molecule.toggle_protein_pivot_edit`` and ``molecule.toggle_pivot_edit``
    now share the row button's session, so they use the one helper name and
    the one open/close path. Both still have to complete their own round trip.
    """
    from proteinblender.operators.pivot_operators import PIVOT_HELPER, pivot_edit_key

    molecule = H.sm().molecules[state["molecule_id"]]
    domain_id, domain = next(iter(molecule.domains.items()))
    with ui_override("VIEW_3D"):
        assert bpy.ops.molecule.toggle_protein_pivot_edit(
            molecule_id=state["molecule_id"]) == {"FINISHED"}
        parent_helper = bpy.data.objects.get(PIVOT_HELPER)
        assert parent_helper is not None, "protein Edit Pivot created no helper"
        parent_helper.location.x += 0.05
        assert bpy.ops.molecule.toggle_protein_pivot_edit(
            molecule_id=state["molecule_id"]) == {"FINISHED"}
        assert bpy.data.objects.get(PIVOT_HELPER) is None
        assert pivot_edit_key(bpy.context.scene) == ""

        bpy.context.scene.selected_molecule_id = state["molecule_id"]
        assert bpy.ops.molecule.toggle_pivot_edit(domain_id=domain_id) == {"FINISHED"}
        domain_helper = bpy.data.objects.get(PIVOT_HELPER)
        assert domain_helper is not None and domain_helper.type == "EMPTY"
        assert bpy.context.active_object == domain_helper, (
            "the helper is not the active object, so the gizmo has nothing to "
            "drag")
        domain_helper.location.z += 0.05
        assert bpy.ops.molecule.toggle_pivot_edit(domain_id=domain_id) == {"FINISHED"}
        assert bpy.data.objects.get(PIVOT_HELPER) is None
        assert pivot_edit_key(bpy.context.scene) == ""
    return f"parent and domain pivot helpers completed for {domain.name}"


def invoke_and_cancel_split_dialog():
    chain = next(row for row in bpy.context.scene.outliner_items if row.item_type == "CHAIN")
    with ui_override("PROPERTIES"):
        result = bpy.ops.proteinblender.split_domain_popup(
            "INVOKE_DEFAULT", item_id=chain.item_id, item_type="CHAIN")
    assert result == {"RUNNING_MODAL"}, result
    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return "split-domain popup invoked and cancelled"


def edit_chain_domains_live_boundary_drag():
    """A row edit in the Domain Splitter must re-tile without waiting for check().

    Only reachable with a real window: in background Blender INVOKE_DEFAULT
    falls through to execute(), so there is no live modal instance to drive.

    The re-tile used to be deferred to the operator's check(), which Blender
    does not reliably call for an edit to a CollectionProperty *element*. When
    it did not fire, moving a boundary left the neighbour behind and the
    viewport preview never updated. So this writes the row property directly -
    exactly what the widget does - and never calls check().
    """
    from proteinblender.core import domain_layout
    from proteinblender.operators import domain_splitter as ds
    from proteinblender.utils.chain_utils import default_domain_name

    scene_manager = H.scene_manager_module()
    chain = next(row for row in bpy.context.scene.outliner_items
                 if row.item_type == "CHAIN")
    molecule = H.sm().molecules[chain.parent_id]
    low, high = domain_layout.chain_residue_range(molecule, chain.chain_id)
    pieces = domain_layout.even_split(low, high, 3)
    # Seed with auto-generated names, so the assertions below exercise the
    # "auto names track their range" rule rather than the rename rule.
    letter = next((d.chain_id for d in molecule.domains.values()), "A")
    payload = json.dumps([{"name": default_domain_name(letter, a, b),
                           "start": a, "end": b, "domain_id": ""}
                          for a, b in pieces])
    with ui_override("PROPERTIES"):
        assert bpy.ops.proteinblender.edit_chain_domains(
            "EXEC_DEFAULT", item_id=chain.item_id,
            layout_json=payload) == {"FINISHED"}
    scene_manager.build_outliner_hierarchy(bpy.context)

    chain_id = next(row.item_id for row in bpy.context.scene.outliner_items
                    if row.item_type == "CHAIN")
    with ui_override("PROPERTIES"):
        result = bpy.ops.proteinblender.edit_chain_domains(
            "INVOKE_DEFAULT", item_id=chain_id)
    assert result == {"RUNNING_MODAL"}, result

    instance = ds.PROTEINBLENDER_OT_edit_chain_domains._active_instance
    assert instance is not None, "the dialog published no live instance"
    assert len(instance.rows) == 3, [r.start for r in instance.rows]

    boundary = instance.rows[1].start
    instance.rows[1].start = boundary + 12
    assert instance.rows[1].start == boundary + 12, "the edited value did not stick"
    assert instance.rows[0].end == boundary + 11, (
        f"neighbour did not follow: rows[0].end={instance.rows[0].end}, "
        f"expected {boundary + 11}")

    new_end = instance.rows[1].end - 7
    instance.rows[1].end = new_end
    assert instance.rows[2].start == new_end + 1, (
        f"next domain did not follow: rows[2].start={instance.rows[2].start}")

    node = ds._preview_node(bpy.context)
    assert node is not None, "editing a range did not start the viewport preview"
    shown = (node.inputs["Min"].default_value, node.inputs["Max"].default_value)
    assert shown == (boundary + 12, new_end), (
        f"preview shows {shown}, expected {(boundary + 12, new_end)}")

    # Auto-generated names track their range; a typed one never changes. Both
    # rules only run through the live dialog.
    label = instance.chain_label
    assert instance.rows[0].name == default_domain_name(
        label, instance.rows[0].start, instance.rows[0].end), (
        f"auto name did not follow its range: {instance.rows[0].name!r}")

    instance.rows[1].name = "Catalytic core"
    instance.rows[1].start = instance.rows[1].start + 4
    assert instance.rows[1].name == "Catalytic core", (
        "a typed name was overwritten by a boundary edit")

    # Changing the count re-divides. This is a method call on the operator
    # through a property update callback, which RNA's `self` wrapper cannot
    # serve - it used to raise AttributeError and leave the rows untouched.
    instance.domain_count = 4
    assert len(instance.rows) == 4, (
        f"changing the count did not re-divide: {len(instance.rows)} rows")
    assert "Catalytic core" in [r.name for r in instance.rows], (
        "the typed name was lost when the chain was re-divided")
    for row in instance.rows:
        assert row.name == "Catalytic core" or row.name == default_domain_name(
            label, row.start, row.end), f"stale auto name {row.name!r}"

    state["splitter_hidden"] = ds._PREVIEW_HIDDEN in bpy.context.scene
    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return f"boundary drag re-tiled live; preview showed {shown}"


def edit_chain_domains_first_start_drag():
    """Dragging the FIRST domain's Start must move it, not stall at the chain.

    Raising it orphans the residues below, and the fix for that used to be to
    insert a domain in front - which moved every later row down by one, out
    from under the cursor. What the user carried on dragging was the domain
    just inserted ahead of theirs, and that one is pinned to the start of the
    chain and cannot move at all, so the drag died one residue in and left a
    stray 1-1 domain behind. Reported as "it just snaps to 2 and creates a new
    domain from 1-1".

    Only reachable through a live dialog: the row list is a CollectionProperty,
    and Blender does not call check() for an edit to a collection *element*, so
    the whole structural path this exercises never ran in the headless lane.
    """
    from proteinblender.core import domain_layout
    from proteinblender.operators import domain_splitter as ds

    scene_manager = H.scene_manager_module()
    # Deliberately the LAST chain, not the first. This scenario is the only one
    # here that *commits*, and the undo scenarios further down rebuild the
    # first chain's domains from scratch and assume the domain covering its
    # first residue is the one they delete. Committing a fourth domain onto
    # that chain quietly broke them.
    # Filtered by parent: earlier scenarios leave CHAIN rows parented to a
    # puppet, and those are not molecules.
    chains = [row for row in bpy.context.scene.outliner_items
              if row.item_type == "CHAIN" and row.parent_id in H.sm().molecules]
    assert len(chains) > 1, "expected a multi-chain fixture"
    chain = chains[-1]
    # Plain values, not the row: build_outliner_hierarchy rebuilds the
    # collection below and every bpy_struct into it goes stale.
    chain_key, parent_id = chain.item_id, chain.parent_id
    molecule = H.sm().molecules[parent_id]
    chain_letter = molecule.chain_mapping[int(chain.chain_id)]
    low, high = domain_layout.chain_residue_range(molecule, chain.chain_id)
    pieces = domain_layout.even_split(low, high, 3)
    payload = json.dumps([{"name": f"Seed {i}", "start": a, "end": b,
                           "domain_id": ""}
                          for i, (a, b) in enumerate(pieces, start=1)])
    with ui_override("PROPERTIES"):
        assert bpy.ops.proteinblender.edit_chain_domains(
            "EXEC_DEFAULT", item_id=chain.item_id,
            layout_json=payload) == {"FINISHED"}
    scene_manager.build_outliner_hierarchy(bpy.context)

    chain_id = next(row.item_id for row in bpy.context.scene.outliner_items
                    if row.item_type == "CHAIN" and row.item_id == chain_key)
    with ui_override("PROPERTIES"):
        result = bpy.ops.proteinblender.edit_chain_domains(
            "INVOKE_DEFAULT", item_id=chain_id)
    assert result == {"RUNNING_MODAL"}, result

    instance = ds.PROTEINBLENDER_OT_edit_chain_domains._active_instance
    assert instance is not None, "the dialog published no live instance"
    assert instance.rows[0].start == low, (
        f"the first row should start at the chain's first residue, "
        f"got {instance.rows[0].start}")
    seeded = len(instance.rows)

    # A drag: Blender fires the update callback once per step, on whatever
    # element sits at row 0 *at that moment*. That is the whole bug.
    target = low + 12
    for _ in range(12):
        instance.rows[0].start = instance.rows[0].start + 1
        instance.check(bpy.context)

    assert instance.rows[0].start == target, (
        f"the drag stalled: rows[0].start reached {instance.rows[0].start}, "
        f"expected {target}")
    assert len(instance.rows) == seeded, (
        f"dragging inserted rows mid-drag: {[(r.start, r.end) for r in instance.rows]}")
    assert instance.rows[0].end > target, "the first domain lost its body"

    # The stretch the drag orphaned gets its own adjuster above the rows. It is
    # drawn from operator properties, not a CollectionProperty element, which
    # is the whole point: a real row there would move the dragged row down and
    # steal the drag, however the insertion is timed.
    assert instance.has_head(), "no adjuster appeared for the orphaned head"
    assert instance.head_end == target - 1, (
        f"the head adjuster ends at {instance.head_end}, expected {target - 1}")
    assert instance.head_name, "the head adjuster has no name to be created with"
    assert not instance.has_tail(), (
        "the far end of the chain is still covered, so no tail adjuster is due")

    # It is a real control, not a label: moving its End moves the boundary.
    instance.head_end = target + 9
    assert instance.rows[0].start == target + 10, (
        f"editing the head adjuster did not move the first domain: "
        f"{[(r.start, r.end) for r in instance.rows]}")
    instance.head_end = target - 1
    assert instance.rows[0].start == target, "the boundary did not come back"

    # A name typed into the adjuster is the name the domain is created with.
    instance.head_name = "Typed Head"

    # Commit through the dialog's own path - execute() on the live instance,
    # with no layout_json - because that is where the orphaned head is turned
    # into a domain. Going via layout_json would take the rows literally and
    # prove nothing about the completion.
    with ui_override("PROPERTIES"):
        assert instance.execute(bpy.context) == {"FINISHED"}
    ds.PROTEINBLENDER_OT_edit_chain_domains._active_instance = None
    scene_manager.build_outliner_hierarchy(bpy.context)

    molecule = H.sm().molecules[parent_id]
    spans = sorted((d.start, d.end) for d in molecule.domains.values()
                   if str(d.chain_id) == str(chain_letter))
    assert (low, target - 1) in spans, (
        f"the orphaned head {low}-{target - 1} did not become a domain: {spans}")
    assert (target, pieces[0][1]) in spans, (
        f"the dragged domain should now be {target}-{pieces[0][1]}: {spans}")
    covered = set()
    for start, end in spans:
        covered |= set(range(start, end + 1))
    assert covered == set(range(low, high + 1)), (
        "committing left the chain not fully covered")
    created = next(d for d in molecule.domains.values()
                   if str(d.chain_id) == str(chain_letter)
                   and (d.start, d.end) == (low, target - 1))
    assert created.name == "Typed Head", (
        f"the adjuster's name did not reach the domain: {created.name!r}")

    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return (f"first-domain Start dragged {low} -> {target}; head adjuster "
            f"committed as {created.name!r}")


def edit_chain_domains_last_end_drag():
    """The mirror case: dragging the LAST domain's End opens a tail adjuster.

    The same trap one row further down - except a row appended *below* the
    dragged one never moves it, so this half was always safe. It still has to
    produce an adjuster rather than silently orphaning the chain's tail, and
    that adjuster has to drive the boundary above it.
    """
    from proteinblender.core import domain_layout
    from proteinblender.operators import domain_splitter as ds

    scene_manager = H.scene_manager_module()
    chains = [row for row in bpy.context.scene.outliner_items
              if row.item_type == "CHAIN" and row.parent_id in H.sm().molecules]
    assert len(chains) > 2, "expected a multi-chain fixture"
    # A chain of its own: the first belongs to the undo scenarios and the last
    # to the head-adjuster scenario, and this one commits too.
    chain = chains[-2]
    # Plain values, not the row: build_outliner_hierarchy rebuilds the
    # collection below and every bpy_struct into it goes stale.
    chain_key, parent_id = chain.item_id, chain.parent_id
    molecule = H.sm().molecules[parent_id]
    chain_letter = molecule.chain_mapping[int(chain.chain_id)]
    low, high = domain_layout.chain_residue_range(molecule, chain.chain_id)
    pieces = domain_layout.even_split(low, high, 2)
    with ui_override("PROPERTIES"):
        assert bpy.ops.proteinblender.edit_chain_domains(
            "EXEC_DEFAULT", item_id=chain.item_id,
            layout_json=json.dumps(
                [{"name": f"Seed {i}", "start": a, "end": b, "domain_id": ""}
                 for i, (a, b) in enumerate(pieces, start=1)])) == {"FINISHED"}
    scene_manager.build_outliner_hierarchy(bpy.context)

    with ui_override("PROPERTIES"):
        assert bpy.ops.proteinblender.edit_chain_domains(
            "INVOKE_DEFAULT", item_id=chain_key) == {"RUNNING_MODAL"}
    instance = ds.PROTEINBLENDER_OT_edit_chain_domains._active_instance
    assert instance is not None, "the dialog published no live instance"
    seeded = len(instance.rows)
    assert instance.rows[-1].end == high, "the last row should reach the chain end"
    assert not instance.has_tail(), "nothing is orphaned yet"

    target = high - 15
    for _ in range(15):
        instance.rows[-1].end = instance.rows[-1].end - 1
        instance.check(bpy.context)

    assert instance.rows[-1].end == target, (
        f"the drag stalled: rows[-1].end reached {instance.rows[-1].end}, "
        f"expected {target}")
    assert len(instance.rows) == seeded, "a row was appended mid-drag"
    assert instance.has_tail(), "no adjuster appeared for the orphaned tail"
    assert instance.tail_start == target + 1, (
        f"the tail adjuster starts at {instance.tail_start}, expected "
        f"{target + 1}")
    assert instance.tail_name, "the tail adjuster has no name to be created with"

    # Editing the adjuster's Start moves the last domain's End.
    instance.tail_start = target - 4
    assert instance.rows[-1].end == target - 5, (
        "editing the tail adjuster did not move the domain above it")
    instance.tail_start = target + 1
    assert instance.rows[-1].end == target, "the boundary did not come back"
    instance.tail_name = "Typed Tail"

    with ui_override("PROPERTIES"):
        assert instance.execute(bpy.context) == {"FINISHED"}
    ds.PROTEINBLENDER_OT_edit_chain_domains._active_instance = None
    scene_manager.build_outliner_hierarchy(bpy.context)

    molecule = H.sm().molecules[parent_id]
    domains = [d for d in molecule.domains.values()
               if str(d.chain_id) == str(chain_letter)]
    spans = sorted((d.start, d.end) for d in domains)
    assert (target + 1, high) in spans, (
        f"the orphaned tail {target + 1}-{high} did not become a domain: {spans}")
    covered = set()
    for start, end in spans:
        covered |= set(range(start, end + 1))
    assert covered == set(range(low, high + 1)), (
        "committing left the chain not fully covered")
    created = next(d for d in domains if (d.start, d.end) == (target + 1, high))
    assert created.name == "Typed Tail", (
        f"the adjuster's name did not reach the domain: {created.name!r}")

    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return (f"last-domain End dragged {high} -> {target}; tail adjuster "
            f"committed as {created.name!r}")


def assert_splitter_preview_restored():
    """Cancelling the dialog must un-hide everything it isolated."""
    from proteinblender.operators import domain_splitter as ds

    assert state.get("splitter_hidden"), "the preview never isolated anything"
    assert ds._PREVIEW_OBJECT not in bpy.context.scene, (
        "cancelling the Domain Splitter left its preview bookkeeping behind")
    hidden = [obj.name for obj in bpy.data.objects
              if obj.type in ds._ISOLATABLE_TYPES and obj.hide_viewport]
    assert not hidden, f"cancelling left these objects hidden: {hidden}"
    return "splitter preview restored on cancel"


def dna_edit_mode_roundtrip():
    dna = H.build_dna(seq="ATCGATCG", name_prefix="UI_DNA")
    state["dna"] = dna.name
    H.select_only(dna)
    with ui_override("VIEW_3D"):
        bpy.ops.proteinblender.dna_add_bend()
        assert bpy.ops.proteinblender.dna_edit_bend() == {"FINISHED"}
        assert bpy.ops.proteinblender.dna_finish_bend_edit() == {"FINISHED"}
    assert bpy.context.view_layer.objects.active == dna
    return "DNA bend edit-mode roundtrip"


def membrane_edit_mode_roundtrip():
    names = H.build_membrane(shape="FLAT", width=8, height=8)
    roots = [bpy.data.objects[name] for name in names
             if bpy.data.objects.get(name) and bpy.data.objects[name].get("pb_is_membrane")]
    assert roots, f"no membrane root in {names}"
    root = roots[0]
    state["membrane"] = root.name
    H.select_only(root)
    with ui_override("VIEW_3D"):
        assert bpy.ops.proteinblender.membrane_edit_deform() == {"FINISHED"}
        assert bpy.ops.proteinblender.membrane_finish_deform() == {"FINISHED"}
    return "membrane deform edit-mode roundtrip"


def create_domain_for_undo():
    scene = bpy.context.scene
    mol_id = state["molecule_id"]
    molecule = H.sm().molecules[mol_id]
    scene.selected_molecule_id = mol_id
    chain_index = sorted(molecule.chain_mapping)[0]
    chain_id = molecule.chain_mapping[chain_index]
    auto_domain = next(domain_id for domain_id, domain in molecule.domains.items()
                       if domain.chain_id == chain_id)
    assert bpy.ops.molecule.delete_domain(
        molecule_id=mol_id, domain_id=auto_domain) == {"FINISHED"}
    before = set(molecule.domains)
    item = next(item for item in scene.molecule_list_items
                if item.identifier == mol_id)
    properties_before = {domain.domain_id for domain in item.domains}
    min_res, max_res = molecule.chain_residue_ranges[chain_id]
    scene.new_domain_chain = str(chain_index)
    scene.new_domain_start = min_res
    scene.new_domain_end = min(min_res + 8, max_res)
    # Timer callbacks are not themselves UI operators, so establish an
    # explicit user-visible undo boundary before executing the add-on
    # operator. Ctrl+Z below still travels through Blender's real window event
    # system and exercises the add-on's undo_post reconstruction handler.
    with ui_override("VIEW_3D"):
        assert bpy.ops.ed.undo_push(message="PB UI domain baseline") == {"FINISHED"}
    result = bpy.ops.molecule.create_domain()
    assert result == {"FINISHED"}, result
    created = set(molecule.domains) - before
    assert created, "domain operation changed no runtime state"
    state["undo_domains_before"] = before
    state["undo_properties_before"] = properties_before
    # Timer-driven bpy.ops calls do not receive Blender's normal UI operator
    # completion bookkeeping. Capture the post-operation state explicitly so
    # undo traverses from this state to the baseline pushed above.
    with ui_override("VIEW_3D"):
        assert bpy.ops.ed.undo_push(message="PB UI domain created") == {"FINISHED"}
    return "created domain behind explicit UI undo boundary"


def perform_undo():
    with ui_override("VIEW_3D"):
        result = bpy.ops.ed.undo()
    assert result == {"FINISHED"}, result
    return "executed Blender UI undo operator"


def domain_state_snapshot():
    mol_id = state["molecule_id"]
    item = next(item for item in bpy.context.scene.molecule_list_items
                if item.identifier == mol_id)
    return {
        "runtime": sorted(H.sm().molecules[mol_id].domains),
        "properties": sorted(domain.domain_id for domain in item.domains),
    }


def assert_undo_and_send_redo():
    mol_id = state["molecule_id"]
    before = state["undo_domains_before"]
    H.scene_manager_module().sync_molecule_list_after_undo()
    snapshot = domain_state_snapshot()
    unexpected = set(snapshot["runtime"]) - before
    assert not unexpected, (
        f"undo retained created domains {sorted(unexpected)}; state={snapshot}; "
        f"persisted baseline={sorted(state['undo_properties_before'])}"
    )
    with ui_override("VIEW_3D"):
        result = bpy.ops.ed.redo()
    assert result == {"FINISHED"}, result
    return "undo restored baseline; executed Blender UI redo operator"


def assert_redo():
    mol_id = state["molecule_id"]
    before = state["undo_domains_before"]
    H.scene_manager_module().sync_molecule_list_after_undo()
    assert set(H.sm().molecules[mol_id].domains) - before, "redo did not restore domain"
    return "domain create -> undo -> redo"


def save_report_and_quit():
    ok = all(item["ok"] for item in results)
    Path(report_path).write_text(json.dumps({
        "ok": ok,
        "blender": bpy.app.version_string,
        "results": results,
    }, indent=2), encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


steps = [
    ("setup and real workspace", setup),
    ("settle workspace activation 1", lambda: "workspace event-loop tick"),
    ("settle workspace activation 2", lambda: "workspace event-loop tick"),
    ("verify Protein Blender Scene UI", verify_workspace_ui),
    ("assert ProteinBlender UI loaded", assert_proteinblender_ui_loaded),
    ("draw every panel", redraw_all_panels),
    ("settle panel redraw", lambda: "redraw event loop tick completed"),
    ("pose invoke dialog", invoke_and_cancel_pose_dialog),
    ("settle pose modal", lambda: "modal cancellation processed"),
    ("puppet invoke dialog", invoke_and_cancel_puppet_dialog),
    ("settle puppet modal", lambda: "modal cancellation processed"),
    ("protein visuals invoke dialog", invoke_and_cancel_protein_visuals_dialog),
    ("settle protein visuals modal", lambda: "modal cancellation processed"),
    ("edit pivot opens the move gizmo", edit_pivot_opens_the_move_gizmo),
    ("settle edit pivot open", lambda: "gizmo activation processed"),
    ("edit pivot second click applies",
     edit_pivot_second_click_applies_and_closes),
    ("parent and domain pivot edit", parent_and_domain_pivot_edit_roundtrip),
    ("split domain invoke dialog", invoke_and_cancel_split_dialog),
    ("settle split modal", lambda: "modal cancellation processed"),
    ("domain splitter live boundary drag", edit_chain_domains_live_boundary_drag),
    ("settle splitter modal", lambda: "modal cancellation processed"),
    ("domain splitter first-start drag", edit_chain_domains_first_start_drag),
    ("settle first-start modal", lambda: "modal cancellation processed"),
    ("domain splitter last-end drag", edit_chain_domains_last_end_drag),
    ("settle last-end modal", lambda: "modal cancellation processed"),
    ("assert splitter preview restored", assert_splitter_preview_restored),
    ("DNA edit mode", dna_edit_mode_roundtrip),
    ("membrane edit mode", membrane_edit_mode_roundtrip),
    ("create domain for undo", create_domain_for_undo),
    ("perform undo", perform_undo),
    ("settle undo event 1", lambda: f"undo settle: {domain_state_snapshot()}"),
    ("settle undo event 2", lambda: f"undo settle: {domain_state_snapshot()}"),
    ("assert undo and send redo", assert_undo_and_send_redo),
    ("settle redo event 1", lambda: f"redo settle: {domain_state_snapshot()}"),
    ("settle redo event 2", lambda: f"redo settle: {domain_state_snapshot()}"),
    ("assert redo", assert_redo),
]


def advance():
    if steps:
        name, function = steps.pop(0)
        record(name, function)
        if not results[-1]["ok"]:
            steps.clear()
        return 0.15
    return save_report_and_quit()


bpy.app.timers.register(advance, first_interval=0.1)
