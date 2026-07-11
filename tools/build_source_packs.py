#!/usr/bin/env python3
"""Split the legacy source catalog into distributable source packs."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "plugins/loyalty-radar/skills/loyalty-radar/references"
SOURCE = REFERENCES / "sources.yaml"
TARGET = REFERENCES / "source-packs"

PACKS = {
    "core": {
        "name": "Core loyalty sources",
        "description": "Stable editorial and deal feeds with strong member-level signal.",
        "default_enabled": True,
    },
    "industry": {
        "name": "Industry and ecosystem radar",
        "description": "Trade press and news-query feeds for structural loyalty ecosystem signals.",
        "default_enabled": True,
    },
    "forums-global": {
        "name": "Global forums",
        "description": "Public forum feeds for user datapoints across global programs.",
        "default_enabled": True,
    },
    "forums-cn": {
        "name": "Chinese-language forums",
        "description": "Public Chinese frequent-traveler and card communities.",
        "default_enabled": False,
    },
    "experimental": {
        "name": "Experimental and browser-assisted sources",
        "description": "Noisy or access-limited sources kept visible in source health.",
        "default_enabled": False,
    },
}

CORE_IDS = {
    "doctor-of-credit-cards",
    "frequent-miler",
    "us-credit-card-guide",
    "loyaltylobby",
    "one-mile-at-a-time",
    "view-from-the-wing",
    "the-points-guy",
    "awardwallet",
    "dannydealguru",
    "milestalk",
    "dansdeals",
    "head-for-points",
    "prince-of-travel",
    "mainly-miles",
}
INDUSTRY_IDS = {"skift", "hospitalitynet-news"}


def pack_for(source: dict[str, object]) -> str:
    source_id = str(source["id"])
    if source_id.startswith("flyert-") or source_id == "uscardforum":
        return "forums-cn"
    if source_id.startswith("ft-") or source_id in {"myfico-credit-cards", "creditboards-credit-forum"}:
        return "forums-global"
    if source_id.startswith("reddit-") or source_id == "slickdeals-hot-deals":
        return "experimental"
    if source_id.startswith("google-news-") or source_id in INDUSTRY_IDS:
        return "industry"
    if source_id in CORE_IDS:
        return "core"
    raise ValueError(f"Source has no pack assignment: {source_id}")


def main() -> int:
    payload = yaml.safe_load(SOURCE.read_text(encoding="utf-8")) or {}
    grouped = {pack_id: [] for pack_id in PACKS}
    for original in payload.get("sources", []):
        source = dict(original)
        source.setdefault("region", "global")
        chinese_ids = {"us-credit-card-guide", "uscardforum"}
        source.setdefault(
            "language",
            "zh-CN" if str(source["id"]).startswith("flyert-") or source["id"] in chinese_ids else "en",
        )
        source.setdefault("default_limit", 10)
        source.setdefault("rate_limit_seconds", 1.5 if source.get("fetch_method") == "flyert_forum" else 0.8)
        grouped[pack_for(source)].append(source)

    TARGET.mkdir(parents=True, exist_ok=True)
    for pack_id, metadata in PACKS.items():
        output = {"pack": {"id": pack_id, **metadata}, "sources": grouped[pack_id]}
        (TARGET / f"{pack_id}.yaml").write_text(
            yaml.safe_dump(output, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    print(f"Wrote {sum(len(rows) for rows in grouped.values())} sources to {len(grouped)} packs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
