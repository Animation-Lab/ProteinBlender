"""Pure-logic unit tests for proteinblender.__init__._restore_missing_libs.

Reproduces the alpha-extension failure mode: on Windows, Blender's extension
installer sometimes extracts a bundled wheel WITHOUT its sibling ``<pkg>.libs``
folder (the OpenBLAS/Arrow DLLs, which are not listed in the wheel's RECORD),
so scipy / MDAnalysis / starfile raise ``DLL load failed`` and the add-on
refuses to load. ``_restore_missing_libs`` re-extracts just that folder from
the bundled wheel.

Ground truth is independent of the code under test: each test builds a
synthetic wheel with a known ``.libs`` payload and asserts that exact byte
content is what lands on disk - never derived from the function's own output.
"""

import os
import zipfile

import pytest

import proteinblender


def _make_wheel(path, dist, pytag, *, package_files, libs_files):
    """Write a minimal but structurally real wheel.

    ``package_files`` / ``libs_files`` map an in-wheel relative path to bytes;
    package files live under ``<dist>/`` and libs under ``<dist>.libs/``.
    """
    with zipfile.ZipFile(path, "w") as zf:
        for rel, data in package_files.items():
            zf.writestr(f"{dist}/{rel}", data)
        for rel, data in libs_files.items():
            zf.writestr(f"{dist}.libs/{rel}", data)
        # A dist-info with a RECORD that - like real delvewheel wheels - does
        # NOT list the .libs entries, matching what bit us in production.
        zf.writestr(f"{dist}-1.0.0.dist-info/RECORD", f"{dist}/__init__.py,,\n")
        zf.writestr(f"{dist}-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")


def _install_package_without_libs(site_dir, dist):
    """Simulate the broken state: package + dist-info present, .libs absent."""
    os.makedirs(os.path.join(site_dir, dist))
    with open(os.path.join(site_dir, dist, "__init__.py"), "w") as fh:
        fh.write("# installed package\n")
    os.makedirs(os.path.join(site_dir, f"{dist}-1.0.0.dist-info"))


@pytest.mark.unit
def test_restores_missing_libs_from_bundled_wheel(tmp_path):
    wheels = tmp_path / "wheels"
    site = tmp_path / "site-packages"
    wheels.mkdir()
    site.mkdir()

    dll_bytes = b"\x4d\x5a" + b"OPENBLAS-PAYLOAD" * 8  # distinctive ground truth
    _make_wheel(
        wheels / "scipy-1.0.0-cp313-cp313-win_amd64.whl",
        "scipy", "cp313",
        package_files={"__init__.py": b"# scipy"},
        libs_files={"libscipy_openblas-abc123.dll": dll_bytes},
    )
    _install_package_without_libs(str(site), "scipy")
    assert not (site / "scipy.libs").exists()

    repaired = proteinblender._restore_missing_libs(
        str(wheels), [str(site)], "cp313")

    assert repaired == [("scipy.libs", str(site))]
    restored = site / "scipy.libs" / "libscipy_openblas-abc123.dll"
    assert restored.is_file()
    # Byte content must equal what the wheel carried - external ground truth.
    assert restored.read_bytes() == dll_bytes


@pytest.mark.unit
def test_healthy_install_is_left_untouched(tmp_path):
    wheels = tmp_path / "wheels"
    site = tmp_path / "site-packages"
    wheels.mkdir()
    site.mkdir()

    _make_wheel(
        wheels / "scipy-1.0.0-cp313-cp313-win_amd64.whl",
        "scipy", "cp313",
        package_files={"__init__.py": b"# scipy"},
        libs_files={"libscipy_openblas-abc123.dll": b"WHEEL-COPY"},
    )
    _install_package_without_libs(str(site), "scipy")
    # A pre-existing, DIFFERENT .libs payload must NOT be overwritten.
    os.makedirs(os.path.join(str(site), "scipy.libs"))
    good = site / "scipy.libs" / "libscipy_openblas-abc123.dll"
    good.write_bytes(b"ALREADY-GOOD")

    repaired = proteinblender._restore_missing_libs(
        str(wheels), [str(site)], "cp313")

    assert repaired == []
    assert good.read_bytes() == b"ALREADY-GOOD"


@pytest.mark.unit
def test_skips_wheel_for_a_different_python_abi(tmp_path):
    wheels = tmp_path / "wheels"
    site = tmp_path / "site-packages"
    wheels.mkdir()
    site.mkdir()

    _make_wheel(
        wheels / "scipy-1.0.0-cp311-cp311-win_amd64.whl",
        "scipy", "cp311",
        package_files={"__init__.py": b"# scipy"},
        libs_files={"libscipy_openblas-abc123.dll": b"CP311"},
    )
    _install_package_without_libs(str(site), "scipy")

    # Asking for cp313 must ignore the cp311 wheel entirely.
    repaired = proteinblender._restore_missing_libs(
        str(wheels), [str(site)], "cp313")

    assert repaired == []
    assert not (site / "scipy.libs").exists()


@pytest.mark.unit
def test_skips_when_package_not_installed_in_site(tmp_path):
    wheels = tmp_path / "wheels"
    site = tmp_path / "site-packages"
    wheels.mkdir()
    site.mkdir()

    _make_wheel(
        wheels / "scipy-1.0.0-cp313-cp313-win_amd64.whl",
        "scipy", "cp313",
        package_files={"__init__.py": b"# scipy"},
        libs_files={"libscipy_openblas-abc123.dll": b"X"},
    )
    # site is empty: scipy is not installed here, so nothing to repair.
    repaired = proteinblender._restore_missing_libs(
        str(wheels), [str(site)], "cp313")

    assert repaired == []
    assert not (site / "scipy.libs").exists()
