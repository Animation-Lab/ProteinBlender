#!/usr/bin/env python3
"""Copy the working ProteinBlender source into normal Blender profiles.

This is the mandatory final step after a locally verified product-code change.
It intentionally preserves installed dependency wheels while replacing Python,
assets, and manifest files from the repository.

Copying is not the same as running. A profile can have another ProteinBlender
copy enabled - an alpha-channel extension, a demo repository - that registers
the same operators and wins, so the deployed code never runs however faithfully
it was copied. Each Blender is therefore started once afterwards and asked
which copy it actually loaded.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
from pathlib import Path, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "proteinblender"
VERSIONS = ("5.2", "5.1", "5.0")

PROBE_MARK = "PB_LOADED_COPIES "
# Runs inside Blender. Every loaded copy, and the one whose classes are live:
# copies share their operator ids, so the last one registered owns them all.
PROBE = """
import json, os, sys, bpy
copies = {}
for addon in bpy.context.preferences.addons:
    if 'proteinblender' in addon.module.lower():
        module = sys.modules.get(addon.module)
        if module is not None and getattr(module, '__file__', None):
            copies[addon.module] = os.path.dirname(module.__file__)
owner = getattr(getattr(bpy.types, 'MOLECULE_OT_import_protein', None), '__module__', '')
live = next((name for name in copies if owner.startswith(name + '.')), None)
print(%r + json.dumps({'copies': copies, 'live': live}))
""" % PROBE_MARK


def default_user_root() -> Path:
    override = os.environ.get("PB_BLENDER_USER_ROOT")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ["APPDATA"]) / "Blender Foundation" / "Blender"
    candidates = sorted(Path("/mnt/c/Users").glob(
        "*/AppData/Roaming/Blender Foundation/Blender"))
    installed = [path for path in candidates if any(
        (path / version).is_dir() for version in VERSIONS)]
    if len(installed) == 1:
        return installed[0]
    raise SystemExit(
        "Cannot determine Blender user root; set PB_BLENDER_USER_ROOT or "
        "pass --user-root")


def deploy(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE, target, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("wheels", "__pycache__", "*.pyc"),
    )
    # A module the source has retired must not linger in an installed copy,
    # where it would still import and still look current.
    for target_file in target.rglob("*.py"):
        relative = target_file.relative_to(target)
        if "wheels" not in relative.parts and not (SOURCE / relative).is_file():
            target_file.unlink()
            print(f"REMOVED {target_file} (no longer in the source)")
    checked = 0
    for source_file in SOURCE.rglob("*.py"):
        relative = source_file.relative_to(SOURCE)
        target_file = target / relative
        if not target_file.is_file() or not filecmp.cmp(
                source_file, target_file, shallow=False):
            raise SystemExit(f"deployment verification failed: {target_file}")
        checked += 1
    print(f"PASS {target} ({checked} Python files verified)")


def find_blender(version: str) -> Path | None:
    roots = [Path(root) / "Blender Foundation" for root in (
        os.environ.get("ProgramFiles", ""), "/mnt/c/Program Files") if root]
    for root in roots:
        exe = root / f"Blender {version}" / "blender.exe"
        if exe.is_file():
            return exe
    return None


def _local(path: str) -> Path:
    """A path Blender reported, as this process would spell it."""
    if os.name != "nt" and PureWindowsPath(path).drive:
        path = subprocess.run(["wslpath", "-u", path], check=True,
                              capture_output=True, text=True).stdout.strip()
    return Path(path).resolve()


def check_loaded(version: str, blender: Path, targets: list[Path]) -> bool:
    """True if this Blender's normal profile runs a deployed copy and no other."""
    output = subprocess.run(
        [str(blender), "--background", "--python-expr", PROBE],
        capture_output=True, text=True, errors="replace").stdout
    line = next((line for line in output.splitlines()
                 if line.startswith(PROBE_MARK)), None)
    if line is None:
        print(f"FAIL Blender {version}: could not ask it which copy it loaded")
        return False
    report = json.loads(line[len(PROBE_MARK):])
    deployed = {target.resolve() for target in targets}
    strays = {name: path for name, path in report["copies"].items()
              if _local(path) not in deployed}
    if not report["copies"]:
        print(f"FAIL Blender {version}: no ProteinBlender copy is enabled and "
              "loading, so the deployed code does not run")
    for name, path in strays.items():
        role = ("and it owns the live operators" if name == report["live"]
                else "alongside the deployed copy")
        print(f"FAIL Blender {version}: add-on '{name}' loads from {path}, "
              f"which this script does not deploy to, {role}. Disable it in "
              "Preferences > Add-ons or the deployed code does not run")
    if strays or not report["copies"]:
        return False
    print(f"PASS Blender {version} runs the deployed copy "
          f"({report['live']} from {report['copies'][report['live']]})")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-root", type=Path)
    args = parser.parse_args()
    user_root = args.user_root or default_user_root()
    running = True
    for version in VERSIONS:
        version_root = user_root / version
        # Legacy add-on location remains the normal 5.2 development install.
        targets = [version_root / "scripts" / "addons" / "proteinblender"]
        # Blender Extensions can be the enabled normal-profile copy (currently
        # true for 5.1). Update every installed repository copy that exists.
        extensions_root = version_root / "extensions"
        if extensions_root.is_dir():
            targets += sorted(extensions_root.glob("*/proteinblender"))
        for target in targets:
            deploy(target)
        blender = find_blender(version)
        if blender is None:
            print(f"SKIP Blender {version} is not installed; load check not run")
        elif not check_loaded(version, blender, targets):
            running = False
    print("Close every running Blender process before validating either profile.")
    if not running:
        raise SystemExit(
            "Deployed, but at least one Blender does not run the deployed copy.")


if __name__ == "__main__":
    main()
