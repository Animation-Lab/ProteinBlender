"""Fixtures for the live-Blender lane.

This lane is the odd one out. Every other lane runs *inside* Blender's Python;
this one runs in ordinary system Python and drives a Blender that is already
open on the desktop, over the BlenderMCP socket.

That inversion has one consequence worth stating up front: the parent
``tests/conftest.py`` must not load here. Its autouse ``_addon_registered``
fixture does ``import proteinblender``, which needs ``bpy`` and cannot work in
system Python. ``run_live_tests.py`` passes ``--confcutdir`` so pytest stops
looking for conftests at this directory. Running ``pytest tests/live`` directly
without that flag will fail at collection, which is why the runner exists.

Everything the tests assert on is computed inside Blender by
``tests/live/remote.py`` and returned as JSON. Screenshots are written to
``tests/live/_artifacts/`` so a failure leaves behind the picture that failed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from mcp_client import BlenderMCP, LiveBlenderError, LiveBlenderUnavailable

LIVE_DIR = Path(__file__).resolve().parent
ARTIFACTS = LIVE_DIR / "_artifacts"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: drives a live, windowed Blender over the BlenderMCP socket")
    config.addinivalue_line(
        "markers",
        "visual: renderer-observed regression or metamorphic image test")
    config.addinivalue_line("markers", "slow: takes more than a couple seconds")
    config.addinivalue_line("markers", "network: needs internet (RCSB/AlphaFold)")
    config.addinivalue_line(
        "markers",
        "crasher: reproducibly kills the live Blender process. Deselected by "
        "default because the whole lane shares one Blender; run with "
        "--include-crashers to reproduce.")


def pytest_sessionstart(session):
    if os.environ.get("PB_LIVE_KEEP_ARTIFACTS"):
        return
    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def blender():
    """The live Blender connection, shared by the whole session.

    Skips the entire lane when nothing is listening. That is deliberate: an
    unopened Blender is a missing environment, not a product regression, and a
    developer running the full suite should not see red for it. CI sets
    ``PB_LIVE_REQUIRED=1`` to turn the skip into a failure so the lane cannot
    silently stop running.
    """
    connection = BlenderMCP()
    try:
        environment = connection.call("return R.env()")
    except (LiveBlenderUnavailable, LiveBlenderError) as exc:
        if os.environ.get("PB_LIVE_REQUIRED"):
            pytest.fail(f"live Blender required but unavailable: {exc}")
        pytest.skip(
            f"no live Blender available ({exc}). Open Blender with "
            "ProteinBlender enabled, then press Connect in the 3D view "
            "N-panel under the BlenderMCP tab.")

    if not environment.get("addon_loaded"):
        pytest.skip("live Blender is running without ProteinBlender enabled")
    if not environment.get("has_view3d"):
        pytest.skip("live Blender has no 3D viewport to observe")

    connection.environment = environment
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def live_reset(request, blender):
    """Scrub add-on state around every live test.

    The live Blender is long-lived and shared across the whole session, exactly
    like the headless lane's single process, so the same discipline applies: a
    test that leaves a molecule behind corrupts the next one. On failure the
    scene is left in place first for a diagnostic screenshot, then cleaned.
    """
    blender.call("return R.reset()")
    yield
    if request.node.stash.get(_FAILED, False):
        try:
            blender.screenshot(ARTIFACTS / f"FAILED-{_slug(request.node.name)}.png")
        except LiveBlenderError:
            pass
    blender.call("return R.reset()")


_FAILED = pytest.StashKey[bool]()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    if report.when == "call" and report.failed:
        item.stash[_FAILED] = True


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:120]


# ---------------------------------------------------------------------------
# Observation helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def shot(request, blender):
    """Capture the viewport and save a PNG artifact named after the test.

        metrics = shot("after-import")

    Returns the metric dict from ``remote.viewport_metrics``. Every call also
    leaves a reviewable image in ``tests/live/_artifacts``, which is what makes
    "does it look right" answerable by a human after the fact rather than only
    by the assertions written in advance.
    """
    counter = {"n": 0}

    def capture(label: str = "", frame: bool = True, resolution: int = 480,
                objects: list[str] | None = None, **kwargs):
        if frame:
            blender.call("return R.frame_all(objects=objects)", objects=objects)
        counter["n"] += 1
        name = f"{_slug(request.node.name)}-{counter['n']:02d}"
        if label:
            name += f"-{_slug(label)}"
        return blender.viewport(ARTIFACTS / f"{name}.png",
                                resolution=resolution, **kwargs)

    return capture


@pytest.fixture
def snapshot_state(blender):
    """Return the add-on's current scene state as a plain dict."""
    return lambda: blender.call("return R.scene_snapshot()")


# ---------------------------------------------------------------------------
# Content fixtures  (imported through the same public operators the headless
# lane uses, via this repo's tests/helpers.py running inside live Blender)
# ---------------------------------------------------------------------------

@pytest.fixture
def single_chain(blender):
    """A freshly imported single-chain protein (1ubq, offline). Returns its id."""
    return blender.call('return H.import_local("1ubq.pdb", "1ubq")')


@pytest.fixture
def multi_chain(blender):
    """A freshly imported 4-chain protein (4hhb, offline). Returns its id."""
    return blender.call('return H.import_local("4hhb.pdb", "4hhb")')


@pytest.fixture
def actin(blender):
    """1atn: has a bound calcium ion and two chains. Returns its id."""
    return blender.call('return H.import_local("1atn.pdb", "1atn")')
