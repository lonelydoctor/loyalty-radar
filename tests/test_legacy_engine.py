#!/usr/bin/env python3
"""Regression tests for loyalty-intel-digest parsers and classifiers."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import run_digest

PROFILE_KEYWORDS = {
    "Air China": ["Air China", "国航", "凤凰知音"],
    "Star Alliance": ["Star Alliance", "星空联盟", "星盟"],
    "Marriott": ["Marriott", "万豪", "Bonvoy"],
    "Hyatt": ["Hyatt", "凯悦", "World of Hyatt"],
    "Hilton": ["Hilton", "希尔顿"],
    "IHG": ["IHG", "洲际", "优悦会"],
    "Chase": ["Chase", "Ultimate Rewards", "Sapphire", "Ink"],
    "American Express": ["American Express", "Amex", "Membership Rewards", "MR"],
    "Capital One": ["Capital One", "Venture X"],
}

CARD_KEYWORDS = {
    "Sapphire": ["Sapphire", "CSR", "CSP", "The Edit"],
    "Ink": ["Ink", "Ink Plus"],
    "Platinum": ["Platinum", "Biz Plat", "Centurion"],
    "Gold": ["Gold Card", "Amex Gold"],
    "Hilton": ["Hilton Aspire", "Hilton Surpass"],
    "Marriott": ["Marriott Brilliant", "Marriott Boundless"],
    "Delta": ["Delta", "SkyMiles"],
}


class ParserTests(unittest.TestCase):
    def test_parse_datetime_accepts_iso_output_values(self) -> None:
        parsed = run_digest.parse_datetime("2026-07-09T20:35:21+00:00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-07-09T20:35:21+00:00")

    def test_clean_text_repairs_common_rss_mojibake(self) -> None:
        self.assertEqual(run_digest.clean_text("I\u00c2\u0092m sure it wasn\u00c2\u0092t posted."), "I'm sure it wasn't posted.")

    def test_flyert_forum_parser_extracts_relevant_boards(self) -> None:
        html = """
        <html><body>
          <a href="forum.php?mod=viewthread&tid=4851001" data-title="国航白金卡休息室新变化">国航白金卡休息室新变化</a>
          <a href="forum.php?mod=viewthread&tid=4851002" data-title="万豪旅享家_文章标题">万豪旅享家 Q3 活动讨论</a>
          <a href="forum.php?mod=viewthread&tid=4851003">海外用卡 Amex Offer 酒店返现 DP</a>
          <a href="forum.php?mod=viewthread&tid=4851003">重复链接</a>
        </body></html>
        """
        rows = run_digest.parse_flyert_forum(
            html,
            {"url": "https://www.flyert.com/forum.php?mod=forumdisplay&fid=68", "name": "飞客测试"},
            10,
        )
        self.assertEqual(len(rows), 3)
        self.assertIn("国航白金卡", rows[0]["title"])
        self.assertEqual(rows[1]["title"], "万豪旅享家 Q3 活动讨论")
        self.assertTrue(rows[0]["url"].startswith("https://www.flyert.com/"))

    def test_rss_parser_extracts_flyertalk_and_doc_comment_fields(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"
          xmlns:content="http://purl.org/rss/1.0/modules/content/"
          xmlns:wfw="http://wellformedweb.org/CommentAPI/"
          xmlns:dc="http://purl.org/dc/elements/1.1/">
          <channel>
            <item>
              <title>Sapphire Preferred refresh including reduced Hyatt transfer ratio to 4:3</title>
              <link>https://example.com/thread</link>
              <pubDate>Wed, 10 Jun 2026 12:27:28 GMT</pubDate>
              <description>Chase Ultimate Rewards to World of Hyatt will decrease from 1:1 to 4:3.</description>
              <content:encoded><![CDATA[<div>Hyatt transfer ratio change and CSR remains 1:1.</div>]]></content:encoded>
              <wfw:commentRss>https://example.com/thread/feed/</wfw:commentRss>
              <dc:creator>notquiteaff</dc:creator>
              <category>Chase | Ultimate Rewards</category>
            </item>
          </channel>
        </rss>
        """
        rows = run_digest.parse_rss_feed(xml, {"source_type": "rss"}, 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["comment_rss"], "https://example.com/thread/feed/")
        self.assertIn("Hyatt transfer ratio", rows[0]["summary"])


class ClassifierTests(unittest.TestCase):
    def classify(self, title: str, summary: str = "") -> run_digest.IntelItem:
        source = {
            "id": "test",
            "name": "Test Source",
            "site": "FlyerTalk",
            "priority": "P0",
            "source_type": "rss",
            "programs": [],
        }
        return run_digest.classify_row(
            {
                "title": title,
                "url": "https://example.com",
                "published_at": "2026-06-21T00:00:00+00:00",
                "summary": summary,
                "raw_tags": [],
                "source_type": "rss",
            },
            source,
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )

    def test_chase_hyatt_transfer_ratio_is_high_priority(self) -> None:
        item = self.classify(
            "Sapphire Preferred refresh (2026) including reduced Hyatt transfer ratio to 4:3",
            "Chase Ultimate Rewards points will transfer to World of Hyatt at a rate of 4:3.",
        )
        self.assertEqual(item.topic_type, "transfer_bonus")
        self.assertIn("Chase", item.program)
        self.assertIn("Hyatt", item.program)
        self.assertGreaterEqual(item.score, 90)

    def test_title_offer_is_not_overridden_by_card_boilerplate(self) -> None:
        item = self.classify(
            "Chase Amazon Prime Visa $200 Signup Bonus",
            "Card details include no annual fee and standard eligibility terms.",
        )
        self.assertEqual(item.topic_type, "offer")
        self.assertEqual(run_digest.loyalty_relevance_reason(item), "non_travel_finance")

    def test_generic_ceo_failure_language_is_not_a_loyalty_bug(self) -> None:
        item = self.classify(
            "SAS CEO exits to become CEO of Air Canada",
            "The current executive failed in a public communication and will leave the airline.",
        )
        self.assertNotEqual(item.topic_type, "bug")
        self.assertEqual(run_digest.loyalty_relevance_reason(item), "generic_travel_news")

    def test_national_park_does_not_trigger_national_car_rental(self) -> None:
        profile = run_digest.flatten_profile_keywords(run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml"))
        cards = run_digest.flatten_card_keywords(run_digest.load_yaml(run_digest.REFERENCES_DIR / "cards.yaml"))
        item = run_digest.classify_row(
            {
                "title": "A Hyatt brand announces its 2027 debut in Zimbabwe",
                "url": "https://example.com/hyatt-zimbabwe",
                "published_at": "2026-07-09T00:00:00+00:00",
                "summary": "The hotel is five minutes from the entrance to a national park.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {"id": "test", "name": "Test", "priority": "P1", "source_type": "rss", "programs": []},
            profile,
            cards,
        )
        self.assertNotIn("National", item.program)
        self.assertNotIn("rental_car", item.vertical)
        self.assertEqual(run_digest.loyalty_relevance_reason(item), "generic_travel_news")

    def test_property_only_forum_thread_is_low_signal_even_if_body_mentions_lounge(self) -> None:
        profile = run_digest.flatten_profile_keywords(run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml"))
        cards = run_digest.flatten_card_keywords(run_digest.load_yaml(run_digest.REFERENCES_DIR / "cards.yaml"))
        item = run_digest.classify_row(
            {
                "title": "Hilton Glasgow versus DoubleTree Glasgow Central",
                "url": "https://example.com/hilton-glasgow",
                "published_at": "2026-07-09T00:00:00+00:00",
                "summary": "A traveler asks which property has the nicer lounge.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {
                "id": "ft-hilton",
                "name": "FlyerTalk Hilton",
                "priority": "P0",
                "source_type": "rss",
                "programs": ["Hilton"],
                "program_fallback": True,
            },
            profile,
            cards,
        )
        self.assertEqual(run_digest.loyalty_relevance_reason(item), "low_signal_forum")

    def test_chase_hotel_credit_clawback_is_risk_item(self) -> None:
        item = self.classify(
            "Chase Clawing Back Hotel Credits For Cancelled Reservations On New Sapphire Preferred Credit",
            "Same for The Edit credits on CSR. Credit was deducted immediately after cancellation.",
        )
        self.assertEqual(item.topic_type, "clawback")
        self.assertEqual(item.risk_label, "可能 clawback")
        self.assertEqual(item.action_label, "高风险勿操作")
        self.assertIn("credit_card", item.vertical)
        self.assertIn("Sapphire", item.card_family)

    def test_amex_flying_blue_failure_is_bug(self) -> None:
        item = self.classify(
            "MR (USA) => Flying Blue not working on first day of transfer bonus",
            "Amex shows confirmation but no miles show up and nothing appears in Membership Rewards history.",
        )
        self.assertEqual(item.topic_type, "bug")
        self.assertIn("American Express", item.program)
        self.assertEqual(item.consumer_impact, "需避坑")
        self.assertEqual(item.risk_label, "YMMV")

    def test_transfer_bonus_extracts_bonus_and_action(self) -> None:
        item = self.classify(
            "Amex Membership Rewards 55% transfer bonus to Flying Blue through July 31",
            "Registration is required before transferring points. The offer is targeted for some accounts.",
        )
        self.assertEqual(item.topic_type, "transfer_bonus")
        self.assertIn("55%", item.metric_snippets)
        self.assertEqual(item.action_label, "需报名")
        self.assertEqual(item.consumer_impact, "直接可用")

    def test_marriott_owner_protest_enters_ecosystem_radar(self) -> None:
        item = self.classify(
            "Marriott owners rebel against Bonvoy reimbursement economics",
            "51 hotel owners complain that loyalty redemption reimbursement is too low while Marriott keeps credit-card and points-sale revenue.",
        )
        self.assertIn("hotel", item.vertical)
        self.assertEqual(item.topic_type, "industry_signal")
        self.assertIn("cost_reimbursement_conflict", item.ecosystem_signal_type)
        self.assertIn("hotel_owner", item.stakeholders)
        self.assertEqual(item.action_label, "只观察")

    def test_branded_franchise_reimbursement_conflict_needs_no_generic_loyalty_word(self) -> None:
        item = self.classify(
            "Marriott franchisees protest reimbursement rates",
            "Hotel owners say reimbursement is too low relative to brand revenue.",
        )
        self.assertIn("cost_reimbursement_conflict", item.ecosystem_signal_type)
        self.assertEqual(item.topic_type, "industry_signal")

    def test_airline_cobrand_financialization_is_ecosystem_signal(self) -> None:
        item = self.classify(
            "Airline miles and co-branded credit cards become profit engines for United and Delta",
            "Airlines sell billions of miles to issuers and reserve elite benefits for higher-spend cardholders.",
        )
        self.assertIn("airline", item.vertical)
        self.assertIn("revenue_shift", item.ecosystem_signal_type)
        self.assertIn("qualification_gatekeeping", item.ecosystem_signal_type)

    def test_dot_cfpb_rewards_scrutiny_is_regulatory_signal(self) -> None:
        item = self.classify(
            "DOT and CFPB scrutinize airline and credit-card rewards programs",
            "Regulators cite bait-and-switch rewards, devaluation, transparency, and consumer complaints.",
        )
        self.assertTrue(set(item.vertical) & {"airline", "credit_card"})
        self.assertIn("regulatory_or_legal_pressure", item.ecosystem_signal_type)
        self.assertIn("regulator", item.stakeholders)

    def test_rental_car_status_match_is_rental_vertical(self) -> None:
        item = self.classify(
            "Hertz and National status match changes reduce elite upgrades at airport locations",
            "Several locations say upgrades are capacity controlled during peak travel weeks.",
        )
        self.assertIn("rental_car", item.vertical)
        self.assertIn(item.topic_type, {"status_match", "policy_change"})
        self.assertTrue(
            set(item.ecosystem_signal_type) & {"qualification_gatekeeping", "benefit_capacity_pressure"}
        )

    def test_future_two_month_event_is_watchlist_item(self) -> None:
        item = run_digest.classify_row(
            {
                "title": "Hyatt award pricing changes begin August 15",
                "url": "https://example.com/future",
                "published_at": "2026-06-21T00:00:00+00:00",
                "summary": "Members have two months to book before the new rates take effect.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {"id": "test", "name": "Test Source", "priority": "P1", "source_type": "rss", "programs": []},
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
            reference_date=dt.datetime(2026, 6, 25, tzinfo=dt.UTC),
        )
        self.assertIn("2026-08-15", item.future_event_dates)
        self.assertEqual(item.impact_horizon, "next_60_days")
        self.assertIn(item, run_digest.section_items([item])["后续观察"])

    def test_broad_credit_card_source_does_not_force_chase_or_amex(self) -> None:
        source = {
            "id": "doctor-of-credit-cards",
            "name": "Doctor of Credit - Credit Cards",
            "site": "Doctor of Credit",
            "priority": "P0",
            "source_type": "rss",
            "programs": ["Chase", "American Express"],
        }
        item = run_digest.classify_row(
            {
                "title": "Capital One Business Spark Cash Select increased signup bonus",
                "url": "https://example.com",
                "published_at": "2026-06-21T00:00:00+00:00",
                "summary": "Not entirely sure it ever went away. Some readers used a referral link.",
                "raw_tags": [],
                "source_type": "rss",
            },
            source,
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        self.assertIn("Capital One", item.program)
        self.assertNotIn("Chase", item.program)
        self.assertNotIn("American Express", item.program)
        self.assertEqual(item.card_family, [])

    def test_specific_board_can_use_program_fallback(self) -> None:
        source = {
            "id": "ft-chase-ur",
            "name": "FlyerTalk - Chase Ultimate Rewards",
            "site": "FlyerTalk",
            "priority": "P0",
            "source_type": "rss",
            "programs": ["Chase"],
            "program_fallback": True,
        }
        item = run_digest.classify_row(
            {
                "title": "Portal redemption value changing for new bookings",
                "url": "https://example.com",
                "published_at": "2026-06-21T00:00:00+00:00",
                "summary": "Several users report a new value in the travel portal.",
                "raw_tags": [],
                "source_type": "rss",
            },
            source,
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        self.assertEqual(item.program, ["Chase"])

    def test_duplicate_flyert_threads_are_merged(self) -> None:
        source_a = {
            "id": "flyert-air-china",
            "name": "飞客茶馆 - 中国国航",
            "site": "Flyert",
            "priority": "P0",
            "source_type": "forum",
            "programs": ["Air China"],
            "program_fallback": True,
        }
        source_b = {
            "id": "flyert-marriott",
            "name": "飞客茶馆 - 万豪旅享家",
            "site": "Flyert",
            "priority": "P0",
            "source_type": "forum",
            "programs": ["Marriott"],
            "program_fallback": True,
        }
        row = {
            "title": "同一篇全站活动帖",
            "url": "https://www.flyert.com/forum.php?mod=viewthread&tid=4852310&extra=page%3D1",
            "published_at": None,
            "summary": "同一篇全站活动帖",
            "raw_tags": [],
            "source_type": "forum",
        }
        items = [
            run_digest.classify_row(row, source_a, PROFILE_KEYWORDS, CARD_KEYWORDS),
            run_digest.classify_row(row, source_b, PROFILE_KEYWORDS, CARD_KEYWORDS),
        ]
        merged = run_digest.dedupe_items(items)
        self.assertEqual(len(merged), 1)
        self.assertIn("中国国航", merged[0].source)
        self.assertIn("万豪", merged[0].source)

    def test_comment_datapoint_keeps_parent_offer_topic(self) -> None:
        item = run_digest.classify_row(
            {
                "title": "评论 DP: Chase Hyatt Credit Card: 75k Offer (45k + 2x Up To 30k)",
                "url": "https://example.com/hyatt-offer#comment-1",
                "published_at": "2026-07-10T01:15:12+00:00",
                "summary": "Not much of a welcome bonus considering the recent devaluation.",
                "raw_tags": [],
                "source_type": "blog_comment",
            },
            {
                "id": "doctor-of-credit-cards",
                "name": "Doctor of Credit",
                "site": "Doctor of Credit",
                "priority": "P0",
                "source_type": "rss",
                "programs": [],
            },
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        self.assertEqual(item.topic_type, "offer")

    def test_non_comment_summary_can_surface_clawback_risk(self) -> None:
        item = run_digest.classify_row(
            {
                "title": "Chase hotel credit offer update",
                "url": "https://example.com/chase-credit-update",
                "published_at": "2026-07-10T01:15:12+00:00",
                "summary": "Chase is clawing back the credit after cancelled reservations.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {
                "id": "source",
                "name": "Source",
                "site": "Source",
                "priority": "P0",
                "source_type": "rss",
                "programs": [],
            },
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        self.assertEqual(item.topic_type, "clawback")

    def test_generic_hotel_lawsuit_is_not_loyalty_ecosystem_signal(self) -> None:
        item = run_digest.classify_row(
            {
                "title": "Pilot's room at Denver Sheraton invaded by bats",
                "url": "https://example.com/hotel-lawsuit",
                "published_at": "2026-07-04T12:22:46+00:00",
                "summary": "The guest received medical treatment and filed a lawsuit against the hotel.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {
                "id": "ft-marriott",
                "name": "FlyerTalk - Marriott Bonvoy",
                "site": "FlyerTalk",
                "priority": "P0",
                "source_type": "rss",
                "programs": ["Marriott"],
                "program_fallback": True,
            },
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        self.assertEqual(item.ecosystem_signal_type, [])
        self.assertNotEqual(item.topic_type, "industry_signal")

    def test_unrelated_lawsuit_with_incidental_points_is_not_ecosystem_signal(self) -> None:
        item = run_digest.classify_row(
            {
                "title": "Guest files lawsuit after hotel room incident",
                "url": "https://example.com/incidental-points-lawsuit",
                "published_at": "2026-07-04T12:22:46+00:00",
                "summary": "The guest earned Bonvoy points for the stay, then filed a lawsuit over a room safety incident.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {
                "id": "source",
                "name": "Source",
                "site": "Source",
                "priority": "P1",
                "source_type": "rss",
                "programs": [],
            },
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        self.assertNotIn("regulatory_or_legal_pressure", item.ecosystem_signal_type)


class EventQualityTests(unittest.TestCase):
    def make_item(
        self,
        title: str,
        source_id: str,
        url: str,
        summary: str = "",
        published_at: str | None = "2026-07-09T12:00:00+00:00",
        priority: str = "P1",
    ) -> run_digest.IntelItem:
        return run_digest.classify_row(
            {
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary": summary,
                "raw_tags": [],
                "source_type": "rss",
            },
            {
                "id": source_id,
                "name": source_id,
                "site": source_id,
                "priority": priority,
                "source_type": "rss",
                "programs": [],
            },
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
            reference_date=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
        )

    def test_strict_window_rejects_undated_items(self) -> None:
        item = self.make_item(
            "Air China lounge access datapoint",
            "flyert-air-china",
            "https://example.com/undated",
            published_at=None,
        )
        self.assertFalse(
            run_digest.within_window(
                item,
                336,
                reference_date=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
                allow_undated=False,
            )
        )

    def test_strict_window_rejects_future_and_invalid_dates(self) -> None:
        reference = dt.datetime(2026, 7, 10, tzinfo=dt.UTC)
        future = self.make_item(
            "Future-dated loyalty item",
            "future-source",
            "https://example.com/future-dated",
            published_at="2026-07-11T00:00:00+00:00",
        )
        invalid = self.make_item(
            "Invalid-date loyalty item",
            "invalid-source",
            "https://example.com/invalid-date",
            published_at="not-a-date",
        )
        self.assertFalse(run_digest.within_window(future, 336, reference_date=reference, allow_undated=False))
        self.assertFalse(run_digest.within_window(invalid, 336, reference_date=reference, allow_undated=False))

    def test_window_accepts_same_day_and_exact_boundary(self) -> None:
        same_day = self.make_item(
            "Same-day loyalty item",
            "same-day",
            "https://example.com/same-day",
            published_at="2026-07-10T18:00:00+00:00",
        )
        boundary = self.make_item(
            "Boundary loyalty item",
            "boundary",
            "https://example.com/boundary",
            published_at="2026-06-26T00:00:00+00:00",
        )
        too_old = self.make_item(
            "Too-old loyalty item",
            "too-old",
            "https://example.com/too-old",
            published_at="2026-06-25T23:59:59+00:00",
        )
        self.assertTrue(run_digest.within_window(same_day, 336, reference_date=dt.date(2026, 7, 10), allow_undated=False))
        reference = dt.datetime(2026, 7, 10, 0, 0, tzinfo=dt.UTC)
        self.assertTrue(run_digest.within_window(boundary, 336, reference_date=reference, allow_undated=False))
        self.assertFalse(run_digest.within_window(too_old, 336, reference_date=reference, allow_undated=False))

    def test_known_cross_board_ad_is_rejected(self) -> None:
        item = self.make_item(
            "兴业三款白金卡火热申办中！商旅健康日常全覆盖，礼遇重磅叠加",
            "flyert-air-china",
            "https://www.flyert.com/forum.php?mod=viewthread&tid=4851000",
            published_at=None,
        )
        self.assertEqual(run_digest.qualification_reason(item, strict_dates=False), "noise")

    def test_noise_matching_does_not_reject_show_to_members_phrase(self) -> None:
        item = self.make_item(
            "Show to members how benefits changed",
            "source",
            "https://example.com/show-to-members",
            "A loyalty program explains its updated elite benefits.",
        )
        self.assertIsNone(run_digest.qualification_reason(item, strict_dates=False))

    def test_marriott_devaluation_sources_form_one_event(self) -> None:
        items = [
            self.make_item(
                "Marriott increases award pricing without notice again",
                "awardwallet",
                "https://awardwallet.example/marriott-award-pricing",
                "Popular properties now cost 5% to 10% more Bonvoy points.",
            ),
            self.make_item(
                "Marriott Bonvoy hit with another 5%-10% points devaluation",
                "dannydealguru",
                "https://danny.example/marriott-devaluation",
                "Award costs rose at many popular Marriott hotels.",
            ),
            self.make_item(
                "Marriott Bonvoy points devaluation: widespread increase in award costs",
                "oma-at",
                "https://oma-at.example/marriott-points-devaluation",
                "Bonvoy award pricing increased across a broad sample of hotels.",
            ),
            self.make_item(
                "Marriott has once again raised award prices at many popular hotels",
                "tpg",
                "https://tpg.example/marriott-raised-award-prices",
                "Data shows higher points prices at popular Marriott properties.",
            ),
        ]
        events = run_digest.cluster_items(items)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0].evidence), 4)
        self.assertEqual(events[0].confidence_label, "多源证实")

    def test_unrelated_same_program_offers_remain_separate(self) -> None:
        events = run_digest.cluster_items(
            [
                self.make_item(
                    "Marriott and United dual points summer promotion",
                    "source-a",
                    "https://example.com/marriott-united",
                ),
                self.make_item(
                    "Marriott Brilliant dining credit targeted offer",
                    "source-b",
                    "https://example.com/marriott-dining-credit",
                ),
            ]
        )
        self.assertEqual(len(events), 2)

    def test_similar_amex_platinum_offers_for_distinct_products_remain_separate(self) -> None:
        events = run_digest.cluster_items(
            [
                self.make_item(
                    "American Express Platinum for Schwab: 150K welcome offer",
                    "source-a",
                    "https://example.com/schwab-platinum",
                    "The Schwab Platinum offer is available to eligible applicants.",
                ),
                self.make_item(
                    "Amex Morgan Stanley Platinum: New 150K welcome offer",
                    "source-b",
                    "https://example.com/morgan-stanley-platinum",
                    "The Morgan Stanley Platinum offer has separate eligibility rules.",
                ),
            ]
        )
        self.assertEqual(len(events), 2)

    def test_same_two_program_promotion_clusters_across_headline_variants(self) -> None:
        first = self.make_item(
            "Marriott Bonvoy and United MileagePlus offer for elites",
            "source-a",
            "https://example.com/marriott-united-offer",
        )
        second = self.make_item(
            "Marriott and United launch Stay Fly Earn summer promotion",
            "source-b",
            "https://example.com/stay-fly-earn",
        )
        first.program = ["Marriott", "United"]
        second.program = ["Marriott", "United"]
        events = run_digest.cluster_items([first, second])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].confidence_label, "多源证实")

    def test_same_partner_announcement_clusters_across_topic_wording(self) -> None:
        first = self.make_item(
            "You can book Explora Journeys cruises with Hilton points",
            "source-a",
            "https://example.com/hilton-explora-booking",
        )
        second = self.make_item(
            "Explora Club expands its Hilton partnership",
            "source-b",
            "https://example.com/explora-hilton-partnership",
        )
        first.program = ["Hilton"]
        second.program = ["Hilton"]
        first.topic_type = "industry_signal"
        second.topic_type = "offer"
        first.ecosystem_signal_type = ["partner_contract_shift"]
        second.ecosystem_signal_type = ["partner_contract_shift"]
        events = run_digest.cluster_items([first, second])
        self.assertEqual(len(events), 1)

    def test_unrelated_cashback_offers_do_not_merge_on_generic_terms(self) -> None:
        events = run_digest.cluster_items(
            [
                self.make_item(
                    "Cathay Pacific Amex Offer: Get $150 back when spending $1K",
                    "source-a",
                    "https://example.com/cathay-amex",
                ),
                self.make_item(
                    "Viator Experiences Chase Offer: Get 8% back on up to $125 spend",
                    "source-b",
                    "https://example.com/viator-chase",
                ),
            ]
        )
        self.assertEqual(len(events), 2)

    def test_direct_profile_event_outranks_unrelated_referral(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        profile["ranking"]["direct_programs"] = ["Marriott", "United"]
        events = run_digest.cluster_items(
            [
                self.make_item(
                    "Marriott Titanium and United elites register for summer dual points",
                    "source-a",
                    "https://example.com/direct-marriott",
                    "Registration ends August 31 for Marriott Titanium members.",
                ),
                self.make_item(
                    "Capital One business referral offers 100,000 bonus points",
                    "source-b",
                    "https://example.com/capital-one-referral",
                    "Targeted referral for existing Capital One business cardholders.",
                ),
            ]
        )
        ranked = run_digest.rank_events(events, profile)
        self.assertIn("Marriott", ranked[0].title)
        self.assertEqual(ranked[0].priority_tier, "P0 必须关注")
        referral = next(event for event in ranked if "Capital One" in event.title)
        self.assertIn(referral.priority_tier, {"P2 值得阅读", "P3 补充信息", "P4 线索库"})

    def test_expired_offer_is_demoted_to_supplemental(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        event = run_digest.cluster_items(
            [
                self.make_item(
                    "[Expired] American Express Platinum 150K welcome offer",
                    "source-a",
                    "https://example.com/expired-amex",
                    "The offer ended yesterday.",
                )
            ]
        )[0]
        ranked = run_digest.rank_events([event], profile)
        self.assertEqual(ranked[0].priority_tier, "P3 补充信息")
        self.assertEqual(ranked[0].action_label, "只观察")

    def test_offer_with_past_ends_date_is_demoted(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        event = run_digest.cluster_items(
            [
                self.make_item(
                    "150K Bonus for Amex Platinum Cards (Ends 7/8)",
                    "source-a",
                    "https://example.com/ended-amex",
                )
            ]
        )[0]
        ranked = run_digest.rank_events(
            [event],
            profile,
            reference_date=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
        )
        self.assertEqual(ranked[0].priority_tier, "P3 补充信息")

    def test_undated_forum_clue_is_never_promoted_above_p4(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        event = run_digest.cluster_items(
            [
                self.make_item(
                    "ANA award booking system bug datapoint",
                    "flyert-star-alliance",
                    "https://example.com/undated-ana-bug",
                    "A single user reports a duplicate segment.",
                    published_at=None,
                )
            ]
        )[0]
        ranked = run_digest.rank_events([event], profile)
        self.assertEqual(ranked[0].priority_tier, "P4 线索库")

    def test_amex_abbreviation_counts_as_explicit_profile_relevance(self) -> None:
        event = self.make_item(
            "Cathay Pacific Amex Offer: Get $150 back",
            "source-a",
            "https://example.com/cathay-amex-offer",
        )
        clustered = run_digest.cluster_items([event])[0]
        self.assertTrue(run_digest.event_title_matches_config(clustered, ["American Express"]))

    def test_uk_card_offer_is_regionally_demoted(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        item = self.make_item(
            "Virgin Atlantic launches a new American Express cashback deal",
            "head-for-points",
            "https://example.com/uk-amex-offer",
            "UK cardholders can register for £200 back on a £2,000 spend.",
        )
        event = run_digest.cluster_items([item])[0]
        self.assertTrue(run_digest.event_is_foreign_market_card_offer(event))
        ranked = run_digest.rank_events([event], profile)
        self.assertIn(ranked[0].priority_tier, {"P2 值得阅读", "P3 补充信息"})
        self.assertEqual(ranked[0].action_label, "只观察")

    def test_structural_devaluation_uses_industry_lane(self) -> None:
        item = self.make_item(
            "Marriott Bonvoy points devaluation raises award prices",
            "source-a",
            "https://example.com/marriott-devaluation-lane",
            "Award costs increased at popular Marriott hotels.",
        )
        event = run_digest.cluster_items([item])[0]
        self.assertEqual(run_digest.event_lane(event), "industry")

    def test_diverse_selection_reserves_rental_and_ecosystem_lanes(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        items = [
            self.make_item(f"Chase Offer number {index}", f"card-{index}", f"https://example.com/card-{index}")
            for index in range(10)
        ]
        items.extend(
            [
                self.make_item(
                    "National Emerald Club status match changes elite upgrade access",
                    "rental-source",
                    "https://example.com/rental",
                    "Rental car locations now capacity-control elite upgrades.",
                ),
                self.make_item(
                    "Hotel owners protest loyalty reimbursement economics",
                    "industry-source",
                    "https://example.com/hotel-owners",
                    "Owners say redemption reimbursement is too low relative to loyalty revenue.",
                ),
            ]
        )
        selected = run_digest.select_diverse_events(run_digest.rank_events(run_digest.cluster_items(items), profile), 8)
        self.assertTrue(any("rental_car" in event.vertical for event in selected))
        self.assertTrue(any(event.ecosystem_signal_type for event in selected))


class SourceCoverageTests(unittest.TestCase):
    def test_focused_airline_and_rental_forum_lanes_are_configured(self) -> None:
        sources = run_digest.load_yaml(run_digest.REFERENCES_DIR / "sources.yaml")["sources"]
        source_ids = {source["id"] for source in sources}
        self.assertTrue(
            {
                "ft-united",
                "ft-aeroplan",
                "ft-ana",
                "ft-krisflyer",
                "ft-miles-more",
                "ft-asiana",
                "ft-rental-car-discussion",
            }.issubset(source_ids)
        )

    def test_google_news_has_signal_specific_global_lanes(self) -> None:
        sources = run_digest.load_yaml(run_digest.REFERENCES_DIR / "sources.yaml")["sources"]
        source_ids = {source["id"] for source in sources}
        self.assertTrue(
            {
                "google-news-loyalty-devaluation",
                "google-news-loyalty-partner-contracts",
                "google-news-loyalty-consumer-backlash",
                "google-news-loyalty-operational-failures",
            }.issubset(source_ids)
        )

    def test_regional_loyalty_sources_cover_uk_canada_and_southeast_asia(self) -> None:
        sources = run_digest.load_yaml(run_digest.REFERENCES_DIR / "sources.yaml")["sources"]
        source_ids = {source["id"] for source in sources}
        self.assertTrue({"head-for-points", "prince-of-travel", "mainly-miles"}.issubset(source_ids))

    def test_profile_defines_ranking_weights_and_diversity_quotas(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        self.assertIn("ranking", profile)
        self.assertIn("weights", profile["ranking"])
        self.assertIn("diversity_quotas", profile["ranking"])
        self.assertTrue(profile["ranking"]["strict_dates"])

    def test_google_news_queries_are_time_bounded_without_fixed_year(self) -> None:
        sources = run_digest.load_yaml(run_digest.REFERENCES_DIR / "sources.yaml")["sources"]
        news_urls = [source["url"] for source in sources if source.get("site") == "Google News"]
        self.assertGreaterEqual(len(news_urls), 10)
        self.assertTrue(all("when:14d" in url for url in news_urls))
        self.assertTrue(all("2026" not in url for url in news_urls))

    def test_source_health_exposes_collection_funnel(self) -> None:
        health = run_digest.SourceHealth(
            "source-id",
            "Source",
            "ok",
            12,
            "parsed",
            "https://example.com/feed",
            fetched=12,
            dated=10,
            eligible=8,
            rejected=2,
            duplicate=1,
            selected=5,
        )
        self.assertEqual(
            (health.fetched, health.dated, health.eligible, health.rejected, health.duplicate, health.selected),
            (12, 10, 8, 2, 1, 5),
        )

    def test_browser_only_source_is_explicitly_reported(self) -> None:
        args = run_digest.build_parser().parse_args([])
        items, health = run_digest.collect_source(
            {
                "id": "reddit-churning",
                "name": "Reddit r/churning",
                "fetch_method": "browser_only",
                "url": "https://www.reddit.com/r/churning/",
                "enabled": True,
                "note": "RSS/JSON often return 403.",
            },
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
            args,
        )
        self.assertEqual(items, [])
        self.assertEqual(health.status, "skipped")
        self.assertIn("403", health.detail)

    def test_unknown_source_id_is_reported(self) -> None:
        args = run_digest.build_parser().parse_args(["--source-id", "not-a-real-source"])
        args.hours = 48
        items, health = run_digest.collect_all(args)
        self.assertEqual(items, [])
        self.assertEqual(health[0].source_id, "not-a-real-source")
        self.assertEqual(health[0].status, "failed")
        self.assertIn("unknown source id", health[0].detail)


class ImageOutputTests(unittest.TestCase):
    def sample_item(self) -> run_digest.IntelItem:
        return run_digest.IntelItem(
            source="Doctor of Credit - Credit Cards",
            source_id="doctor-of-credit-cards",
            source_type="blog_comment",
            priority="P0",
            program=["Chase"],
            card_family=["Sapphire"],
            topic_type="clawback",
            title="Chase hotel credit clawback datapoints",
            url="https://www.doctorofcredit.com/example-post/",
            published_at="2026-06-21T00:00:00+00:00",
            summary="Multiple readers report that hotel credits were deducted after cancelled reservations.",
            why_it_matters="涉及权益扣回或积分/credit 收回，使用 Chase、Sapphire 时需要保守处理。",
            confidence_label="多用户 DP",
            risk_label="可能 clawback",
            score=140,
            vertical=["credit_card"],
            ecosystem_signal_type=["operational_reliability"],
            stakeholders=["member", "issuer"],
            consumer_impact="需避坑",
            impact_horizon="today",
            action_label="高风险勿操作",
            metric_snippets=[],
            future_event_dates=[],
            raw_tags=[],
        )

    def future_item(self) -> run_digest.IntelItem:
        item = self.sample_item()
        item.title = "Amex transfer bonus ends July 31"
        item.url = "https://example.com/future-bonus"
        item.topic_type = "transfer_bonus"
        item.action_label = "需报名"
        item.consumer_impact = "直接可用"
        item.impact_horizon = "next_60_days"
        item.future_event_dates = ["2026-07-31"]
        item.ecosystem_signal_type = []
        item.risk_label = "正常权益"
        return item

    def ecosystem_item(self) -> run_digest.IntelItem:
        item = self.sample_item()
        item.title = "Hotel owners protest loyalty reimbursement economics"
        item.url = "https://example.com/ecosystem"
        item.topic_type = "industry_signal"
        item.action_label = "只观察"
        item.consumer_impact = "长期观察"
        item.impact_horizon = "watchlist"
        item.future_event_dates = []
        item.vertical = ["hotel"]
        item.ecosystem_signal_type = ["cost_reimbursement_conflict"]
        item.risk_label = "正常权益"
        item.score = 120
        return item

    def long_title_item(self) -> run_digest.IntelItem:
        item = self.sample_item()
        item.title = (
            "NotebookLM-style complete title rendering check for a very long loyalty intelligence item "
            "covering Chase Sapphire Reserve credits, Marriott gift cards, Hyatt award access, and future deadlines"
        )
        item.summary = (
            "This deliberately long item verifies that the infographic source keeps every title intact "
            "and uses natural card height instead of fixed-height truncation."
        )
        item.url = "https://example.com/very-long-title"
        item.risk_label = "正常权益"
        item.action_label = "可直接用"
        item.topic_type = "policy_change"
        item.future_event_dates = ["2026-08-31"]
        return item

    def test_item_time_label_converts_to_profile_timezone(self) -> None:
        self.assertEqual(run_digest.item_time_label(self.sample_item(), "Asia/Shanghai"), "06-21 08:00")

    def test_default_profile_uses_two_week_window(self) -> None:
        profile = run_digest.load_yaml(run_digest.REFERENCES_DIR / "profile.yaml")
        self.assertEqual(profile["default_modes"]["daily_hours"], 336)
        self.assertEqual(profile["default_modes"]["weekly_hours"], 336)

    def test_horizontal_layout_profiles_scale_by_information_volume(self) -> None:
        compact = run_digest.infographic_layout_profile(4)
        standard = run_digest.infographic_layout_profile(12)
        dense = run_digest.infographic_layout_profile(24)
        self.assertEqual(compact["name"], "compact")
        self.assertEqual(standard["name"], "standard")
        self.assertEqual(dense["name"], "dense")
        self.assertLess(compact["height"], standard["height"])
        self.assertLess(standard["height"], dense["height"])
        self.assertGreater(compact["width"], compact["height"])

    def test_notebook_style_html_preserves_complete_chinese_titles(self) -> None:
        args = run_digest.build_parser().parse_args([])
        args.hours = 336
        args.timezone = "Asia/Shanghai"
        item = self.long_title_item()
        event = run_digest.event_from_items([item])
        event.title_zh = (
            "NotebookLM 风格完整标题渲染检查：覆盖大通蓝宝石储备卡报销、万豪礼品卡、"
            "凯悦积分房可用性以及未来截止日期的超长忠诚计划情报标题"
        )
        event.summary_zh = "这条超长内容用于验证信息图完整保留标题，并让卡片高度自然适应内容。"
        event.evidence = [
            dataclasses.replace(
                event.evidence[0],
                title_zh=event.title_zh,
                summary_zh=event.summary_zh,
            )
        ]
        html = run_digest.render_infographic_html(
            [event],
            [run_digest.SourceHealth("doctor-of-credit-cards", "Doctor of Credit", "ok", 1, "parsed", "https://example.com/feed/")],
            args,
            dt.datetime(2026, 6, 22, 10, 0, tzinfo=run_digest.timezone_or_utc("Asia/Shanghai")),
            Path("/tmp/example.md"),
            Path("/tmp/example.json"),
        )
        self.assertIn(event.title_zh, html)
        self.assertNotIn(item.title, html)
        self.assertIn("未来节点时间线", html)
        self.assertNotIn("text-overflow", html)
        self.assertNotIn("line-clamp", html)
        self.assertNotIn("overflow: hidden", html)

    def test_interactive_html_has_semantic_controls_and_single_event_cards(self) -> None:
        args = run_digest.build_parser().parse_args([])
        args.hours = 336
        args.timezone = "Asia/Shanghai"
        item = self.sample_item()
        html = run_digest.render_infographic_html(
            [item],
            [run_digest.SourceHealth("doctor-of-credit-cards", "Doctor of Credit", "ok", 1, "parsed", "https://example.com/feed/")],
            args,
            dt.datetime(2026, 7, 10, 10, 0, tzinfo=run_digest.timezone_or_utc("Asia/Shanghai")),
        )
        self.assertIn("<nav", html)
        self.assertIn('id="intel-search"', html)
        self.assertIn('id="vertical-filter"', html)
        self.assertIn('id="priority-filter"', html)
        self.assertIn('id="sort-control"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('<details class="evidence"', html)
        self.assertIn('<a class="source-link"', html)
        self.assertIn("@media", html)
        self.assertEqual(html.count('class="event-card"'), 1)

    def test_overview_html_is_bounded_to_twelve_events(self) -> None:
        args = run_digest.build_parser().parse_args([])
        args.hours = 336
        args.timezone = "Asia/Shanghai"
        items = []
        for index in range(20):
            item = self.sample_item()
            item.title = f"Unique priority event {index}"
            item.url = f"https://example.com/event-{index}"
            items.append(item)
        html = run_digest.render_overview_html(
            items,
            [run_digest.SourceHealth("source", "Source", "ok", 20, "parsed", "https://example.com/feed")],
            args,
            dt.datetime(2026, 7, 10, 10, 0, tzinfo=run_digest.timezone_or_utc("Asia/Shanghai")),
        )
        self.assertLessEqual(html.count('class="overview-card"'), 12)
        self.assertIn("完整交互报告", html)

    def test_render_digest_image_writes_png_with_metadata(self) -> None:
        args = run_digest.build_parser().parse_args(["--output-dir", "/private/tmp/loyalty-intel-test"])
        args.hours = 336
        args.timezone = "Asia/Shanghai"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "digest.png"
            run_digest.render_digest_image(
                [self.sample_item(), self.future_item(), self.ecosystem_item()],
                [run_digest.SourceHealth("doctor-of-credit-cards", "Doctor of Credit", "ok", 1, "parsed", "https://example.com/feed/")],
                args,
                out,
                dt.datetime(2026, 6, 22, 10, 0, tzinfo=run_digest.timezone_or_utc("Asia/Shanghai")),
                Path(tmp) / "digest.md",
                Path(tmp) / "digest.json",
            )
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 10_000)
            self.assertTrue(out.with_suffix(".html").exists())
            with run_digest.Image.open(out) as image:
                self.assertGreaterEqual(image.width, 2400)
                self.assertEqual(image.height, 1800)

    def test_section_items_include_required_radars(self) -> None:
        transfer = run_digest.classify_row(
            {
                "title": "Chase Ultimate Rewards 30% transfer bonus to Avios, enrollment required",
                "url": "https://example.com/transfer",
                "published_at": "2026-06-21T00:00:00+00:00",
                "summary": "Register by July 15 before transferring.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {"id": "test-transfer", "name": "Test", "priority": "P0", "source_type": "rss", "programs": []},
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        ecosystem = run_digest.classify_row(
            {
                "title": "Hotel owners protest loyalty reimbursement economics",
                "url": "https://example.com/ecosystem",
                "published_at": "2026-06-21T00:00:00+00:00",
                "summary": "Franchisees say redemption reimbursement costs are not aligned with loyalty revenue.",
                "raw_tags": [],
                "source_type": "rss",
            },
            {"id": "test-eco", "name": "Test", "priority": "P1", "source_type": "rss", "programs": []},
            PROFILE_KEYWORDS,
            CARD_KEYWORDS,
        )
        sections = run_digest.section_items([transfer, ecosystem])
        self.assertIn("C端玩法雷达", sections)
        self.assertIn("忠诚计划生态雷达", sections)
        self.assertIn(transfer, sections["C端玩法雷达"])
        self.assertIn(ecosystem, sections["忠诚计划生态雷达"])


class SimplifiedChineseOutputTests(unittest.TestCase):
    def sample_event(self) -> run_digest.IntelEvent:
        item = IntelItemFactory.make(
            title="Chase hotel credit clawback datapoints",
            summary="Multiple readers report that hotel credits were deducted after cancelled reservations.",
        )
        return run_digest.event_from_items([item])

    def test_localized_fields_preserve_original_text(self) -> None:
        event = self.sample_event()
        self.assertEqual(event.title_zh, "")
        self.assertEqual(event.summary_zh, "")
        self.assertEqual(event.evidence[0].title_zh, "")
        self.assertEqual(event.evidence[0].summary_zh, "")
        self.assertEqual(event.title, "Chase hotel credit clawback datapoints")

    def test_display_label_maps_user_visible_taxonomy(self) -> None:
        self.assertEqual(run_digest.display_label("hotel", "vertical"), "酒店")
        self.assertEqual(run_digest.display_label("transfer_bonus", "topic"), "转点奖励")
        self.assertEqual(
            run_digest.display_label("cost_reimbursement_conflict", "ecosystem_signal"),
            "成本补偿冲突",
        )
        self.assertEqual(run_digest.display_label("hotel_owner", "stakeholder"), "酒店业主")
        self.assertEqual(run_digest.display_label("Marriott Bonvoy", "program"), "万豪旅享家")
        self.assertEqual(run_digest.display_label("Sapphire", "card_family"), "蓝宝石卡")

    def test_translation_cache_hit_avoids_network(self) -> None:
        event = self.sample_event()
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "translations.json"
            originals = {
                event.title: "大通酒店报销追回实测",
                event.summary: "多位读者表示，取消预订后酒店报销被扣回。",
            }
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "target_language": "zh-CN",
                        "entries": {
                            run_digest.translation_cache_key(source): {
                                "source": source,
                                "translation": translated,
                            }
                            for source, translated in originals.items()
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            def unexpected_request(_: str) -> object:
                raise AssertionError("cache hit must not call the translation endpoint")

            health = run_digest.localize_events([event], cache_path, request_fn=unexpected_request)

        self.assertEqual(event.title_zh, originals[event.title])
        self.assertEqual(event.evidence[0].summary_zh, originals[event.summary])
        self.assertEqual(health.cache_hits, 2)
        self.assertEqual(health.failed, 0)

    def test_batch_translation_populates_event_and_evidence(self) -> None:
        event = self.sample_event()

        def fake_request(batch: str) -> object:
            self.assertIn("[[[LID_0000]]]", batch)
            return [
                [
                    [
                        "[[[LID_0000]]]\n大通酒店报销追回实测\n"
                        "[[[LID_0001]]]\n多位读者表示，Chase hotel credit clawback datapoints 记录了取消预订后酒店报销被扣回。",
                        batch,
                        None,
                        None,
                    ]
                ]
            ]

        with tempfile.TemporaryDirectory() as tmp:
            health = run_digest.localize_events(
                [event],
                Path(tmp) / "translations.json",
                request_fn=fake_request,
            )

        self.assertEqual(event.title_zh, "大通酒店报销追回实测")
        self.assertEqual(
            event.summary_zh,
            "多位读者表示，大通酒店报销追回实测 记录了取消预订后酒店报销被扣回。",
        )
        self.assertEqual(event.evidence[0].title_zh, event.title_zh)
        self.assertEqual(health.translated, 2)

    def test_translation_failure_uses_chinese_placeholder(self) -> None:
        event = self.sample_event()

        def failed_request(_: str) -> object:
            raise RuntimeError("network unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            health = run_digest.localize_events(
                [event],
                Path(tmp) / "translations.json",
                request_fn=failed_request,
            )

        self.assertEqual(event.title_zh, run_digest.TRANSLATION_FAILURE_TEXT)
        self.assertEqual(event.summary_zh, run_digest.TRANSLATION_FAILURE_TEXT)
        self.assertGreaterEqual(health.failed, 2)

    def test_missing_translation_markers_never_leak_original_text(self) -> None:
        event = self.sample_event()

        def malformed_response(_: str) -> object:
            return [[["返回内容缺少编号标记", "source", None, None]]]

        with tempfile.TemporaryDirectory() as tmp:
            health = run_digest.localize_events(
                [event],
                Path(tmp) / "translations.json",
                request_fn=malformed_response,
            )

        self.assertEqual(event.title_zh, run_digest.TRANSLATION_FAILURE_TEXT)
        self.assertEqual(event.evidence[0].summary_zh, run_digest.TRANSLATION_FAILURE_TEXT)
        self.assertGreater(health.failed, 0)

    def test_url_only_summary_uses_chinese_non_text_notice(self) -> None:
        event = self.sample_event()
        event.title = "中文标题"
        event.summary = "https://images.example.com/banner.jpg"
        event.evidence = [
            dataclasses.replace(event.evidence[0], title=event.title, summary=event.summary)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            health = run_digest.localize_events([event], Path(tmp) / "translations.json")

        self.assertEqual(event.summary_zh, run_digest.NON_TEXT_SUMMARY)
        self.assertEqual(event.evidence[0].summary_zh, run_digest.NON_TEXT_SUMMARY)
        self.assertEqual(health.skipped_non_text, 1)
        self.assertEqual(health.failed, 0)

    def test_visible_outputs_use_only_localized_article_text(self) -> None:
        event = self.sample_event()
        event.title_zh = "大通酒店报销追回实测"
        event.summary_zh = "多位读者表示，取消预订后酒店报销被扣回。"
        event.evidence = [
            dataclasses.replace(
                event.evidence[0],
                title_zh=event.title_zh,
                summary_zh=event.summary_zh,
            )
        ]
        args = run_digest.build_parser().parse_args([])
        args.hours = 336
        args.timezone = "Asia/Shanghai"
        args.translation_health = run_digest.TranslationHealth(
            provider="测试翻译器", requested=2, translated=2
        )
        health = [
            run_digest.SourceHealth(
                "source",
                "测试来源",
                "ok",
                1,
                "parsed; fetched 1, dated 1, eligible 1, rejected 0, duplicate 0, selected 1",
                "https://example.com/feed",
                fetched=1,
                dated=1,
                eligible=1,
                selected=1,
            )
        ]
        generated_at = dt.datetime(
            2026, 7, 10, 10, 0, tzinfo=run_digest.timezone_or_utc("Asia/Shanghai")
        )

        html = run_digest.render_infographic_html([event], health, args, generated_at)
        overview = run_digest.render_overview_html([event], health, args, generated_at)
        markdown = run_digest.render_markdown([event], health, args)

        for output in (html, overview, markdown):
            self.assertIn(event.title_zh, output)
            self.assertNotIn(event.title, output)
            self.assertNotIn(event.summary, output)
        self.assertIn("转点奖励", run_digest.display_label("transfer_bonus", "topic"))
        self.assertIn("解析成功", html)


class IntelItemFactory:
    @staticmethod
    def make(title: str, summary: str) -> run_digest.IntelItem:
        return run_digest.IntelItem(
            source="Doctor of Credit - Credit Cards",
            source_id="doctor-of-credit-cards",
            source_type="blog_comment",
            priority="P0",
            program=["Chase"],
            card_family=["Sapphire"],
            topic_type="clawback",
            title=title,
            url="https://www.doctorofcredit.com/example-post/",
            published_at="2026-07-09T00:00:00+00:00",
            summary=summary,
            why_it_matters="涉及权益扣回，使用相关卡片时需要保守处理。",
            confidence_label="多用户 DP",
            risk_label="可能 clawback",
            score=140,
            vertical=["credit_card"],
            ecosystem_signal_type=["operational_reliability"],
            stakeholders=["member", "issuer"],
            consumer_impact="需避坑",
            impact_horizon="today",
            action_label="高风险勿操作",
            metric_snippets=[],
            future_event_dates=[],
            raw_tags=[],
        )


if __name__ == "__main__":
    unittest.main()
