"""The live harness testing itself.

If these fail, nothing else in the lane can be trusted: the connection, the
remote code path, scene isolation between tests, and the viewport capture are
what every other live module is built on.
"""

from __future__ import annotations

import pytest


@pytest.mark.live
def test_connection_reports_a_usable_live_blender(blender):
    environment = blender.environment
    assert environment["addon_loaded"], "ProteinBlender is not enabled"
    assert environment["has_view3d"], "no 3D viewport to observe"
    assert not environment["background"], (
        "this lane must drive a windowed Blender; a background process has no "
        "viewport and would silently reduce every visual test to a no-op")


@pytest.mark.live
def test_remote_calls_return_values_and_bind_arguments(blender):
    assert blender.call("return 2 + 2") == 4
    assert blender.call("return [x * n for x in values]",
                        values=[1, 2, 3], n=3) == [3, 6, 9]


@pytest.mark.live
def test_remote_exceptions_surface_as_failures_with_a_traceback(blender):
    """A remote error must fail the test loudly, carrying the Blender-side
    traceback. Silent success on a broken call would make the lane worthless."""
    from mcp_client import LiveBlenderError

    with pytest.raises(LiveBlenderError) as caught:
        blender.call("raise ValueError('deliberate harness probe')")
    assert "deliberate harness probe" in str(caught.value)
    assert "ValueError" in str(caught.value)


@pytest.mark.live
def test_scene_starts_clean(blender, snapshot_state):
    """The autouse reset must hand every test an empty add-on scene."""
    state = snapshot_state()
    assert state["molecules"] == []
    assert state["molecule_rows"] == []
    assert state["outliner"] == []


@pytest.mark.live
def test_import_registers_a_molecule_and_leaves_no_residue(blender,
                                                           snapshot_state):
    molecule_id = blender.call('return H.import_local("1ubq.pdb", "1ubq")')
    assert molecule_id == "1ubq"
    state = snapshot_state()
    assert "1ubq" in state["molecules"]
    assert "1ubq" in state["molecule_rows"]
    # The next test's clean-scene assertion is what proves teardown works; here
    # we only prove the import was real.
    assert any(item["type"] == "CHAIN" for item in state["outliner"])


@pytest.mark.live
@pytest.mark.visual
def test_empty_scene_renders_nothing_and_a_molecule_renders_something(
        blender, shot):
    """The capture path must be able to tell empty from non-empty.

    This is the calibration for every coverage assertion in the lane. If an
    empty scene already reported coverage, "the molecule is on screen" would be
    unfalsifiable.
    """
    empty = shot("empty", frame=False)
    assert empty["covered"] == 0, (
        f"an empty scene rendered {empty['covered']} covered pixels; the "
        "capture is picking up something other than add-on geometry")

    blender.call('return H.import_local("1ubq.pdb", "1ubq")')
    loaded = shot("with-1ubq")
    assert loaded["covered"] > 0, "an imported molecule rendered nothing"


@pytest.mark.live
@pytest.mark.visual
def test_captures_can_be_compared_without_transferring_images(blender, shot):
    """``R.capture`` / ``R.compare`` underpin every metamorphic visual test."""
    blender.call('return H.import_local("1ubq.pdb", "1ubq")')
    blender.call("return R.frame_all()")
    blender.call('return R.capture("a")')
    blender.call('return R.capture("b")')

    same = blender.call('return R.compare("a", "b")')
    assert same["xor"] == 0, "two captures of an unchanged scene differed"
    assert same["iou"] == pytest.approx(1.0)
