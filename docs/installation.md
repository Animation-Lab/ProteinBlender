---
layout: default
title: Installation
---

# Installation Guide

[Back to Home](index.html)

ProteinBlender can be installed in two ways: through the extension repository (recommended) or manually from a zip file.

## Requirements

- **Blender 4.2** or newer
- **Operating System**: Windows, macOS, or Linux  
- **Internet connection** (for initial installation and updates)

## Option 1: Extension Repository (Recommended)

The extension repository provides automatic update notifications and one-click updates.

### Step 1: Add the Repository

1. **Open Blender** (4.2 or newer)
2. Go to Edit -> Preferences
3. Navigate to the **Get Extensions** section
4. Click on the **Repositories** dropdown at the top
5. Click the **+** (plus) button
6. Select **Add Remote Repository**

### Step 2: Configure Repository

Enter the following information:

- **Name**: ProteinBlender
- **URL**: https://ORGNAME.github.io/proteinblender/index.json

Click **OK** to save.

### Step 3: Install ProteinBlender

1. Return to the main **Get Extensions** view
2. Make sure the ProteinBlender repository is selected in the dropdown
3. Find **ProteinBlender** in the extensions list
4. Click **Install**
5. Wait for the installation to complete
6. **Restart Blender**

### Step 4: Enable Auto-Updates (Optional)

1. Go to Edit -> Preferences -> Get Extensions -> Repositories
2. Select the ProteinBlender repository
3. Enable **Check for Updates on Start**

Blender will now automatically notify you when updates are available.

## Option 2: Manual Installation

If you prefer to install manually or need to use an older version of Blender:

### Step 1: Download

1. Go to the [Releases page](https://github.com/ORGNAME/proteinblender/releases)
2. Download the latest .zip file for your platform:
   - proteinblender-X.X.X-windows-x64.zip (Windows)
   - proteinblender-X.X.X-linux-x64.zip (Linux)
   - proteinblender-X.X.X-macos-arm64.zip (Mac M1/M2)
   - proteinblender-X.X.X-macos-x64.zip (Mac Intel)

### Step 2: Install in Blender

1. **Open Blender**
2. Go to Edit -> Preferences -> Get Extensions
3. Click **Install from Disk** (top-right corner)
4. Navigate to and select the downloaded .zip file
5. Click **Install from Disk**
6. **Restart Blender**

**Note**: Manual installation does not provide automatic update notifications.

## Verifying Installation

After restarting Blender:

1. Open a new project or create a blank scene
2. Look for the **ProteinBlender** workspace tab at the top
3. Or press N in the 3D viewport to open the sidebar
4. You should see ProteinBlender panels

If you see the panels, installation was successful!

attempt 1
[![Final video of fixing issues in your code in VS Code](https://img.youtube.com/vi/FpLOwE0MfCk/maxresdefault.jpg)](https://www.youtube.com/watch?v=FpLOwE0MfCk)


attempt 2
{% include youtube.html id="FpLOwE0MfCk" %}

## Troubleshooting

### Extension Doesn't Appear

- Verify you're using **Blender 4.2** or newer
- Check that you restarted Blender after installation
- Try Edit -> Preferences -> Get Extensions and look for ProteinBlender in the list

### Repository Cannot Be Accessed

- Check your internet connection
- Verify the repository URL is correct
- Try clicking the refresh button in the repositories list

### Installation Fails

- Check Blender's system console for error messages
- Try manual installation from zip file instead
- Report issues at [GitHub Issues](https://github.com/ORGNAME/proteinblender/issues)

### Dependencies Not Installing

ProteinBlender automatically installs required dependencies on first load. If you see errors:

1. Check that you have internet access
2. Wait for dependency installation to complete (may take 1-2 minutes)
3. Restart Blender if installation completes
4. Check the Blender console for specific error messages

## Uninstallation

To remove ProteinBlender:

1. Go to Edit -> Preferences -> Get Extensions
2. Find **ProteinBlender** in the list
3. Click the **dropdown arrow** next to the extension
4. Click **Remove**
5. Restart Blender

## Next Steps

Now that ProteinBlender is installed, learn how to:

- [Import Proteins](import.html) - Load your first protein structure
- [Update Visuals](visuals.html) - Customize how proteins look

---

[Back to Home](index.html) | [Next: Import Proteins](import.html)



