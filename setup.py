import glob
import os
import subprocess
import sys
import platform
from dataclasses import dataclass
from typing import List, Union
from setuptools import setup, find_packages

def run_python(args: str | List[str]):
    python = os.path.realpath(sys.executable)
    if isinstance(args, str):
        args = [python] + args.split(" ")
    elif isinstance(args, list):
        args = [python] + args
    else:
        raise ValueError(
            "Arguments must be a string to split into individual arguments by space"
            "or a list of individual arguments already split"
        )
    subprocess.run(args)

TOML_PATH = "blender_manifest.toml"
WHL_PATH = "./libs"

@dataclass
class Platform:
    pypi_suffix: str
    metadata: str

windows_x64 = Platform(pypi_suffix="win_amd64", metadata="windows-x64")
linux_x64 = Platform(pypi_suffix="manylinux2014_x86_64", metadata="linux-x64")
macos_arm = Platform(pypi_suffix="macosx_12_0_arm64", metadata="macos-arm64")
macos_intel = Platform(pypi_suffix="macosx_10_16_x86_64", metadata="macos-x64")

def get_current_platform():
    # Force Windows platform when running in WSL
    if os.path.exists('/proc/version'):
        with open('/proc/version', 'r') as f:
            if 'Microsoft' in f.read():
                return windows_x64
    
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == 'windows':
        return windows_x64
    elif system == 'linux':
        return linux_x64
    elif system == 'darwin':  # macOS
        if machine == 'arm64':
            return macos_arm
        else:
            return macos_intel
    else:
        raise ValueError(f"Unsupported platform: {system} {machine}")

def download_whls(platform: Platform, python_version="3.11"):
    os.makedirs(WHL_PATH, exist_ok=True)
    
    # Force platform to windows_x64 when in WSL
    if platform == linux_x64 and os.path.exists('/proc/version'):
        with open('/proc/version', 'r') as f:
            if 'Microsoft' in f.read():
                platform = windows_x64
    
    # Download packages for Windows platform when in WSL
    run_python([
        "-m", "pip", "download",
        "--dest", WHL_PATH,
        "--only-binary=:all:",
        f"--python-version={python_version}",
        f"--platform={platform.pypi_suffix}",
        "--no-deps",  # Don't download dependencies to avoid conflicts
        "databpy==0.0.8",
        "MDAnalysis==2.7.0",
        "biotite==0.40",
        "numpy"
    ])

def update_toml_whls(platform: Platform):
    wheel_files = glob.glob(f"{WHL_PATH}/*.whl")
    wheel_files.sort()

    try:
        import tomlkit
    except ModuleNotFoundError:
        run_python("-m pip install tomlkit")
        import tomlkit

    # Create default manifest if it doesn't exist
    if not os.path.exists(TOML_PATH):
        manifest = tomlkit.document()
        manifest["schema_version"] = "1.0.0"
        manifest["id"] = "ProteinBlender"
        manifest["version"] = "0.1.0"
        manifest["name"] = "ProteinBlender"
        manifest["tagline"] = "Visualize proteins in Blender"
        manifest["maintainer"] = "Dillon Lee <dlee123@gmail.com>"
        manifest["type"] = "add-on"
        manifest["website"] = "https://github.com/dillonlee/ProteinBlender"
        manifest["tags"] = ["Protein", "Visualization", "Blender"]
        manifest["blender_version_min"] = "4.2.0"
        manifest["license"] = ["SPDX:GPL-3.0-or-later"]
        manifest["copyright"] = ["2025"]
    else:
        with open(TOML_PATH, "r") as file:
            manifest = tomlkit.parse(file.read())

    # Update wheels and force Windows platform
    manifest["wheels"] = [f"./libs/{os.path.basename(whl)}" for whl in wheel_files]
    manifest["platforms"] = ["windows-x64"]  # Force Windows platform

    with open(TOML_PATH, "w") as file:
        file.write(tomlkit.dumps(manifest))

def build(platform: Platform) -> None:
    download_whls(platform)
    update_toml_whls(platform)

if __name__ == "__main__":
    current_platform = get_current_platform()
    
    # Run setup first
    setup(
        name="proteinblender",
        version="0.1.0",
        packages=find_packages(include=[
            'data*',
            'handlers*',
            'layout*',
            'operators*',
            'panels*',
            'properties*',
            'resources*',
            'utils*',
            'visualizer*'
        ]),
        include_package_data=True,
        install_requires=[
            "databpy==0.0.8",
            "MDAnalysis==2.7.0",
            "biotite==0.40",
            "numpy",
        ],
    )
    
    # Then build wheels for current platform only
    build(current_platform)
