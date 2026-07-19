"""Launch the foreground, event-loop-driven Blender UI regression suite."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "ui" / "run_ui_scenarios.py"


def _for_blender(path, blender):
    value = str(path)
    if os.name == "posix" and str(blender).lower().endswith(".exe"):
        converter = shutil.which("wslpath")
        if converter:
            return subprocess.check_output([converter, "-w", value], text=True).strip()
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default=os.environ.get("BLENDER_PATH", "blender"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--keep-report", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pb-ui-") as tmp:
        report = Path(tmp) / "ui-report.json"
        command = [
            args.blender,
            "--factory-startup",
            "--no-window-focus",
            "--enable-event-simulate",
            "--python-exit-code", "23",
            "--python", _for_blender(DRIVER, args.blender),
            "--", _for_blender(ROOT, args.blender), _for_blender(report, args.blender),
        ]
        print("[ui]", " ".join(command), flush=True)
        proc = subprocess.run(command, cwd=ROOT, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=args.timeout)
        print(proc.stdout)
        if proc.returncode:
            raise SystemExit(proc.returncode)
        if not report.exists():
            raise SystemExit("UI Blender exited without producing a report")
        report_text = report.read_text(encoding="utf-8")
        print(report_text)
        report_data = json.loads(report_text)
        if report_data.get("ok") is not True:
            raise SystemExit("one or more foreground UI scenarios failed")
        # Blender often prints draw callback failures instead of surfacing them.
        bad = ("Traceback (most recent call last)", "Error: Python:")
        if any(token in proc.stdout for token in bad):
            raise SystemExit("Blender reported a Python/draw exception during UI scenarios")
        if args.keep_report:
            target = ROOT / "ui-test-report.json"
            target.write_text(report_text, encoding="utf-8")
            print(f"[ui] copied report to {target}")


if __name__ == "__main__":
    main()
