#!/usr/bin/env python3
"""List source IDs added or materially changed between a base commit and HEAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACK_PREFIX = "plugins/loyalty-radar/skills/loyalty-radar/references/source-packs/"


def git(*args: str, allow_failure: bool = False) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if result.returncode and not allow_failure:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout if result.returncode == 0 else ""


def source_map(text: str) -> dict[str, dict[str, Any]]:
    if not text.strip():
        return {}
    payload = yaml.safe_load(text) or {}
    rows = payload.get("sources") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("source pack must contain a sources list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            raise ValueError("every source must be an object with an id")
        source_id = str(row["id"]).strip()
        if source_id in result:
            raise ValueError(f"duplicate source id: {source_id}")
        result[source_id] = row
    return result


def changed_source_ids(base: str, limit: int = 25) -> list[str]:
    names = git("diff", "--name-only", f"{base}...HEAD", "--", PACK_PREFIX).splitlines()
    changed: set[str] = set()
    for relative in sorted(name for name in names if name.startswith(PACK_PREFIX)):
        previous = source_map(git("show", f"{base}:{relative}", allow_failure=True))
        path = ROOT / relative
        current = source_map(path.read_text(encoding="utf-8")) if path.is_file() else {}
        for source_id, row in current.items():
            if previous.get(source_id) != row:
                changed.add(source_id)
    return sorted(changed)[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if not 1 <= args.limit <= 25:
        parser.error("--limit must be from 1 through 25")
    try:
        rows = changed_source_ids(args.base, args.limit)
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        print(f"changed-source-ids: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"{source_id}\n" for source_id in rows), encoding="utf-8")
    print(f"Selected {len(rows)} changed source(s) for a bounded public probe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
