"""Versioned report JSON and backward-compatible readers."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


def _asdict(value: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return copy.deepcopy(value)
    raise TypeError(f"Expected dataclass or mapping, got {type(value).__name__}")


def _event_id(row: dict[str, Any]) -> str:
    existing = str(row.get("event_id") or "").strip()
    if existing:
        return existing
    basis = f"{row.get('url', '')}\n{row.get('title', '')}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _legacy_localized(row: dict[str, Any]) -> dict[str, dict[str, str]]:
    localized: dict[str, dict[str, str]] = {}
    title_zh = str(row.get("title_zh") or "").strip()
    summary_zh = str(row.get("summary_zh") or "").strip()
    why_zh = str(row.get("why_it_matters_zh") or row.get("why_it_matters") or "").strip()
    if title_zh or summary_zh:
        localized["zh-CN"] = {
            "title": title_zh,
            "summary": summary_zh,
            "why_it_matters": why_zh,
        }
    return localized


def normalize_evidence(row: dict[str, Any]) -> dict[str, Any]:
    if "original" in row:
        result = copy.deepcopy(row)
        result.setdefault("localized", {})
        return result
    result = {
        key: copy.deepcopy(value)
        for key, value in row.items()
        if key not in {"title", "summary", "title_zh", "summary_zh"}
    }
    result["original"] = {
        "title": str(row.get("title") or ""),
        "summary": str(row.get("summary") or ""),
    }
    result["localized"] = _legacy_localized(row)
    return result


def normalize_event(value: Any) -> dict[str, Any]:
    row = _asdict(value)
    if "original" in row:
        result = copy.deepcopy(row)
        result.setdefault("localized", {})
        result["evidence"] = [normalize_evidence(item) for item in result.get("evidence", [])]
        result.setdefault("event_id", _event_id(result))
        return result
    excluded = {
        "title",
        "summary",
        "why_it_matters",
        "title_zh",
        "summary_zh",
        "why_it_matters_zh",
        "evidence",
    }
    result = {key: copy.deepcopy(value) for key, value in row.items() if key not in excluded}
    result["event_id"] = _event_id(row)
    result["original"] = {
        "title": str(row.get("title") or ""),
        "summary": str(row.get("summary") or ""),
        "why_it_matters": str(row.get("why_it_matters") or ""),
    }
    result["localized"] = _legacy_localized(row)
    result["evidence"] = [normalize_evidence(item) for item in row.get("evidence", [])]
    return result


def build_report(
    events: Iterable[Any],
    health: Iterable[Any],
    *,
    generated_at: str,
    mode: str,
    focus: str,
    hours: int,
    timezone: str,
    source_packs: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "product": {"name": "Loyalty Radar", "version": "0.1.0"},
        "generated_at": generated_at,
        "mode": mode,
        "focus": focus,
        "hours": hours,
        "future_watch_days": 60,
        "timezone": timezone,
        "source_packs": list(source_packs),
        "items": [normalize_event(event) for event in events],
        "health": [_asdict(row) for row in health],
        "translation_health": {},
    }


def upgrade_report(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Report JSON must contain an object")
    upgraded = copy.deepcopy(payload)
    upgraded["schema_version"] = SCHEMA_VERSION
    upgraded.setdefault("product", {"name": "Loyalty Radar", "version": "0.1.0"})
    upgraded.setdefault("future_watch_days", 60)
    upgraded.setdefault("source_packs", [])
    upgraded.setdefault("translation_health", {})
    upgraded["items"] = [normalize_event(item) for item in upgraded.get("items", []) if isinstance(item, dict)]
    upgraded["health"] = [copy.deepcopy(item) for item in upgraded.get("health", []) if isinstance(item, dict)]
    return upgraded


def read_report(path: Path) -> dict[str, Any]:
    return upgrade_report(json.loads(path.read_text(encoding="utf-8")))


def write_report(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = upgrade_report(payload)
    normalized.setdefault("localized_at", dt.datetime.now(dt.UTC).isoformat())
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
