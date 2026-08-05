"""The workspace builder must not drive UI operators in a headless Blender.

`ProteinWorkspaceManager` rearranges editors with `screen.area_close`,
`screen.area_split` and `workspace.duplicate`. Those complete by way of the
window event loop, and `blender --background` has no event loop, so
`screen.area_close` never returns: it spins at 100% CPU forever.

That is not hypothetical. It wedged every leg of the nightly artifact job -
ubuntu, windows and macos - for 45 minutes apiece, and a py-spy profile of a
headless repro put 790 of 798 samples in exactly one stack:

    create_workspace_on_load   (handlers/load_handlers.py)
      add_panels_to_workspace  (layout/workspace_setup.py)
        _reduce_to_main_viewport -> bpy.ops.screen.area_close()

These tests pin the guard rather than the symptom: a hang cannot be asserted on
directly without wedging the suite, so they prove the UI path is never entered.
The UI entry points are replaced with something that raises, so a regression
fails loudly and instantly instead of hanging CI.
"""

from __future__ import annotations

import bpy
import pytest

from proteinblender.layout.workspace_setup import ProteinWorkspaceManager


# Never collides with a real workspace, so the "already exists" early return can
# not make these pass vacuously.
UNIQUE_NAME = "PB Headless Contract Probe"


def test_suite_runs_headless():
    """Guards the premise of the other two tests in this module."""
    assert bpy.app.background, (
        "these contracts only mean anything in a background Blender")


def test_add_panels_does_not_touch_the_ui_in_background(monkeypatch):
    manager = ProteinWorkspaceManager(UNIQUE_NAME)

    def explode():
        raise AssertionError(
            "add_panels_to_workspace entered the UI path in a background "
            "Blender; screen.area_close there never returns")

    monkeypatch.setattr(manager, "_discover_editor_areas", explode)

    manager.add_panels_to_workspace()


def test_create_custom_workspace_does_not_duplicate_in_background(monkeypatch):
    manager = ProteinWorkspaceManager(UNIQUE_NAME)
    assert UNIQUE_NAME not in bpy.data.workspaces

    def explode(*args, **kwargs):
        raise AssertionError(
            "create_custom_workspace called workspace.duplicate in a "
            "background Blender")

    monkeypatch.setattr(bpy.ops.workspace, "duplicate", explode)

    manager.create_custom_workspace()

    assert UNIQUE_NAME not in bpy.data.workspaces, (
        "a headless run must not materialise a UI workspace")
