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


def test_behavioral_tests_trigger_import_and_split_through_public_ui_operators():
    """Prevent regressions from silently bypassing the user interaction path."""
    behavioral_roots = [ROOT / "tests" / "integration",
                        ROOT / "tests" / "roundtrip",
                        ROOT / "tests" / "ui",
                        ROOT / "tests" / "artifact",
                        ROOT / "tests" / "live"]
    forbidden = {
        "bpy.ops.molecule.split_domain": "use helpers.split_domain_from_outliner",
        "bpy.ops.proteinblender.split_domain(": "use the public split_domain_popup",
        ".import_molecule_from_file(": "use bpy.ops.molecule.import_local",
    }
    violations = []
    for root in behavioral_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for trigger, replacement in forbidden.items():
                if trigger in text:
                    violations.append(
                        f"{path.relative_to(ROOT)}: {trigger} ({replacement})")
    assert not violations, "non-UI behavioral triggers found:\n" + "\n".join(violations)


def test_normal_profile_deployer_covers_supported_local_blender_versions():
    """The deployer must reach every Blender the add-on is developed against.

    Asserted per version rather than against the literal tuple: pinning the
    exact source line made *adding* a supported version (5.0) fail this test,
    which says nothing about coverage. Dropping one still fails, which is the
    contract worth keeping.
    """
    deployer = (ROOT / "scripts" / "deploy_normal_blender.py").read_text(
        encoding="utf-8")
    versions = ast.literal_eval(
        re.search(r"^VERSIONS\s*=\s*(\([^)]*\))", deployer, re.MULTILINE).group(1))
    for version in ("5.2", "5.1", "5.0"):
        assert version in versions, (
            f"deployer must install into the Blender {version} profile; "
            f"it covers {versions}")
    assert 'extensions_root.glob("*/proteinblender")' in deployer
    assert "filecmp.cmp" in deployer, "deployer must verify copied files"


def test_no_identity_comparisons_on_blender_data():
    """Blender structs must be compared with ``==``, never ``is`` / ``is not``.

    Blender returns a *fresh* ``bpy_struct`` wrapper on every attribute access,
    so ``a is b`` compares Python wrappers, not data, and is False even for the
    same datablock. ``bpy_struct`` implements ``__eq__`` for data identity;
    ``is`` does not.

    This class of bug has bitten this project repeatedly and always silently:
    ``ensure_pivot_input`` used ``link.to_node is not transform`` and wired a
    Transform node to its own output, so every imported protein rendered
    nothing while the whole suite stayed green. ``_rebuild_hole_assignments``
    used ``mod.node_group is not tree``, which is always True, so it reassigned
    the node group on every call - and reassigning it clears the modifier's
    input values.

    Comparisons against None/True/False are fine and are ignored here. So are
    the handful of places that deliberately compare *Python object* identity
    rather than Blender data; those are listed explicitly so adding one is a
    conscious act.
    """
    # (path suffix, symbol on the right-hand side) pairs that really do mean
    # Python-object identity. `_active_instance is self` tracks whether this
    # very operator instance is the one holding the modal dialog slot.
    allowed = {
        ("operators/keyframe_operators.py", "self"),
    }

    def is_trivial(node):
        return isinstance(node, ast.Constant) and node.value in (None, True, False)

    violations = []
    for path in PACKAGE.rglob("*.py"):
        if "molecularnodes" in path.parts:
            continue  # embedded upstream package, not ours to police
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for operator, comparator in zip(node.ops, node.comparators):
                if not isinstance(operator, (ast.Is, ast.IsNot)):
                    continue
                if is_trivial(comparator) or is_trivial(node.left):
                    continue
                right = ast.unparse(comparator)
                if any(relative.endswith(suffix) and right == symbol
                       for suffix, symbol in allowed):
                    continue
                violations.append(
                    f"{relative}:{node.lineno}: "
                    f"{ast.unparse(node.left)} is{'' if isinstance(operator, ast.Is) else ' not'} {right}")

    assert not violations, (
        "identity comparison on Blender data (use == or compare .name):\n  "
        + "\n  ".join(violations))


# --- extension repository index: Python-version compatibility -----------------
#
# Blender decides whether to *offer* a remote extension by reading the index
# entry's `python_versions` (bl_pkg/cli/blender_ext.py). When that key is absent
# the listing advertises the build to every Blender, and an incompatible one only
# fails later at install time with "This Python version (3.13) isn't compatible
# with (3.11)". That is exactly what release 1.0.0 did to Blender 5.1/5.2 users:
# it shipped cp311-only wheels, so it could never load on Python 3.13, yet the
# index happily offered it. Blender's own `server-generate` emits this key; our
# generator must too.

def _load_index_generator():
    """Import .github/scripts/generate_index.py as a module."""
    import importlib.util

    path = ROOT / ".github" / "scripts" / "generate_index.py"
    spec = importlib.util.spec_from_file_location("pb_generate_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_entry_declares_python_versions_derived_from_wheels():
    """An index entry must advertise the Python versions its wheels support.

    Ground truth is the wheel filenames written out below, not anything the
    generator computes: cp311 + cp313 compiled wheels and a pure-python wheel
    mean the build runs on 3.11 and 3.13, and on nothing else.
    """
    module = _load_index_generator()

    manifest = {
        "schema_version": "1.0.0",
        "id": "proteinblender",
        "name": "ProteinBlender",
        "version": "9.9.9",
        "tagline": "test",
        "blender_version_min": "5.0.0",
        "type": "add-on",
        "maintainer": "test",
        "license": ["SPDX:GPL-3.0-or-later"],
        "website": "https://example.invalid",
        "wheels": [
            "./wheels/biotite-1.6.0-cp311-cp311-win_amd64.whl",
            "./wheels/biotite-1.6.0-cp313-cp313-win_amd64.whl",
            "./wheels/starfile-0.5.13-py3-none-any.whl",
        ],
    }

    entry = module.build_extension_entry(
        manifest=manifest,
        archive_url="https://example.invalid/x.zip",
        archive_size=1,
        archive_hash="0" * 64,
        platform="windows-x64",
    )

    assert "python_versions" in entry, (
        "index entry omits python_versions; Blender will advertise this build to "
        "Python versions it cannot run on and fail at install time instead"
    )
    assert sorted(entry["python_versions"]) == ["3.11", "3.13"]


def test_cp311_only_build_is_not_advertised_to_python_313():
    """The 1.0.0 regression, pinned: cp311-only wheels must declare only 3.11.

    A build like release 1.0.0 (Blender 4.2 era, cp311 wheels only) genuinely
    cannot load on Python 3.13. The index must say so, so Blender filters it out
    of the listing rather than offering an install that cannot work.
    """
    module = _load_index_generator()

    manifest = {
        "schema_version": "1.0.0",
        "id": "proteinblender",
        "name": "ProteinBlender",
        "version": "1.0.0",
        "tagline": "test",
        "blender_version_min": "4.2.0",
        "type": "add-on",
        "maintainer": "test",
        "license": ["SPDX:GPL-3.0-or-later"],
        "website": "https://example.invalid",
        "wheels": [
            "./wheels/biotite-1.4.0-cp311-cp311-win_amd64.whl",
            "./wheels/msgpack-1.1.0-cp311-cp311-win_amd64.whl",
        ],
    }

    entry = module.build_extension_entry(
        manifest=manifest,
        archive_url="https://example.invalid/x.zip",
        archive_size=1,
        archive_hash="0" * 64,
        platform="windows-x64",
    )

    assert entry.get("python_versions") == ["3.11"]
    assert "3.13" not in entry.get("python_versions", []), (
        "a cp311-only build must not be advertised as 3.13-compatible"
    )


def test_shipped_manifest_runs_on_every_supported_blender_python():
    """The wheels we ship must cover the Python of every supported Blender.

    Blender 5.0 runs Python 3.11; 5.1 and 5.2 run 3.13. Both are declared
    supported by blender_version_min = 5.0.0, so a build whose wheels cover only
    one of them is unloadable on the rest - silently, until a user installs it.
    The expected set here comes from the Blender releases themselves, not from
    anything the add-on computes.
    """
    module = _load_index_generator()

    manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text(encoding="utf-8"))
    derived = set(module.python_versions_from_wheels(manifest.get("wheels", [])))

    assert {"3.11", "3.13"} <= derived, (
        f"shipped wheels cover Python {sorted(derived)}, but Blender 5.0 needs "
        f"3.11 and Blender 5.1/5.2 need 3.13"
    )
