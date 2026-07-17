"""Tests for the bounded, rotating GitHub source-health probe."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "live_source_health.py"
SPEC = importlib.util.spec_from_file_location("loyalty_radar_live_source_health", SCRIPT)
assert SPEC and SPEC.loader
health = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = health
SPEC.loader.exec_module(health)

ESCALATION_SCRIPT = ROOT / ".github" / "scripts" / "source_health_escalation.py"
ESCALATION_SPEC = importlib.util.spec_from_file_location(
    "loyalty_radar_source_health_escalation", ESCALATION_SCRIPT
)
assert ESCALATION_SPEC and ESCALATION_SPEC.loader
escalation = importlib.util.module_from_spec(ESCALATION_SPEC)
sys.modules[ESCALATION_SPEC.name] = escalation
ESCALATION_SPEC.loader.exec_module(escalation)

CHANGED_SCRIPT = ROOT / ".github" / "scripts" / "changed_source_ids.py"
CHANGED_SPEC = importlib.util.spec_from_file_location(
    "loyalty_radar_changed_source_ids", CHANGED_SCRIPT
)
assert CHANGED_SPEC and CHANGED_SPEC.loader
changed = importlib.util.module_from_spec(CHANGED_SPEC)
sys.modules[CHANGED_SPEC.name] = changed
CHANGED_SPEC.loader.exec_module(changed)


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
    assert {row["status"] for row in browser_assisted} == {"skipped"}
    assert {row["fetch_method"] for row in browser_assisted} == {"browser_only"}


def test_explicit_probe_keeps_browser_sources_skipped() -> None:
    candidates, browser_assisted, disabled = health.load_candidates()
    scripted_id = next(iter(candidates["core"]))["id"]
    browser_id = browser_assisted[0]["source_id"]

    selected, skipped_browser, skipped_disabled = health.select_explicit_sources(
        candidates, browser_assisted, disabled, [scripted_id, browser_id]
    )

    assert [row["id"] for row in selected] == [scripted_id]
    assert [row["source_id"] for row in skipped_browser] == [browser_id]
    assert skipped_disabled == []


def test_changed_source_parser_compares_source_objects() -> None:
    before = changed.source_map(
        "sources:\n  - id: alpha\n    url: https://alpha.example/feed\n"
    )
    after = changed.source_map(
        "sources:\n  - id: alpha\n    url: https://alpha.example/new-feed\n"
    )

    assert before["alpha"] != after["alpha"]


def health_report(status: str, generated_at: str = "2026-07-20T00:00:00Z") -> dict:
    return {
        "generated_at": generated_at,
        "checked": 1,
        "results": [
            {
                "source_id": "doctor-of-credit",
                "source_name": "Doctor of Credit",
                "pack_id": "core",
                "priority": "P0",
                "fetch_method": "rss",
                "url": "https://www.doctorofcredit.com/feed/",
                "status": status,
            }
        ],
        "browser_assisted_sources": [
            {
                "source_id": "uscardforum",
                "pack_id": "forums-cn",
                "priority": "P1",
                "fetch_method": "browser_only",
                "status": "skipped",
            }
        ],
        "disabled_sources": [],
    }


def test_p0_requires_two_consecutive_observed_failures() -> None:
    first, first_actions = escalation.update_streaks(
        health_report("http_error"), {"schema": escalation.STATE_SCHEMA, "sources": {}}
    )
    second, second_actions = escalation.update_streaks(
        health_report("network_error", "2026-07-27T00:00:00Z"), first
    )
    third, third_actions = escalation.update_streaks(
        health_report("network_error", "2026-08-03T00:00:00Z"), second
    )

    assert first["sources"]["doctor-of-credit"]["failure_streak"] == 1
    assert first_actions == []
    assert [row["action"] for row in second_actions] == ["open"]
    assert second["sources"]["doctor-of-credit"]["failure_streak"] == 2
    assert third["sources"]["doctor-of-credit"]["failure_streak"] == 3
    assert third_actions == []
    assert third["sources"]["uscardforum"]["status"] == "skipped"
    assert third["sources"]["uscardforum"]["failure_streak"] == 0


def test_recovery_closes_once_and_resets_streak() -> None:
    prior = {
        "schema": escalation.STATE_SCHEMA,
        "sources": {
            "doctor-of-credit": {
                "source_id": "doctor-of-credit",
                "priority": "P0",
                "failure_streak": 2,
                "alerted": True,
            }
        },
    }
    recovered, actions = escalation.update_streaks(health_report("ok"), prior)
    next_state, next_actions = escalation.update_streaks(
        health_report("ok", "2026-07-27T00:00:00Z"), recovered
    )

    assert [row["action"] for row in actions] == ["close"]
    assert recovered["sources"]["doctor-of-credit"]["failure_streak"] == 0
    assert next_actions == []
    assert not next_state["sources"]["doctor-of-credit"]["alerted"]


def test_dashboard_marker_round_trips_machine_state() -> None:
    state, _ = escalation.update_streaks(
        health_report("ok"), {"schema": escalation.STATE_SCHEMA, "sources": {}}
    )
    body = escalation.render_dashboard(state, health_report("ok"))
    parsed = escalation.parse_state(body)

    assert parsed == state
    marker_json = body.split("<!-- loyalty-radar-source-health-state:v1\n", 1)[1].split("\n-->", 1)[0]
    assert json.loads(marker_json)["schema"] == escalation.STATE_SCHEMA
