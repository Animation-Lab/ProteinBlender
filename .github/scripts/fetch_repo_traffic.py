#!/usr/bin/env python3
"""Fetch and persist GitHub repository traffic metrics for GitHub Pages."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "docs" / "data" / "traffic"
DAILY_PATH = DATA_DIR / "daily.json"
LATEST_PATH = DATA_DIR / "latest.json"
API_BASE = "https://api.github.com"


def github_get(endpoint: str, token: str) -> dict:
    request = Request(
        f"{API_BASE}{endpoint}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "proteinblender-traffic-dashboard",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urlopen(request) as response:
            return json.load(response)
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed: {exc.code} {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub API request failed: {exc.reason}") from exc


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def normalize_views(entry: dict) -> dict:
    return {
        "date": entry["timestamp"][:10],
        "views": entry["count"],
        "visitors": entry["uniques"],
    }


def normalize_clones(entry: dict) -> dict:
    return {
        "date": entry["timestamp"][:10],
        "clones": entry["count"],
        "cloners": entry["uniques"],
    }


def merge_daily(existing: dict, views: dict, clones: dict) -> dict:
    merged = {item["date"]: item for item in existing.get("daily", [])}

    for item in views:
        row = merged.setdefault(
            item["date"],
            {
                "date": item["date"],
                "views": 0,
                "visitors": 0,
                "clones": 0,
                "cloners": 0,
            },
        )
        row["views"] = item["views"]
        row["visitors"] = item["visitors"]

    for item in clones:
        row = merged.setdefault(
            item["date"],
            {
                "date": item["date"],
                "views": 0,
                "visitors": 0,
                "clones": 0,
                "cloners": 0,
            },
        )
        row["clones"] = item["clones"]
        row["cloners"] = item["cloners"]

    ordered = [merged[key] for key in sorted(merged)]
    return {"daily": ordered}


def delta(current: dict | None, previous: dict | None) -> dict:
    if not current:
        return {"views": 0, "visitors": 0, "clones": 0, "cloners": 0}

    if not previous:
        return {
            "views": current["views"],
            "visitors": current["visitors"],
            "clones": current["clones"],
            "cloners": current["cloners"],
        }

    return {
        "views": current["views"] - previous["views"],
        "visitors": current["visitors"] - previous["visitors"],
        "clones": current["clones"] - previous["clones"],
        "cloners": current["cloners"] - previous["cloners"],
    }


def main() -> int:
    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")

    if not token:
        raise RuntimeError("GITHUB_TOKEN is required.")
    if not repository or "/" not in repository:
        raise RuntimeError("GITHUB_REPOSITORY must look like owner/repo.")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    owner, repo = repository.split("/", 1)

    views_payload = github_get(f"/repos/{owner}/{repo}/traffic/views", token)
    clones_payload = github_get(f"/repos/{owner}/{repo}/traffic/clones", token)
    referrers_payload = github_get(f"/repos/{owner}/{repo}/traffic/popular/referrers", token)
    paths_payload = github_get(f"/repos/{owner}/{repo}/traffic/popular/paths", token)

    normalized_views = [normalize_views(item) for item in views_payload.get("views", [])]
    normalized_clones = [normalize_clones(item) for item in clones_payload.get("clones", [])]

    existing_daily = read_json(DAILY_PATH, {"daily": []})
    daily = merge_daily(existing_daily, normalized_views, normalized_clones)
    daily.update(
        {
            "repo": repository,
            "generated_at": now,
        }
    )

    current_day = daily["daily"][-1] if daily["daily"] else None
    previous_day = daily["daily"][-2] if len(daily["daily"]) > 1 else None

    all_time = {
        "views": sum(d.get("views", 0) for d in daily["daily"]),
        "visitors": sum(d.get("visitors", 0) for d in daily["daily"]),
        "clones": sum(d.get("clones", 0) for d in daily["daily"]),
        "cloners": sum(d.get("cloners", 0) for d in daily["daily"]),
        "days_tracked": len(daily["daily"]),
    }

    latest = {
        "repo": repository,
        "generated_at": now,
        "summary": {
            "views": views_payload.get("count", 0),
            "visitors": views_payload.get("uniques", 0),
            "clones": clones_payload.get("count", 0),
            "cloners": clones_payload.get("uniques", 0),
        },
        "all_time": all_time,
        "current_day": current_day,
        "previous_day": previous_day,
        "delta_since_previous_day": delta(current_day, previous_day),
        "referrers": referrers_payload,
        "popular_paths": paths_payload,
    }

    write_json(DAILY_PATH, daily)
    write_json(LATEST_PATH, latest)

    print(f"Updated traffic data for {repository} at {now}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - surfaced in GitHub Actions logs
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
