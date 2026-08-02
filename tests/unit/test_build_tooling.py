"""Contracts for `build.py`, the release/wheel resolver.

These run inside Blender's Python, which has no `tomlkit`. `build.py` installs
it at import time, so every helper here imports the module through
`_load_build_module`, which injects a stdlib-backed stand-in first. Importing
`build` directly from a test would shell out to pip and mutate the Blender
install running the suite.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _tomlkit_stub() -> types.ModuleType:
    """A `tomlkit` stand-in good enough for build.py's module-level parse."""
    stub = types.ModuleType("tomlkit")
    stub.parse = tomllib.loads
    stub.dumps = lambda document: ""
    return stub


@contextlib.contextmanager
def _cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _load_build_module() -> types.ModuleType:
    """Import `build.py` hermetically, under a fresh module name each call."""
    stub = _tomlkit_stub()
    saved = sys.modules.get("tomlkit")
    sys.modules["tomlkit"] = stub
    try:
        spec = importlib.util.spec_from_file_location(
            "pb_build_under_test", ROOT / "build.py")
        module = importlib.util.module_from_spec(spec)
        # build.py reads ./pyproject.toml at import time.
        with _cwd(ROOT):
            spec.loader.exec_module(module)
        return module
    finally:
        if saved is None:
            sys.modules.pop("tomlkit", None)
        else:
            sys.modules["tomlkit"] = saved


def test_run_python_raises_when_the_child_process_fails():
    """A failed child must abort the build, not be silently discarded.

    `run_python` drives `pip download` for every wheel in the release matrix.
    Swallowing a non-zero exit lets `update_toml_whls` publish a manifest built
    from whatever wheels happened to land, so a partial download ships as a
    complete release. Ground truth is an interpreter exit code chosen here, not
    anything build.py computes.
    """
    build = _load_build_module()

    with pytest.raises(subprocess.CalledProcessError):
        build.run_python(["-c", "raise SystemExit(3)"])


def test_run_python_still_returns_normally_on_success():
    build = _load_build_module()

    build.run_python(["-c", "raise SystemExit(0)"])


class _BlockTomlkit:
    """Make `import tomlkit` fail the way a machine without it would.

    Needed because the developer machines that run this suite usually *do* have
    tomlkit on the user site-packages, so the bootstrap would short-circuit and
    the install path - the thing under test - would never execute.
    """

    def find_spec(self, name, path=None, target=None):
        if name == "tomlkit":
            raise ModuleNotFoundError("No module named 'tomlkit'", name=name)
        return None


def _simulate_missing_tomlkit(monkeypatch):
    monkeypatch.delitem(sys.modules, "tomlkit", raising=False)
    blocker = _BlockTomlkit()
    monkeypatch.setattr(sys, "meta_path", [blocker] + list(sys.meta_path))
    return blocker


def test_tomlkit_bootstrap_retries_with_a_user_install(monkeypatch):
    """A read-only system site-packages must not sink the build.

    GitHub's ubuntu runners expose a Python whose dist-packages the job user
    cannot write, so the plain install dies with EACCES. pip's documented escape
    hatch is `--user`; that flag is the external ground truth here, not anything
    derived from build.py.
    """
    build = _load_build_module()
    stub = _tomlkit_stub()
    _simulate_missing_tomlkit(monkeypatch)
    monkeypatch.setattr(
        build, "site", types.SimpleNamespace(getusersitepackages=lambda: "/nonexistent"))

    attempts: list[list[str]] = []

    def fake_run(command, **kwargs):
        attempts.append(list(command))
        if "--user" in command:
            # A successful install is what makes the module importable.
            sys.modules["tomlkit"] = stub
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(
            command, 1, "",
            "ERROR: Could not install packages due to an OSError: "
            "[Errno 13] Permission denied: '/usr/local/lib/python3.12/dist-packages'")

    monkeypatch.setattr(
        build, "subprocess",
        types.SimpleNamespace(
            run=fake_run, CompletedProcess=subprocess.CompletedProcess,
            CalledProcessError=subprocess.CalledProcessError))

    resolved = build._ensure_tomlkit()

    assert resolved is stub
    assert len(attempts) == 2, f"expected a retry, got {attempts}"
    assert "--user" not in attempts[0]
    assert "--user" in attempts[1]


def test_tomlkit_bootstrap_reports_both_failures_when_it_cannot_install(monkeypatch):
    """If every install route fails, say so - do not raise ModuleNotFoundError.

    The bare ModuleNotFoundError this used to produce hid the real EACCES from
    pip, which is what made the nightly failure hard to read.
    """
    build = _load_build_module()
    _simulate_missing_tomlkit(monkeypatch)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "Permission denied")

    monkeypatch.setattr(
        build, "subprocess",
        types.SimpleNamespace(
            run=fake_run, CompletedProcess=subprocess.CompletedProcess,
            CalledProcessError=subprocess.CalledProcessError))

    with pytest.raises(SystemExit) as excinfo:
        build._ensure_tomlkit()

    message = str(excinfo.value)
    assert "tomlkit" in message
    assert "Permission denied" in message, (
        "the installer must surface pip's own error, not just its own summary")
