# ProteinBlender Build and Installation Instructions

This document explains how to build the ProteinBlender addon for distribution and how to run it for development purposes.

## Building the Distributable Addon (.zip)

This process packages the addon code and its Python dependencies into a single `.zip` file that can be easily installed into Blender. It downloads required packages for multiple platforms (Windows, Linux, macOS).

### Using VS Code Tasks

1.  Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`).
2.  Type `Tasks: Run Task` and select it.
3.  Choose the `plugin: build-wheels` task.

This will execute the `build.py` script using Blender's Python interpreter.

### Using the Command Line

1.  Make sure you have Blender installed and know the path to its internal Python interpreter.
2.  Open a terminal or command prompt in the project's root directory.
3.  Run the following command, replacing the path to Blender's Python if necessary:

    ```bash
    # Example for Blender 4.4 on Windows
    "C:\Program Files\Blender Foundation\Blender 4.4\4.4\python\bin\python.exe" build.py
    ```

### Build Output

Both methods will:
*   Download necessary Python wheels into `proteinblender/wheels/`.
*   Update `proteinblender/blender_manifest.toml`.
*   Create the distributable zip file (e.g., `proteinblender-x.y.z.zip`) inside the `dist/` directory in your project root.

## Running for Development

This method allows you to run the addon directly from the source code within Blender, which is useful for testing and debugging. It automatically handles installing dependencies into your user Python environment.

### Using VS Code Tasks

1.  This is the default build task. Simply press `Ctrl+Shift+B` (or `Cmd+Shift+B`).
2.  Alternatively, open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`), type `Tasks: Run Task`, and select `Blender: Dev–build & install`.

This will:
1.  Ensure Blender's pip is installed (`plugin: install-deps` task).
2.  Install the required Python dependencies from `proteinblender/wheels/` into your user site-packages directory (`plugin: pip-deps` task).
3.  Launch Blender, automatically adding the necessary project directories to Blender's Python path and enabling the `proteinblender` addon (`dev_register.py` script).

Blender should open with the ProteinBlender addon enabled and ready to use. Check Blender's system console (Window -> Toggle System Console) for any potential error messages during startup.

## Installing the Distributable (.zip) Manually

1.  Build the addon using the instructions above to create the `.zip` file in the `dist/` directory.
2.  Open Blender.
3.  Go to `Edit` -> `Preferences` -> `Add-ons`.
4.  Click the `Install...` button.
5.  Navigate to the `dist/` directory in your project, select the `proteinblender-x.y.z.zip` file, and click `Install Add-on`.
6.  Find "ProteinBlender" in the add-on list and enable it by checking the box next to its name. 