#!/usr/bin/env python3
"""
Generate a local extension repository for testing.

This script creates a local extension repository that can be tested in Blender
before publishing to GitHub Pages.

Usage:
    python generate_local_repo.py

Then in Blender:
    1. Go to Preferences → Get Extensions → Repositories
    2. Add Remote Repository
    3. Use: file:///path/to/ProteinBlender/extensions/index.json
       (On Windows: file:///C:/path/to/ProteinBlender/extensions/index.json)
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).parent
DIST_DIR = REPO_ROOT / "dist"
EXTENSIONS_DIR = REPO_ROOT / "extensions"
INDEX_FILE = EXTENSIONS_DIR / "index.json"


def get_blender_path():
    """Get Blender executable path from environment or prompt user."""
    blender_path = os.environ.get("BLENDER_PATH")

    if not blender_path:
        print("\n⚠️  BLENDER_PATH environment variable not set.")
        print("\nPlease enter the full path to your Blender executable:")
        print("  Windows: C:\\Program Files\\Blender Foundation\\Blender 4.2\\blender.exe")
        print("  macOS: /Applications/Blender.app/Contents/MacOS/Blender")
        print("  Linux: /usr/bin/blender")
        blender_path = input("\nBlender path: ").strip().strip('"').strip("'")

    if not os.path.exists(blender_path):
        print(f"\n❌ Blender not found at: {blender_path}")
        print("Please set BLENDER_PATH environment variable or provide a valid path.")
        sys.exit(1)

    return blender_path


def main():
    print("=" * 60)
    print("ProteinBlender Local Extension Repository Generator")
    print("=" * 60)

    # Check if dist directory exists and has .zip files
    if not DIST_DIR.exists():
        print(f"\n❌ dist/ directory not found: {DIST_DIR}")
        print("\nPlease build the extension first:")
        print("  python build.py")
        sys.exit(1)

    zip_files = list(DIST_DIR.glob("*.zip"))
    if not zip_files:
        print(f"\n❌ No .zip files found in: {DIST_DIR}")
        print("\nPlease build the extension first:")
        print("  python build.py")
        sys.exit(1)

    print(f"\n✓ Found {len(zip_files)} extension file(s) in dist/")
    for zf in zip_files:
        print(f"  - {zf.name}")

    # Create extensions directory
    print(f"\n📁 Creating extensions directory...")
    EXTENSIONS_DIR.mkdir(exist_ok=True)

    # Copy .zip files
    print(f"\n📦 Copying extension files...")
    for zip_file in zip_files:
        dest = EXTENSIONS_DIR / zip_file.name
        shutil.copy2(zip_file, dest)
        print(f"  ✓ {zip_file.name}")

    # Get Blender path
    blender_path = get_blender_path()
    print(f"\n🎨 Using Blender: {blender_path}")

    # Generate index.json using Blender
    print(f"\n🔧 Generating index.json...")
    cmd = [
        blender_path,
        "--background",
        "--command", "extension", "server-generate",
        f"--repo-dir={EXTENSIONS_DIR}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if INDEX_FILE.exists():
            print(f"✓ index.json generated successfully!")
        else:
            print(f"\n❌ Failed to generate index.json")
            print("\nBlender output:")
            print(result.stdout)
            if result.stderr:
                print("\nErrors:")
                print(result.stderr)
            sys.exit(1)

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Blender command failed!")
        print(f"\nCommand: {' '.join(cmd)}")
        print(f"\nOutput: {e.stdout}")
        print(f"\nError: {e.stderr}")
        sys.exit(1)

    # Show success message with instructions
    print("\n" + "=" * 60)
    print("✅ Local repository generated successfully!")
    print("=" * 60)

    # Platform-specific URL format
    abs_index_path = INDEX_FILE.absolute()
    if sys.platform == "win32":
        # Windows file:/// URL
        file_url = f"file:///{abs_index_path}".replace("\\", "/")
    else:
        # Unix file:/// URL
        file_url = f"file://{abs_index_path}"

    print(f"\n📍 Repository URL:")
    print(f"   {file_url}")

    print(f"\n📖 To test in Blender 4.2+:")
    print(f"   1. Open Blender")
    print(f"   2. Edit → Preferences → Get Extensions")
    print(f"   3. Click 'Repositories' dropdown → '+' → 'Add Remote Repository'")
    print(f"   4. Name: ProteinBlender (Local)")
    print(f"   5. URL: {file_url}")
    print(f"   6. Click OK")
    print(f"   7. Select the new repository and install ProteinBlender")

    print(f"\n💡 Tip: Enable 'Check for Updates on Start' to test update notifications")
    print(f"   when you rebuild with a new version number.\n")


if __name__ == "__main__":
    main()
