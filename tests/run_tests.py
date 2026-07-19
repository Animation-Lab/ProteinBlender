"""One-command test runner (system Python).

Finds a Blender executable, then launches the suite headless inside it. All
extra CLI args are forwarded to pytest.

Examples::

    python tests/run_tests.py                     # whole suite
    python tests/run_tests.py -v                   # verbose
    python tests/run_tests.py tests/unit           # just the unit lane
    python tests/run_tests.py -m "not network"     # skip network tests
    python tests/run_tests.py -k domain            # by keyword
    python tests/run_tests.py --blender "C:/.../Blender 5.1/blender.exe"

Blender discovery order:
  1. --blender <path> argument (consumed, not forwarded to pytest)
  2. $BLENDER_PATH environment variable
  3. Common install locations (newest version first)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
RUN_BLENDER = TESTS_DIR / "run_blender.py"


def _for_blender(path, blender):
    """Translate WSL paths when the selected host is Windows Blender."""
    value = str(path)
    if os.name == "posix" and str(blender).lower().endswith(".exe") and shutil.which("wslpath"):
        return subprocess.check_output(["wslpath", "-w", value], text=True).strip()
    return value


def _candidate_blenders():
    seen = []
    env = os.environ.get("BLENDER_PATH")
    if env:
        seen.append(Path(env))
    # Windows default install roots
    roots = [
        Path(r"C:/Program Files/Blender Foundation"),
        Path(r"C:/Program Files (x86)/Blender Foundation"),
    ]
    for root in roots:
        if root.is_dir():
            for sub in sorted(root.iterdir(), reverse=True):  # newest first
                exe = sub / "blender.exe"
                if exe.exists():
                    seen.append(exe)
    # POSIX fallbacks
    for name in ("blender",):
        seen.append(Path(name))
    return seen


def find_blender(explicit=None):
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        resolved = shutil.which(explicit)
        if resolved:
            return Path(resolved)
        raise SystemExit(f"--blender path does not exist: {explicit}")
    for cand in _candidate_blenders():
        try:
            if cand.exists():
                return cand
            if cand.name == "blender":
                resolved = shutil.which(str(cand))
                if resolved:
                    return Path(resolved)
        except Exception:
            continue
    raise SystemExit(
        "Could not find Blender. Set $BLENDER_PATH or pass --blender <path>.")


def main():
    argv = sys.argv[1:]
    explicit = None
    if "--blender" in argv:
        i = argv.index("--blender")
        explicit = argv[i + 1]
        del argv[i:i + 2]

    blender = find_blender(explicit)
    pytest_args = argv or ["tests"]

    cmd = [
        str(blender),
        "--background",
        "--factory-startup",
        "--python-exit-code", "17",
        "--python", _for_blender(RUN_BLENDER, blender),
        "--",
        *pytest_args,
    ]
    print(f"[run_tests] blender: {blender}")
    print(f"[run_tests] pytest : {pytest_args}")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
