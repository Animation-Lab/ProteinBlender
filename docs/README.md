# ProteinBlender Documentation Site

This directory contains the GitHub Pages documentation site for ProteinBlender.

## Setup

To enable GitHub Pages:

1. Push this repository to GitHub
2. Go to repository Settings -> Pages
3. Under "Build and deployment":
   - Source: Deploy from a branch
   - Branch: main (or master)
   - Folder: /docs
4. Click Save

GitHub Pages will automatically build and deploy the site.

## Viewing the Site

**GitHub Pages will automatically build and host the site** when you push to GitHub.

No local preview setup is needed - the documentation is ready to deploy!

After pushing to GitHub and enabling GitHub Pages (see Setup section above), the site will be live at:
- `https://[your-org].github.io/proteinblender/`

### Local Preview (Optional, Advanced)

Local preview requires Ruby development tools (C compiler, make, etc.).

If you want to preview locally, you'll need to install:
- **Windows**: Install MSYS2 and ridk install (via RubyInstaller with DevKit)
- **Mac**: Install Xcode command line tools: `xcode-select --install`
- **Linux**: Install build tools: `sudo apt-get install ruby-dev build-essential`

Then run `bundle install` and `bundle exec jekyll serve`.

**For most users, we recommend using the live GitHub Pages site instead of local preview.**

## Updating After Repository Transfer

After transferring to the organization, update:

1. `_config.yml` - Change `url:` to new organization URL
2. All `.md` files - Replace `ORGNAME` with actual organization name

You can do this with find/replace:
- Find: `ORGNAME`
- Replace: `your-org-name`

## Pages

- `index.md` - Home page
- `installation.md` - Installation guide  
- `import.md` - Import proteins guide
- `visuals.md` - Visual customization guide
- `puppets.md` - Protein puppets guide
- `poses.md` - Pose management guide
- `keyframes.md` - Animation guide

## Theme

Uses the Cayman theme. To change, edit `theme:` in `_config.yml`.

Available themes: https://pages.github.com/themes/
