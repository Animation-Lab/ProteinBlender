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


def _needs_reinstall(package_name: str, required_version: str) -> bool:
    """Check if a package needs to be reinstalled.

    Args:
        package_name: The name of the package to check.
        required_version: The required version specification (e.g., ">=2.7.0").

    Returns:
        bool: True if the package needs to be reinstalled, False otherwise.
    """
    try:
        import pkg_resources
        dist = pkg_resources.get_distribution(package_name)

        if not required_version:
            # No specific version required, package exists, so it's fine
            # But still check if it can be imported
            pass
        else:
            from pkg_resources import Requirement
            req = Requirement.parse(f"{package_name}{required_version}")

            # Check if current version meets requirement
            if dist.version not in req:
                logger.info(f"{package_name} version {dist.version} does not meet requirement {required_version}")
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
        # Deliberately broad, and deliberately NOT a tuple naming
        # pkg_resources.DistributionNotFound: the `import pkg_resources` above is
        # inside this try, so naming that attribute in the except clause raised
        # NameError in exactly the case it was meant to catch. Exception already
        # covers DistributionNotFound.
        return True  # Package not found or error checking, needs install


def _can_import_core_packages():
    """Quick check if all core packages can be imported without errors.

    This is used to skip pip installation attempts when packages are already
    working, which prevents permission errors during addon updates.

    Returns:
        bool: True if all core packages can be imported successfully
    """
    import importlib

    core_packages = ['biotite', 'databpy', 'MDAnalysis', 'numpy', 'scipy', 'mrcfile', 'starfile']

    for package in core_packages:
        try:
            # Map package names to their import names if different
            import_name = 'yaml' if package == 'PyYAML' else package
            importlib.import_module(import_name)
        except ImportError:
            logger.debug(f"Core package {package} cannot be imported")
            return False

    logger.debug("All core packages are importable")
    return True


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

    try:
        import pkg_resources
    except ImportError:
        logger.error("pkg_resources not found. Attempting to install setuptools...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools"])
            import pkg_resources
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install setuptools: {e}")
            _show_error_popup("Failed to install setuptools. Please install manually.")
            return False

    import importlib.util
    import glob

    # Find the wheels directory relative to this file
    wheels_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "wheels"))

    # Reload pkg_resources to ensure it picks up newly installed packages
    try:
        importlib.reload(pkg_resources)
    except Exception as e:
        logger.warning(f"Could not reload pkg_resources: {e}")

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

def _show_error_popup(message: str) -> None:
    """Show an error popup in Blender's UI."""
    def draw_error(self, context):
        self.layout.label(text=message, icon='ERROR')
        if "System Console" not in message:
            self.layout.label(text="See System Console (Window > Toggle System Console).", icon='INFO')
    
    try:
        if bpy.context.window_manager and bpy.context.window:
            bpy.context.window_manager.popup_menu(draw_error, title="ProteinBlender Dependency Error", icon='ERROR')
        else:
            logger.error(f"Could not show popup (no window context): {message}")
    except RuntimeError:
        logger.error(f"Could not show popup: {message}")


def _reload_modules(packages: Dict[str, str]) -> None:
    """Reload modules after package installation."""
    try:
        import pkg_resources
        importlib.reload(pkg_resources)

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
    "version": (1, 0, 6),  # Synced with blender_manifest.toml
    "blender": (4, 2, 0),  # Updated to match manifest requirement
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
    # biotite is capped below 1.7 for the same reason as pyproject.toml: 1.7
    # removed structure.connect_via_residue_names, which the embedded
    # MolecularNodes imports at module scope. Without the cap this fallback
    # "repairs" a broken install by fetching the one version guaranteed to break.
    "biotite": ">=1.1,<1.7",
    "databpy": ">=0.0.18",
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

_cache_file = Path(__file__).parent / ".dependency_cache.json"
_cache_validity_hours = 24  # Check dependencies once per day

def _should_check_dependencies():
    """Check if we need to verify dependencies based on cache"""
    if not _cache_file.exists():
        return True

    try:
        with open(_cache_file, 'r') as f:
            cache_data = json.load(f)

        last_check = cache_data.get('last_check', 0)
        import time
        hours_since_check = (time.time() - last_check) / 3600

        return hours_since_check > _cache_validity_hours
    except:
        return True

def _update_dependency_cache():
    """Update the cache file with current timestamp"""
    try:
        import time
        with open(_cache_file, 'w') as f:
            json.dump({'last_check': time.time()}, f)
    except Exception as e:
        logger.debug(f"Could not update dependency cache: {e}")


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
    _update_dependency_cache()
elif _should_check_dependencies():
    logger.info("Core packages missing, verifying dependencies...")
    dependencies_installed = ensure_packages(REQUIRED_PACKAGES)
    # Record the attempt either way, so a persistently failing install backs
    # off instead of re-running pip on every startup.
    _update_dependency_cache()
else:
    logger.warning(
        "Core packages are not importable and an install was attempted "
        "recently; not retrying yet.")
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
    # Define dummy functions if dependencies failed
    logger.error("Dependencies failed to install. Addon will not be fully functional.")

    def register() -> None:
        """Dummy register function when dependencies are missing."""
        logger.error(f"Cannot register {bl_info['name']} due to missing dependencies.")
        _show_error_popup(f"Cannot register {bl_info['name']} due to missing dependencies.")

    def unregister() -> None:
        """Dummy unregister function when dependencies are missing."""
        logger.info(f"Unregistering {bl_info['name']} (no-op due to failed registration).")

    def _test_register() -> None:
        """Dummy test register function when dependencies are missing."""
        pass