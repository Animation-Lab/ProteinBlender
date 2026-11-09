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


def private_temp_env(run_dir, blender):
    """The environment that gives Blender ``run_dir/blender-temp`` as its temp.

    A windowed Blender saves quit.blend (File > Recover > Last Session) and
    autosaves into its temp directory, which is the system Temp under
    --factory-startup. Each UI run gets its own, or every run overwrites the
    developer's real session-recovery file.
    """
    blender_temp = Path(run_dir) / 'blender-temp'
    blender_temp.mkdir(exist_ok=True)
    env = dict(os.environ)
    env['TEMP'] = env['TMP'] = _for_blender(blender_temp, blender)
    env['TMPDIR'] = str(blender_temp)
    if os.name == "posix" and str(blender).lower().endswith(".exe"):
        # A Windows exe launched from WSL only sees the variables WSLENV names.
        env['WSLENV'] = ':'.join(filter(None, (os.environ.get('WSLENV', ''), 'TEMP', 'TMP')))
    return env


def _inside(path, folder):
    """Whether Blender's ``path`` lies in ``folder`` (both as Blender spells them)."""
    norm = lambda p: str(p).replace('/', '\\').rstrip('\\').lower()  # noqa: E731
    return norm(path) == norm(folder) or norm(path).startswith(norm(folder) + '\\')


def assert_private_temp(blender, env, profile_args, expected=None):
    """Ask a headless Blender, launched as the UI run will be, where its temp is.

    The environment alone is not proof: a normal profile's preferences can name
    a temp directory of their own, and a Windows Blender started from WSL only
    sees what WSLENV forwards. Refuses to go on unless ``bpy.app.tempdir`` is
    inside ``expected`` (this run's own directory, ``env['TEMP']``). Returns it.
    """
    expected = expected or env['TEMP']
    probe = subprocess.run(
        [blender, '-b', *profile_args, '--python-expr',
         "import bpy; print('PB_TEMPDIR=' + bpy.app.tempdir)"],
        env=env, text=True, capture_output=True, timeout=120)
    found = next((line.split('=', 1)[1].strip() for line in probe.stdout.splitlines()
                  if line.startswith('PB_TEMPDIR=')), None)
    print(f"[ui] Blender temp directory: {found} (expected inside {expected})", flush=True)
    # A probe that crashed proves nothing, whatever it printed first.
    if probe.returncode:
        raise SystemExit(
            f"The temp-directory probe Blender exited with {probe.returncode}; not "
            f"starting a foreground run whose temp is unverified.\n{probe.stdout}{probe.stderr}")
    if found is None or not _inside(found, expected):
        raise SystemExit(
            f"Blender's temp directory is {found!r}, not inside {expected!r}: a "
            "foreground run would overwrite the shared session-recovery file "
            "(quit.blend). Not starting it.")
    return expected


def assert_recovery_saved_privately(output, folder):
    """Fail if Blender's log says it saved session recovery anywhere else."""
    marker = 'Saved session recovery to "'
    for line in output.splitlines():
        if marker in line:
            path = line.split(marker, 1)[1].rsplit('"', 1)[0]
            if not _inside(path, folder):
                raise SystemExit(f"Blender saved session recovery to {path}, "
                                 f"outside this run's temp {folder}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default=os.environ.get("BLENDER_PATH", "blender"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--keep-report", action="store_true")
    parser.add_argument("--normal-profile", action="store_true",
                        help="Test the enabled installed add-on in a fresh normal-profile process")
    parser.add_argument("--scenario", choices=('all', 'morphsets', 'morph-states', 'shared-morphs', 'model-morphsets', 'saved-model-morphsets', 'morph-outliner', 'puppet-morphsets', 'thermal-motion', 'assembly-conformations', 'assembly-edit', 'assembly-from-id', 'filament', 'filament-nodes', 'local-import', 'membrane'), default='all',
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
    drivers['assembly-conformations'] = ROOT / 'tests/ui/run_feedback_scenarios.py'
    drivers['assembly-edit'] = ROOT / 'tests/ui/run_assembly_edit_scenarios.py'
    drivers['assembly-from-id'] = ROOT / 'tests/ui/run_assembly_import_scenarios.py'
    drivers['filament'] = ROOT / 'tests/ui/run_filament_scenarios.py'
    drivers['filament-nodes'] = ROOT / 'tests/ui/run_filament_nodes_scenarios.py'
    drivers['local-import'] = ROOT / 'tests/ui/run_local_import_scenarios.py'
    drivers['membrane'] = ROOT / 'tests/ui/run_membrane_scenarios.py'
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
        env = private_temp_env(Path(tmp), args.blender)
        private_temp = assert_private_temp(
            args.blender, env, [] if args.normal_profile else ["--factory-startup"])
        timed_out = None
        try:
            with log_path.open('w', encoding='utf-8') as log:
                proc = subprocess.run(command, cwd=ROOT, text=True, env=env,
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
        assert_recovery_saved_privately(output, private_temp)
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
