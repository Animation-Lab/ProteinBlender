"""Build, validate, install, enable, and smoke-test the shipped extension ZIP.

This runner uses an isolated Blender user directory.  It deliberately never
puts the repository on ``sys.path``: all product imports must resolve from the
installed ``bl_ext.pb_test.proteinblender`` package and its bundled wheels.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "proteinblender"
SMOKE = Path(__file__).with_name("smoke_installed.py")
VERIFY = Path(__file__).with_name("verify_installed_roundtrip.py")


def _windows_path(value):
    converter = shutil.which("wslpath")
    if converter:
        return subprocess.check_output(
            [converter, "-w", str(value)], text=True).strip()
    return str(value)


# Per-step ceiling, well under the workflow's timeout-minutes. A step that blows
# through this is wedged, not slow: the whole lane takes a few minutes end to
# end. Without it a stuck child burns the entire job budget and Actions reports
# "The operation was canceled", which says nothing about what was stuck.
STEP_TIMEOUT_SECONDS = float(os.environ.get("PB_ARTIFACT_STEP_TIMEOUT", "900"))


def run(command, *, env, cwd=ROOT, blender_command=False,
        timeout=None):
    values = [str(x) for x in command]
    run_env = env
    if blender_command and os.name == "posix" and values[0].lower().endswith(".exe"):
        values = [values[0]] + [
            _windows_path(value) if value.startswith("/") else value
            for value in values[1:]
        ]
        run_env = env.copy()
        for key in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS",
                    "BLENDER_USER_DATAFILES", "BLENDER_USER_EXTENSIONS",
                    "PB_ARTIFACT_REPO_ROOT"):
            run_env[key] = _windows_path(run_env[key])
    print("[artifact]", " ".join(values), flush=True)
    started = time.monotonic()
    if timeout is None:
        timeout = STEP_TIMEOUT_SECONDS
    try:
        subprocess.run(values, cwd=cwd, env=run_env, check=True,
                       timeout=timeout if timeout > 0 else None)
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"[artifact] TIMEOUT: no exit after {timeout:.0f}s from:\n"
            f"  {' '.join(values)}\n"
            "The step is wedged. Raise PB_ARTIFACT_STEP_TIMEOUT if the machine is "
            "genuinely this slow; otherwise read the watchdog traceback above.")
    print(f"[artifact] ok in {time.monotonic() - started:.1f}s", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default=os.environ.get("BLENDER_PATH", "blender"))
    parser.add_argument(
        "--prepare-wheels", action="store_true",
        help="resolve the release wheel matrix in a disposable staging copy")
    parser.add_argument("--keep", action="store_true", help="keep isolated user/build directories")
    args = parser.parse_args()

    owner = tempfile.TemporaryDirectory(prefix="pb-artifact-")
    base = Path(owner.name)
    build_dir = base / "dist"
    repo_dir = base / "extensions"
    user_dir = base / "user"
    for path in (build_dir, repo_dir, user_dir):
        path.mkdir(parents=True)

    env = os.environ.copy()
    env.update({
        # Blender exposes individual user-directory overrides; there is no
        # BLENDER_USER_RESOURCES umbrella variable. Isolate every
        # state-bearing location so local add-ons/preferences cannot leak in.
        "BLENDER_USER_CONFIG": str(user_dir / "config"),
        "BLENDER_USER_SCRIPTS": str(user_dir / "scripts"),
        "BLENDER_USER_DATAFILES": str(user_dir / "datafiles"),
        "BLENDER_USER_EXTENSIONS": str(user_dir / "extensions"),
        "PYTHONNOUSERSITE": "1",
        "PB_ARTIFACT_REPO_ROOT": str(ROOT),
    })
    blender = args.blender
    archive = build_dir / "proteinblender.zip"
    source = SOURCE

    if args.prepare_wheels:
        # Exercise the exact resolver used by releases, without prompting for a
        # version. Work in a disposable staging tree so the resolver's cleanup
        # and manifest rewrite never touch a developer's tracked files.
        staging = base / "staging"
        staging.mkdir()
        shutil.copytree(SOURCE, staging / "proteinblender")
        shutil.copy2(ROOT / "pyproject.toml", staging / "pyproject.toml")
        shutil.copy2(ROOT / "build.py", staging / "build.py")
        run([sys.executable, "-c",
             "import build; build.download_whls(build.build_platforms); "
             "build.update_toml_whls(build.build_platforms)"], env=env, cwd=staging)
        source = staging / "proteinblender"

    run([blender, "--command", "extension", "validate", source], env=env,
        blender_command=True)
    run([blender, "--command", "extension", "build",
         "--source-dir", source, "--output-filepath", archive], env=env,
        blender_command=True)
    if not archive.is_file():
        raise SystemExit(f"extension build reported success but did not create {archive}")
    run([blender, "--command", "extension", "validate", archive], env=env,
        blender_command=True)
    run([blender, "--command", "extension", "repo-add", "pb_test",
         "--name", "ProteinBlender Test", "--directory", repo_dir,
         "--clear-all"], env=env, blender_command=True)
    run([blender, "--command", "extension", "install-file", "-r", "pb_test",
         "-e", archive], env=env, blender_command=True)

    blend = base / "installed-roundtrip.blend"
    report = base / "smoke-report.json"
    # Do not use --factory-startup here: it intentionally discards the
    # preference state written by `extension install-file -e`, which would
    # turn this into a false negative for an otherwise enabled artifact.
    # Isolation is already guaranteed by BLENDER_USER_* above.
    run([blender, "--background", "--offline-mode",
         "--python-exit-code", "19", "--python", SMOKE, "--",
         str(ROOT / "tests" / "data" / "1ubq.pdb"), str(blend), str(report)], env=env,
        blender_command=True)
    run([blender, str(blend), "--background", "--offline-mode",
         "--python-exit-code", "20", "--python", VERIFY, "--", str(report)], env=env,
        blender_command=True)

    print(f"[artifact] PASS: installed extension report at {report}")
    if args.keep:
        print(f"[artifact] kept: {base}")
        owner.cleanup = lambda: None


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
