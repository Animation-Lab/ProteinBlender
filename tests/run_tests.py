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
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
RUN_BLENDER = TESTS_DIR / "run_blender.py"


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
        raise SystemExit(f"--blender path does not exist: {explicit}")
    for cand in _candidate_blenders():
        try:
            if cand.exists() or cand.name == "blender":
                return cand
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
        "--python", str(RUN_BLENDER),
        "--",
        *pytest_args,
    ]
    print(f"[run_tests] blender: {blender}")
    print(f"[run_tests] pytest : {pytest_args}")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
