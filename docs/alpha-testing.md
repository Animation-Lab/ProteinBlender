---
layout: default
title: Alpha Testing
---

# Alpha Testing Channel

[Back to Home](index.html)

The **Alpha** channel is a separate release stream for testers. It installs as its
own extension - **ProteinBlender (Alpha)** - so you get update notifications for
alpha builds through Blender's normal extension updater instead of passing zip
files around.

> **Important - do not run both at once.** The alpha build shares internal
> identifiers with the release build, so having **ProteinBlender** and
> **ProteinBlender (Alpha)** *enabled at the same time* will cause errors.
> **Disable (or uninstall) the release version before enabling the alpha**, and
> switch back when you're done testing. Installing both is fine; only one may be
> **enabled** at a time.

## Add the Alpha Repository

1. **Open Blender** (5.0 or newer)
2. Go to **Edit -> Preferences -> Get Extensions**
3. Click the **Repositories** dropdown at the top -> **+** -> **Add Remote Repository**
4. **URL**:

   ```
   https://animation-lab.github.io/ProteinBlender/extensions/alpha/index.json
   ```

5. (Recommended) Enable **Check for Updates on Start** so you're notified when a
   new alpha is published.
6. Click **OK**.

## Switch to the Alpha Build

1. In **Get Extensions**, first **disable** the release **ProteinBlender**
   (untick it), or uninstall it.
2. Select the alpha repository in the dropdown (it may show as
   *animation-lab.github.io*).
3. Find **ProteinBlender (Alpha)** and click **Install**.
4. **Restart Blender.**

## Switch Back to the Release Build

1. **Disable** or uninstall **ProteinBlender (Alpha)**.
2. Re-enable the release **ProteinBlender**.
3. **Restart Blender.**

## Updating Safely

Blender replaces the whole extension folder during an update, and a crash in the middle of that can leave the alpha half-installed.

1. Save your work, then restart Blender and open an empty scene (**File -> New -> General**).
2. Go to **Edit -> Preferences -> Get Extensions** and click **Update** next to **ProteinBlender (Alpha)**.
3. Wait for the update to finish, then **restart Blender**.

## If the Alpha Disappears or Will Not Update

**"Remote data unavailable, sync with the remote repository"**, or **Check for Updates** does nothing:
Blender crashed during an earlier update and left the repository locked.
The lock is kept with your Blender settings, so reinstalling Blender does not clear it.

1. Go to **Edit -> Preferences -> Get Extensions**.
2. Open the **Repositories** dropdown at the top right and select the alpha repository (it may show as *animation-lab.github.io*).
3. Click the small down-arrow to the right of the repository list and choose **Force Unlock Repository...**.
4. Click **Check for Updates**, then install **ProteinBlender (Alpha)** again and **restart Blender**.

**The alpha vanished after an update**:
the update failed partway and Blender removed the half-installed copy.
Install **ProteinBlender (Alpha)** again from the alpha repository (keep the release **ProteinBlender** disabled) and restart Blender.

**The ProteinBlender tab says "ProteinBlender could not load"**:
one of the Python packages it needs is broken.
Click **Retry Install** in that tab and restart Blender.
If that does not fix it, reinstall the alpha as above.

**Something else, or the Add-ons list is empty**:
open **Window -> Toggle System Console**, reproduce the problem, and send us a screenshot of the console text.
If Blender crashed, it also writes a `.crash.txt` file to your Temp folder (type `%TEMP%` into the File Explorer address bar); please send that too.

## Reporting Issues

When you report a bug, please include the alpha **version number**
(shown under the extension name in *Get Extensions*), your **Blender version**,
and your **operating system**.

---

## For Maintainers - Publishing an Alpha

The alpha channel is a "swap" build of the same codebase with a different
extension `id`. To publish one:

1. Check out the branch you want testers to try.
2. Build the alpha zips (temporarily rewrites the manifest to
   `id = "proteinblender_alpha"`, then restores the working tree):

   ```bash
   python build.py --alpha
   ```

3. Create a GitHub **Release** and attach the `dist/proteinblender_alpha-*.zip`
   files. Tick **"Set as a pre-release"** to keep alphas visually separated from
   production releases.
4. The publish workflow regenerates the indexes and routes entries by `id`:
   - release builds -> `extensions/index.json`
   - alpha builds -> `extensions/alpha/index.json`

   Testers on the alpha repo URL only ever see the alpha builds, and vice versa.
