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
from typing import Dict, Set

# Development mode flag - set to True to skip dependency checks for faster reloads
# build.py automatically sets this to False when building for release
DEV_MODE = False  # Change to False for production, or set PROTEINBLENDER_DEV_MODE env var

# Set up logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

if DEV_MODE:
    logger.info("🔧 DEV_MODE enabled - skipping dependency checks for faster reloads")

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

    except (pkg_resources.DistributionNotFound, Exception):
        return True  # Package not found or error checking, needs install


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
            if is_windows and attempt < max_retries - 1:
                # On Windows, might be a temporary lock
                logger.warning(f"Installation attempt {attempt + 1} failed. Retrying...")
                _unload_modules()  # Try unloading again
                time.sleep(delay * (attempt + 1))  # Exponential backoff
            else:
                raise
        except PermissionError as e:
            if is_windows:
                logger.error(f"Permission denied accessing files. This usually means Blender has locked DLL files.")
                logger.error("Please restart Blender and try installing the addon again.")
                _show_error_popup(
                    "Installation blocked by locked files. Please restart Blender and reinstall the addon."
                )
                return False
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
    
    if bpy.context.window_manager:
        bpy.context.window_manager.popup_menu(draw_error, title="ProteinBlender Dependency Error", icon='ERROR')
    else:
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
    "version": (1, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > ProteinBlender",
    "description": "A Blender addon for protein visualization and animation.",
    "warning": "",  # Will be set dynamically if dependencies fail
    "doc_url": "https://github.com/dillonleelab/proteinblender",
    "tracker_url": "https://github.com/dillonleelab/proteinblender/issues",
    "category": "3D View"
}

# --- Constants ---
REQUIRED_PACKAGES = {
    "biotite": "==1.2.0",
    "databpy": "==0.0.15",
    "MDAnalysis": ">=2.7.0",
    "mrcfile": "",
    "starfile": "",
    "PyYAML": "",
    # Critical dependencies that might be corrupted
    "msgpack": "",  # Required by MDAnalysis, often corrupted on Windows
    "scipy": "",  # Required by MDAnalysis, needs BLAS DLLs
    "numpy": "",  # Required by scipy, needs to be compatible version
}

# --- Dependency Management ---
if DEV_MODE:
    # In development mode, skip dependency checks for faster reloads
    logger.info("Skipping dependency check in DEV_MODE")
    dependencies_installed = True
else:
    # Normal mode: check and install dependencies
    dependencies_installed = ensure_packages(REQUIRED_PACKAGES)

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