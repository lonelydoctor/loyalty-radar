#!/usr/bin/env python3
"""Probe a bounded, stratified source sample and persist health metadata only."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "plugins" / "loyalty-radar" / "skills" / "loyalty-radar" / "references" / "source-packs"
USER_AGENT = "Loyalty-Radar-Health/0.1 (+https://github.com/lonelydoctor/loyalty-radar)"


def bounded_limit(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 25:
        raise argparse.ArgumentTypeError("limit must be between 1 and 25")
    return number


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def load_candidates() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]], list[dict[str, str]]]:
    by_pack: dict[str, list[dict[str, Any]]] = defaultdict(list)
    browser_only: list[dict[str, str]] = []
    disabled: list[dict[str, str]] = []
    for path in sorted(PACK_DIR.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pack = payload.get("pack") or {}
        pack_id = str(pack.get("id") or path.stem)
        for source in payload.get("sources") or []:
            if not isinstance(source, dict):
                continue
            if not source.get("enabled", True):
                disabled.append({"source_id": str(source.get("id") or ""), "pack_id": pack_id, "reason": "disabled_in_catalog"})
                continue
            if source.get("fetch_method") == "browser_only":
                browser_only.append({"source_id": str(source.get("id") or ""), "pack_id": pack_id, "reason": "browser_assisted"})
                continue
            item = dict(source)
            item["pack_id"] = pack_id
            by_pack[pack_id].append(item)

    ordered = {
        pack_id: sorted(
            rows,
            key=lambda row: (
                PRIORITY_ORDER.get(str(row.get("priority") or "P2"), 3),
                str(row.get("id") or ""),
            ),
        )
        for pack_id, rows in by_pack.items()
    }
    return ordered, browser_only, disabled


def select_rotating_sample(
    candidates_by_pack: dict[str, list[dict[str, Any]]],
    limit: int,
    rotation: int,
) -> list[dict[str, Any]]:
    """Select a balanced sample and advance each pack by its weekly quota."""

    pack_ids = sorted(pack_id for pack_id, rows in candidates_by_pack.items() if rows)
    if not pack_ids or limit <= 0:
        return []
    pack_shift = rotation % len(pack_ids)
    pack_ids = pack_ids[pack_shift:] + pack_ids[:pack_shift]
    total = sum(len(candidates_by_pack[pack_id]) for pack_id in pack_ids)
    remaining = min(limit, total)
    quotas = {pack_id: 0 for pack_id in pack_ids}
    while remaining:
        progressed = False
        for pack_id in pack_ids:
            if quotas[pack_id] >= len(candidates_by_pack[pack_id]):
                continue
            quotas[pack_id] += 1
            remaining -= 1
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            break

    selected_by_pack: dict[str, deque[dict[str, Any]]] = {}
    for pack_id in pack_ids:
        rows = candidates_by_pack[pack_id]
        quota = quotas[pack_id]
        start = (rotation * quota) % len(rows) if quota else 0
        selected_by_pack[pack_id] = deque(rows[(start + index) % len(rows)] for index in range(quota))

    selected: list[dict[str, Any]] = []
    while any(selected_by_pack.values()):
        for pack_id in pack_ids:
            if selected_by_pack[pack_id]:
                selected.append(selected_by_pack[pack_id].popleft())
    return selected


def default_rotation() -> int:
    calendar = datetime.now(UTC).isocalendar()
    return calendar.year * 53 + calendar.week


def check_source(source: dict[str, Any], last_request: dict[str, float]) -> dict[str, Any]:
    source_url = str(source["url"])
    host = urlparse(source_url).netloc.lower()
    rate_limit = max(0.0, float(source.get("rate_limit_seconds") or 0.0))
    wait_seconds = last_request.get(host, 0.0) + rate_limit - time.monotonic()
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    started = time.monotonic()
    result: dict[str, Any] = {
        "source_id": source.get("id"),
        "source_name": source.get("name"),
        "pack_id": source.get("pack_id"),
        "priority": source.get("priority"),
        "fetch_method": source.get("fetch_method"),
        "url": source_url,
    }
    try:
        with requests.get(
            source_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/html;q=0.9, */*;q=0.1"},
            timeout=(6, 18),
            allow_redirects=True,
            stream=True,
        ) as response:
            sample = next(response.iter_content(chunk_size=2048), b"")
            result.update(
                {
                    "status": "ok" if response.status_code < 400 else "http_error",
                    "status_code": response.status_code,
                    "content_type": response.headers.get("Content-Type", "").split(";", 1)[0],
                    "final_host": urlparse(response.url).netloc.lower(),
                    "sampled_bytes": len(sample),
                }
            )
    except requests.RequestException as exc:
        result.update(
            {
                "status": "network_error",
                "status_code": None,
                "error_type": type(exc).__name__,
                "error": str(exc).replace("\n", " ")[:240],
            }
        )
    finally:
        last_request[host] = time.monotonic()
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


def write_summary(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "## Loyalty Radar limited source health",
        "",
        f"Checked **{report['checked']}** public endpoints; browser-assisted sources were not scripted.",
        "",
        f"- OK: {counts.get('ok', 0)}",
        f"- HTTP errors: {counts.get('http_error', 0)}",
        f"- Network errors: {counts.get('network_error', 0)}",
        f"- Browser-assisted sources skipped: {len(report['browser_assisted_sources'])}",
        f"- Catalog-disabled sources skipped: {len(report['disabled_sources'])}",
        "",
        "The artifact contains endpoint health metadata only. Response bodies are neither retained nor uploaded.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=bounded_limit, default=15)
    parser.add_argument("--rotation", type=int, help="Deterministic sample rotation; defaults to the current ISO week")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    try:
        candidates_by_pack, browser_only, disabled = load_candidates()
    except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
        print(f"Could not load source packs: {exc}", file=sys.stderr)
        return 2

    rotation = args.rotation if args.rotation is not None else default_rotation()
    selected = select_rotating_sample(candidates_by_pack, args.limit, rotation)
    candidate_count = sum(len(rows) for rows in candidates_by_pack.values())
    last_request: dict[str, float] = {}
    results = [check_source(source, last_request) for source in selected]
    counts = dict(Counter(str(item["status"]) for item in results))
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "limited_source_health",
        "requested_limit": args.limit,
        "rotation": rotation,
        "catalog_sources": candidate_count + len(browser_only) + len(disabled),
        "script_eligible_sources": candidate_count,
        "checked": len(results),
        "not_selected_this_run": max(0, candidate_count - len(results)),
        "selected_by_pack": dict(Counter(str(item.get("pack_id") or "") for item in selected)),
        "browser_assisted_sources": browser_only,
        "disabled_sources": disabled,
        "counts": counts,
        "notice": "Health metadata only. No response body, article text, cookie, or credential is retained.",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        write_summary(args.summary, report)
    print(json.dumps({"checked": len(results), "counts": counts, "artifact": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
