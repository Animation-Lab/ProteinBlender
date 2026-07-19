"""Cheap repository/package contracts that catch omissions before runtime."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "proteinblender"


def test_versions_are_synchronized():
    manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'["\']version["\']\s*:\s*\((\d+),\s*(\d+),\s*(\d+)\)', init_text)
    assert match, "could not find bl_info version tuple"
    addon_version = ".".join(match.groups())
    assert manifest["version"] == pyproject["project"]["version"] == addon_version


def test_manifest_wheel_entries_are_unique_and_safe():
    manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text(encoding="utf-8"))
    wheels = manifest.get("wheels", [])
    assert wheels, "extension manifest declares no bundled dependencies"
    assert len(wheels) == len(set(wheels)), "duplicate wheel paths in extension manifest"
    assert all(path.startswith("./wheels/") and ".." not in path for path in wheels)


def test_every_first_party_operator_appears_in_a_registration_inventory():
    operators = set()
    inventories = set()
    for path in PACKAGE.rglob("*.py"):
        if "molecularnodes" in path.parts:
            continue  # embedded upstream package owns its own registration model
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                (isinstance(base, ast.Name) and base.id == "Operator")
                or (isinstance(base, ast.Attribute) and base.attr == "Operator")
                for base in node.bases
            ):
                operators.add(node.name)
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(target, ast.Name) and target.id == "CLASSES"
                       for target in targets):
                continue
            inventories.update(child.id for child in ast.walk(node.value)
                               if isinstance(child, ast.Name))

    # animation_panel's delete operator is deliberately imported into the panel
    # inventory under an alias to avoid colliding with the molecule operator.
    aliases = {"PROTEINBLENDER_OT_delete_keyframe": "PROTEINBLENDER_OT_anim_delete_keyframe"}
    missing = [name for name in sorted(operators)
               if name not in inventories and aliases.get(name) not in inventories]
    assert not missing, "operators absent from every CLASSES inventory: " + ", ".join(missing)


def test_test_data_is_small_and_offline_reproducible():
    fixtures = sorted((ROOT / "tests" / "data").glob("*.pdb"))
    assert {path.name for path in fixtures} >= {"1ubq.pdb", "1aki.pdb", "1atn.pdb", "4hhb.pdb"}
    assert all(path.stat().st_size < 5_000_000 for path in fixtures)

