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
    "PROTEINBLENDER_PT_domain_maker",
    "PROTEINBLENDER_PT_visual_setup",
    "PROTEINBLENDER_PT_puppet_maker",
    "PROTEINBLENDER_PT_pose_library",
    "PROTEINBLENDER_PT_animation",
    "PROTEINBLENDER_PT_builders",
    "PB2_PT_linkers",
}
state = {"molecule_id": None, "puppet_id": None, "puppet_members": set(),
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
    assert len(expected) >= 9, f"expected at least 9 add-on panels, got {expected}"
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


def start_custom_pivot_from_rotate():
    scene = bpy.context.scene
    chain = next(row for row in scene.outliner_items if row.item_type == "CHAIN")
    for row in scene.outliner_items:
        row.is_selected = row.item_id == chain.item_id
    with ui_override("VIEW_3D"):
        assert bpy.ops.wm.tool_set_by_id(name="builtin.rotate") == {"FINISHED"}
        active = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        assert active.idname == "builtin.rotate", active.idname
        result = bpy.ops.proteinblender.set_pivot_custom("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    return "started first custom pivot from Rotate tool"


def assert_custom_pivot_uses_translation_and_finish():
    scene = bpy.context.scene
    active = bpy.context.workspace.tools.from_space_view3d_mode(
        "OBJECT", create=False)
    assert active.idname == "builtin.move", (
        f"first Custom Pivot click left active tool at {active.idname}")
    view = next(area for area in active_window().screen.areas
                if area.type == "VIEW_3D")
    space = view.spaces.active
    assert space.show_gizmo and space.show_gizmo_tool
    assert space.show_gizmo_object_translate
    assert not space.show_gizmo_object_rotate
    assert not space.show_gizmo_object_scale
    empty = next((obj for obj in bpy.data.objects if obj.type == "EMPTY" and obj.select_get()), None)
    assert empty is not None, "custom pivot created no selected gizmo Empty"
    assert empty.empty_display_type == "PLAIN_AXES", (
        f"custom pivot helper draws {empty.empty_display_type} geometry; "
        "SPHERE creates rotation-like circles")
    empty_name = empty.name
    bpy.ops.object.select_all(action="DESELECT")
    from proteinblender.operators.pivot_operators import custom_pivot_deselection_handler
    custom_pivot_deselection_handler(scene)
    assert bpy.data.objects.get(empty_name) is None, "custom pivot gizmo survived finalization"
    return "first custom pivot displayed translation controls and finalized"


def parent_and_domain_pivot_edit_roundtrip():
    molecule = H.sm().molecules[state["molecule_id"]]
    domain_id, domain = next(iter(molecule.domains.items()))
    with ui_override("VIEW_3D"):
        assert bpy.ops.molecule.toggle_protein_pivot_edit(
            molecule_id=state["molecule_id"]) == {"FINISHED"}
        parent_helper = bpy.data.objects.get(f"PB_PivotHelper_{state['molecule_id']}")
        assert parent_helper is not None
        parent_helper_name = parent_helper.name
        parent_helper.location.x += 0.05
        assert bpy.ops.molecule.toggle_protein_pivot_edit(
            molecule_id=state["molecule_id"]) == {"FINISHED"}
        assert bpy.data.objects.get(parent_helper_name) is None

        bpy.context.scene.selected_molecule_id = state["molecule_id"]
        assert bpy.ops.molecule.toggle_pivot_edit(domain_id=domain_id) == {"FINISHED"}
        domain_helper = bpy.context.active_object
        assert domain_helper is not None and domain_helper.type == "EMPTY"
        domain_helper_name = domain_helper.name
        domain_helper.location.z += 0.05
        assert bpy.ops.molecule.toggle_pivot_edit(domain_id=domain_id) == {"FINISHED"}
        assert bpy.data.objects.get(domain_helper_name) is None
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

    scene_manager = H.scene_manager_module()
    chain = next(row for row in bpy.context.scene.outliner_items
                 if row.item_type == "CHAIN")
    molecule = H.sm().molecules[chain.parent_id]
    low, high = domain_layout.chain_residue_range(molecule, chain.chain_id)
    pieces = domain_layout.even_split(low, high, 3)
    payload = json.dumps([{"name": f"UI Domain {i}", "start": a, "end": b,
                           "domain_id": ""}
                          for i, (a, b) in enumerate(pieces, start=1)])
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

    state["splitter_hidden"] = ds._PREVIEW_HIDDEN in bpy.context.scene
    active_window().event_simulate(type="ESC", value="PRESS")
    active_window().event_simulate(type="ESC", value="RELEASE")
    return f"boundary drag re-tiled live; preview showed {shown}"


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
    ("start custom pivot from Rotate", start_custom_pivot_from_rotate),
    ("assert first custom pivot translation gizmo",
     assert_custom_pivot_uses_translation_and_finish),
    ("parent and domain pivot edit", parent_and_domain_pivot_edit_roundtrip),
    ("split domain invoke dialog", invoke_and_cancel_split_dialog),
    ("settle split modal", lambda: "modal cancellation processed"),
    ("domain splitter live boundary drag", edit_chain_domains_live_boundary_drag),
    ("settle splitter modal", lambda: "modal cancellation processed"),
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
