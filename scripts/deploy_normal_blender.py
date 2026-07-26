#!/usr/bin/env python3
"""Copy the working ProteinBlender source into normal Blender profiles.

This is the mandatory final step after a locally verified product-code change.
It intentionally preserves installed dependency wheels while replacing Python,
assets, and manifest files from the repository.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "proteinblender"
VERSIONS = ("5.2", "5.1", "5.0")


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
    checked = 0
    for source_file in SOURCE.rglob("*.py"):
        relative = source_file.relative_to(SOURCE)
        target_file = target / relative
        if not target_file.is_file() or not filecmp.cmp(
                source_file, target_file, shallow=False):
            raise SystemExit(f"deployment verification failed: {target_file}")
        checked += 1
    print(f"PASS {target} ({checked} Python files verified)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-root", type=Path)
    args = parser.parse_args()
    user_root = args.user_root or default_user_root()
    for version in VERSIONS:
        version_root = user_root / version
        # Legacy add-on location remains the normal 5.2 development install.
        deploy(version_root / "scripts" / "addons" / "proteinblender")
        # Blender Extensions can be the enabled normal-profile copy (currently
        # true for 5.1). Update every installed repository copy that exists.
        extensions_root = version_root / "extensions"
        if extensions_root.is_dir():
            for target in sorted(extensions_root.glob("*/proteinblender")):
                deploy(target)
    print("Close every running Blender process before validating either profile.")


if __name__ == "__main__":
    main()
