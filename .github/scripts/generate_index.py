#!/usr/bin/env python3
"""
Generate Blender extension repository index.json from GitHub Releases.

This script fetches release information from GitHub, downloads each extension zip
to extract metadata from blender_manifest.toml, and generates an index.json file
that references the GitHub Release download URLs directly.

This avoids GitHub's 100MB file size limit for regular commits by keeping
the large zip files in GitHub Releases while only committing the small index.json.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

try:
    import tomli
except ImportError:
    import tomllib as tomli  # Python 3.11+

import requests


REPO_OWNER = "Animation-Lab"
REPO_NAME = "ProteinBlender"
GITHUB_API = "https://api.github.com"

# One published extension repository ("channel") per extension id. Each channel
# gets its own index.json so testers can add the alpha repo URL independently of
# the release repo. Any id not listed here falls back to the release channel so
# an unexpected build is never silently dropped.
#   release -> <site>/extensions/index.json
#   alpha   -> <site>/extensions/alpha/index.json
CHANNELS = {
    "proteinblender": "",
    "proteinblender_alpha": "alpha",
}
DEFAULT_CHANNEL_SUBDIR = ""

# Base directory the index files are written under. In CI this is set to the
# Pages output dir (e.g. "_site/extensions"); locally it defaults to ".".
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")


def get_releases():
    """Fetch all releases from GitHub API."""
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    releases = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/releases?per_page=100&page={page}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        releases.extend(data)
        page += 1

    return releases


def download_file(url, dest_path, token=None):
    """Download a file from URL to destination path."""
    headers = {"Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, stream=True, allow_redirects=True)
    response.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def compute_sha256(file_path):
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def extract_manifest(zip_path):
    """Extract and parse blender_manifest.toml from a zip file."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Look for blender_manifest.toml in the zip
        manifest_names = [
            "blender_manifest.toml",
            "proteinblender/blender_manifest.toml",
        ]
        for name in zf.namelist():
            if name.endswith("blender_manifest.toml"):
                with zf.open(name) as f:
                    return tomli.load(f)

    raise FileNotFoundError("blender_manifest.toml not found in zip")


def get_platform_from_filename(filename):
    """Extract platform from filename like proteinblender-1.0.0-windows_x64.zip"""
    # Map filename patterns to Blender platform identifiers
    platform_map = {
        "windows_x64": "windows-x64",
        "windows-x64": "windows-x64",
        "linux_x64": "linux-x64",
        "linux-x64": "linux-x64",
        "macos_x64": "macos-x64",
        "macos-x64": "macos-x64",
        "macos_arm64": "macos-arm64",
        "macos-arm64": "macos-arm64",
    }

    filename_lower = filename.lower()
    for pattern, platform in platform_map.items():
        if pattern in filename_lower:
            return platform

    return None  # Unknown platform


def python_versions_from_wheels(wheel_paths):
    """Return the Python versions a set of bundled wheels supports, e.g. ["3.11", "3.13"].

    Mirrors Blender's own derivation (`python_versions_from_wheels` in
    `bl_pkg/cli/blender_ext.py`): take the *union* of the versions named by each
    wheel's Python tag, drop Python 2, and collapse a bare major ("3", from a
    py3-none-any wheel) when a specific minor for that major is also present.

    Blender uses this to decide whether to even offer an extension to the running
    Blender. Emitting it means an incompatible build is filtered out of the
    listing instead of being advertised and then failing at install with
    "This Python version (3.13) isn't compatible with (3.11)".
    """
    major_only = set()
    major_minor = set()

    for path in wheel_paths:
        stem = os.path.basename(path)
        if not stem.endswith(".whl"):
            continue
        # {distribution}-{version}(-{build})?-{python tag}-{abi tag}-{platform tag}
        parts = stem[: -len(".whl")].split("-")
        if len(parts) < 5:
            continue
        python_tag = parts[-3]

        for tag in python_tag.split("."):
            match = re.fullmatch(r"(?:cp|py)(\d)(\d*)", tag)
            if not match:
                continue
            major = int(match.group(1))
            if major <= 2:
                continue  # never useful to advertise Python 2 support
            minor = match.group(2)
            if minor:
                major_minor.add((major, int(minor)))
            else:
                major_only.add((major,))

    # "3" is redundant once "3.11" is known.
    for major, _minor in major_minor:
        major_only.discard((major,))

    return sorted(".".join(str(n) for n in v) for v in (major_only | major_minor))


def build_extension_entry(manifest, archive_url, archive_size, archive_hash, platform):
    """Build a single extension entry for the index.json data array."""
    entry = {
        "schema_version": manifest.get("schema_version", "1.0.0"),
        "id": manifest.get("id", ""),
        "name": manifest.get("name", ""),
        "version": manifest.get("version", ""),
        "tagline": manifest.get("tagline", ""),
        "archive_url": archive_url,
        "archive_size": archive_size,
        "archive_hash": f"sha256:{archive_hash}",
        "blender_version_min": manifest.get("blender_version_min", "5.0.0"),
        "type": manifest.get("type", "add-on"),
        "maintainer": manifest.get("maintainer", ""),
        "license": manifest.get("license", []),
        "website": manifest.get("website", ""),
    }

    # Add platform if specific
    if platform:
        entry["platforms"] = [platform]

    # Declare which Python versions the bundled wheels actually support, so
    # Blender filters incompatible builds out of the listing rather than
    # offering an install that cannot succeed.
    python_versions = python_versions_from_wheels(manifest.get("wheels", []))
    if python_versions:
        entry["python_versions"] = python_versions

    # Add optional fields if present
    if "tags" in manifest:
        entry["tags"] = manifest["tags"]
    if "permissions" in manifest:
        entry["permissions"] = manifest["permissions"]
    if "copyright" in manifest:
        entry["copyright"] = manifest["copyright"]

    return entry


def main():
    print("Fetching releases from GitHub...")
    releases = get_releases()
    print(f"Found {len(releases)} releases")

    token = os.environ.get("GITHUB_TOKEN")
    extensions = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for release in releases:
            tag_name = release["tag_name"]
            print(f"\nProcessing release: {tag_name}")

            for asset in release.get("assets", []):
                filename = asset["name"]
                if not filename.endswith(".zip"):
                    continue

                print(f"  Processing asset: {filename}")

                # Download the zip file
                zip_path = Path(tmpdir) / filename
                download_url = asset["browser_download_url"]

                print(f"    Downloading from: {download_url}")
                download_file(asset["url"], zip_path, token)

                # Get file size and hash
                archive_size = zip_path.stat().st_size
                archive_hash = compute_sha256(zip_path)
                print(f"    Size: {archive_size}, SHA256: {archive_hash[:16]}...")

                # Extract manifest
                try:
                    manifest = extract_manifest(zip_path)
                    print(f"    Manifest: {manifest.get('id')} v{manifest.get('version')}")
                except FileNotFoundError as e:
                    print(f"    Warning: {e}, skipping")
                    continue

                # Determine platform from filename
                platform = get_platform_from_filename(filename)
                print(f"    Platform: {platform or 'all'}")

                # Build entry using the browser download URL (direct download, no auth needed)
                entry = build_extension_entry(
                    manifest=manifest,
                    archive_url=download_url,
                    archive_size=archive_size,
                    archive_hash=archive_hash,
                    platform=platform,
                )
                extensions.append(entry)

    # Blender's repository index expects ONE entry per extension id + platform:
    # the single version it should offer. Emitting every past release's zip as
    # its own entry makes Blender's updater resolve to whichever entry lands
    # last in the array - the oldest here - so it offered a downgrade
    # (e.g. installed 1.0.8 -> "update" to 1.0.7). Collapse to the highest
    # version per (id, platform).
    def _version_key(version):
        key = []
        for part in str(version).split("."):
            key.append(int(part) if part.isdigit() else 0)
        return tuple(key)

    best_by_key = {}
    for entry in extensions:
        key = (entry["id"], tuple(entry.get("platforms", [])))
        current = best_by_key.get(key)
        if current is None or _version_key(entry["version"]) > _version_key(current["version"]):
            best_by_key[key] = entry
    extensions = list(best_by_key.values())

    # Group entries into channels by extension id, then write one index.json per
    # channel. Unknown ids fall back to the release channel so nothing is lost.
    channels = {subdir: [] for subdir in set(CHANNELS.values()) | {DEFAULT_CHANNEL_SUBDIR}}
    for entry in extensions:
        subdir = CHANNELS.get(entry["id"], DEFAULT_CHANNEL_SUBDIR)
        if entry["id"] not in CHANNELS:
            print(f"  Note: id '{entry['id']}' has no channel mapping; using release channel")
        channels[subdir].append(entry)

    for subdir, entries in channels.items():
        index = {
            "version": "v1",
            "blocklist": [],
            "data": entries,
        }
        out_dir = Path(OUTPUT_DIR) / subdir if subdir else Path(OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "index.json"
        with open(output_path, "w") as f:
            json.dump(index, f, indent=2)

        label = subdir or "release"
        print(f"\nGenerated {output_path} ({label} channel) with {len(entries)} extensions")
        for ext in entries:
            platform = ext.get("platforms", ["all"])[0] if "platforms" in ext else "all"
            print(f"  - {ext['id']} v{ext['version']} ({platform})")


if __name__ == "__main__":
    main()
