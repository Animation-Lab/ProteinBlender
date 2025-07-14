'''
Shamelessly stolen from https://github.com/molecularnodes/molecularnodes/blob/main/build.py

This script is used to build the ProteinBlender extension for Blender.

It is used to download the necessary wheels for the extension, and then build the extension.

It is used to update the blender manifest.toml file with the necessary wheels for the extension.

'''

import glob
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Union


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

TOML_PATH = "proteinblender/blender_manifest.toml"
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


def get_blender_path():
    blender_path = os.environ.get("BLENDER_PATH")
    if not blender_path:
        raise RuntimeError(
            "The BLENDER_PATH environment variable must be set to the path for blender.exe. "
            "Please set BLENDER_PATH and try again."
        )
    return blender_path


def build_extension(split: bool = True) -> None:
    for suffix in [".blend1", ".MNSession"]:
        clean_files(suffix=suffix)

    blender_path = get_blender_path()
    if split:
        command = [
            blender_path,
            "--command", "extension", "build",
            "--split-platforms",
            "--source-dir", "proteinblender",
            "--output-dir", "."
        ]
    else:
        command = [
            blender_path,
            "--command", "extension", "build",
            "--source-dir", "proteinblender",
            "--output-dir", "."
        ]
    print(f"Running command: {command}")
    subprocess.run(command)


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