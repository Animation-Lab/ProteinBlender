# GitHub Pages Setup for Extension Repository

This guide explains how to enable GitHub Pages to host the ProteinBlender extension repository.

## Prerequisites

- Repository admin access
- At least one release with a `.zip` extension file

## Setup Steps

### 1. Enable GitHub Pages

1. Go to the repository on GitHub
2. Click `Settings` (top navigation)
3. Scroll down to `Pages` in the left sidebar
4. Under `Source`, select:
   - **Branch**: `gh-pages`
   - **Folder**: `/ (root)`
5. Click `Save`

### 2. Trigger the First Workflow Run

The workflow runs automatically when releases are published, but you can trigger it manually:

1. Go to `Actions` tab
2. Select `Publish Blender Extension` workflow
3. Click `Run workflow` → `Run workflow`
4. Wait for the workflow to complete (green checkmark)

### 3. Verify GitHub Pages Deployment

1. Go back to `Settings` → `Pages`
2. You should see: "Your site is live at `https://<username>.github.io/<repo>/`"
3. Click the link to verify the page loads
4. Test the index.json URL: `https://<username>.github.io/<repo>/index.json`

### 4. Update Documentation with Final URL

Once the repository is transferred to the organization:

1. Note the final URL (will be something like `https://proteinblender.github.io/extensions/index.json`)
2. Update placeholder URLs in:
   - [`EXTENSION_REPOSITORY.md`](../EXTENSION_REPOSITORY.md)
   - [`.github/gh-pages-readme.md`](./gh-pages-readme.md)
   - Main `README.md` (if applicable)

Replace all instances of `PLACEHOLDER_URL_HERE` with the actual URL.

### 5. Test in Blender

1. Open Blender 4.2+
2. Go to `Edit` → `Preferences` → `Get Extensions` → `Repositories`
3. Add a new remote repository with your URL
4. Verify that ProteinBlender appears in the extensions list
5. Test installation

## Workflow Behavior

The GitHub Actions workflow (`publish-extension.yml`) automatically:

- **Triggers**: When a new release is published or manually dispatched
- **Downloads**: All `.zip` files from all releases
- **Generates**: `index.json` using Blender's built-in command
- **Deploys**: To `gh-pages` branch for GitHub Pages hosting

## Custom Domain (Optional)

If you want to use a custom domain like `extensions.proteinblender.org`:

### Prerequisites

- A registered domain
- DNS access

### Steps

1. In your DNS provider, add a CNAME record:
   - **Name**: `extensions` (or your preferred subdomain)
   - **Value**: `<username>.github.io`
   - **TTL**: 3600 (or default)

2. In GitHub repository settings → Pages:
   - Enter your custom domain: `extensions.proteinblender.org`
   - Enable "Enforce HTTPS" (recommended, may take a few minutes)

3. Wait for DNS propagation (5 minutes to 48 hours, usually ~30 minutes)

4. Test: `https://extensions.proteinblender.org/index.json`

5. Update all documentation with the new URL

## Troubleshooting

### Workflow fails with "No zips for <tag>"

This is normal if a release doesn't have `.zip` files. The workflow continues processing other releases.

### index.json not generated

Check the workflow logs:
1. Go to `Actions` tab
2. Click on the failed run
3. Expand the "Generate extension repository index" step
4. Look for error messages

Common issues:
- Blender download failed (network issue)
- No `.zip` files found (check release assets)
- Permission denied (check GitHub token permissions)

### GitHub Pages shows 404

1. Verify the `gh-pages` branch exists and has files
2. Check Settings → Pages shows the branch is deployed
3. Wait a few minutes for GitHub's CDN to update
4. Try clearing browser cache

### Extension repository can't be accessed in Blender

1. Test the URL in a web browser - should download/show index.json
2. Check for CORS issues (GitHub Pages handles this correctly by default)
3. Verify you're using Blender 4.2+
4. Try removing and re-adding the repository in Blender

## Maintenance

### When creating a new release

1. Build the extension: `python build.py`
2. Create a GitHub release with version tag (e.g., `v0.1.3`)
3. Upload the generated `.zip` files from `dist/` folder
4. Publish the release
5. GitHub Actions automatically updates the repository index
6. Users with auto-update enabled will be notified

### Updating the URL after repository transfer

1. Transfer repository to organization
2. Note new GitHub Pages URL
3. Update placeholder URLs in all documentation files
4. Commit and push changes
5. Announce the URL change to users (they'll need to update once)

## Security Notes

- The workflow uses `GITHUB_TOKEN` which is automatically provided
- No manual secrets configuration needed
- GitHub Pages content is public (appropriate for extension distribution)
- The `gh-pages` branch is auto-generated and force-updated each run

## Next Steps

After setup is complete:

1. ✅ Create your first release with extension `.zip` files
2. ✅ Manually run the workflow or wait for it to trigger
3. ✅ Verify GitHub Pages is serving `index.json`
4. ✅ Test adding the repository in Blender
5. ✅ Update documentation with final URL
6. ✅ Announce the repository to users

---

*For questions or issues, see the main [EXTENSION_REPOSITORY.md](../EXTENSION_REPOSITORY.md) documentation.*
