"""Source-health checks independent of report ranking."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import engine
from .config import resolve_cards, resolve_profile
from .i18n import Catalog


def localized_health_detail(row: dict[str, Any], catalog: Catalog) -> str:
    status = str(row.get("status") or "failed")
    detail = str(row.get("detail") or "")
    lower = detail.lower()
    if status == "ok":
        return catalog.text("health.detail_ok")
    if "browser" in lower or "cloudflare" in lower:
        return catalog.text("health.detail_browser_only")
    if "p2" in lower:
        return catalog.text("health.detail_p2")
    if "disabled" in lower:
        return catalog.text("health.detail_disabled")
    match = re.search(r"http\s+(\d{3})", lower)
    if match:
        return catalog.text("health.detail_http", code=match.group(1))
    if any(term in lower for term in ("parse", "xml", "feed", "unsupported fetch")):
        return catalog.text("health.detail_parser")
    if any(term in lower for term in ("timeout", "connection", "network", "dns", "ssl")):
        return catalog.text("health.detail_network")
    return catalog.text("health.detail_unknown")


def check_sources(
    sources: Iterable[dict[str, Any]],
    *,
    profile: Path | None = None,
    cards: Path | None = None,
    source_ids: set[str] | None = None,
    max_sources: int | None = None,
    per_source_limit: int = 2,
) -> list[dict[str, Any]]:
    profile_path = profile or resolve_profile()
    cards_path = cards or resolve_cards()
    profile_keywords = engine.flatten_profile_keywords(engine.load_yaml(profile_path))
    card_keywords = engine.flatten_card_keywords(engine.load_yaml(cards_path))
    selected = [source for source in sources if not source_ids or str(source.get("id")) in source_ids]
    if max_sources is not None:
        selected = selected[: max(0, max_sources)]
    args = argparse.Namespace(
        include_p2=True,
        per_source_limit=per_source_limit,
        fetch_details=False,
        detail_delay=0.0,
        reference_date=dt.datetime.now(dt.UTC),
    )
    rows: list[dict[str, Any]] = []
    for source in selected:
        _items, health = engine.collect_source(source, profile_keywords, card_keywords, args)
        rows.append(dataclasses.asdict(health))
        delay = float(source.get("rate_limit_seconds", 0))
        if health.status == "ok" and delay:
            time.sleep(delay)
    return rows
