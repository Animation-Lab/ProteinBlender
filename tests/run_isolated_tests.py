"""Run high-risk tests in separate Blender processes.

The main suite intentionally amortizes startup cost in one process. This lane
proves selected lifecycle regressions do not depend on collection order or on
state left by an earlier test.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tests" / "run_tests.py"
DEFAULT_NODEIDS = [
    "tests/test_harness_smoke.py::test_offline_import_single_chain",
    "tests/integration/test_registration_contract.py",
    "tests/integration/test_rendering.py::test_imported_molecule_actually_puts_pixels_on_screen",
    "tests/integration/test_split_domain_regression.py",
    "tests/roundtrip/test_saveload.py",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default=os.environ.get("BLENDER_PATH", "blender"))
    parser.add_argument("nodeids", nargs="*", default=DEFAULT_NODEIDS)
    args = parser.parse_args()
    failures = []
    env = os.environ.copy()
    env["BLENDER_PATH"] = args.blender
    for nodeid in args.nodeids:
        print(f"\n[isolated] {nodeid}", flush=True)
        result = subprocess.run([sys.executable, str(RUNNER), "--blender", args.blender,
                                 nodeid, "-q"], cwd=ROOT, env=env)
        if result.returncode:
            failures.append((nodeid, result.returncode))
    if failures:
        for nodeid, code in failures:
            print(f"[isolated] FAIL {code}: {nodeid}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
