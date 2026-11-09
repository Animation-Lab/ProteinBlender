"""The foreground UI runner keeps Blender's temp files out of the shared Temp.

A windowed Blender writes quit.blend (File > Recover > Last Session) into its
temp directory when it quits. Before 2026-11-08 the UI runner left that at the
system Temp, so each foreground run overwrote the developer's own recovery
file. The runner now gives every run a private temp and, before starting,
asks a real headless Blender where its temp is. These tests launch that same
Blender and check its answer, not the environment the runner builds.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import bpy
import pytest

RUNNER = Path(__file__).resolve().parents[1] / "run_ui_tests.py"


def _runner():
    spec = importlib.util.spec_from_file_location("pb_run_ui_tests", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blender_uses_the_private_temp_it_is_given(tmp_path):
    runner = _runner()
    env = runner.private_temp_env(tmp_path, bpy.app.binary_path)
    private = runner.assert_private_temp(bpy.app.binary_path, env, ["--factory-startup"])
    assert Path(private) == tmp_path / "blender-temp"


def test_a_run_whose_blender_temp_is_elsewhere_is_refused(tmp_path):
    runner = _runner()
    # Blender is given one directory while the run expects another: what
    # happens when TEMP never reaches it and it falls back to the shared one.
    (tmp_path / "given").mkdir()
    env = runner.private_temp_env(tmp_path / "given", bpy.app.binary_path)
    elsewhere = tmp_path / "expected"
    elsewhere.mkdir()
    with pytest.raises(SystemExit, match="would overwrite the shared session-recovery"):
        runner.assert_private_temp(bpy.app.binary_path, env, ["--factory-startup"],
                                   expected=str(elsewhere))


def test_a_probe_that_is_not_blender_is_refused(tmp_path):
    """Blender's own Python takes none of Blender's flags: it fails, no marker."""
    import sys
    runner = _runner()
    env = runner.private_temp_env(tmp_path, bpy.app.binary_path)
    with pytest.raises(SystemExit, match="probe Blender exited with"):
        runner.assert_private_temp(sys.executable, env, ["--factory-startup"])


def _fake_probe(runner, monkeypatch, stdout, returncode):
    def run(command, **_kwargs):
        return runner.subprocess.CompletedProcess(command, returncode, stdout, "")
    monkeypatch.setattr(runner.subprocess, "run", run)


def test_a_probe_that_crashes_after_a_matching_answer_is_refused(tmp_path, monkeypatch):
    runner = _runner()
    env = runner.private_temp_env(tmp_path, bpy.app.binary_path)
    _fake_probe(runner, monkeypatch,
                f"PB_TEMPDIR={env['TEMP']}\\blender_a1\\\nWindows fatal exception\n", 3221225477)
    with pytest.raises(SystemExit, match="exited with 3221225477"):
        runner.assert_private_temp(bpy.app.binary_path, env, ["--factory-startup"])


def test_a_probe_that_never_answers_is_refused(tmp_path, monkeypatch):
    runner = _runner()
    env = runner.private_temp_env(tmp_path, bpy.app.binary_path)
    _fake_probe(runner, monkeypatch, "Blender 5.2.0\n", 0)
    with pytest.raises(SystemExit, match="temp directory is None"):
        runner.assert_private_temp(bpy.app.binary_path, env, ["--factory-startup"])


@pytest.mark.parametrize("path, private", [
    (r"C:\Run\blender-temp\quit.blend", True),
    (r"c:\run\BLENDER-TEMP\sub\quit.blend", True),
    (r"C:\Users\someone\AppData\Local\Temp\quit.blend", False),
    (r"C:\Run\blender-temp-other\quit.blend", False),
])
def test_a_recovery_file_saved_outside_the_run_fails_it(path, private):
    runner = _runner()
    line = f'00:53.547  blend  | Saved session recovery to "{path}"'
    if private:
        runner.assert_recovery_saved_privately(line, r"C:\Run\blender-temp")
    else:
        with pytest.raises(SystemExit, match="outside this run's temp"):
            runner.assert_recovery_saved_privately(line, r"C:\Run\blender-temp")
