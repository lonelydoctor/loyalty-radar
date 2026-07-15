"""Tests for the bounded, rotating GitHub source-health probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "live_source_health.py"
SPEC = importlib.util.spec_from_file_location("loyalty_radar_live_source_health", SCRIPT)
assert SPEC and SPEC.loader
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


def source(source_id: str, pack_id: str, priority: str = "P1") -> dict[str, str]:
    return {"id": source_id, "pack_id": pack_id, "priority": priority, "url": f"https://{source_id}.test"}


def test_rotating_sample_balances_available_source_packs() -> None:
    candidates = {
        pack: [source(f"{pack}-{index}", pack) for index in range(4)]
        for pack in ("core", "experimental", "forums-cn", "forums-global", "industry")
    }

    selected = health.select_rotating_sample(candidates, limit=10, rotation=0)

    counts: dict[str, int] = {}
    for row in selected:
        counts[row["pack_id"]] = counts.get(row["pack_id"], 0) + 1
    assert counts == {pack: 2 for pack in candidates}


def test_rotation_eventually_covers_every_candidate_in_a_pack() -> None:
    candidates = {"core": [source(f"core-{index}", "core") for index in range(6)]}

    observed = {
        row["id"]
        for rotation in range(3)
        for row in health.select_rotating_sample(candidates, limit=2, rotation=rotation)
    }

    assert observed == {f"core-{index}" for index in range(6)}


def test_small_limits_rotate_the_first_pack_instead_of_starving_it_forever() -> None:
    candidates = {
        pack: [source(f"{pack}-0", pack)]
        for pack in ("core", "experimental", "forums-cn", "forums-global", "industry")
    }

    selected_packs = {
        health.select_rotating_sample(candidates, limit=1, rotation=rotation)[0]["pack_id"]
        for rotation in range(5)
    }

    assert selected_packs == set(candidates)


def test_committed_catalog_keeps_all_health_states_explicit() -> None:
    candidates, browser_assisted, disabled = health.load_candidates()

    assert sum(len(rows) for rows in candidates.values()) == 53
    assert set(candidates) == {"core", "forums-cn", "forums-global", "industry"}
    assert len(browser_assisted) == 5
    assert len(disabled) == 1
