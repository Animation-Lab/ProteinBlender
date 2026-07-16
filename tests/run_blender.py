"""Headless pytest entrypoint — runs INSIDE Blender's Python.

Invoked as::

    blender --background --factory-startup --python tests/run_blender.py -- <pytest args>

Everything after ``--`` is forwarded to pytest. Examples::

    blender -b --factory-startup --python tests/run_blender.py -- tests -v
    blender -b --factory-startup --python tests/run_blender.py -- tests/unit -q
    blender -b --factory-startup --python tests/run_blender.py -- tests -m "not network"

The crucial detail is ``sys.exit(result)`` — without it Blender exits 0 even
when tests fail, and any CI/local gate would never see the failure.

Prefer the convenience wrapper ``python tests/run_tests.py`` which locates
Blender and passes these flags for you.
"""

import os
import site
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent


def _bootstrap_paths():
    # User site-packages holds pytest/syrupy (installed via Blender's
    # python -m pip). Blender usually enables it, but make it explicit so the
    # runner works regardless of ENABLE_USER_SITE.
    try:
        user_site = site.getusersitepackages()
        if user_site and os.path.isdir(user_site) and user_site not in sys.path:
            sys.path.append(user_site)
    except Exception:
        pass
    for p in (str(REPO_ROOT), str(TESTS_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def main():
    _bootstrap_paths()

    try:
        import pytest
    except ImportError:
        sys.stderr.write(
            "\n[run_blender] pytest is not installed in Blender's Python.\n"
            "Install it with:\n"
            '  "<blender>/<ver>/python/bin/python.exe" -m pip install '
            "pytest syrupy\n\n")
        sys.exit(3)

    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else [str(TESTS_DIR)]
    # Default rootdir to the repo so pyproject pytest config is picked up.
    os.chdir(str(REPO_ROOT))

    print("=" * 70)
    print("ProteinBlender test suite (inside Blender)")
    print(f"  python : {sys.version.split()[0]}")
    try:
        import bpy
        print(f"  blender: {bpy.app.version_string}")
    except Exception:
        pass
    print(f"  pytest : {pytest.__version__}")
    print(f"  args   : {args}")
    print("=" * 70)

    result = pytest.main(args)
    # pytest.main returns an int (or ExitCode enum). Propagate it.
    sys.exit(int(result))


if __name__ == "__main__":
    main()
