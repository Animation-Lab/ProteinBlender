"""Run the test suite against EVERY installed Blender, with one summary.

Discovers all Blender executables (all versions), then runs the offline suite
in each - and, with ``--ui``, the foreground event-loop UI suite too. Prints a
per-version PASS/FAIL table and exits non-zero if any version failed.

Examples::

    python tests/run_all_versions.py                 # offline suite, every Blender
    python tests/run_all_versions.py --ui             # + foreground UI suite
    python tests/run_all_versions.py --bootstrap      # install pytest/deps first
    python tests/run_all_versions.py --only 5.1 5.2   # just these versions
    python tests/run_all_versions.py -k pivot -x      # extra pytest args pass through

Each version's dependencies must be present in that Blender's Python. Use
``--bootstrap`` to install pytest+syrupy (and the scientific deps) into each
Blender once, or the machine-specific ``dev/install_deps.sh <version>`` for the
manifest-pinned set. A version whose deps are broken fails fast with a clear
message (see the preflight in run_blender.py), it does not hang the run.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
RUN_TESTS = TESTS_DIR / "run_tests.py"
RUN_UI = TESTS_DIR / "run_ui_tests.py"
BOOTSTRAP = TESTS_DIR / "ci" / "bootstrap_pytest.py"

_SUMMARY_RE = re.compile(r"(\d+ (?:passed|failed|error)[^\n]*)")
_VERSION_RE = re.compile(r"[Bb]lender[ /\\]+(\d+\.\d+)")


def discover_blenders():
    """Return [(label, Path)] for every installed Blender, newest last."""
    found = {}  # resolved path -> label
    roots = [
        # Native Windows.
        Path(r"C:/Program Files/Blender Foundation"),
        Path(r"C:/Program Files (x86)/Blender Foundation"),
        # WSL driving Windows Blender (this repo's primary dev setup).
        Path("/mnt/c/Program Files/Blender Foundation"),
        Path("/mnt/c/Program Files (x86)/Blender Foundation"),
        # Linux install roots.
        Path("/opt"),
        Path.home() / "blender",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            exe = next((c for c in (sub / "blender.exe", sub / "blender",
                                    sub / "bin" / "blender") if c.is_file()), None)
            if exe is not None:
                m = _VERSION_RE.search(sub.name)
                found[str(exe)] = m.group(1) if m else sub.name
    # POSIX / PATH fallback.
    if not found:
        import shutil
        exe = shutil.which("blender")
        if exe:
            found[exe] = "system"
    pairs = [(label, Path(p)) for p, label in found.items()]
    pairs.sort(key=lambda t: [int(x) for x in t[0].split(".")] if t[0][0].isdigit() else [999])
    return pairs


def _bootstrap(exe):
    print(f"  [bootstrap] installing pytest + deps into Blender {exe} ...", flush=True)
    cmd = [str(exe), "--background", "--factory-startup",
           "--python-exit-code", "12", "--python", str(BOOTSTRAP)]
    return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode == 0


def _run(label, script, exe, passthrough):
    header = f"===== Blender {label}: {script.name} ====="
    print("\n" + header, flush=True)
    cmd = [sys.executable, str(script), "--blender", str(exe), *passthrough]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(proc.stdout, flush=True)
    summaries = _SUMMARY_RE.findall(proc.stdout)
    summary = summaries[-1].rstrip(" =") if summaries else (
        "ok" if proc.returncode == 0 else f"exit {proc.returncode}")
    return proc.returncode == 0, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="store_true",
                        help="also run the foreground event-loop UI suite")
    parser.add_argument("--bootstrap", action="store_true",
                        help="install pytest/syrupy + deps into each Blender first")
    parser.add_argument("--only", nargs="+", metavar="VER",
                        help="limit to these versions, e.g. --only 5.1 5.2")
    parser.add_argument("--offline-args", default='-m "not network"',
                        help='pytest args for the offline suite '
                             '(default: -m "not network")')
    args, passthrough = parser.parse_known_args()

    blenders = discover_blenders()
    if args.only:
        wanted = set(args.only)
        blenders = [(lbl, p) for lbl, p in blenders if lbl in wanted]
    if not blenders:
        raise SystemExit("No Blender installs found (looked under "
                         "C:/Program Files/Blender Foundation and $PATH).")

    print("Testing these Blenders: " + ", ".join(lbl for lbl, _ in blenders))

    # The offline default lives in --offline-args so it can be overridden; split
    # it the shell way but keep it simple (no quotes-in-values needed here).
    import shlex
    offline_args = shlex.split(args.offline_args) + passthrough

    results = []  # (label, suite, ok, summary)
    for label, exe in blenders:
        if args.bootstrap:
            _bootstrap(exe)
        ok, summary = _run(label, RUN_TESTS, exe, offline_args)
        results.append((label, "offline", ok, summary))
        if args.ui:
            ok_ui, summary_ui = _run(label, RUN_UI, exe, [])
            results.append((label, "ui", ok_ui, summary_ui))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    width = max(len(lbl) for lbl, *_ in results)
    all_ok = True
    for label, suite, ok, summary in results:
        mark = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"  Blender {label:<{width}}  {suite:<8}  {mark}  {summary}")
    print("=" * 60)
    if not all_ok:
        print("Some versions FAILED.")
        sys.exit(1)
    print("All versions passed.")


if __name__ == "__main__":
    main()
