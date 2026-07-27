#!/usr/bin/env bash
# Detect hand-edits on gh-pages that a publish would destroy.
#
# gh-pages is BUILD OUTPUT. The publish workflow regenerates index.html and the
# other pages from docs/*.md via Jekyll on every deploy. Anything committed
# straight to gh-pages therefore survives only until the next publish, and then
# disappears with no conflict and no warning.
#
# This has already cost real work three times (jiwasa's tutorial sections).
#
# Exits 1 if unported hand-edits exist, 0 if the branch is clean.
#
# Usage:  ./check-docs-drift.sh

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo root: $REPO" >&2; exit 2; }

REMOTE="${PB_REMOTE:-origin}"
# A deploy commit is one the workflow made. Everything else is a human.
DEPLOY_RE="Update site and extensions"
BOT_RE="github-actions"

echo "Fetching $REMOTE/gh-pages ..."
if ! git fetch "$REMOTE" gh-pages --quiet 2>/dev/null; then
  echo "NOTE: could not fetch $REMOTE/gh-pages (no such branch, or offline)."
  echo "      Skipping the docs-drift gate - verify by hand before publishing."
  exit 0
fi

# Newest deploy commit: everything after it is at risk right now. Hand-edits
# older than the last deploy were either already ported or already destroyed;
# either way there is nothing left to rescue.
last_deploy="$(git log "$REMOTE/gh-pages" --format="%H|%an|%s" \
  | grep -E "$DEPLOY_RE|$BOT_RE" | head -1 | cut -d'|' -f1)"

if [[ -z "$last_deploy" ]]; then
  range="$REMOTE/gh-pages"
  echo "No deploy commit found; inspecting the whole branch."
else
  range="${last_deploy}..${REMOTE}/gh-pages"
  echo "Last deploy: $(git log -1 --format='%h %s' "$last_deploy")"
fi

mapfile -t manual < <(git log "$range" --format="%h|%an|%ad|%s" --date=short 2>/dev/null \
  | grep -viE "$DEPLOY_RE|$BOT_RE")

if (( ${#manual[@]} == 0 )); then
  echo ""
  echo "GATE PASSED: no hand-edits on gh-pages since the last deploy."
  exit 0
fi

echo ""
echo "GATE FAILED: hand-edits on gh-pages that the next publish will destroy:"
echo ""
for entry in "${manual[@]}"; do
  sha="${entry%%|*}"
  rest="${entry#*|}"; author="${rest%%|*}"
  rest="${rest#*|}";  date="${rest%%|*}"
  subject="${rest#*|}"
  echo "  $sha  $date  $author"
  echo "      $subject"
  git show --name-only --format="" "$sha" 2>/dev/null | sed 's/^/        touched: /'
done

cat <<'EOF'

These live only in the generated HTML on gh-pages. Before publishing:

  1. See what changed:
       git diff <sha>~1 <sha> -- index.html
  2. Port the same change into the Jekyll SOURCE (docs/*.md), commit it.
  3. Re-run this check, or confirm the content is already in docs/.

Do NOT `git merge origin/gh-pages` into the source branch - that drags built
HTML, assets and the extension index JSON into the tree, and still does not
protect anything, because the next deploy regenerates from docs/ regardless.
EOF
exit 1
