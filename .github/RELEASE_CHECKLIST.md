# Release Checklist

Quick reference for creating a new ProteinBlender release.

## Pre-Release

- [ ] All changes committed and pushed
- [ ] Code tested in Blender
- [ ] Version number decided (following semantic versioning)

## Build & Version

```bash
python build.py
```

- [ ] Enter new version number when prompted (e.g., `0.1.3`)
- [ ] Verify all three version files updated:
  - [ ] `proteinblender/blender_manifest.toml`
  - [ ] `pyproject.toml`
  - [ ] `proteinblender/__init__.py` (bl_info)
- [ ] Check `dist/` folder has `.zip` files for all platforms

## Test Locally (Optional but Recommended)

```bash
python generate_local_repo.py
```

- [ ] Add local repository to Blender using file:/// URL
- [ ] Install and test the extension
- [ ] Verify all features work

## Create Git Tag

```bash
git add .
git commit -m "Release v0.1.3"
git tag v0.1.3
git push origin main
git push origin v0.1.3
```

## Create GitHub Release

1. [ ] Go to https://github.com/[username]/proteinblender/releases/new
2. [ ] Tag: `v0.1.3` (must match version from build)
3. [ ] Release title: `ProteinBlender v0.1.3`
4. [ ] Description: Add changelog and notable changes
5. [ ] Upload all `.zip` files from `dist/` folder
6. [ ] Click "Publish release"

## Verify Automation

- [ ] Go to Actions tab
- [ ] Verify "Publish Blender Extension" workflow started
- [ ] Wait for green checkmark (workflow completed)
- [ ] Check `gh-pages` branch has updated `index.json`
- [ ] Test repository URL in browser shows valid JSON

## Test in Blender

- [ ] Open Blender 4.2+
- [ ] Refresh extension repository
- [ ] Verify new version appears
- [ ] Test installation
- [ ] Test update from previous version (if applicable)

## Announce

- [ ] Update documentation if needed
- [ ] Announce on relevant channels
- [ ] Update website/social media if applicable

## Post-Release

- [ ] Monitor for issues
- [ ] Respond to user feedback
- [ ] Plan next release based on feedback

---

## Version Numbering Guide

Use semantic versioning: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes (e.g., 1.0.0 → 2.0.0)
- **MINOR**: New features, backwards compatible (e.g., 0.1.0 → 0.2.0)
- **PATCH**: Bug fixes, backwards compatible (e.g., 0.1.0 → 0.1.1)

Examples:
- `0.1.2` → `0.1.3`: Bug fix
- `0.1.3` → `0.2.0`: New feature added
- `0.9.0` → `1.0.0`: First stable release

## Troubleshooting

### Build fails

```bash
# Check Blender path
echo $BLENDER_PATH  # Unix
echo %BLENDER_PATH%  # Windows

# Verify Python dependencies
pip install tomlkit
```

### Workflow fails

- Check Actions tab for error logs
- Verify `.zip` files were uploaded to release
- Ensure release tag matches version format

### Extension doesn't appear in Blender

- Verify `index.json` is accessible
- Check Blender version is 4.2+
- Try removing and re-adding repository
- Clear Blender's extension cache

---

**Need help?** See full documentation in [AUTO_UPDATER_IMPLEMENTATION.md](../AUTO_UPDATER_IMPLEMENTATION.md)
