"""Deterministic contracts for GitHub-native growth and outreach automation."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / ".github" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"loyalty_radar_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


growth = load_script("growth_metrics")
outreach = load_script("generate_outreach")
public_site = load_script("build_public_site")


def receipt(version: str = "0.1.2") -> str:
    return json.dumps(
        {
            "schema": "loyalty-radar-doctor-receipt/v1",
            "product": "loyalty-radar",
            "version": version,
            "python": "3.12",
            "os": "macos",
            "surfaces": {
                "skill": "ok",
                "plugin": "available",
                "source_catalog": "ok",
                "render": "degraded",
            },
        }
    )


def test_doctor_receipt_is_strict_and_rejects_private_values() -> None:
    parsed = growth.parse_doctor_receipt(f"```json\n{receipt()}\n```")
    assert parsed and parsed["version"] == "0.1.2"

    private = json.loads(receipt())
    private["path"] = "/" + "Users/alice/.config/loyalty-radar"
    assert growth.parse_doctor_receipt(json.dumps(private)) is None

    missing_surface = json.loads(receipt())
    del missing_surface["surfaces"]["render"]
    assert growth.parse_doctor_receipt(json.dumps(missing_surface)) is None

    legacy_yaml = """receipt_version: 1\nproduct_version: 0.1.2\nos_family: macos\nskill_manifest_status: ok\n"""
    assert growth.parse_doctor_receipt(legacy_yaml) is None


def test_install_confirmations_exclude_owner_bots_prelaunch_and_duplicates() -> None:
    launch = dt.datetime(2026, 7, 20, tzinfo=dt.UTC)
    comments = [
        {"author": {"login": "alice", "type": "User"}, "createdAt": "2026-07-21T00:00:00Z", "body": receipt(), "url": "https://github.com/x#1"},
        {"author": {"login": "Alice", "type": "User"}, "createdAt": "2026-07-22T00:00:00Z", "body": receipt(), "url": "https://github.com/x#2"},
        {"author": {"login": "lonelydoctor", "type": "User"}, "createdAt": "2026-07-21T00:00:00Z", "body": receipt()},
        {"author": {"login": "dependabot[bot]", "type": "Bot"}, "createdAt": "2026-07-21T00:00:00Z", "body": receipt()},
        {"author": {"login": "before", "type": "User"}, "createdAt": "2026-07-19T00:00:00Z", "body": receipt()},
        {"author": {"login": "invalid", "type": "User"}, "createdAt": "2026-07-21T00:00:00Z", "body": "installed"},
        {"author": {"login": "old-version", "type": "User"}, "createdAt": "2026-07-21T00:00:00Z", "body": receipt("0.1.1")},
    ]

    valid = growth.valid_install_confirmations(comments, "lonelydoctor", launch)

    assert [row["login"] for row in valid] == ["alice"]
    assert valid[0]["url"].endswith("#1")


def test_external_feedback_requires_maintainer_reply_and_valid_labels() -> None:
    launch = dt.datetime(2026, 7, 20, tzinfo=dt.UTC)
    base = {
        "kind": "issue",
        "number": 12,
        "title": "Install failed on Windows",
        "url": "https://github.com/lonelydoctor/loyalty-radar/issues/12",
        "created_at": "2026-07-21T00:00:00Z",
        "user": {"login": "external-user", "type": "User"},
        "labels": [],
        "comments": [{"user": {"login": "maintainer"}, "author_association": "MEMBER"}],
    }
    assert growth.qualifies_external_feedback(base, "lonelydoctor", launch)
    assert not growth.qualifies_external_feedback(base | {"comments": []}, "lonelydoctor", launch)
    assert not growth.qualifies_external_feedback(base | {"labels": [{"name": "duplicate"}]}, "lonelydoctor", launch)
    assert not growth.qualifies_external_feedback(base | {"pull_request": {}}, "lonelydoctor", launch)


def test_source_contribution_accepts_merged_pack_pr_or_accepted_request() -> None:
    launch = dt.datetime(2026, 7, 20, tzinfo=dt.UTC)
    author = {"login": "contributor", "type": "User"}
    pull = {
        "kind": "pull_request",
        "user": author,
        "merged_at": "2026-07-22T00:00:00Z",
        "files": [{"filename": "plugins/loyalty-radar/skills/loyalty-radar/references/source-packs/japan.yaml"}],
    }
    request = {
        "kind": "issue",
        "user": author,
        "closed_at": "2026-07-22T00:00:00Z",
        "labels": [{"name": "source-accepted"}],
    }
    unrelated = pull | {"files": [{"filename": "README.md"}]}

    assert growth.qualifies_source_contribution(pull, "lonelydoctor", launch)
    assert growth.qualifies_source_contribution(request, "lonelydoctor", launch)
    assert not growth.qualifies_source_contribution(unrelated, "lonelydoctor", launch)


def public_event(index: int = 1, title: str = "Chase transfer bonus ends July 31") -> dict:
    return {
        "event_id": f"event-{index}",
        "lane": "c-end",
        "priority": "P0",
        "published_at": f"2026-07-{20 + index:02d}T08:00:00Z",
        "metric_snippets": ["25%"],
        "future_event_dates": ["2026-07-31"],
        "localized": {
            "en": {"title": title, "summary": "A source-linked offer summary.", "why_it_matters": "Registration may be required."},
            "zh-CN": {"title": "Chase 转点奖励将于 7 月 31 日结束", "summary": "这是带来源链接的优惠摘要。", "why_it_matters": "可能需要报名。"},
        },
        "source_refs": [
            {
                "source_id": "frequent-miler",
                "source": "Frequent Miler",
                "source_type": "rss",
                "url": f"https://frequentmiler.com/offer-{index}",
                "published_at": f"2026-07-{20 + index:02d}T08:00:00Z",
            }
        ],
        "taxonomy": {
            "programs": ["Chase"],
            "card_families": ["Sapphire"],
            "topic_type": "transfer_bonus",
            "verticals": ["credit_card"],
            "ecosystem_signal_types": [],
            "stakeholders": ["member"],
            "consumer_impact": "直接可用",
            "impact_horizon": "this_week",
        },
        "confidence_label": "博客整理",
        "risk_label": "正常权益",
        "action_label": "需报名",
    }


def public_report(items: list[dict] | None = None) -> dict:
    rows = items if items is not None else [public_event()]
    return {
        "schema_id": "loyalty-radar-public-report/v1",
        "publication": {
            "policy": "public",
            "product": {"name": "Loyalty Radar", "version": "0.1.2"},
            "generated_at": "2026-07-24T01:27:00Z",
            "audited_at": "2026-07-24T02:00:00Z",
            "mode": "weekly",
            "focus": "all",
            "hours": 336,
            "future_watch_days": 60,
            "timezone": "UTC",
            "source_packs": ["core", "industry", "forums-global", "forums-cn"],
            "locales": ["en", "zh-CN"],
            "event_count": len(rows),
        },
        "items": rows,
        "health": {
            "configured_sources": 59,
            "script_eligible_sources": 53,
            "script_ok_sources": 44,
            "script_ok_rate": 0.8302,
            "p0_script_sources": 12,
            "p0_ok_sources": 11,
            "p0_ok_rate": 0.9167,
            "status_counts": {"ok": 44, "failed": 9, "skipped": 6},
            "events_checked": len(rows),
            "duplicate_events": 0,
            "duplicate_rate": 0.0,
            "top_events_checked": len(rows),
        },
    }


def test_outreach_accepts_only_the_authoritative_schema_id_shape() -> None:
    report = public_report()
    outreach.validate_public_report(report)

    old_shape = dict(report)
    old_shape["schema"] = old_shape.pop("schema_id")
    with pytest.raises(ValueError, match="schema_id"):
        outreach.validate_public_report(old_shape)

    incomplete = public_report()
    incomplete["items"][0]["localized"]["zh-CN"]["summary"] = ""
    with pytest.raises(ValueError, match="localized.zh-CN"):
        outreach.validate_public_report(incomplete)


def test_outreach_drafts_are_deterministic_and_flyertalk_is_self_contained() -> None:
    report = public_report()
    first = outreach.build_drafts(report, "2026-W30")
    second = outreach.build_drafts(report, "2026-W30")

    assert first == second
    assert "I am the maintainer" in first["flyertalk.md"]
    assert "The highest-priority findings" in first["flyertalk.md"]
    assert "Chase transfer bonus" in first["flyertalk.md"]
    assert "返利或付费推广" in first["flyert.md"]


def test_authoritative_public_report_builds_bilingual_pages(tmp_path: Path) -> None:
    reports = tmp_path / "public-briefs"
    report_path = reports / "2026-W30" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(public_report(), ensure_ascii=False), encoding="utf-8"
    )
    site = tmp_path / "site"

    report_count, source_count = public_site.build(
        site, reports, public_site.PACK_DIR
    )

    assert report_count == 1
    assert source_count == 59
    en = (site / "en" / "index.html").read_text(encoding="utf-8")
    zh = (site / "zh-CN" / "index.html").read_text(encoding="utf-8")
    assert "Chase transfer bonus ends July 31" in en
    assert "Chase 转点奖励将于 7 月 31 日结束" in zh
    assert '<span class="badge priority">P0</span>' in en
    assert 'data-health="duplicate_events"><strong>0</strong>' in en
    assert "https://frequentmiler.com/offer-1" in en
    assert not list(site.rglob("*.json"))


def test_public_site_rejects_lane_taxonomy_mismatch(tmp_path: Path) -> None:
    report = public_report()
    report["items"][0]["lane"] = "ecosystem"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicts with its audited taxonomy"):
        public_site.load_public_report(path, "2026-W30")


def test_public_site_accepts_member_risk_with_ecosystem_signal(tmp_path: Path) -> None:
    report = public_report()
    event = report["items"][0]
    event["taxonomy"]["topic_type"] = "clawback"
    event["taxonomy"]["ecosystem_signal_types"] = ["operational_reliability"]
    event["lane"] = "c-end"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    loaded = public_site.load_public_report(path, "2026-W30")

    assert loaded.events[0]["lane"] == "c-end"


def test_growth_snapshot_uses_release_date_and_excludes_traffic() -> None:
    launch = "2026-07-20T00:00:00Z"
    payload = {
        "repository": {"stargazers_count": 8, "forks_count": 3},
        "releases": [{"tag_name": "v0.1.2", "published_at": launch, "assets": [{"download_count": 4}]}],
        "stargazers": [
            {"starred_at": "2026-07-19T00:00:00Z"},
            {"starred_at": "2026-07-21T00:00:00Z"},
        ],
        "install_comments": [{"author": {"login": "alice"}, "createdAt": "2026-07-21T00:00:00Z", "body": receipt()}],
        "issues": [],
        "discussions": [],
        "pull_requests": [],
        "contributors": [
            {"login": "lonelydoctor", "type": "User"},
            {"login": "alice", "type": "User"},
            {"login": "dependabot[bot]", "type": "Bot"},
        ],
        "traffic": {
            "status": "available",
            "views": {"count": 20, "uniques": 12},
            "popular_paths": [
                {"path": "/lonelydoctor/loyalty-radar/reports/2026-W30", "title": "Weekly Brief", "count": 8, "uniques": 5},
                {"path": "/lonelydoctor/loyalty-radar", "title": "Repository", "count": 12, "uniques": 7},
            ],
            "popular_referrers": [{"referrer": "news.ycombinator.com", "count": 6, "uniques": 4}],
            "clones": {"status": "excluded"},
        },
        "workflows": [],
        "pages": {"status": "built"},
    }

    snapshot, state = growth.build_snapshot(
        payload,
        repository_name="lonelydoctor/loyalty-radar",
        now=dt.datetime(2026, 7, 22, tzinfo=dt.UTC),
    )

    assert snapshot["campaign"]["day"] == 2
    assert snapshot["metrics"]["stars"]["baseline"] == 1
    assert snapshot["metrics"]["stars"]["gained"] == 7
    assert snapshot["metrics"]["confirmed_external_installs"]["count"] == 1
    assert snapshot["metrics"]["auxiliary"]["forks"] == 3
    assert snapshot["metrics"]["auxiliary"]["external_contributors"]["logins"] == ["alice"]
    assert snapshot["metrics"]["auxiliary"]["report_pages"]["uniques"] == 5
    assert snapshot["metrics"]["auxiliary"]["popular_referrers"][0]["referrer"] == "news.ycombinator.com"
    assert snapshot["health"]["traffic"]["clones"]["status"] == "excluded"
    assert len(state["history"]) == 1


def test_net_new_stars_can_be_negative_and_milestone_is_resolvable() -> None:
    payload = {
        "repository": {"stargazers_count": 3},
        "releases": [{"tag_name": "v0.1.2", "published_at": "2026-07-20T00:00:00Z", "assets": []}],
        "stargazers": [],
        "install_comments": [],
        "issues": [],
        "discussions": [],
        "pull_requests": [],
        "contributors": [],
        "workflows": [],
        "pages": {},
    }
    snapshot, _ = growth.build_snapshot(
        payload,
        repository_name="lonelydoctor/loyalty-radar",
        now=dt.datetime(2026, 7, 22, tzinfo=dt.UTC),
        prior_state={
            "launch_at": "2026-07-20T00:00:00+00:00",
            "star_baseline": 5,
            "history": [],
        },
    )

    assert snapshot["metrics"]["stars"]["gained"] == -2
    assert growth.resolve_milestone_number([{"number": 7, "title": "v0.1.2 Public Launch"}]) == 7
    assert growth.resolve_milestone_number([], explicit=12) == 12


def test_first_release_observation_replaces_prelaunch_star_baseline() -> None:
    payload = {
        "repository": {"stargazers_count": 4},
        "releases": [
            {
                "tag_name": "v0.1.2",
                "published_at": "2026-07-20T00:00:00Z",
                "assets": [],
            }
        ],
        "stargazers": [
            {"starred_at": "2026-07-19T00:00:00Z"},
            {"starred_at": "2026-07-20T01:00:00Z"},
        ],
        "install_comments": [],
        "issues": [],
        "discussions": [],
        "pull_requests": [],
        "contributors": [],
        "workflows": [],
        "pages": {},
    }

    snapshot, state = growth.build_snapshot(
        payload,
        repository_name="lonelydoctor/loyalty-radar",
        now=dt.datetime(2026, 7, 20, 2, tzinfo=dt.UTC),
        prior_state={"star_baseline": 0, "launch_at": None, "history": []},
    )

    assert snapshot["metrics"]["stars"]["baseline"] == 1
    assert snapshot["metrics"]["stars"]["gained"] == 3
    assert state["launch_at"] == "2026-07-20T00:00:00+00:00"


def workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_job_environment_does_not_use_runner_context() -> None:
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line != "    env:":
                continue
            block: list[str] = []
            for candidate in lines[index + 1 :]:
                if candidate and not candidate.startswith("      "):
                    break
                block.append(candidate)
            assert "${{ runner." not in "\n".join(block), path.name


def test_weekly_public_brief_workflow_has_audited_dry_run_and_no_auto_merge() -> None:
    text = workflow("weekly-public-brief.yml")

    assert 'cron: "27 1 * * 2"' in text
    assert "dry_run:" in text
    assert "--preset public-weekly" in text
    assert "loyalty-radar audit" in text
    assert "--policy public" in text
    assert "build_public_site.py" in text
    assert "generate_outreach.py audit" not in text
    assert "retention-days: 14" in text
    assert "bot/brief-${WEEK}" in text
    assert "gh pr merge" not in text
    assert "--auto" not in text


def test_growth_workflow_has_no_checkout_and_only_github_native_inputs() -> None:
    text = workflow("growth-metrics.yml")

    assert 'cron: "13 2 * * *"' in text
    assert "actions/checkout" not in text
    assert "INSTALL_CONFIRMATION_DISCUSSION_NUMBER" in text
    assert "GROWTH_MILESTONE_NUMBER" in text
    assert "growth_metrics.py" in text
    assert "retention-days: 90" in text
    assert "GITHUB_TOKEN" in text
    assert not any(value in text for value in ("TWITTER_TOKEN", "REDDIT_TOKEN", "FLYERTALK_TOKEN", "V2EX_TOKEN"))


def test_discussion_feedback_query_stays_below_github_node_budget() -> None:
    query = growth.DISCUSSIONS_QUERY

    assert "discussions(first:50" in query
    assert "comments(first:50)" in query
    assert "replies(first:20)" in query
    assert "discussions(first:100" not in query


def test_stargazer_collection_degrades_to_the_current_count_baseline() -> None:
    class Client:
        repository = "lonelydoctor/loyalty-radar"

        def __init__(self) -> None:
            self.calls = 0

        def paginate(self, _path: str, **kwargs):
            self.calls += 1
            raise growth.GitHubAPIError("token cannot list stargazers")

    client = Client()
    warnings: list[str] = []

    rows = growth.collect_stargazers(client, warnings)

    assert rows == []
    assert client.calls == 1
    assert "current public star count" in warnings[0]


def test_approved_merge_workflow_only_posts_inside_github_and_uploads_drafts() -> None:
    text = workflow("public-brief-merged.yml")

    assert "github.event.pull_request.merged == true" in text
    assert "public-report" in text
    assert "--publish-announcement" in text
    assert "actions/upload-artifact@v7" in text
    assert not any(value in text for value in ("curl twitter", "reddit.com/api", "flyertalk.com/login", "v2ex.com/api"))


def test_network_skills_check_is_isolated_from_fixture_pr_tests() -> None:
    ci = workflow("ci.yml")
    ecosystem = workflow("ecosystem-smoke.yml")
    release = workflow("release.yml")

    assert "npx --yes skills" not in ci
    assert "continue-on-error: true" in ecosystem
    assert 'npx --yes skills add "${GITHUB_REPOSITORY}" --list' in ecosystem
    assert "uv tool install" in ci
    assert "uv tool install" in release
    assert "uv tool install --python 3.12 --force --from" not in ci + release
    assert "continue-on-error: true" in release
