#!/usr/bin/env python3
"""Run the live-Blender lane against an already-open Blender.

    python tests/run_live_tests.py -v
    python tests/run_live_tests.py tests/live/test_live_membrane.py
    python tests/run_live_tests.py -k domain
    python tests/run_live_tests.py --preflight        # just check the connection

Unlike the rest of the suite this does **not** launch Blender. It attaches to
one you already have open, with a real window and the deployed add-on, and
drives it over the BlenderMCP socket. That is the whole point of the lane: it
observes the viewport a user actually looks at, which `--background` cannot
show.

Setup, once per Blender session:

  1. Open Blender with ProteinBlender enabled.
  2. In the 3D viewport press N, choose the "BlenderMCP" tab, press Connect.

This runner exists rather than a bare ``pytest tests/live`` because the lane
needs ``--confcutdir`` to keep the parent ``tests/conftest.py`` (which imports
``bpy``) out of a system-Python collection.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
LIVE_DIR = TESTS_DIR / "live"
REPO_ROOT = TESTS_DIR.parent

sys.path.insert(0, str(LIVE_DIR))


def preflight() -> int:
    from mcp_client import BlenderMCP, LiveBlenderError, LiveBlenderUnavailable

    connection = BlenderMCP()
    try:
        environment = connection.call("return R.env()")
    except (LiveBlenderUnavailable, LiveBlenderError) as exc:
        print(f"NOT CONNECTED\n\n{exc}")
        return 1

    print("connected to live Blender")
    for key in ("blender", "numpy", "addon_loaded", "has_view3d", "engine",
                "areas", "workspaces"):
        print(f"  {key:16} {environment.get(key)}")
    if not environment.get("addon_loaded"):
        print("\nProteinBlender is NOT enabled in that session.")
        return 1
    if not environment.get("has_view3d"):
        print("\nThat Blender has no 3D viewport; visual tests cannot run.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="run the live-Blender test lane",
        epilog="unrecognised arguments are passed straight to pytest")
    parser.add_argument("--preflight", action="store_true",
                        help="report the live connection and exit")
    parser.add_argument("--required", action="store_true",
                        help="fail rather than skip when no Blender is live")
    parser.add_argument("--include-crashers", action="store_true",
                        help="also run tests known to kill the live Blender")
    args, pytest_args = parser.parse_known_args(argv)

    if args.preflight:
        return preflight()

    import os

    if args.required:
        os.environ["PB_LIVE_REQUIRED"] = "1"

    import pytest

    # Pass pytest's arguments through in their original order. Splitting them
    # into "flags" and "targets" silently breaks any option that takes a
    # separate value: `-k expansion` loses its argument, because `expansion`
    # does not start with a dash and gets collected as a file path.
    forwarded = list(pytest_args)

    # Only supply a default target when the caller named none. A bare word is
    # assumed to belong to the preceding option rather than to be a path.
    value_taking = {"-k", "-m", "-p", "-n", "--tb", "--maxfail", "--deselect",
                    "--ignore", "-o"}
    has_target = False
    skip_next = False
    for argument in forwarded:
        if skip_next:
            skip_next = False
            continue
        if argument in value_taking:
            skip_next = True
            continue
        if not argument.startswith("-"):
            has_target = True
    if not has_target:
        forwarded.append(str(LIVE_DIR))

    # The whole lane shares one Blender process, so a test that reliably crashes
    # it does not just fail: it takes every later test down with it and the run
    # reports noise instead of the one real defect. Known crashers are therefore
    # recorded, marked, and deselected by default.
    if not args.include_crashers and "-m" not in forwarded:
        forwarded += ["-m", "not crasher"]

    return pytest.main([
        f"--confcutdir={LIVE_DIR}",
        "--rootdir", str(REPO_ROOT),
        "-p", "no:cacheprovider",
        *forwarded,
    ])


if __name__ == "__main__":
    raise SystemExit(main())
