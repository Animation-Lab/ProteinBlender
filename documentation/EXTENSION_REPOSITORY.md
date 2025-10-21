# ProteinBlender Extension Repository

This document explains how to install and update ProteinBlender using the custom extension repository with automatic updates.

## What is the Extension Repository?

Starting with Blender 4.2, extensions can be distributed through custom repositories that provide automatic update notifications. Once you add the ProteinBlender repository to Blender, you'll automatically be notified when new versions are available and can update with one click.

## Prerequisites

- **Blender 4.2.0 or higher** (required for extension repository support)

## Installation Steps

### Step 1: Open Blender Preferences

1. Open Blender
2. Go to `Edit` → `Preferences`
3. Navigate to the `Get Extensions` section

### Step 2: Add the ProteinBlender Repository

1. Click on the `Repositories` dropdown at the top
2. Click the `+` (plus) button to add a new repository
3. Select `Add Remote Repository`

### Step 3: Configure the Repository

Enter the following information:

- **Name**: `ProteinBlender`
- **URL**: `https://PLACEHOLDER_URL_HERE/index.json`
  _(Replace with actual URL once repository is transferred)_

Click `OK` to save.

### Step 4: Install ProteinBlender

1. Return to the main `Get Extensions` view
2. Make sure the `ProteinBlender` repository is selected in the dropdown
3. Find `ProteinBlender` in the list
4. Click `Install` to download and install the extension

### Step 5: Enable Auto-Update Checking (Optional but Recommended)

1. Go back to `Preferences` → `Get Extensions` → `Repositories`
2. Select the `ProteinBlender` repository
3. Enable `Check for Updates on Start`

Now Blender will automatically check for updates when it starts and notify you in the status bar.

## Updating ProteinBlender

When a new version is available:

1. You'll see a notification in Blender's status bar (bottom of the window)
2. Click the notification or go to `Preferences` → `Get Extensions`
3. You'll see an `Update` button next to ProteinBlender
4. Click `Update` to install the latest version
5. Restart Blender to complete the update

## Alternative: Manual Installation

If you prefer not to use the extension repository or are using an older version of Blender:

1. Download the latest `.zip` file from [GitHub Releases](https://github.com/dillonleelab/proteinblender/releases)
2. In Blender, go to `Edit` → `Preferences` → `Get Extensions`
3. Click `Install from Disk` (top-right corner)
4. Select the downloaded `.zip` file
5. Restart Blender

**Note**: Manual installation does not provide automatic update notifications.

## Troubleshooting

### "Repository cannot be accessed" error

- Ensure you have an active internet connection
- Verify the repository URL is correct
- Try clicking the refresh button in the repositories list

### Extension doesn't appear in the list

- Make sure the `ProteinBlender` repository is selected in the dropdown
- Click the refresh icon to reload the repository
- Check that you're using Blender 4.2.0 or higher

### Update notification doesn't appear

- Verify that `Check for Updates on Start` is enabled for the repository
- Manually check for updates by going to `Preferences` → `Get Extensions` and clicking the refresh icon

### Installation fails

- Try installing from disk manually (see Alternative: Manual Installation above)
- Check Blender's system console for error messages (`Window` → `Toggle System Console` on Windows)
- Report issues at https://github.com/dillonleelab/proteinblender/issues

## For Developers

### Building a Release

When creating a new release, the build process automatically:

1. Prompts for a version number
2. Updates all three version files:
   - `blender_manifest.toml`
   - `pyproject.toml`
   - `__init__.py` (bl_info)
3. Downloads platform-specific dependency wheels
4. Builds the extension package

Run the build script:

```bash
python build.py
```

### GitHub Actions Workflow

When a GitHub release is published, the workflow automatically:

1. Downloads all extension `.zip` files from releases
2. Generates the `index.json` repository index using Blender
3. Deploys to GitHub Pages on the `gh-pages` branch

Users accessing `https://PLACEHOLDER_URL_HERE/index.json` will see all available versions.

### Manual Repository Generation

To generate the repository index locally for testing:

```bash
# Build your extension first
python build.py

# Create a directory for the repository
mkdir -p extensions

# Copy your .zip files to the directory
cp dist/*.zip extensions/

# Generate the index.json using Blender
blender --background --command extension server-generate --repo-dir=extensions/

# Test locally by adding file:///path/to/extensions/index.json as a repository in Blender
```

## Version Management

All version numbers are kept in sync across three files:

- **`blender_manifest.toml`**: Source of truth (semantic versioning: `"X.Y.Z"`)
- **`pyproject.toml`**: Python package version (semantic versioning: `"X.Y.Z"`)
- **`__init__.py`**: bl_info version (tuple format: `(X, Y, Z)`)

The `build.py` script ensures all three are updated together.

## Repository URL Notes

**Current Status**: Using placeholder URL until repository transfer

Once the repository is transferred to the ProteinBlender organization:

1. Update the repository URL in this document
2. Update any announcements or documentation
3. Users with the old URL will need to update their repository settings (one-time change)

**Recommended URL Structure**:
- GitHub Pages: `https://<org>.github.io/<repo>/index.json`
- Custom domain: `https://extensions.proteinblender.org/index.json`

## Support

- **Issues**: https://github.com/dillonleelab/proteinblender/issues
- **Documentation**: https://github.com/dillonleelab/proteinblender
- **Releases**: https://github.com/dillonleelab/proteinblender/releases
