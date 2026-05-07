"""Outer orchestrator: invokes Blender 5.1 once per phase per scenario.

Usage:
  python tests/stress_test/run_stress_test.py [--only=01_empty,02_single]
"""

import os
import sys
import json
import subprocess
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent.parent
WORKDIR = WORKTREE / "tests" / "stress_test_workdir"
RESULTS = WORKDIR / "results"
BLENDS = WORKDIR / "blends"
EXPECTED = WORKDIR / "expected"
LOGS = WORKDIR / "logs"
INNER = WORKTREE / "tests" / "stress_test" / "inner_runner.py"

# Force Blender 5.1 — the user explicitly asked for 5.1 and the existing
# BLENDER_PATH env var on this workstation points at 5.0.
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"

ALL_SCENARIOS = [
    "01_empty",
    "02_single",
    "03_multi",
    "04_domains",
    "05_poses",
    "06_keyframes",
    "07_delete",
    "08_resave",
    "09_in_process_reopen",
]


def run_phase(scenario, phase, blend_path, expected_path, result_path, log_path):
    # For verify, we pass the .blend on the command line so Blender opens it
    # BEFORE our script runs. Registering proteinblender and then calling
    # bpy.ops.wm.open_mainfile() on Blender 5.1 segfaults with
    # EXCEPTION_STACK_OVERFLOW; opening first sidesteps that bug.
    cmd = [BLENDER, "--background", "--factory-startup"]
    if phase == "verify":
        cmd.append(str(blend_path))
    cmd += [
        "--python", str(INNER),
        "--",
        str(WORKTREE),
        str(result_path),
        str(blend_path),
        str(expected_path),
        scenario,
        phase,
    ]
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        try:
            proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, timeout=120)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            logf.write("\n[harness] TIMEOUT after 120s — Blender hung\n")
            rc = -1
    elapsed = time.time() - t0
    return rc, elapsed


def main():
    only = None
    for arg in sys.argv[1:]:
        if arg.startswith("--only="):
            only = set(arg.split("=", 1)[1].split(","))

    scenarios = [s for s in ALL_SCENARIOS if (only is None or s in only)]

    for d in (RESULTS, BLENDS, EXPECTED, LOGS):
        d.mkdir(parents=True, exist_ok=True)

    summary = []
    for scenario in scenarios:
        blend = BLENDS / f"{scenario}.blend"
        expected = EXPECTED / f"{scenario}.json"
        setup_result = RESULTS / f"{scenario}_setup.json"
        verify_result = RESULTS / f"{scenario}_verify.json"
        setup_log = LOGS / f"{scenario}_setup.log"
        verify_log = LOGS / f"{scenario}_verify.log"

        # Setup
        print(f"[{scenario}] setup ...", flush=True)
        rc, secs = run_phase(scenario, "setup", blend, expected, setup_result, setup_log)
        setup_payload = _safe_load(setup_result)
        setup_ok = setup_payload.get("ok", False) and rc == 0
        print(f"  setup {'OK' if setup_ok else 'FAIL'} ({secs:.1f}s, rc={rc})", flush=True)
        if not setup_ok:
            print(f"    log: {setup_log}", flush=True)
            print(f"    err: {setup_payload.get('error') or '(no JSON)'}", flush=True)
            summary.append({"scenario": scenario, "setup_ok": False, "verify_ok": False,
                            "setup_secs": secs, "verify_secs": 0,
                            "setup_payload": setup_payload, "verify_payload": None})
            continue

        # Verify
        print(f"[{scenario}] verify ...", flush=True)
        rc, vsecs = run_phase(scenario, "verify", blend, expected, verify_result, verify_log)
        verify_payload = _safe_load(verify_result)
        verify_ok = verify_payload.get("ok", False) and rc == 0
        print(f"  verify {'OK' if verify_ok else 'FAIL'} ({vsecs:.1f}s, rc={rc})", flush=True)
        if not verify_ok:
            print(f"    log: {verify_log}", flush=True)
            for issue in verify_payload.get("issues", []):
                print(f"    - {issue}", flush=True)
            if verify_payload.get("error"):
                print(f"    err: {verify_payload['error']}", flush=True)

        summary.append({
            "scenario": scenario,
            "setup_ok": setup_ok,
            "verify_ok": verify_ok,
            "setup_secs": secs,
            "verify_secs": vsecs,
            "setup_payload": setup_payload,
            "verify_payload": verify_payload,
        })

    summary_path = RESULTS / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSummary written to {summary_path}", flush=True)

    # Pretty print final table
    print("\n=== Stress test results ===")
    print(f"{'Scenario':20s}  {'Setup':>6s}  {'Verify':>7s}  {'Setup s':>9s}  {'Verify s':>9s}")
    for row in summary:
        print(f"{row['scenario']:20s}  "
              f"{'OK' if row['setup_ok'] else 'FAIL':>6s}  "
              f"{'OK' if row['verify_ok'] else 'FAIL':>7s}  "
              f"{row['setup_secs']:9.1f}  {row['verify_secs']:9.1f}")


def _safe_load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"could not read result: {e}"}


if __name__ == "__main__":
    main()
