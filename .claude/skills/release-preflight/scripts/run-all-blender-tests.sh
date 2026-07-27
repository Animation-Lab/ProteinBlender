#!/usr/bin/env bash
# Run the full ProteinBlender suite on every supported Blender version.
#
# Exits non-zero if ANY version is missing or ANY suite fails, so it can be used
# as a hard release gate. Prints one summary line per version.
#
# Usage:  ./run-all-blender-tests.sh [extra pytest args...]
#
# Override the Blender search with PB_BLENDER_ROOT (a directory containing
# "Blender <version>" subfolders).

set -uo pipefail

VERSIONS=("5.0" "5.1" "5.2")
ROOT="${PB_BLENDER_ROOT:-/mnt/c/Program Files/Blender Foundation}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo root: $REPO" >&2; exit 2; }

if [[ ! -f tests/run_tests.py ]]; then
  echo "FAIL: tests/run_tests.py not found under $REPO" >&2
  exit 2
fi

declare -a SUMMARY=()
missing=0
failed=0

# --- every declared version must actually be installed -----------------------
# A silently-absent Blender would turn "all versions pass" into "the versions
# that happened to exist pass", which is exactly the gap that let an untested
# 4.2 floor ship for months.
for v in "${VERSIONS[@]}"; do
  exe="$ROOT/Blender $v/blender.exe"
  [[ -f "$exe" ]] || exe="$ROOT/Blender $v/blender"
  if [[ ! -f "$exe" ]]; then
    echo "FAIL: Blender $v not found (looked in '$ROOT/Blender $v')" >&2
    SUMMARY+=("  $v  NOT INSTALLED")
    missing=$((missing + 1))
  fi
done
if (( missing > 0 )); then
  printf '%s\n' "${SUMMARY[@]}" >&2
  echo "" >&2
  echo "Cannot gate a release on versions that are not installed." >&2
  echo "Install them, or change VERSIONS here AND blender_version_min together." >&2
  exit 2
fi

# --- run the suite on each ---------------------------------------------------
for v in "${VERSIONS[@]}"; do
  exe="$ROOT/Blender $v/blender.exe"
  [[ -f "$exe" ]] || exe="$ROOT/Blender $v/blender"

  echo "=== Blender $v: full suite ==="
  out="$(BLENDER_PATH="$exe" python tests/run_tests.py -q "$@" 2>&1)"
  rc=$?

  line="$(grep -E "[0-9]+ (passed|failed|error)" <<<"$out" | tail -1)"
  [[ -n "$line" ]] || line="(no pytest summary line - see output below)"

  # run_tests.py can exit 0 while pytest reported failures, so trust the
  # summary text as well as the exit code.
  if (( rc != 0 )) || grep -qE "[0-9]+ (failed|error)" <<<"$line"; then
    echo "$out" | tail -40
    SUMMARY+=("  $v  FAILED   $line")
    failed=$((failed + 1))
  else
    SUMMARY+=("  $v  ok       $line")
  fi
  echo "$line"
  echo ""
done

echo "================ suite summary ================"
printf '%s\n' "${SUMMARY[@]}"
echo "==============================================="

if (( failed > 0 )); then
  echo "GATE FAILED: $failed of ${#VERSIONS[@]} versions did not pass." >&2
  echo "Do not release. Fix the failures and re-run." >&2
  exit 1
fi

echo "GATE PASSED: full suite green on ${VERSIONS[*]}."
