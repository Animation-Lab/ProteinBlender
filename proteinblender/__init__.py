import bpy
import sys
import subprocess
import os
import importlib

# Function to check and install packages
def ensure_packages(packages):
    """Checks if packages are installed and installs them if not."""
    try:
        import pkg_resources
    except ImportError:
        print("pkg_resources not found. Attempting to install setuptools...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools"])
            import pkg_resources
        except Exception as e:
            print(f"Failed to install setuptools: {e}")
            print("Please install setuptools manually in Blender's Python environment.")
            return False

    blender_python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    
    # Reload pkg_resources to ensure it picks up newly installed packages if Blender was just started
    try:
        importlib.reload(pkg_resources)
    except Exception as reload_e:
        print(f"Could not reload pkg_resources: {reload_e}")
        # Continue execution, but installation checks might be less reliable

    packages_installed_or_updated = False

    for package_name, package_version_spec in packages.items():
        try:
            dist = pkg_resources.get_distribution(package_name)
            # Attempt to parse the version specifier to check compatibility
            from pkg_resources import Requirement
            req = Requirement.parse(f"{package_name}{package_version_spec}")
            if dist.version not in req:
                print(f"{package_name} version {dist.version} found, but {req} is required. Attempting upgrade/downgrade...")
                raise pkg_resources.DistributionNotFound # Trigger install
            else:
                 print(f"ProteinBlender: {package_name} {dist.version} already installed and meets requirement {req}.")

        except pkg_resources.DistributionNotFound:
            print(f"ProteinBlender: {package_name} not found or wrong version. Installing/Updating {package_name}{package_version_spec}...")
            try:
                # Ensure pip is available and updated
                print("Updating pip...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
                # Install the package
                print(f"Installing {package_name}{package_version_spec}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", f"{package_name}{package_version_spec}"])
                print(f"Successfully installed {package_name}{package_version_spec}.")
                packages_installed_or_updated = True
                
            except subprocess.CalledProcessError as e:
                print(f"Failed to install {package_name}: {e}")
                # Check if running in background mode might hide prompts (less common now)
                if not sys.stdout.isatty():
                    print("Hint: Pip installation might require user interaction. Try installing manually from Blender's Python console.")
                
                # Display a user-friendly error in Blender's UI
                def draw_error(self, context):
                    self.layout.label(text=f"Failed to install '{package_name}'. See System Console (Window > Toggle System Console).", icon='ERROR')
                if bpy.context.window_manager:
                   bpy.context.window_manager.popup_menu(draw_error, title=f"{bl_info.get('name')} Dependency Error", icon='ERROR')
                else:
                   print(f"ERROR: Could not show popup for {package_name} installation failure.")
                return False # Indicate failure

            except Exception as e:
                 print(f"An unexpected error occurred during installation of {package_name}: {e}")
                 def draw_error(self, context):
                      self.layout.label(text=f"Error installing '{package_name}'. See Console.", icon='ERROR')
                 if bpy.context.window_manager:
                     bpy.context.window_manager.popup_menu(draw_error, title=f"{bl_info.get('name')} Dependency Error", icon='ERROR')
                 else:
                    print(f"ERROR: Could not show popup for {package_name} installation failure.")
                 return False # Indicate failure
                 
    if packages_installed_or_updated:
         print("ProteinBlender: Dependencies installed/updated. Reloading relevant modules.")
         # It's difficult to reliably reload modules that might already be partially imported
         # due to the installation happening mid-load. A restart is often the safest.
         # We can try reloading the specific top-level dependencies if known.
         try:
             importlib.reload(pkg_resources) # Reload pkg_resources again
             if "numpy" in packages:
                 numpy_module = sys.modules.get("numpy")
                 if numpy_module:
                    importlib.reload(numpy_module)
                    print("Reloaded numpy.")
             if "biotite" in packages:
                 biotite_module = sys.modules.get("biotite")
                 if biotite_module:
                     importlib.reload(biotite_module)
                     print("Reloaded biotite.")
                     # Potentially reload submodules if needed, e.g., biotite.structure
                     biotite_structure = sys.modules.get("biotite.structure")
                     if biotite_structure:
                        importlib.reload(biotite_structure)
                        print("Reloaded biotite.structure")

         except Exception as reload_e:
            print(f"Failed to reload modules after installation: {reload_e}")
            print("A restart of Blender might be required for changes to take full effect.")


    return True # Indicate success

# --- Dependency Management ---
required_packages = {
    "biotite": "==1.2.0",
    "numpy": ">=1.26.0,<2.0" 
}

dependencies_installed = ensure_packages(required_packages)

# --- Addon Info ---
bl_info = {
    "name": "ProteinBlender",
    "author": "Dillon Lee",
    "version": (1, 0, 1), # Incremented version
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > ProteinBlender",
    "description": "A Blender addon for protein visualization and animation.",
    "warning": "", # Initialize warning as empty - MUST be static
    "doc_url": "", # Add your documentation URL here
    "tracker_url": "", # Add your bug tracker URL here
    "category": "3D View"
}

# Dynamically set warning if dependencies failed *after* bl_info is defined
if not dependencies_installed:
    bl_info['warning'] = "Required Python packages failed to install. See console."


if dependencies_installed:
    # Proceed with standard registration if dependencies are met
    print("ProteinBlender: Dependencies met. Loading addon.")
    from .addon import register, unregister, _test_register
else:
    # Define dummy functions if dependencies failed, preventing addon load errors
    # and inform the user via bl_info warning.
    print("ProteinBlender: Dependencies failed to install. Addon will not be fully functional.")
    
    def register():
        print(f"Cannot register {bl_info['name']} due to missing dependencies. Check the System Console.")
        def draw_error(self, context):
            self.layout.label(text=f"Cannot register {bl_info['name']} due to missing dependencies.", icon='ERROR')
            self.layout.label(text="Please check Blender's System Console for details.")
        bpy.context.window_manager.popup_menu(draw_error, title="Registration Failed", icon='ERROR')

    def unregister():
        # Minimal unregister if needed, likely nothing to unregister if register failed early.
        print(f"Unregistering {bl_info['name']} (likely due to failed registration).")
        pass 
    
    def _test_register():
         pass # Do nothing if dependencies aren't there

# No changes below this line needed for this edit. Only adding code above bl_info and conditionally importing/defining register/unregister.
# The original lines were:
# bl_info = { ... }
# from .addon import register, unregister, _test_register

