from __future__ import annotations

import contextlib
import copy
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from loyalty_radar import cli
from loyalty_radar.config import (
    PUBLIC_WEEKLY_SOURCE_PACKS,
    load_yaml,
    resolve_public_weekly_cards,
    resolve_public_weekly_profile,
)
from loyalty_radar.doctor import DOCTOR_RECEIPT_SCHEMA, build_share_receipt, share_receipt_json
from loyalty_radar.paths import SCHEMAS_DIR
from loyalty_radar.public_audit import (
    PUBLIC_REPORT_SCHEMA_ID,
    PublicAuditError,
    _validate_language_completeness,
    audit_public_report,
)

AUDITED_AT = "2026-07-17T04:00:00+00:00"
RAW_BODY_TOKEN = "RAW_BODY_ALPHA_7492"
RAW_EVIDENCE_TOKEN = "RAW_EVIDENCE_BETA_8315"


def fixture_report() -> dict:
    return {
        "schema_version": "1.0",
        "product": {"name": "Loyalty Radar", "version": "0.1.1"},
        "generated_at": "2026-07-17T03:30:00+00:00",
        "mode": "weekly",
        "focus": "all",
        "hours": 336,
        "future_watch_days": 60,
        "timezone": "UTC",
        "source_packs": ["core"],
        "source_filter": ["doctor-of-credit-cards", "frequent-miler"],
        "items": [
            {
                "event_id": "event-alpha-20260717",
                "url": "https://www.doctorofcredit.com/example-transfer-window/",
                "source": "Doctor of Credit - Credit Cards",
                "source_id": "doctor-of-credit-cards",
                "source_type": "rss",
                "priority": "P0",
                "program": ["Chase", "Flying Blue"],
                "card_family": ["Sapphire"],
                "topic_type": "transfer_bonus",
                "published_at": "2026-07-16T18:00:00+00:00",
                "confidence_label": "多源证实",
                "risk_label": "正常权益",
                "score": 180,
                "vertical": ["credit_card", "airline"],
                "ecosystem_signal_type": [],
                "stakeholders": ["member", "issuer"],
                "consumer_impact": "直接可用",
                "impact_horizon": "next_60_days",
                "action_label": "需报名",
                "metric_snippets": ["25%"],
                "future_event_dates": ["2026-08-31"],
                "raw_tags": ["must remain local"],
                "original": {
                    "title": "Transfer window source headline",
                    "summary": RAW_BODY_TOKEN,
                    "why_it_matters": "Local editorial note",
                },
                "localized": {
                    "en": {
                        "title": "A 25% transfer window is available",
                        "summary": "Localized body text is also excluded",
                        "why_it_matters": "Localized editorial note is excluded",
                    },
                    "zh-CN": {
                        "title": "25% 转点窗口已经开放",
                        "summary": "本地化正文同样不会公开",
                        "why_it_matters": "本地编辑说明不会公开",
                    },
                },
                "evidence": [
                    {
                        "source_id": "frequent-miler",
                        "source": "Frequent Miler",
                        "source_type": "rss",
                        "url": "https://frequentmiler.com/example-transfer-window/",
                        "published_at": "2026-07-16T19:00:00+00:00",
                        "author": "private-by-policy",
                        "original": {"title": "Evidence title", "summary": RAW_EVIDENCE_TOKEN},
                        "localized": {
                            "en": {"title": "Second source", "summary": "Evidence body"},
                            "zh-CN": {"title": "第二个来源", "summary": "证据正文"},
                        },
                    }
                ],
            },
            {
                "event_id": "event-beta-20260717",
                "url": "https://frequentmiler.com/example-hotel-economics/",
                "source": "Frequent Miler",
                "source_id": "frequent-miler",
                "source_type": "rss",
                "priority": "P0",
                "program": ["Marriott"],
                "card_family": [],
                "topic_type": "industry_signal",
                "published_at": "2026-07-15T12:00:00+00:00",
                "confidence_label": "博客整理",
                "risk_label": "YMMV",
                "score": 145,
                "vertical": ["hotel"],
                "ecosystem_signal_type": ["cost_reimbursement_conflict"],
                "stakeholders": ["member", "hotel_owner"],
                "consumer_impact": "长期观察",
                "impact_horizon": "watchlist",
                "action_label": "只观察",
                "metric_snippets": ["51 owners"],
                "future_event_dates": [],
                "raw_tags": [],
                "original": {
                    "title": "Hotel reimbursement source headline",
                    "summary": "ANOTHER_LOCAL_BODY_8821",
                    "why_it_matters": "Another local note",
                },
                "localized": {
                    "en": {
                        "title": "Hotel owners discuss award reimbursement",
                        "summary": "Localized article body",
                        "why_it_matters": "Localized note",
                    },
                    "zh-CN": {
                        "title": "酒店业主讨论积分房补偿",
                        "summary": "本地化文章正文",
                        "why_it_matters": "本地化说明",
                    },
                },
                "evidence": [],
            },
        ],
        "health": [
            {
                "source_id": "doctor-of-credit-cards",
                "source": "Doctor of Credit - Credit Cards",
                "status": "ok",
                "items": 3,
                "detail": "parsed",
                "url": "https://www.doctorofcredit.com/category/credit-cards/feed/",
            },
            {
                "source_id": "frequent-miler",
                "source": "Frequent Miler",
                "status": "ok",
                "items": 4,
                "detail": "parsed",
                "url": "https://frequentmiler.com/feed/",
            },
        ],
        "translation_health": {},
    }


class PublicWeeklyPresetTests(unittest.TestCase):
    def test_default_public_weekly_policy_is_bilingual_and_non_personal(self) -> None:
        args = cli.build_parser().parse_args(["run", "--preset", "public-weekly"])
        effective = cli._effective_run_args(args)
        self.assertEqual(effective.mode, "weekly")
        self.assertEqual(effective.focus, "all")
        self.assertEqual(effective.hours, 336)
        self.assertEqual(effective.timezone, "UTC")
        self.assertEqual(effective.locale, ["en", "zh-CN"])
        self.assertEqual(effective.source_pack, list(PUBLIC_WEEKLY_SOURCE_PACKS))
        self.assertFalse(effective.quiet)
        self.assertEqual(Path(effective.profile), resolve_public_weekly_profile())
        self.assertEqual(Path(effective.cards), resolve_public_weekly_cards())

    def test_public_language_gate_checks_every_event_not_only_top_twenty(self) -> None:
        public_rows = []
        for index in range(21):
            row = {
                "localized": {
                    locale: {
                        "title": f"title-{index}",
                        "summary": "summary",
                        "why_it_matters": "why",
                    }
                    for locale in ("en", "zh-CN")
                }
            }
            public_rows.append(row)
        public_rows[20]["localized"]["zh-CN"]["title"] = ""
        issues: list[str] = []

        _validate_language_completeness(public_rows, issues)

        self.assertEqual(issues, ["item 21 has incomplete zh-CN visible fields: title"])

        profile = load_yaml(resolve_public_weekly_profile())
        cards = load_yaml(resolve_public_weekly_cards())
        self.assertEqual(profile["loyalty_profile"], {"airline": [], "hotel": []})
        self.assertEqual(profile["ranking"]["direct_programs"], [])
        self.assertEqual(profile["ranking"]["direct_issuers"], [])
        self.assertEqual(profile["ranking"]["direct_cards"], [])
        self.assertFalse(profile["ranking"]["allow_undated_fallback"])
        self.assertEqual(profile["ranking"]["max_undated"], 0)
        self.assertEqual(cards, {"held_cards": [], "preferred_issuers": [], "issuers": []})

    def test_safe_options_can_only_narrow_public_weekly(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "run",
                "--preset",
                "public-weekly",
                "--locale",
                "en",
                "--source-id",
                "frequent-miler",
                "--max-sources",
                "1",
                "--per-source-limit",
                "2",
                "--max-items",
                "5",
                "--no-image",
                "--quiet",
            ]
        )
        effective = cli._effective_run_args(args)
        self.assertEqual(effective.locale, ["en"])
        self.assertEqual(effective.source_id, ["frequent-miler"])
        self.assertEqual(effective.max_sources, 1)
        self.assertEqual(effective.per_source_limit, 2)
        self.assertEqual(effective.max_items, 5)
        self.assertTrue(effective.no_image)
        self.assertTrue(effective.quiet)
        engine_args = cli._run_namespace(
            effective,
            Path(effective.profile),
            Path(effective.cards),
            Path("sources.yaml"),
            dt.datetime(2026, 7, 17, tzinfo=dt.UTC),
            effective.hours,
        )
        self.assertTrue(engine_args.quiet)

    def test_personal_or_broadening_overrides_are_rejected(self) -> None:
        args = cli.build_parser().parse_args(
            ["run", "--preset", "public-weekly", "--focus", "bug", "--profile", "profile.yaml"]
        )
        with self.assertRaisesRegex(ValueError, "safe narrowing"):
            cli._effective_run_args(args)

    def test_run_help_documents_preset_precedence(self) -> None:
        parser = cli.build_parser()
        subparsers = next(
            action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
        )
        help_text = " ".join(subparsers.choices["run"].format_help().split())
        self.assertIn("public-weekly precedence", help_text)
        self.assertIn("neutral profile", help_text)


class PublicAuditTests(unittest.TestCase):
    def test_public_output_is_allowlisted_and_summaries_are_deterministic(self) -> None:
        report = fixture_report()
        first = audit_public_report(report, audited_at=AUDITED_AT)
        second = audit_public_report(report, audited_at=AUDITED_AT)
        self.assertEqual(first, second)
        self.assertEqual(first["schema_id"], PUBLIC_REPORT_SCHEMA_ID)
        self.assertEqual(first["publication"]["locales"], ["en", "zh-CN"])
        self.assertEqual(first["health"]["script_ok_rate"], 1.0)
        self.assertEqual(first["health"]["p0_ok_rate"], 1.0)
        self.assertEqual(first["health"]["duplicate_rate"], 0.0)
        self.assertEqual(first["items"][0]["lane"], "c-end")
        self.assertEqual(first["items"][0]["priority"], "P0")
        self.assertEqual(first["items"][1]["lane"], "ecosystem")

        encoded = json.dumps(first, ensure_ascii=False)
        self.assertNotIn(RAW_BODY_TOKEN, encoded)
        self.assertNotIn(RAW_EVIDENCE_TOKEN, encoded)
        self.assertNotIn("Localized article body", encoded)
        self.assertNotIn("author", encoded.casefold())
        self.assertNotIn("original", encoded.casefold())
        self.assertNotIn("raw_tags", encoded.casefold())
        self.assertIn("25%", first["items"][0]["localized"]["en"]["summary"])
        self.assertIn("2 public sources", first["items"][0]["localized"]["en"]["summary"])
        self.assertEqual(
            set(first["items"][0]["source_refs"][0]),
            {"source_id", "source", "source_type", "url", "published_at"},
        )

    def test_public_policy_has_no_minimum_event_count(self) -> None:
        report = fixture_report()
        report["items"] = []
        result = audit_public_report(report, audited_at=AUDITED_AT)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["health"]["top_events_checked"], 0)

    def test_public_metrics_prefer_representative_evidence_and_drop_cluster_noise(self) -> None:
        report = fixture_report()
        event = report["items"][0]
        event["original"]["title"] = "CSP 100,000 Points Offer"
        event["original"]["summary"] = (
            "Earn 100,000 points after $5,000 spend. The annual fee is $95 and the "
            "travel credit is $100. Other text mentions 1:1 to 4:3 and ends 100,000 b..."
        )
        event["localized"]["en"]["title"] = "CSP 100,000 Points Offer"
        event["localized"]["zh-CN"]["title"] = "CSP 100,000 积分优惠"
        event["topic_type"] = "offer"
        event["metric_snippets"] = [
            "100,000 Points",
            "$5,000",
            "$95",
            "$100",
            "1:1",
            "4:3",
            "100%",
            "100,000 b",
        ]

        result = audit_public_report(report, audited_at=AUDITED_AT)

        self.assertEqual(
            result["items"][0]["metric_snippets"],
            ["100,000 Points", "$5,000", "$95", "$100"],
        )
        self.assertNotIn("100%", result["items"][0]["localized"]["en"]["summary"])
        self.assertNotIn("100,000 b", result["items"][0]["localized"]["en"]["summary"])

    def test_quality_gates_reject_health_translation_url_duplicates_and_markers(self) -> None:
        cases: list[tuple[dict, str]] = []

        low_health = fixture_report()
        low_health["health"][1]["status"] = "failed"
        cases.append((low_health, "source ok rate"))

        missing_locale = fixture_report()
        missing_locale["items"][0]["localized"]["zh-CN"]["title"] = ""
        cases.append((missing_locale, "incomplete zh-CN"))

        bad_url = fixture_report()
        bad_url["items"][0]["url"] = "https://example.invalid/not-public"
        cases.append((bad_url, "reserved .invalid"))

        duplicate = fixture_report()
        duplicate_row = copy.deepcopy(duplicate["items"][0])
        duplicate_row["event_id"] = "event-gamma-20260717"
        duplicate["items"].append(duplicate_row)
        cases.append((duplicate, "duplicate rate"))

        marker = fixture_report()
        marker["items"][0]["original"]["summary"] = "A mock publication entry"
        cases.append((marker, "mock marker"))

        for report, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(PublicAuditError) as caught:
                    audit_public_report(report, audited_at=AUDITED_AT)
                self.assertIn(message, " ".join(caught.exception.issues))

    def test_cli_audit_writes_only_the_public_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "full.json"
            output_path = Path(directory) / "public.json"
            input_path.write_text(json.dumps(fixture_report(), ensure_ascii=False), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "audit",
                        "--input-json",
                        str(input_path),
                        "--policy",
                        "public",
                        "--output",
                        str(output_path),
                    ]
                )
            self.assertEqual(code, 0)
            public = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(public["schema_id"], PUBLIC_REPORT_SCHEMA_ID)
            self.assertNotIn(RAW_BODY_TOKEN, output_path.read_text(encoding="utf-8"))

    def test_public_report_schema_is_repository_owned(self) -> None:
        schema = json.loads((SCHEMAS_DIR / "public-report.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_id"]["const"], PUBLIC_REPORT_SCHEMA_ID)
        self.assertFalse(schema["additionalProperties"])


class DoctorReceiptTests(unittest.TestCase):
    def test_share_receipt_is_stable_and_contains_no_identity_or_paths(self) -> None:
        first = build_share_receipt()
        second = build_share_receipt()
        self.assertEqual(first, second)
        self.assertEqual(
            list(first),
            [
                "schema",
                "product",
                "version",
                "python",
                "os",
                "surfaces",
            ],
        )
        self.assertEqual(first["schema"], DOCTOR_RECEIPT_SCHEMA)
        self.assertEqual(first["product"], "loyalty-radar")
        self.assertEqual(first["surfaces"]["skill"], "ok")
        self.assertEqual(first["surfaces"]["plugin"], "ok")
        self.assertEqual(first["surfaces"]["source_catalog"], "ok")
        receipt = share_receipt_json()
        self.assertEqual(json.loads(receipt), first)
        lowered = receipt.casefold()
        for forbidden in (str(Path.home()).casefold(), "username", "profile", "card", "cookie", "ip_address"):
            self.assertNotIn(forbidden, lowered)

    def test_doctor_share_cli_prints_yaml_receipt(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["doctor", "--share"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), build_share_receipt())

    def test_doctor_receipt_round_trips_through_growth_parser(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / ".github" / "scripts" / "growth_metrics.py"
        spec = importlib.util.spec_from_file_location("loyalty_radar_growth_contract", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertEqual(module.parse_doctor_receipt(share_receipt_json()), build_share_receipt())


if __name__ == "__main__":
    unittest.main()
