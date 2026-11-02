"""What a tester sees when ProteinBlender's Python dependencies are broken.

Janet and Rachel lost the alpha after an update went wrong (2026-10-30): the
ProteinBlender tab was gone and nothing said why. Blender deletes ``bl_info``
from an extension's module before calling ``register()`` (addon_utils.enable),
and the missing-dependencies ``register()`` read ``bl_info['name']``, so it
raised NameError and Blender dropped the add-on without a word.

These tests load exact copies of the shipped ``proteinblender/__init__.py`` and
``dependency_fallback.py``
the way Blender loads an extension - with one core dependency made
unimportable (``sys.modules[name] = None`` makes ``import name`` raise
ImportError) - then delete ``bl_info`` and call ``register()``.
The copy lives in a temporary folder, so its dependency-attempt record never
touches the real package. pip is never run: ``subprocess.check_call`` is
replaced by a recorder that fails like an offline pip.
"""
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import bpy
import pytest

pytestmark = pytest.mark.integration

PACKAGE = Path(__file__).resolve().parents[2] / "proteinblender"
SOURCE = PACKAGE / "__init__.py"
BROKEN = "biotite"


def _load_broken_copy(tmp_path, monkeypatch, cache=None):
    """Import a copy of the add-on's entry module with ``biotite`` broken.

    Returns ``(module, pip_calls)``. ``cache`` is written as the package's
    ``.dependency_cache.json`` before import, standing in for what an
    earlier Blender session left behind.
    """
    package = tmp_path / "pb_broken_probe"
    package.mkdir()
    shutil.copy(SOURCE, package / "__init__.py")
    shutil.copy(PACKAGE / "dependency_fallback.py", package / "dependency_fallback.py")
    if cache is not None:
        (package / ".dependency_cache.json").write_text(json.dumps(cache))

    pip_calls = []

    def offline_pip(command, *args, **kwargs):
        pip_calls.append(list(command))
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setitem(sys.modules, BROKEN, None)
    monkeypatch.setattr(subprocess, "check_call", offline_pip)
    # The Windows path unloads scipy/pandas from sys.modules before installing,
    # which would pull them out from under the rest of this test session.
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    spec = importlib.util.spec_from_file_location(
        "pb_broken_probe", package / "__init__.py",
        submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "pb_broken_probe", module)
    monkeypatch.delitem(sys.modules, "pb_broken_probe.dependency_fallback", raising=False)
    spec.loader.exec_module(module)
    return module, pip_calls


def _enable_like_blender(module):
    """addon_utils.enable for an extension: drop bl_info, then register()."""
    if hasattr(module, "bl_info"):
        del module.bl_info
    module.register()


def _sidebar_panels(category):
    return [cls for cls in bpy.types.Panel.__subclasses__()
            if getattr(cls, "bl_space_type", "") == "VIEW_3D"
            and getattr(cls, "bl_region_type", "") == "UI"
            and getattr(cls, "bl_category", "") == category
            and getattr(cls, "is_registered", False)]


def test_broken_dependencies_still_register_and_say_why(tmp_path, monkeypatch):
    """The ProteinBlender tab must still appear, and name what is broken."""
    # Both keys: the record a just-failed repair leaves, in the old and new
    # spelling, so the old code also takes its "not retrying yet" branch.
    recent = {"last_check": time.time(), "last_install_attempt": time.time()}
    module, _ = _load_broken_copy(tmp_path, monkeypatch, cache=recent)
    assert module.dependencies_installed is False
    try:
        _enable_like_blender(module)
        panels = _sidebar_panels("ProteinBlender")
        assert panels, "no ProteinBlender sidebar tab when dependencies are broken"
        text = module.dependency_problem()
        assert BROKEN in text, text
        assert hasattr(bpy.ops.proteinblender, "retry_dependency_install")
    finally:
        module.unregister()
    assert not _sidebar_panels("ProteinBlender") or all(
        p.__module__ != module.__name__ for p in _sidebar_panels("ProteinBlender"))


def test_a_healthy_start_does_not_hold_back_a_later_repair(tmp_path, monkeypatch):
    """A cache left by a session whose dependencies worked must not stop a repair.

    Before the fix every healthy start refreshed the same 24-hour timestamp a
    failed install used, so dependencies breaking within a day of a good start
    skipped the repair and logged "an install was attempted recently".
    """
    # Exactly what the pre-fix add-on wrote on every successful start.
    healthy = {"last_check": time.time()}
    module, pip_calls = _load_broken_copy(tmp_path, monkeypatch, cache=healthy)
    assert pip_calls, "dependencies broke after a healthy start, and no repair was tried"


def test_a_failed_repair_is_not_retried_on_every_start(tmp_path, monkeypatch):
    """The back-off a failed install earns is kept - pip is slow and freezes startup."""
    module, pip_calls = _load_broken_copy(tmp_path, monkeypatch)
    assert pip_calls, "first broken start should try a repair"
    cache = json.loads((Path(module.__file__).parent / ".dependency_cache.json").read_text())

    sys.modules.pop("pb_broken_probe", None)
    sys.modules.pop("pb_broken_probe.dependency_fallback", None)
    shutil.rmtree(tmp_path / "pb_broken_probe")
    again, second_calls = _load_broken_copy(tmp_path, monkeypatch, cache=cache)
    assert not second_calls, "a repair that just failed was retried on the next start"
    assert again.dependencies_installed is False


def test_retry_runs_a_repair_even_inside_the_back_off(tmp_path, monkeypatch):
    """The panel's Retry button is the way out of the 24-hour back-off."""
    recent = {"last_install_attempt": time.time()}
    module, pip_calls = _load_broken_copy(tmp_path, monkeypatch, cache=recent)
    assert not pip_calls
    try:
        _enable_like_blender(module)
        # Offline pip fails, and the button says so (an ERROR report, which
        # bpy.ops turns into RuntimeError when called from Python).
        with pytest.raises(RuntimeError, match="Still broken - biotite"):
            bpy.ops.proteinblender.retry_dependency_install()
        assert pip_calls, "Retry did not attempt an install"
    finally:
        module.unregister()


def test_version_check_reads_installed_versions_without_pkg_resources():
    """The installer's version check, against numpy's own idea of its version."""
    import numpy
    import proteinblender

    major = int(numpy.__version__.split(".")[0])
    assert proteinblender._needs_reinstall("numpy", f">={major}.0") is False
    assert proteinblender._needs_reinstall("numpy", f"<{major}.0") is True
    assert proteinblender._needs_reinstall("numpy", "") is False
    assert proteinblender._needs_reinstall("no-such-package-pb", "") is True
