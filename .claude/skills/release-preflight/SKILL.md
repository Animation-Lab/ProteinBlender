---
name: release-preflight
description: Runs the mandatory ProteinBlender release gates - the full test suite on Blender 5.0, 5.1 and 5.2, and a docs check that no hand-edits on gh-pages are about to be destroyed. Use before building, tagging, pushing or publishing any release, including alpha builds.
---

<objective>
Two gates that must both pass before any ProteinBlender release goes out.

Neither is optional and neither is advisory. If a gate fails, stop and report -
do not release, and do not "fix it after". Both gates exist because the failure
they catch is silent: a broken build reports success, and destroyed docs leave
no conflict and no warning.
</objective>

<essential_principles>
**Gate on the release commit, not a proxy.**
Run the tests on the exact commit being released - after the version bump, not
before. A version bump touches the manifest, `pyproject.toml` and `__init__.py`,
and there are contract tests asserting those three stay in sync. Testing the
pre-bump tree proves nothing about what ships.

**All three Blender versions, every time.**
5.0, 5.1 and 5.2 are all supported (`blender_version_min = "5.0.0"`). They are
genuinely different: 5.0 runs Python 3.11 while 5.1 and 5.2 run 3.13, and 5.2
changed the geometry-nodes modifier socket API. A subset run is not a gate.
Never narrow the version list to make a release pass.

**A missing Blender is a failed gate, not a skipped one.**
If a version is not installed, the gate fails. "All installed versions passed"
silently becomes the answer to a different question - that is how a 4.2 floor
stayed advertised for months without ever being tested.

**gh-pages is build output, never a source of truth.**
The publish workflow regenerates every page from `docs/*.md` via Jekyll. Anything
committed straight to gh-pages survives only until the next deploy. Work has been
lost this way three times. The fix is always to port the content into `docs/`,
and never to merge gh-pages into the source branch - that drags built HTML,
assets and the extension index JSON into the tree, and protects nothing, because
the next deploy regenerates from `docs/` anyway.
</essential_principles>

<process>
**Step 1 - Confirm what is being released.**

Check the working tree is clean, note the branch, and confirm the version is what
you intend to ship and is in sync across all three files:

```bash
git status --porcelain            # must be empty
git rev-parse --abbrev-ref HEAD
grep -E "^version" proteinblender/blender_manifest.toml pyproject.toml
grep -n '"version": (' proteinblender/__init__.py
```

If the version bump has not happened yet, do it first (`python build.py [--alpha]`
prompts for it), then continue - the gates run on the bumped commit.

**Step 2 - Gate A: full suite on all three Blender versions.**

```bash
./.claude/skills/release-preflight/scripts/run-all-blender-tests.sh
```

Takes roughly 9-10 minutes (about 3 per version). Exits non-zero if any version
is missing or any suite fails, and prints a per-version summary.

If it fails: stop. Report which version failed and the pytest output. Do not
release, do not push, do not tag.

**Step 3 - Gate B: docs drift on gh-pages.**

```bash
./.claude/skills/release-preflight/scripts/check-docs-drift.sh
```

Exits non-zero if anyone has hand-edited gh-pages since the last deploy. If it
fails, for each flagged commit:

1. See what changed: `git diff SHA~1 SHA -- index.html`
2. Port the same change into the Jekyll source (`docs/*.md`) and commit it.
3. Re-run the check, or confirm the content is already in `docs/`.

The script cannot tell "already ported" from "not ported yet", so a flagged
commit whose content is verifiably in `docs/` is a pass - say so explicitly in
the report rather than silently ignoring it.

**Step 4 - Report both gates before proceeding.**

State the result of each gate plainly, with the numbers:

```
Gate A  full suite   5.0 / 5.1 / 5.2   passed | FAILED   (N passed each)
Gate B  docs drift   clean | ported SHA | FAILED
```

Only then continue to whatever the release actually is (build, tag, push,
GitHub release, publish). If either gate failed, that is the whole report.

**Step 5 - After publishing, verify what testers actually receive.**

A green workflow is not proof the artifact landed. GitHub Pages serves a cached
copy, so always cache-bust:

```bash
curl -s -H 'Cache-Control: no-cache' \
  "https://animation-lab.github.io/ProteinBlender/extensions/alpha/index.json?cb=$(date +%s)"
```

Confirm the expected version, `blender_version_min`, and all four platform zips,
and confirm the other channel's index was not disturbed.
</process>

<extension_points>
This skill is expected to grow. When adding a gate:

- Put the runnable part in `scripts/` as its own script that exits non-zero on
  failure, so it can be run standalone and composed later.
- Add a step to the process section and a line to the Step 4 report block.
- Keep every gate independently runnable. A gate that only works as part of a
  sequence stops being run.

Known candidates not yet implemented: verifying the alpha build restored the
release manifest identity (`id = "proteinblender"`) in the working tree after
`build.py --alpha`, and checking that the built zips carry the intended
extension id.
</extension_points>

<success_criteria>
- Working tree clean and the version verified in sync across all three files
- Gate A run on the release commit; full suite passed on 5.0, 5.1 AND 5.2
- Gate B run; gh-pages either clean or every hand-edit ported into `docs/`
- Both gate results reported with numbers before any release action
- If published: the served index verified with a cache-busted fetch
- On any gate failure: stopped, reported, released nothing
</success_criteria>
