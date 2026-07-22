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


# The addon's runtime dependencies. Import name first; the pip name (when it
# differs) is only used in the error hint. Mirrors __init__._can_import_core_packages.
_CORE_DEPS = (
    ("numpy", None), ("scipy", None), ("biotite", None), ("databpy", None),
    ("MDAnalysis", None), ("mrcfile", None), ("starfile", None),
    ("yaml", "PyYAML"), ("msgpack", None),
)


def _preflight_core_deps():
    """Fail loudly and clearly if the addon's runtime deps can't import here.

    Without this, a broken or incomplete dependency install surfaces only as a
    cryptic error deep in collection (``KeyError:
    proteinblender.utils.scene_manager``), which makes a broken *environment*
    look like a broken *test* - and does so differently on each Blender version.
    The failure mode that motivated this: on Windows a wheel unpacked without
    its sibling ``*.libs`` folder (the OpenBLAS / Arrow DLLs) leaves scipy /
    MDAnalysis / starfile raising ``ImportError: DLL load failed`` while every
    other package imports fine, so the addon quietly refuses to load.

    Import every core dependency up front and, on any failure, print an
    actionable message naming the package(s) and how to repair the env, then
    exit with a distinct code. Set ``PB_SKIP_DEP_CHECK=1`` to bypass.
    """
    if os.environ.get("PB_SKIP_DEP_CHECK"):
        return
    import importlib

    broken = []
    for import_name, pip_name in _CORE_DEPS:
        try:
            importlib.import_module(import_name)
        except Exception as exc:  # ModuleNotFoundError OR DLL/other ImportError
            broken.append((import_name, pip_name or import_name,
                           f"{type(exc).__name__}: {exc}"))
    if not broken:
        return

    out = ["", "=" * 70,
           "[run_blender] ProteinBlender runtime dependencies are not usable "
           "in this Blender's Python:"]
    for import_name, _pip, err in broken:
        out.append(f"  - {import_name}: {err}")
    out += [
        "",
        "This is an ENVIRONMENT problem, not a test failure. The most common "
        "cause on Windows is a wheel installed/unpacked without its sibling "
        "'<pkg>.libs' folder (missing OpenBLAS/Arrow DLLs), which breaks scipy "
        "/ MDAnalysis / starfile while leaving pure-Python packages importable.",
        "",
        "Repair the deps for THIS Blender version, then re-run the suite:",
        "  ./dev/install_deps.sh [blender-version]        # dev helper",
        "  # or force-reinstall the pinned wheels into this Blender's python.",
        "",
        "Set PB_SKIP_DEP_CHECK=1 to bypass this preflight (not recommended).",
        "=" * 70, ""]
    sys.stderr.write("\n".join(out) + "\n")
    sys.exit(4)


def main():
    _bootstrap_paths()
    _preflight_core_deps()

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
