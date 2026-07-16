"""pytest bootstrap + fixtures for the ProteinBlender suite.

Runs *inside* Blender's bundled Python (launched by ``tests/run_blender.py``).
Responsibilities:

  1. Put the repo root + tests dir on ``sys.path`` so ``import proteinblender``
     and ``import helpers`` both resolve.
  2. Register the addon once per session (never via ``addon_disable`` — that
     triggers wheel cleanup that corrupts the dev install on Windows).
  3. Reset the scene + addon registry around every test so headless Blender's
     single long-lived process can't leak state between tests.
  4. Provide convenience fixtures (scene, sm, imported proteins, snapshots).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent

# Make `import helpers` and `import proteinblender` work no matter which
# subdirectory a test lives in. Done at import time (before collection) so it
# applies to every conftest/test module.
for p in (str(TESTS_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import helpers  # noqa: E402  (path set above)


# --------------------------------------------------------------------------
# Session: register the addon exactly once
# --------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _addon_registered():
    """Import + register ProteinBlender in-process. Idempotent via the addon's
    own ``_test_register`` (which unregisters+registers if already loaded)."""
    import proteinblender

    proteinblender._test_register()

    # Sanity: the scene-level properties the whole suite relies on must exist.
    import bpy
    scene = bpy.context.scene
    missing = [name for name in ("protein_props", "molecule_list_items",
                                 "outliner_items")
               if not hasattr(scene, name)]
    if missing:
        raise RuntimeError(
            f"addon registered but scene is missing properties: {missing} — "
            "dependencies probably failed to import in Blender's Python")

    yield proteinblender
    # Intentionally do NOT unregister at session end: Blender is tearing down
    # anyway, and unregister-during-shutdown occasionally races the depsgraph.


# --------------------------------------------------------------------------
# Per-test isolation
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_scene(_addon_registered):
    """Wipe addon-managed state before and after each test."""
    helpers.reset_scene()
    yield
    helpers.reset_scene()


# --------------------------------------------------------------------------
# Convenience fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def scene():
    import bpy
    return bpy.context.scene


@pytest.fixture
def sm():
    return helpers.sm()


@pytest.fixture
def single_chain():
    """A freshly imported single-chain protein (1ubq, offline). Returns the
    molecule id."""
    return helpers.import_local("1ubq.pdb", "1ubq")


@pytest.fixture
def multi_chain():
    """A freshly imported 4-chain protein (4hhb, offline). Returns the id."""
    return helpers.import_local("4hhb.pdb", "4hhb")


# --------------------------------------------------------------------------
# syrupy geometry snapshot extension
# --------------------------------------------------------------------------

@pytest.fixture
def geo_snapshot(snapshot):
    """syrupy snapshot with deterministic numpy-array serialization, for
    regression-testing geometry-node / mesh output. Compare against
    ``helpers.eval_positions(obj)`` or ``helpers.geometry_summary(obj)``."""
    try:
        from snapshot_ext import NumpySnapshotExtension
        return snapshot.use_extension(NumpySnapshotExtension)
    except Exception:
        return snapshot


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------

def pytest_configure(config):
    for marker in (
        "unit: pure-logic test, no live Blender scene needed",
        "integration: drives addon operators against a real Blender scene",
        "roundtrip: save/load or undo/redo state-preservation test",
        "network: fetches data from RCSB/AlphaFold (needs internet)",
        "slow: takes more than a couple seconds",
    ):
        config.addinivalue_line("markers", marker)
