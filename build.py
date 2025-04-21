import glob
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Union
# Try importing Blender API for extension CLI; skip if not running inside Blender
try:
    import bpy
    HAVE_BPY = True
except ImportError:
    HAVE_BPY = False
import shutil  # packaging utilities


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


try:
    import tomlkit
except ModuleNotFoundError:
    run_python("-m pip install tomlkit")
    import tomlkit

TOML_PATH = "./proteinblender/blender_manifest.toml"
WHL_PATH = "./proteinblender/wheels"
PYPROJ_PATH = "./pyproject.toml"


@dataclass
class Platform:
    pypi_suffix: str
    metadata: str


# tags for blender metadata
# platforms = ["windows-x64", "macos-arm64", "linux-x64", "windows-arm64", "macos-x64"]


windows_x64 = Platform(pypi_suffix="win_amd64", metadata="windows-x64")
linux_x64 = Platform(pypi_suffix="manylinux2014_x86_64", metadata="linux-x64")
macos_arm = Platform(pypi_suffix="macosx_12_0_arm64", metadata="macos-arm64")
macos_intel = Platform(pypi_suffix="macosx_10_16_x86_64", metadata="macos-x64")


with open(PYPROJ_PATH, "r") as file:
    pyproj = tomlkit.parse(file.read())
    required_packages = pyproj["project"]["dependencies"]


build_platforms = [
    windows_x64,
    linux_x64,
    macos_arm,
    macos_intel,
]


def remove_whls():
    for whl_file in glob.glob(os.path.join(WHL_PATH, "*.whl")):
        os.remove(whl_file)


def download_whls(
    platforms: Union[Platform, List[Platform]],
    required_packages: List[str] = required_packages,
    python_version="3.11",
    clean: bool = True,
):
    if isinstance(platforms, Platform):
        platforms = [platforms]

    if clean:
        remove_whls()

    for platform in platforms:
        run_python(
            f"-m pip download {' '.join(required_packages)} --dest ./proteinblender/wheels --only-binary=:all: --python-version={python_version} --platform={platform.pypi_suffix}"
        )


def update_toml_whls(platforms):
    # Define the path for wheel files
    wheels_dir = "proteinblender/wheels"
    wheel_files = glob.glob(f"{wheels_dir}/*.whl")
    wheel_files.sort()

    # Packages to remove
    packages_to_remove = {
        "pyarrow",
        "certifi",
        "charset_normalizer",
        "idna",
        "numpy",
        "requests",
        "urllib3",
    }

    # Filter out unwanted wheel files
    to_remove = []
    to_keep = []
    for whl in wheel_files:
        if any(pkg in whl for pkg in packages_to_remove):
            to_remove.append(whl)
        else:
            to_keep.append(whl)

    # Remove the unwanted wheel files from the filesystem
    for whl in to_remove:
        os.remove(whl)

    # Load the TOML file
    with open(TOML_PATH, "r") as file:
        manifest = tomlkit.parse(file.read())

    # Update the wheels list with the remaining wheel files
    manifest["wheels"] = [f"./wheels/{os.path.basename(whl)}" for whl in to_keep]

    # Simplify platform handling
    if not isinstance(platforms, list):
        platforms = [platforms]
    manifest["platforms"] = [p.metadata for p in platforms]

    # Write the updated TOML file
    with open(TOML_PATH, "w") as file:
        file.write(
            tomlkit.dumps(manifest)
            .replace('["', '[\n\t"')
            .replace("\\\\", "/")
            .replace('", "', '",\n\t"')
            .replace('"]', '",\n]')
        )


def clean_files(suffix: str = ".blend1") -> None:
    pattern_to_remove = f"proteinblender/**/*{suffix}"
    for blend1_file in glob.glob(pattern_to_remove, recursive=True):
        os.remove(blend1_file)


def build_extension(split: bool = True) -> None:
    # Clean up any Blender temporary files
    for suffix in [".blend1", ".MNSession"]:
        clean_files(suffix=suffix)

    # If running inside Blender, use CLI extension build for dev workflows
    if HAVE_BPY:
        try:
            cmd = [bpy.app.binary_path, "--command", "extension", "build"]
            if split:
                cmd.append("--split-platforms")
            cmd.extend(["--source-dir", "proteinblender", "--output-dir", "."])
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Blender extension CLI build failed: {e}")

    # Create dist directory for output zip
    dist_dir = os.path.join(os.getcwd(), "dist")
    os.makedirs(dist_dir, exist_ok=True)

    # Determine addon name and version from pyproject.toml
    name = pyproj["project"]["name"]
    version = pyproj["project"]["version"]
    zip_base = f"{name}-{version}"
    zip_path = os.path.join(dist_dir, zip_base)
    # Remove existing zip if present
    if os.path.exists(zip_path + ".zip"):
        os.remove(zip_path + ".zip")

    # Create zip archive of the addon folder for Blender installation
    shutil.make_archive(base_name=zip_path, format="zip", root_dir=".", base_dir=name)
    print(f"Created addon zip at {zip_path}.zip")


def build(platform) -> None:
    download_whls(platform)
    update_toml_whls(platform)
    build_extension()


def main():
    # for platform in build_platforms:
    #     build(platform)
    build(build_platforms)


if __name__ == "__main__":
    main()