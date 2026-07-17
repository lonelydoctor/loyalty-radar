from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from loyalty_radar import __version__, cli
from loyalty_radar.config import load_settings, load_yaml
from loyalty_radar.i18n import load_catalog, validate_catalogs
from loyalty_radar.paths import REFERENCES_DIR
from loyalty_radar.rendering import (
    render_html,
    render_locale,
    render_markdown,
    render_overview_html,
    select_overview_events,
)
from loyalty_radar.schema import (
    SCHEMA_VERSION,
    build_report,
    read_report,
    upgrade_report,
    write_report,
)
from loyalty_radar.sources import combine_packs, list_packs, validate_all_packs, validate_pack_data
from loyalty_radar.translation import (
    _postprocess_report_locale,
    _postprocess_translation,
    localize_report,
)


class FakeProvider:
    name = "fake"
    model = "fixture-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, str]] = []

    def translate_batch(self, texts: list[str], source_locale: str, target_locale: str) -> list[str]:
        self.calls.append((texts, source_locale, target_locale))
        prefix = "中译" if target_locale == "zh-CN" else "EN"
        return [f"{prefix}: {text}" for text in texts]


def sample_report() -> dict:
    return {
        "schema_version": "1.0",
        "product": {"name": "Loyalty Radar", "version": "0.1.0"},
        "generated_at": "2026-07-11T08:30:00+08:00",
        "mode": "daily",
        "focus": "all",
        "hours": 336,
        "future_watch_days": 60,
        "timezone": "Asia/Shanghai",
        "source_packs": ["core", "industry"],
        "items": [
            {
                "event_id": "member-1",
                "url": "https://example.invalid/member-1",
                "source": "Synthetic Member Desk",
                "source_id": "synthetic-member",
                "source_type": "rss",
                "priority": "P0",
                "priority_tier": "P0 必须关注",
                "program": ["Atlas Rewards"],
                "card_family": ["Summit Card"],
                "topic_type": "transfer_bonus",
                "published_at": "2026-07-10T10:00:00+00:00",
                "confidence_label": "多源证实",
                "risk_label": "正常权益",
                "score": 180,
                "vertical": ["credit_card", "airline"],
                "ecosystem_signal_type": [],
                "stakeholders": ["member", "issuer"],
                "consumer_impact": "直接可用",
                "impact_horizon": "next_60_days",
                "action_label": "需报名",
                "metric_snippets": ["30%"],
                "future_event_dates": ["2026-08-15"],
                "raw_tags": [],
                "original": {
                    "title": "ORIGINAL_MEMBER_TITLE_SHOULD_NOT_LEAK",
                    "summary": "ORIGINAL_MEMBER_SUMMARY_SHOULD_NOT_LEAK",
                    "why_it_matters": "ORIGINAL_MEMBER_WHY_SHOULD_NOT_LEAK",
                },
                "localized": {
                    "en": {"title": "Synthetic 30% transfer bonus", "summary": "A fictional limited transfer window.", "why_it_matters": "The deadline is explicit."},
                    "zh-CN": {"title": "合成示例：30% 转点奖励", "summary": "这是虚构的限时转点窗口。", "why_it_matters": "截止日期明确。"},
                },
                "evidence": [
                    {
                        "source_id": "synthetic-member",
                        "source": "Synthetic Member Desk",
                        "source_type": "rss",
                        "url": "https://example.invalid/evidence/member-1",
                        "published_at": "2026-07-10T10:00:00+00:00",
                        "original": {"title": "ORIGINAL_EVIDENCE_SHOULD_NOT_LEAK", "summary": "ORIGINAL_EVIDENCE_SUMMARY"},
                        "localized": {
                            "en": {"title": "Synthetic member evidence", "summary": "A fictional datapoint."},
                            "zh-CN": {"title": "合成会员证据", "summary": "一条虚构实测。"},
                        },
                    }
                ],
            },
            {
                "event_id": "industry-1",
                "url": "https://example.invalid/industry-1",
                "source": "Synthetic Industry Wire",
                "source_id": "synthetic-industry",
                "source_type": "rss",
                "priority": "P1",
                "priority_tier": "P1 高价值",
                "program": ["Atlas Hotels"],
                "card_family": [],
                "topic_type": "industry_signal",
                "published_at": "2026-07-09T12:00:00+00:00",
                "confidence_label": "博客整理",
                "risk_label": "YMMV",
                "score": 150,
                "vertical": ["hotel"],
                "ecosystem_signal_type": ["cost_reimbursement_conflict"],
                "stakeholders": ["member", "hotel_owner"],
                "consumer_impact": "长期观察",
                "impact_horizon": "watchlist",
                "action_label": "只观察",
                "metric_snippets": ["42 owners", "18%"],
                "future_event_dates": [],
                "raw_tags": [],
                "original": {"title": "ORIGINAL_INDUSTRY_TITLE", "summary": "ORIGINAL_INDUSTRY_SUMMARY", "why_it_matters": "ORIGINAL_INDUSTRY_WHY"},
                "localized": {
                    "en": {"title": "Synthetic owners debate reimbursement", "summary": "A fictional hotel-owner dispute.", "why_it_matters": "It may change award-night economics."},
                    "zh-CN": {"title": "合成示例：业主讨论积分房补偿", "summary": "这是虚构的酒店业主争议。", "why_it_matters": "可能改变积分房经济模型。"},
                },
                "evidence": [],
            },
        ],
        "health": [
            {"source_id": "synthetic-member", "source": "Synthetic Member Desk", "status": "ok", "items": 3, "detail": "parsed", "url": "https://example.invalid/source/member", "fetched": 3, "dated": 3, "eligible": 2, "rejected": 1, "duplicate": 0, "selected": 1},
            {"source_id": "synthetic-browser", "source": "Synthetic Browser Source", "status": "skipped", "items": 0, "detail": "browser-only source", "url": "https://example.invalid/source/browser", "fetched": 0, "dated": 0, "eligible": 0, "rejected": 0, "duplicate": 0, "selected": 0},
        ],
        "translation_health": {},
    }


class I18nAndSchemaTests(unittest.TestCase):
    def test_locale_catalogs_have_identical_keys(self) -> None:
        self.assertEqual(validate_catalogs(), [])
        self.assertEqual(load_catalog("zh").locale, "zh-CN")

    def test_legacy_json_is_upgraded_without_losing_original(self) -> None:
        legacy = {
            "generated_at": "2026-07-11T00:00:00+00:00",
            "items": [{"title": "Original", "summary": "Body", "why_it_matters": "Why", "title_zh": "中文标题", "summary_zh": "中文摘要", "url": "https://example.invalid/a", "evidence": []}],
            "health": [],
        }
        upgraded = upgrade_report(legacy)
        self.assertEqual(upgraded["schema_version"], SCHEMA_VERSION)
        self.assertEqual(upgraded["items"][0]["original"]["title"], "Original")
        self.assertEqual(upgraded["items"][0]["localized"]["zh-CN"]["title"], "中文标题")

    def test_report_round_trip_keeps_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report(sample_report(), path)
            payload = read_report(path)
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["items"][0]["original"]["title"], "ORIGINAL_MEMBER_TITLE_SHOULD_NOT_LEAK")

    def test_new_reports_use_the_installed_product_version(self) -> None:
        payload = build_report(
            [],
            [],
            generated_at="2026-07-15T00:00:00+00:00",
            mode="daily",
            focus="all",
            hours=336,
            timezone="UTC",
        )
        self.assertEqual(payload["product"]["version"], __version__)


class TranslationTests(unittest.TestCase):
    def test_loyalty_glossary_repairs_misleading_public_translation(self) -> None:
        self.assertEqual(
            _postprocess_translation(
                "Chase 向 IHG 提供 100% 转会奖金：不要错过",
                "Chase offers a 100% transfer bonus to IHG: give it a miss",
                "zh-CN",
            ),
            "Chase 向 IHG 提供 100% 转点奖励：不建议转点",
        )
        self.assertEqual(
            _postprocess_translation(
                "Chase Sapphire 首选100,000积分优惠",
                "Chase Sapphire Preferred 100,000 points offer",
                "zh-CN",
            ),
            "Chase Sapphire Preferred 100,000 积分优惠",
        )

    def test_bonus_points_context_repairs_currency_mistranslation(self) -> None:
        payload = {
            "items": [
                {
                    "original": {
                        "title": "ALL Accor Up To 7,500 Per Stay",
                        "summary": "Members can earn up to 7,500 bonus points per stay.",
                    },
                    "localized": {"zh-CN": {"title": "ALL Accor 每次住宿最高 7,500 元"}},
                }
            ]
        }
        _postprocess_report_locale(payload, "zh-CN")
        self.assertEqual(
            payload["items"][0]["localized"]["zh-CN"]["title"],
            "ALL Accor 每次住宿最高 7,500 点奖励积分",
        )

    def test_existing_localized_fields_receive_glossary_repairs(self) -> None:
        payload = {
            "items": [
                {
                    "original": {
                        "title": "Chase Sapphire Preferred 100,000 points offer",
                        "summary": "",
                        "why_it_matters": "",
                    },
                    "localized": {"zh-CN": {"title": "Chase Sapphire 首选100,000积分优惠"}},
                    "evidence": [],
                }
            ]
        }
        _postprocess_report_locale(payload, "zh-CN")
        self.assertEqual(
            payload["items"][0]["localized"]["zh-CN"]["title"],
            "Chase Sapphire Preferred 100,000 积分优惠",
        )

    def test_batch_provider_populates_target_locale_and_cache(self) -> None:
        payload = sample_report()
        for event in payload["items"]:
            event["localized"].pop("zh-CN", None)
            for evidence in event["evidence"]:
                evidence["localized"].pop("zh-CN", None)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            provider = FakeProvider()
            health = localize_report(payload, "zh-CN", provider, cache_path=cache, batch_size=2)
            self.assertGreater(health.translated, 0)
            self.assertEqual(health.cache_path, "cache.json")
            self.assertTrue(payload["items"][0]["localized"]["zh-CN"]["title"].startswith("中译:"))
            second = FakeProvider()
            cached_health = localize_report(payload, "zh-CN", second, cache_path=cache)
            self.assertEqual(cached_health.requested, 0)
            self.assertEqual(second.calls, [])

    def test_cache_keys_are_isolated_by_locale_and_model(self) -> None:
        payload = sample_report()
        payload["items"][0]["localized"].pop("zh-CN", None)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            first = FakeProvider()
            localize_report(payload, "zh-CN", first, cache_path=cache)
            payload["items"][0]["localized"].pop("zh-CN", None)
            second = FakeProvider()
            second.model = "fixture-v2"
            localize_report(payload, "zh-CN", second, cache_path=cache)
            self.assertTrue(second.calls)


class SourcePackAndConfigTests(unittest.TestCase):
    def test_catalog_has_five_packs_and_59_unique_sources(self) -> None:
        packs = list_packs()
        self.assertEqual(len(packs), 5)
        self.assertEqual(sum(len(pack.sources) for pack in packs), 59)
        sources, _ = combine_packs([pack.pack_id for pack in packs])
        self.assertEqual(len({source["id"] for source in sources}), 59)
        self.assertEqual(validate_all_packs(), [])

    def test_source_pack_validator_rejects_bad_url_and_duplicate_id(self) -> None:
        payload = {
            "pack": {"id": "bad", "name": "Bad", "default_enabled": False},
            "sources": [
                {"id": "same", "name": "One", "url": "javascript:alert(1)", "priority": "P0", "fetch_method": "rss", "default_limit": 1, "rate_limit_seconds": 0},
                {"id": "same", "name": "Two", "url": "https://example.invalid/two", "priority": "P9", "fetch_method": "login", "default_limit": 0, "rate_limit_seconds": -1},
            ],
        }
        errors = validate_pack_data(payload)
        self.assertTrue(any("http(s)" in error for error in errors))
        self.assertTrue(any("duplicates" in error for error in errors))
        self.assertTrue(any("unsupported" in error for error in errors))

    def test_init_writes_only_to_requested_user_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code = cli.main(["init", "--non-interactive", "--config-dir", directory, "--locale", "zh-CN", "--membership", "Atlas Rewards=Gold", "--issuer", "Chase", "--card", "Synthetic Card"])
            self.assertEqual(exit_code, 0)
            settings = load_settings(Path(directory))
            self.assertEqual(settings["locale"], "zh-CN")
            self.assertEqual(load_yaml(Path(directory) / "cards.yaml")["held_cards"], ["Synthetic Card"])
            self.assertEqual(load_yaml(Path(directory) / "profile.yaml")["ranking"]["direct_cards"], ["Synthetic Card"])
            self.assertEqual(load_yaml(Path(directory) / "profile.yaml")["loyalty_profile"]["hotel"][0]["status"], "Gold")
            self.assertIn("forums-cn", settings["source_packs"])
            repository_profile = load_yaml(REFERENCES_DIR / "profile.default.yaml")
            self.assertEqual(repository_profile["ranking"]["direct_programs"], [])


class RenderingTests(unittest.TestCase):
    def test_visible_html_uses_only_requested_locale(self) -> None:
        payload = sample_report()
        rendered = render_html(payload, "zh-CN", "demo", ["zh-CN", "en"])
        self.assertIn("合成示例：30% 转点奖励", rendered)
        self.assertNotIn("ORIGINAL_MEMBER_TITLE_SHOULD_NOT_LEAK", rendered)
        self.assertNotIn("ORIGINAL_EVIDENCE_SHOULD_NOT_LEAK", rendered)
        self.assertEqual(rendered.count('class="event-card"'), len(payload["items"]))
        self.assertIn("demo-en.html", rendered)

    def test_long_title_is_complete_and_not_line_clamped(self) -> None:
        payload = sample_report()
        long_title = "完整长标题" * 80
        payload["items"][0]["localized"]["zh-CN"]["title"] = long_title
        rendered = render_html(payload, "zh-CN", "demo", ["zh-CN"])
        self.assertIn(long_title, rendered)
        self.assertNotIn("line-clamp", rendered)
        self.assertNotIn("text-overflow:ellipsis", rendered.replace(" ", ""))

    def test_markdown_does_not_leak_original_text(self) -> None:
        rendered = render_markdown(sample_report(), "en")
        self.assertIn("Synthetic 30% transfer bonus", rendered)
        self.assertNotIn("ORIGINAL_MEMBER_TITLE_SHOULD_NOT_LEAK", rendered)

    def test_visible_links_reject_non_http_schemes(self) -> None:
        payload = sample_report()
        payload["items"][0]["url"] = "javascript:alert(1)"
        payload["items"][0]["evidence"][0]["url"] = "data:text/html,unsafe"
        rendered_html = render_html(payload, "en", "demo", ["en"])
        rendered_markdown = render_markdown(payload, "en")
        self.assertNotIn("javascript:", rendered_html)
        self.assertNotIn("data:text", rendered_html)
        self.assertNotIn("javascript:", rendered_markdown)

    def test_overview_is_two_lane_and_bounded(self) -> None:
        payload = sample_report()
        catalog = load_catalog("en")
        selected = select_overview_events(payload["items"] * 8, "en", catalog)
        self.assertLessEqual(len(selected), 12)
        rendered = render_overview_html(payload, "en")
        self.assertIn("Member play radar", rendered)
        self.assertIn("Loyalty ecosystem radar", rendered)
        self.assertNotIn("ORIGINAL_INDUSTRY_TITLE", rendered)

    def test_render_locale_writes_html_markdown_and_overview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifacts = render_locale(sample_report(), "en", Path(directory), "demo", ["en", "zh-CN"], image=False)
            self.assertTrue(artifacts.html.exists())
            self.assertTrue(artifacts.overview_html.exists())
            self.assertTrue(artifacts.markdown.exists())
            self.assertIsNone(artifacts.png)


if __name__ == "__main__":
    unittest.main()
