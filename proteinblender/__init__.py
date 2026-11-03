"""ProteinBlender - A Blender addon for protein visualization and animation.

This module handles dependency management and addon registration for ProteinBlender.
"""

import bpy
import sys
import subprocess
import os
import importlib
import site
import logging
import platform
import gc
import time
from typing import Dict

# Set up logging.
# Guard against adding a duplicate handler when this module is re-imported (e.g. a dev
# hot-reload, or Blender re-enabling the addon): without this the same StreamHandler
# stacks on the module-level logger and every log line prints once per past import.
# propagate=False keeps records from also surfacing via the root logger.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

# Add user site-packages to sys.path if not already present
user_site = site.getusersitepackages()
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.append(user_site)
    logger.info(f"Added user site-packages to sys.path: {user_site}")


def _unload_modules() -> None:
    """Unload matplotlib and related modules that might have loaded DLLs.

    This is particularly important on Windows where DLL files can remain locked.
    """
    modules_to_unload = [
        'matplotlib', 'matplotlib.pyplot', 'matplotlib.figure', 'matplotlib.backends',
        'matplotlib.ft2font', 'matplotlib._c_internal_utils', 'matplotlib._path',
        'PIL', 'PIL.Image', 'PIL._imaging',
        'scipy', 'scipy.spatial', 'scipy.stats',
        'pandas', 'pandas._libs',
        'MDAnalysis',
    ]

    # Collect all modules that start with any of the target prefixes
    modules_to_remove = set()
    for module_name in list(sys.modules.keys()):
        for target in modules_to_unload:
            if module_name == target or module_name.startswith(target + '.'):
                modules_to_remove.add(module_name)

    # Remove the modules
    for module_name in modules_to_remove:
        if module_name in sys.modules:
            logger.debug(f"Unloading module: {module_name}")
            try:
                del sys.modules[module_name]
            except Exception as e:
                logger.debug(f"Could not unload {module_name}: {e}")

    # Force garbage collection to release references
    gc.collect()

    # On Windows, give a moment for DLL handles to be released
    if platform.system() == "Windows":
        time.sleep(0.5)


def _specifier_set(spec: str):
    """A packaging SpecifierSet for ``spec``, e.g. ">=1.1,<1.7".

    Blender 5.1+ bundles ``packaging``; 5.0 does not, but its pip vendors it.
    """
    try:
        from packaging.specifiers import SpecifierSet
    except ImportError:
        from pip._vendor.packaging.specifiers import SpecifierSet
    return SpecifierSet(spec, prereleases=True)


def _needs_reinstall(package_name: str, required_version: str) -> bool:
    """Check if a package needs to be reinstalled.

    Args:
        package_name: The name of the package to check.
        required_version: The required version specification (e.g., ">=2.7.0").

    Returns:
        bool: True if the package needs to be reinstalled, False otherwise.
    """
    try:
        # importlib.metadata, not pkg_resources: setuptools has deprecated
        # pkg_resources and is removing it, and Blender bundles setuptools.
        from importlib import metadata
        installed = metadata.version(package_name)

        if required_version:
            if installed not in _specifier_set(required_version):
                logger.info(f"{package_name} version {installed} does not meet requirement {required_version}")
                return True

        # Try to import the package to verify it's not corrupted
        # Map package names to their import names and test imports
        import_tests = {
            'MDAnalysis': [('MDAnalysis', None)],
            'PyYAML': [('yaml', None)],
            'biotite': [('biotite', None)],
            'databpy': [('databpy', None)],
            'mrcfile': [('mrcfile', None)],
            'starfile': [('starfile', None)],
            'msgpack': [('msgpack', None), ('msgpack.exceptions', None)],
            'scipy': [('scipy', None), ('scipy.linalg', None), ('scipy.linalg._fblas', None)],
            'numpy': [('numpy', None)]
        }

        # Get the tests for this package, or use default
        tests = import_tests.get(package_name, [(package_name.replace('-', '_').lower(), None)])

        for import_name, _ in tests:
            try:
                importlib.import_module(import_name)
            except ImportError as e:
                logger.warning(f"{package_name}: module '{import_name}' cannot be imported: {e}. Will reinstall.")
                return True

        return False  # Package is installed and working

    except Exception:
        # Deliberately broad: a missing distribution (PackageNotFoundError), an
        # unreadable one, or an unparseable spec all mean "reinstall".
        return True  # Package not found or error checking, needs install


def _can_import_core_packages():
    """Quick check if all core packages can be imported without errors.

    This is used to skip pip installation attempts when packages are already
    working, which prevents permission errors during addon updates.

    Returns:
        bool: True if all core packages can be imported successfully
    """
    import importlib
    global _import_problem

    core_packages = ['biotite', 'databpy', 'MDAnalysis', 'numpy', 'scipy', 'mrcfile', 'starfile']

    for package in core_packages:
        try:
            # Map package names to their import names if different
            import_name = 'yaml' if package == 'PyYAML' else package
            importlib.import_module(import_name)
        except Exception as e:
            # Not just ImportError: a half-replaced package can fail on import
            # with anything (AttributeError from a mismatched version, OSError
            # from a missing DLL), and letting that escape kills the whole
            # add-on import with no explanation.
            _import_problem = f"{package}: {type(e).__name__}: {e}"
            logger.warning(f"Core package cannot be imported - {_import_problem}")
            return False

    _import_problem = ""
    logger.debug("All core packages are importable")
    return True


#: Why the core packages cannot be imported, for the sidebar panel; empty when they can.
_import_problem = ""


def _install_with_retry(command: list, max_retries: int = 3, delay: float = 1.0) -> bool:
    """Execute pip install command with retry logic for permission errors.

    Args:
        command: The command list to execute.
        max_retries: Maximum number of retry attempts.
        delay: Delay between retries in seconds.

    Returns:
        bool: True if successful, False otherwise.
    """
    is_windows = platform.system() == "Windows"

    for attempt in range(max_retries):
        try:
            subprocess.check_call(command)
            return True
        except subprocess.CalledProcessError as e:
            # Check if this is a permission error (common during addon updates)
            error_output = str(e)
            if "Permission denied" in error_output or "PermissionError" in error_output:
                if is_windows:
                    logger.info("Some files are locked (likely during addon update). Skipping for now.")
                    logger.info("Dependencies will be verified on next Blender restart.")
                    return False  # Not an error - just defer to next restart

            if is_windows and attempt < max_retries - 1:
                # On Windows, might be a temporary lock
                logger.warning(f"Installation attempt {attempt + 1} failed. Retrying...")
                _unload_modules()  # Try unloading again
                time.sleep(delay * (attempt + 1))  # Exponential backoff
            else:
                raise
        except PermissionError:
            if is_windows:
                logger.info("Some package files are locked (addon update in progress).")
                logger.info("Dependencies will be verified on next Blender restart.")
                return False  # Not an error - just defer to next restart
            else:
                raise

    return False


def ensure_packages(packages: Dict[str, str]) -> bool:
    """Ensure required packages are installed.

    Checks if packages are installed and installs them if not.
    Handles Windows DLL locking issues gracefully.
    Prefers local wheels in ./wheels/ before falling back to PyPI.

    Args:
        packages: Dictionary mapping package names to version specifications.

    Returns:
        bool: True if all packages are successfully installed, False otherwise.
    """
    is_windows = platform.system() == "Windows"

    # On Windows, try to unload modules that might have DLLs loaded
    if is_windows:
        logger.info("Preparing for package installation on Windows...")
        _unload_modules()

    import importlib.util
    import glob

    # Find the wheels directory relative to this file
    wheels_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "wheels"))

    # Make the import system and importlib.metadata see packages installed
    # since the last look.
    importlib.invalidate_caches()

    packages_installed_or_updated = False
    restart_required = False

    # On Windows, ensure numpy and scipy are installed first and in the correct order
    # This helps avoid DLL loading issues
    if is_windows:
        ordered_packages = []
        # First numpy
        if 'numpy' in packages:
            ordered_packages.append(('numpy', packages['numpy']))
        # Then scipy
        if 'scipy' in packages:
            ordered_packages.append(('scipy', packages['scipy']))
        # Then everything else
        for name, version in packages.items():
            if name not in ['numpy', 'scipy']:
                ordered_packages.append((name, version))
    else:
        ordered_packages = list(packages.items())

    for package_name, package_version_spec in ordered_packages:
        # Check if the package needs to be reinstalled
        if not _needs_reinstall(package_name, package_version_spec):
            logger.debug(f"{package_name} is already installed and working correctly.")
            continue

        logger.info(f"Installing/Updating {package_name}{package_version_spec}...")

        try:
            # Ensure pip is available and updated (only once)
            if not packages_installed_or_updated:
                logger.info("Updating pip...")
                _install_with_retry([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])

            # Try to find a matching wheel in the local wheels directory
            wheel_pattern = os.path.join(wheels_dir, f"{package_name.replace('-', '_')}*")
            wheel_files = glob.glob(wheel_pattern)
            wheel_installed = False

            # Determine the platform tag for Windows
            if is_windows:
                platform_tag = "win_amd64"
            elif platform.system() == "Linux":
                platform_tag = "manylinux"
            elif platform.system() == "Darwin":
                # Check if ARM or Intel Mac
                import platform as plat
                if plat.machine() == "arm64":
                    platform_tag = "macosx_11_0_arm64"
                else:
                    platform_tag = "macosx"
            else:
                platform_tag = None

            for wheel_path in wheel_files:
                # Check if the wheel matches the required version and platform
                wheel_filename = os.path.basename(wheel_path)

                # Skip if platform tag doesn't match
                if platform_tag and platform_tag not in wheel_filename:
                    continue

                # Check version match
                if package_version_spec.strip('=<>!') in wheel_filename or not package_version_spec:
                    logger.info(f"Installing {package_name} from local wheel: {wheel_filename}")

                    install_cmd = [sys.executable, "-m", "pip", "install"]
                    if is_windows:
                        # On Windows, force reinstall to overwrite locked files
                        # For scipy, we need deps to ensure proper BLAS libraries
                        if package_name == 'scipy':
                            install_cmd.append("--force-reinstall")
                        else:
                            install_cmd.extend(["--force-reinstall", "--no-deps"])
                    install_cmd.append(wheel_path)

                    if _install_with_retry(install_cmd):
                        wheel_installed = True
                        packages_installed_or_updated = True
                        break
                    else:
                        restart_required = True
                        logger.error(f"Failed to install {package_name} from wheel. Restart may be required.")

            if not wheel_installed:
                logger.info(f"No matching local wheel found for {package_name}. Installing from PyPI...")

                install_cmd = [sys.executable, "-m", "pip", "install"]
                if is_windows:
                    # On Windows, force reinstall to overwrite locked files
                    install_cmd.append("--force-reinstall")
                install_cmd.append(f"{package_name}{package_version_spec}")

                if _install_with_retry(install_cmd):
                    packages_installed_or_updated = True
                else:
                    restart_required = True
                    logger.error(f"Failed to install {package_name}. Restart may be required.")

            if wheel_installed or not restart_required:
                logger.info(f"Successfully installed {package_name}{package_version_spec}.")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install {package_name}: {e}")
            if is_windows and "Permission" in str(e):
                restart_required = True
                _show_error_popup(
                    "Installation blocked by locked files. Please restart Blender and reinstall the addon."
                )
            else:
                _show_error_popup(f"Failed to install '{package_name}'. See System Console.")
            return False
        except PermissionError as e:
            logger.error(f"Permission error installing {package_name}: {e}")
            restart_required = True
            _show_error_popup(
                "Installation blocked by locked files. Please restart Blender and reinstall the addon."
            )
            return False
        except Exception as e:
            logger.error(f"Unexpected error during installation of {package_name}: {e}")
            _show_error_popup(f"Error installing '{package_name}'. See Console.")
            return False

    if restart_required:
        logger.error("Some packages could not be installed due to locked files.")
        logger.error("Please restart Blender and try installing the addon again.")
        _show_error_popup(
            "Installation partially complete. Please restart Blender to finish installation."
        )
        return False

    if packages_installed_or_updated:
        logger.info("Dependencies installed/updated. Reloading relevant modules.")
        _reload_modules(packages)

    return True

_pending_popups = []


def _show_error_popup(message: str) -> None:
    """Tell the user about a dependency problem once Blender has a window.

    Never opens the popup on the spot. This runs while the add-on is being
    imported or registered, when Blender has no usable window: calling
    ``popup_menu`` there crashed Blender outright (an access violation, seen
    in background mode), and at an interactive startup it was silently lost.
    The message is logged now and shown from a timer once a window exists.
    """
    logger.error(message)
    _pending_popups.append(message)
    if bpy.app.background:
        return
    try:
        if not bpy.app.timers.is_registered(_flush_popups):
            bpy.app.timers.register(_flush_popups, first_interval=1.0, persistent=True)
    except Exception as e:
        logger.debug(f"Could not schedule the dependency popup: {e}")


def _flush_popups():
    """Timer: show the queued dependency messages in the first window."""
    wm = bpy.context.window_manager
    windows = list(wm.windows) if wm else []
    if not windows:
        return 1.0  # Blender is still starting up; try again shortly
    messages = list(dict.fromkeys(_pending_popups))
    _pending_popups.clear()

    def draw_error(self, context):
        for message in messages:
            self.layout.label(text=message, icon='ERROR')
        self.layout.label(text="Open the ProteinBlender tab in the 3D View sidebar (N) to retry.",
                          icon='INFO')
        self.layout.label(text="See System Console (Window > Toggle System Console).", icon='CONSOLE')

    try:
        with bpy.context.temp_override(window=windows[0]):
            wm.popup_menu(draw_error, title="ProteinBlender Dependency Error", icon='ERROR')
    except Exception as e:
        logger.error(f"Could not show popup: {e}")
    return None


def _reload_modules(packages: Dict[str, str]) -> None:
    """Reload modules after package installation."""
    try:
        importlib.invalidate_caches()

        # Reload specific modules if they were updated
        modules_to_reload = {
            "numpy": ["numpy"],
            "biotite": ["biotite", "biotite.structure"],
        }

        for package_name in packages:
            if package_name in modules_to_reload:
                for module_name in modules_to_reload[package_name]:
                    module = sys.modules.get(module_name)
                    if module:
                        importlib.reload(module)
                        logger.debug(f"Reloaded {module_name}")
    except Exception as e:
        logger.warning(f"Failed to reload modules after installation: {e}")
        logger.info("A restart of Blender might be required for changes to take full effect.")


# --- Addon Metadata (defined early for error messages) ---
bl_info = {
    "name": "ProteinBlender",
    "author": "Dillon Lee",
    "version": (1, 2, 5),  # Synced with blender_manifest.toml
    "blender": (5, 0, 0),  # Synced with blender_manifest.toml's blender_version_min
    "location": "View3D > Sidebar > ProteinBlender",
    "description": "A Blender addon for protein visualization and animation.",
    "warning": "",  # Will be set dynamically if dependencies fail
    "doc_url": "https://animation-lab.github.io/ProteinBlender/",
    "tracker_url": "https://github.com/Animation-Lab/ProteinBlender/issues",
    "category": "3D View"
}

# --- Constants ---
# Runtime specs for the last-resort pip fallback (Blender installs the bundled
# wheels itself; this only runs when that has failed and the imports are broken).
#
# The specs that overlap pyproject.toml's [project.dependencies] MUST match it -
# that list drives `pip download` at build time, and this one drives pip at
# runtime, so a disagreement means the addon repairs itself to a version it was
# never built against. They had already drifted (databpy >=0.0.15 here vs
# >=0.0.18 there; biotite >=1.2.0 here vs the cap there).
REQUIRED_PACKAGES = {
    # Core scientific packages - must be installed first with compatible versions
    "numpy": ">=1.24.0",  # Blender 5.1 ships numpy 2.x; don't cap
    "scipy": ">=1.13",  # Required by biotite and MDAnalysis

    # Main dependencies
    # biotite is capped below 1.7 as in pyproject.toml, which explains why:
    # 1.7 moved struc.bonds.connect_via_residue_names, and the cap is now
    # precautionary because the embedded MolecularNodes uses the top-level name.
    # Keep this spec identical to pyproject.toml's.
    "biotite": ">=1.1,<1.7",
    # Capped below 0.8: databpy 0.8.0 imports bpy.types.Float4Attribute at
    # module scope, which only exists in Blender 5.2+. 0.7.x works on 5.0-5.2.
    "databpy": ">=0.0.18,<0.8",
    "MDAnalysis": ">=2.7.0",

    # File format handlers
    "mrcfile": "",
    "starfile": "",
    "PyYAML": "",

    # Critical sub-dependencies (often corrupted on Windows)
    "msgpack": ">=0.5.6",  # Required by MDAnalysis and biotite
}

# --- Dependency Management ---
# Cache file to avoid checking dependencies on every startup
import json
from pathlib import Path

# A record of the last automatic repair attempt, so a repair that fails is not
# re-run on every startup (pip is slow and freezes Blender while it runs).
#
# It records attempts only. It used to be refreshed on every *healthy* start
# too, under a key it then read as "an install was attempted", so dependencies
# that broke within a day of a good start were never repaired and the log said
# a repair had been tried when none had. Older files carry only that old
# 'last_check' key, which is deliberately ignored.
_cache_file = Path(__file__).parent / ".dependency_cache.json"
_cache_validity_hours = 24
_ATTEMPT_KEY = 'last_install_attempt'


def _last_install_attempt():
    """When an automatic repair last ran (seconds since the epoch), or None."""
    try:
        with open(_cache_file, 'r') as f:
            value = json.load(f).get(_ATTEMPT_KEY)
        return float(value) if value is not None else None
    except Exception:
        return None


def _install_attempted_recently():
    last = _last_install_attempt()
    return last is not None and (time.time() - last) / 3600 < _cache_validity_hours


def _record_install_attempt():
    try:
        with open(_cache_file, 'w') as f:
            json.dump({_ATTEMPT_KEY: time.time()}, f)
    except Exception as e:
        logger.debug(f"Could not record the dependency repair attempt: {e}")


def _clear_install_attempt():
    """The dependencies work, so a future breakage should be repaired at once."""
    try:
        _cache_file.unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"Could not clear the dependency repair record: {e}")


def _restore_missing_libs(wheels_dir, site_dirs, pytag):
    """Extract missing ``<pkg>.libs`` folders from bundled win wheels.

    Core of :func:`_repair_partial_wheels`, split out with no platform
    assumptions so it is unit-testable on any OS. For each ``*win_amd64`` wheel
    matching ``pytag`` that ships a ``<pkg>.libs`` directory, look in every
    ``site_dirs`` entry that already has the package installed but is missing
    that ``.libs`` sibling, and extract the wheel's ``.libs`` members there.

    Returns a list of ``(libs_root, site_dir)`` for each restored folder.
    """
    import glob
    import zipfile

    repaired = []
    for whl in glob.glob(os.path.join(wheels_dir, "*win_amd64.whl")):
        base = os.path.basename(whl)
        if pytag not in base:
            continue
        dist = base.split("-", 1)[0]  # e.g. "scipy", "pandas"
        try:
            with zipfile.ZipFile(whl) as zf:
                libs_members = [
                    n for n in zf.namelist()
                    if "/" in n and n.split("/")[0].endswith(".libs")
                ]
                if not libs_members:
                    continue  # pure/compiled-without-external-DLLs wheel
                libs_root = libs_members[0].split("/")[0]  # e.g. "scipy.libs"
                for site in site_dirs:
                    installed = (
                        os.path.isdir(os.path.join(site, dist)) or
                        glob.glob(os.path.join(site, dist + "-*.dist-info")))
                    if not installed:
                        continue
                    if os.path.isdir(os.path.join(site, libs_root)):
                        continue  # healthy - .libs already present
                    for member in libs_members:
                        zf.extract(member, site)
                    repaired.append((libs_root, site))
                    logger.warning(
                        "Repaired partial install: restored %s in %s from the "
                        "bundled wheel", libs_root, site)
        except Exception as e:
            logger.debug("Wheel repair check skipped for %s: %s", base, e)
    return repaired


def _repair_partial_wheels() -> bool:
    """Restore missing ``<pkg>.libs`` DLL folders from the bundled wheels.

    Blender's extension installer occasionally leaves a bundled wheel only
    partially extracted on Windows: the package's ``.py`` / ``.pyd`` files land
    but the sibling ``<pkg>.libs`` directory - which holds the OpenBLAS (scipy)
    and Arrow (pandas/pyarrow) DLLs, and is NOT listed in the wheel's RECORD -
    is dropped. The package then imports at top level but its compiled
    submodules raise ``ImportError: DLL load failed`` (e.g. ``scipy.linalg
    ._fblas``), so scipy / MDAnalysis / starfile break and the add-on refuses to
    load with an unhelpful "Dependencies failed to install".

    Detect that exact state and re-extract just the ``.libs`` members from the
    matching bundled wheel into that same site-packages directory.
    Filesystem-only, offline (the wheels ship with the add-on), and run BEFORE
    any compiled dependency is imported so scipy's ``_distributor_init``
    registers the restored DLL directory. Best-effort: every failure is
    swallowed so this can never block a healthy load. Returns True if anything
    was repaired.
    """
    if sys.platform != "win32":
        return False

    wheels_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "wheels"))
    if not os.path.isdir(wheels_dir):
        return False
    pytag = "cp{}{}".format(sys.version_info.major, sys.version_info.minor)

    # site-packages directories actually on the import path (the extension
    # ".local", the user site, Blender's bundled one). Only these can shadow.
    site_dirs = [
        p for p in sys.path
        if p and os.path.isdir(p) and os.path.basename(p) == "site-packages"
    ]
    if not site_dirs:
        return False

    repaired = _restore_missing_libs(wheels_dir, site_dirs, pytag)
    for libs_root, site in repaired:
        # Make the restored DLLs discoverable even if the package was already
        # imported (its _distributor_init ran before the folder existed).
        try:
            os.add_dll_directory(os.path.join(site, libs_root))
        except Exception:
            pass
    return bool(repaired)

# Normal mode: avoid pip operations when the packages already work (running
# pip during an addon update triggers Windows permission errors).
#
# The import check is authoritative: if it fails, the dependencies are not
# usable, and no cache entry can make them usable. The cache only rate-limits
# how often a *failing* install is retried - it must never be read as success.
# It previously was, so a failed import plus a fresh cache entry left
# dependencies_installed True and the addon carried on into
# `from .addon import register`, which then died on ImportError with no
# warning shown to the user.
# Repair a partially-extracted bundled wheel (missing '<pkg>.libs' DLLs) before
# importing anything - this is offline and always safe, and unlike the pip
# fallback below it is NOT rate-limited by the daily cache, because a broken
# .libs never fixes itself and repairing it is cheap and deterministic.
try:
    _repair_partial_wheels()
except Exception as _repair_exc:  # never let repair block a load
    logger.debug("Wheel repair pass failed: %s", _repair_exc)

if _can_import_core_packages():
    logger.info("All core packages importable, skipping installation")
    dependencies_installed = True
    _clear_install_attempt()
elif not _install_attempted_recently():
    logger.info("Core packages missing, verifying dependencies...")
    # Recorded before pip runs, so an install that hangs or crashes Blender
    # still backs off instead of re-running on every startup.
    _record_install_attempt()
    # ensure_packages can report success while an import still fails, and
    # going on to `from .addon import register` would then kill the import.
    dependencies_installed = ensure_packages(REQUIRED_PACKAGES) and _can_import_core_packages()
else:
    logger.warning(
        "Core packages are not importable and an automatic repair was tried "
        "in the last %d hours; not retrying at startup. Use Retry in the "
        "ProteinBlender sidebar tab.", _cache_validity_hours)
    dependencies_installed = False

# Dynamically set warning if dependencies failed
if not dependencies_installed:
    bl_info['warning'] = "Required Python packages failed to install. See console."


# --- Registration ---
if dependencies_installed:
    # Proceed with standard registration if dependencies are met
    logger.info("Dependencies met. Loading addon.")
    from .addon import register, unregister, _test_register
else:
    logger.error("Dependencies failed to install. Addon will not be fully functional.")
    from .dependency_fallback import register, unregister, dependency_problem

    def _test_register() -> None:
        """Dummy test register function when dependencies are missing."""
        pass
