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
from typing import Dict

# Set up logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Add user site-packages to sys.path if not already present
user_site = site.getusersitepackages()
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.append(user_site)
    logger.info(f"Added user site-packages to sys.path: {user_site}")

def ensure_packages(packages: Dict[str, str]) -> bool:
    """Ensure required packages are installed.
    
    Checks if packages are installed and installs them if not. 
    Prefers local wheels in ./wheels/ before falling back to PyPI.
    
    Args:
        packages: Dictionary mapping package names to version specifications.
        
    Returns:
        bool: True if all packages are successfully installed, False otherwise.
    """
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

    for package_name, package_version_spec in packages.items():
        try:
            dist = pkg_resources.get_distribution(package_name)
            from pkg_resources import Requirement
            req = Requirement.parse(f"{package_name}{package_version_spec}")
            if dist.version not in req:
                print(f"{package_name} version {dist.version} found, but {req} is required. Attempting upgrade/downgrade...")
                raise pkg_resources.DistributionNotFound
            else:
                logger.debug(f"{package_name} {dist.version} already installed and meets requirement {req}.")
        except pkg_resources.DistributionNotFound:
            logger.info(f"{package_name} not found or wrong version. Installing/Updating {package_name}{package_version_spec}...")
            try:
                # Ensure pip is available and updated
                logger.info("Updating pip...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
                # Try to find a matching wheel in the local wheels directory
                wheel_pattern = os.path.join(wheels_dir, f"{package_name.replace('-', '_')}*")
                wheel_files = glob.glob(wheel_pattern)
                wheel_installed = False
                for wheel_path in wheel_files:
                    # Check if the wheel matches the required version and platform
                    wheel_filename = os.path.basename(wheel_path)
                    if package_version_spec.strip('=<>!') in wheel_filename:
                        logger.info(f"Installing {package_name} from local wheel: {wheel_filename}")
                        subprocess.check_call([sys.executable, "-m", "pip", "install", wheel_path])
                        wheel_installed = True
                        break
                if not wheel_installed:
                    logger.info(f"No matching local wheel found for {package_name}. Installing from PyPI...")
                    subprocess.check_call([sys.executable, "-m", "pip", "install", f"{package_name}{package_version_spec}"])
                logger.info(f"Successfully installed {package_name}{package_version_spec}.")
                packages_installed_or_updated = True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to install {package_name}: {e}")
                _show_error_popup(f"Failed to install '{package_name}'. See System Console.")
                return False
            except Exception as e:
                logger.error(f"Unexpected error during installation of {package_name}: {e}")
                _show_error_popup(f"Error installing '{package_name}'. See Console.")
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


# --- Constants ---
REQUIRED_PACKAGES = {
    "biotite": "==1.2.0",
    "databpy": "==0.0.15",
    "MDAnalysis": ">=2.7.0",
    "mrcfile": "",
    "starfile": "",
    "PyYAML": ""
}

# --- Dependency Management ---
dependencies_installed = ensure_packages(REQUIRED_PACKAGES)

# --- Addon Metadata ---
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

# Dynamically set warning if dependencies failed *after* bl_info is defined
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