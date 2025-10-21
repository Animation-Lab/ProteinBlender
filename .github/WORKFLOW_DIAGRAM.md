# Auto-Updater Workflow Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DEVELOPER WORKFLOW                           │
└─────────────────────────────────────────────────────────────────────┘

    Developer                Build System              GitHub
    ─────────                ────────────              ──────
        │
        │  python build.py
        ├──────────────────────►  Updates 3 files:
        │                         • blender_manifest.toml (0.1.3)
        │                         • pyproject.toml (0.1.3)
        │                         • __init__.py (0, 1, 3)
        │
        │                         Downloads wheels
        │
        │  dist/*.zip             Builds extension packages
        │◄──────────────────────  • proteinblender-0.1.3-windows-x64.zip
        │                         • proteinblender-0.1.3-linux-x64.zip
        │                         • proteinblender-0.1.3-macos-arm64.zip
        │                         • proteinblender-0.1.3-macos-x64.zip
        │
        │  git tag v0.1.3
        │  git push
        ├──────────────────────►
        │                                │
        │  Create GitHub Release         │
        │  Upload .zip files             │
        ├────────────────────────────────┤
        │                                │
        │                                │  Triggers workflow
        │                                ▼


┌─────────────────────────────────────────────────────────────────────┐
│                      GITHUB ACTIONS WORKFLOW                         │
└─────────────────────────────────────────────────────────────────────┘

        GitHub Actions                  Blender CLI              GitHub Pages
        ──────────────                  ───────────              ────────────
              │
              │  On release published
              ├──────────►  Download all .zip files
              │             from all releases
              │
              │             ┌─ v0.1.1 ─► proteinblender-0.1.1-*.zip
              │             ├─ v0.1.2 ─► proteinblender-0.1.2-*.zip
              │             └─ v0.1.3 ─► proteinblender-0.1.3-*.zip
              │
              │             Setup Blender 4.2
              │
              │  blender --command extension server-generate
              ├─────────────────────►
              │                           Scans .zip files
              │                           Reads manifests
              │
              │  index.json               Generates repository index
              │◄─────────────────────
              │
              │  Deploy to gh-pages
              ├───────────────────────────────────────────────►
              │                                                  │
              │                                                  │
              │                                                  ▼
              │                                       https://[org].github.io/
              │                                       [repo]/index.json


┌─────────────────────────────────────────────────────────────────────┐
│                          USER WORKFLOW                               │
└─────────────────────────────────────────────────────────────────────┘

    User                    Blender                GitHub Pages
    ────                    ───────                ────────────
      │
      │  One-time setup
      │  Add repository URL
      ├──────────────────►  Saves:
      │                     • Name: ProteinBlender
      │                     • URL: https://[...]/index.json
      │                     • Auto-check: enabled
      │
      │  Start Blender
      ├──────────────────►
      │                     Checks for updates
      │                     ├────────────────────────────────►
      │                     │                                 │
      │                     │  GET index.json                 │
      │                     │◄────────────────────────────────┤
      │                     │  {                              │
      │                     │    "version": "0.1.3",          │
      │                     │    "downloads": {...}           │
      │                     │  }                              │
      │                     │
      │                     Compares:
      │                     Installed: 0.1.2
      │                     Available: 0.1.3
      │  Notification
      │  "Update available!"
      │◄──────────────────
      │
      │  Click "Update"
      ├──────────────────►
      │                     Downloads .zip
      │                     ├────────────────────────────────►
      │                     │  GET proteinblender-0.1.3.zip  │
      │                     │◄────────────────────────────────┤
      │                     │
      │                     Extracts files
      │                     Installs extension
      │  "Restart Blender"
      │◄──────────────────
      │
      │  Restart
      ├──────────────────►
      │                     Loads ProteinBlender v0.1.3
      │  Ready to use! ✓
      │◄──────────────────
```

## Data Flow

### Version Information Flow

```
build.py (update_version)
    │
    ├──► blender_manifest.toml ──────┐
    │         version = "0.1.3"      │
    │                                 │
    ├──► pyproject.toml ──────────────┤
    │         version = "0.1.3"      │
    │                                 ├──► Extension .zip
    └──► __init__.py ────────────────┤         package
              version = (0, 1, 3)     │
                                      │
                                      ▼
                              GitHub Release
                                      │
                                      ▼
                              GitHub Actions
                                      │
                                      ▼
                              index.json
                                {
                                  "id": "proteinblender",
                                  "version": "0.1.3",
                                  "blender_version_min": "4.2.0",
                                  ...
                                }
                                      │
                                      ▼
                              GitHub Pages
                                      │
                                      ▼
                              Blender Client
                                      │
                                      ▼
                              User Notification
```

## File Relationships

```
Repository Root
│
├── proteinblender/
│   ├── __init__.py ──────────────────┐ Version synced via build.py
│   └── blender_manifest.toml ────────┤ (all three files updated together)
├── pyproject.toml ───────────────────┘
│
├── build.py ─────────────► Coordinates version updates
│                            Downloads wheels
│                            Builds extensions
│
├── dist/
│   └── *.zip ────────────► Uploaded to GitHub Release
│
├── .github/
│   └── workflows/
│       └── publish-extension.yml ───► Triggers on release
│                                       Generates index.json
│                                       Deploys to gh-pages
│
└── extensions/ (local testing only)
    ├── *.zip
    └── index.json ───────────────────► Generated for local testing
```

## Update Check Flow

```
┌──────────────────────────────────────────────────────────────┐
│ Blender Startup (with "Check for Updates on Start" enabled) │
└──────────────────────────────────────────────────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ For each repository:  │
            │ GET [repo-url]/       │
            │     index.json        │
            └───────────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ Parse JSON:           │
            │ - Available versions  │
            │ - Blender compat      │
            │ - Download URLs       │
            └───────────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ Compare versions:     │
            │ Installed vs Available│
            └───────────────────────┘
                        │
            ┌───────────┴────────────┐
            │                        │
         No │                        │ Yes
    ┌───────▼──────┐      ┌─────────▼──────────┐
    │ No action    │      │ Show notification: │
    │              │      │ "Update available" │
    └──────────────┘      └────────────────────┘
                                     │
                          User clicks "Update"
                                     │
                                     ▼
                          ┌──────────────────┐
                          │ Download new .zip│
                          │ Extract files    │
                          │ Replace addon    │
                          │ Prompt restart   │
                          └──────────────────┘
```

## Component Interaction Matrix

```
┌────────────┬───────────┬──────────┬────────────┬──────────────┐
│ Component  │ build.py  │ workflow │ index.json │ Blender      │
├────────────┼───────────┼──────────┼────────────┼──────────────┤
│ Version    │ Updates   │ Reads    │ Contains   │ Compares     │
│ files      │           │          │            │              │
├────────────┼───────────┼──────────┼────────────┼──────────────┤
│ .zip files │ Creates   │ Collects │ References │ Downloads    │
│            │           │          │            │              │
├────────────┼───────────┼──────────┼────────────┼──────────────┤
│ index.json │ -         │ Generates│ -          │ Fetches      │
│            │           │          │            │              │
├────────────┼───────────┼──────────┼────────────┼──────────────┤
│ GitHub     │ -         │ Reads    │ Links to   │ Downloads    │
│ Releases   │           │          │            │ from         │
└────────────┴───────────┴──────────┴────────────┴──────────────┘
```

## Timeline: From Code to User

```
T+0 min    Developer runs: python build.py
           ├─ Version updated in 3 files
           └─ Extension built to dist/

T+5 min    Developer creates GitHub release
           └─ Uploads .zip files

T+5 min    GitHub Actions workflow triggers
           ├─ Downloads all release .zips
           ├─ Generates index.json
           └─ Deploys to gh-pages

T+10 min   GitHub Pages live
           └─ index.json accessible at URL

T+10 min   User opens Blender
  +10 sec  ├─ Auto-check runs
           ├─ Finds new version
           └─ Shows notification

T+11 min   User clicks "Update"
  +30 sec  ├─ Downloads .zip
           ├─ Installs extension
           └─ Prompts restart

T+12 min   User restarts Blender
           └─ New version active ✓
```

---

This workflow ensures users receive updates within **minutes** of a release being published, with zero manual intervention required after the initial repository setup.
