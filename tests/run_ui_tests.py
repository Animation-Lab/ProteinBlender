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
    parser.add_argument("--normal-profile", action="store_true",
                        help="Test the enabled installed add-on in a fresh normal-profile process")
    parser.add_argument("--scenario", choices=('all', 'morphsets', 'morph-states', 'shared-morphs', 'model-morphsets', 'saved-model-morphsets', 'morph-outliner', 'puppet-morphsets', 'thermal-motion'), default='all',
                        help="Run a focused workflow in a fresh Blender process")
    parser.add_argument("--blend", type=Path, help="Open a saved test scene before running UI checks")
    parser.add_argument("--artifact-dir", type=Path,
                        help="Keep the report and screenshots, including failed runs")
    args = parser.parse_args()
    if args.scenario == 'saved-model-morphsets' and not args.blend:
        parser.error('--scenario saved-model-morphsets requires --blend')
    drivers = {name: ROOT / 'tests/ui/run_model_morphset_scenarios.py'
               for name in ('morph-states', 'shared-morphs', 'model-morphsets')}
    drivers['saved-model-morphsets'] = ROOT / 'tests/ui/check_model_morphset_file.py'
    drivers['morph-outliner'] = ROOT / 'tests/ui/run_morph_outliner_scenarios.py'
    drivers['puppet-morphsets'] = ROOT / 'tests/ui/run_puppet_morphset_scenarios.py'
    drivers['thermal-motion'] = ROOT / 'tests/ui/run_thermal_motion_scenarios.py'
    driver = drivers.get(args.scenario, DRIVER)

    with tempfile.TemporaryDirectory(prefix="pb-ui-") as tmp:
        report = Path(tmp) / "ui-report.json"
        command = [
            args.blender,
            *([_for_blender(args.blend.resolve(), args.blender)] if args.blend else []),
            *([] if args.normal_profile else ["--factory-startup"]),
            "--no-window-focus",
            "--enable-event-simulate",
            "--python-exit-code", "23",
            "--python", _for_blender(driver, args.blender),
            "--", _for_blender(ROOT, args.blender), _for_blender(report, args.blender),
            *(["--normal-profile"] if args.normal_profile else []),
            *(['--morphsets-only'] if args.scenario == 'morphsets' else []),
        ]
        print("[ui]", " ".join(command), flush=True)
        # Keep Blender output readable while a scenario is running, and retain
        # it on timeout. A stopped timer otherwise leaves only a timeout error.
        log_path = Path(tmp) / 'blender.log'
        timed_out = None
        try:
            with log_path.open('w', encoding='utf-8') as log:
                proc = subprocess.run(command, cwd=ROOT, text=True,
                                      stdout=log, stderr=subprocess.STDOUT,
                                      timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            timed_out = exc
        output = log_path.read_text(encoding='utf-8', errors='replace')
        print(output)
        if args.artifact_dir:
            args.artifact_dir.mkdir(parents=True, exist_ok=True)
            for path in Path(tmp).iterdir():
                if path.is_file():
                    shutil.copy2(path, args.artifact_dir / path.name)
        if timed_out:
            raise SystemExit(f"Blender UI scenarios timed out after {args.timeout} seconds")
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
        if any(token in output for token in bad):
            raise SystemExit("Blender reported a Python/draw exception during UI scenarios")
        if args.keep_report:
            target = ROOT / "ui-test-report.json"
            target.write_text(report_text, encoding="utf-8")
            print(f"[ui] copied report to {target}")


if __name__ == "__main__":
    main()
