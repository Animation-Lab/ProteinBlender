"""GUI-only geometry check for the Protein Blender workspace right column.

This is the width/position half of the regression guard (the always-on decision
half lives in ``tests/unit/test_workspace_layout.py``). It drives the *real*
``ProteinWorkspaceManager`` against a live window and measures the resulting
editor areas, because a panel's width, x-position and height simply do not exist
in a ``--background`` session — there is no window or screen to lay out.

So under the standard headless harness (``python tests/run_tests.py``, which
launches Blender with ``--background``) every test here SKIPS with a clear
reason. Run the suite inside a windowed Blender — e.g. the VS Code "Blender
Development" extension, or ``blender --python tests/run_blender.py`` without
``--background`` — and they execute and assert on real geometry.

Regression being guarded (2026-07): the add-on inherited the default Layout
right column — a native **Outliner** editor stacked above a **narrow**
Properties editor — instead of the single full-height ~30%-wide Properties
column it is designed around.

Ground truth is independent of the product code: the intended design is
viewport 70% / Properties 30% (split factor 0.7), a right-aligned column that
runs the full height with no editor stacked above it, and no native OUTLINER
anywhere. The regression produced an Outliner in the column, a Properties area
only ~18% wide, and only ~half height. Every threshold below sits in the gap
between those two states, so the assertions fail on the bug and pass on the fix.
"""

import bpy
import pytest

from proteinblender.layout.workspace_setup import ProteinWorkspaceManager

WS_NAME = "Protein Blender"

# Intended split: viewport 0.7 | Properties 0.3. The regression left Properties
# at the stock Layout width (~0.18 of the window). 0.25 cleanly separates them.
MIN_PANEL_WIDTH_FRAC = 0.25
MAX_PANEL_WIDTH_FRAC = 0.5
# Fixed column runs nearly the full window height (measured live: 0.95); the
# regressed one was 0.77 because the Outliner ate the top of the column. 0.85
# sits in the gap so the height check alone discriminates the two states.
MIN_PANEL_HEIGHT_FRAC = 0.85


def _gui_window():
    """A window manager window that owns a real screen, or None headless."""
    wm = bpy.context.window_manager
    for win in getattr(wm, "windows", []) or []:
        if getattr(win, "screen", None) is not None:
            return win
    return None


def _build_workspace(win):
    """Run the full public setup sequence on the live session, then return the
    (window, screen) that hosts the Protein Blender workspace."""
    mgr = ProteinWorkspaceManager(WS_NAME)
    mgr.create_custom_workspace()
    mgr.add_panels_to_workspace()
    mgr.set_properties_context()

    ws = bpy.data.workspaces.get(WS_NAME)
    assert ws is not None, "workspace setup did not create the Protein Blender workspace"
    # Find the window showing our workspace (setup activates it on some window).
    for w in bpy.context.window_manager.windows:
        if w.workspace == ws and w.screen is not None:
            return w, w.screen
    # Fall back to the manager's own bound handles.
    return mgr.window or win, mgr.screen


@pytest.fixture
def workspace_screen():
    win = _gui_window()
    if win is None:
        pytest.skip("workspace geometry needs a real Blender window (run in a "
                    "GUI Blender; --background has no screen)")
    return _build_workspace(win)


def _properties_area(screen):
    props = [a for a in screen.areas if a.type == "PROPERTIES"]
    assert props, "no Properties editor in the Protein Blender workspace"
    # The panel column is the tallest Properties area (there is only one).
    return max(props, key=lambda a: a.height)


@pytest.mark.gui
@pytest.mark.integration
def test_no_native_outliner_in_workspace(workspace_screen):
    _win, screen = workspace_screen
    outliners = [a for a in screen.areas if a.type == "OUTLINER"]
    assert not outliners, (
        "the Protein Blender workspace still has a native Outliner editor; the "
        "right column was not consolidated (the Protein Outliner is a panel "
        "inside Properties, not an OUTLINER editor)")


@pytest.mark.gui
@pytest.mark.integration
def test_panel_is_wide_enough(workspace_screen):
    win, screen = workspace_screen
    props = _properties_area(screen)
    frac = props.width / win.width
    assert MIN_PANEL_WIDTH_FRAC <= frac <= MAX_PANEL_WIDTH_FRAC, (
        f"Properties panel width fraction {frac:.3f} outside intended "
        f"[{MIN_PANEL_WIDTH_FRAC}, {MAX_PANEL_WIDTH_FRAC}] — the regression left "
        f"it at the stock ~0.18 Layout width")


@pytest.mark.gui
@pytest.mark.integration
def test_panel_is_on_the_right(workspace_screen):
    win, screen = workspace_screen
    props = _properties_area(screen)
    # Its right edge hugs the window's right edge, and it starts past the middle.
    right_edge = props.x + props.width
    assert right_edge >= win.width - 4, (
        f"Properties panel right edge {right_edge} is not against the window "
        f"right edge {win.width}")
    assert props.x > win.width * 0.5, (
        f"Properties panel starts at x={props.x}, left of the window midpoint "
        f"{win.width * 0.5:.0f}; it is not the right column")


@pytest.mark.gui
@pytest.mark.integration
def test_panel_runs_full_height_with_nothing_stacked_above(workspace_screen):
    win, screen = workspace_screen
    props = _properties_area(screen)

    frac = props.height / win.height
    assert frac >= MIN_PANEL_HEIGHT_FRAC, (
        f"Properties panel height fraction {frac:.3f} below {MIN_PANEL_HEIGHT_FRAC} "
        f"— an editor is eating the top of the column (the regressed Outliner)")

    # Direct "nothing stacked on top" invariant: no other area shares the
    # panel's horizontal span and sits above it. This is what the Outliner did.
    p_lo, p_hi = props.x, props.x + props.width
    stacked = []
    for a in screen.areas:
        if a == props:
            continue
        a_lo, a_hi = a.x, a.x + a.width
        overlap = min(p_hi, a_hi) - max(p_lo, a_lo)
        if overlap > props.width * 0.5 and a.y > props.y:
            stacked.append((a.type, a.y))
    assert not stacked, (
        f"editor(s) stacked above the Properties column: {stacked} — the right "
        f"column must be a single full-height Properties panel")
