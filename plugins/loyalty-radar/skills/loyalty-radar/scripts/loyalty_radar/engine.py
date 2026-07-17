#!/usr/bin/env python3
"""Collect and score public loyalty and Chase/Amex intelligence.

This script intentionally avoids private accounts, login bypass, CAPTCHA
workarounds, and official-site verification. It summarizes public forum/RSS
signals for a Codex agent to review.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is bundled in this workspace.
    yaml = None

try:
    from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
except Exception:  # pragma: no cover - regex fallback is used.
    BeautifulSoup = None
    MarkupResemblesLocatorWarning = None

try:
    import requests
except Exception:  # pragma: no cover - urllib fallback is used.
    requests = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Markdown/JSON output still works.
    Image = None
    ImageDraw = None
    ImageFont = None

if MarkupResemblesLocatorWarning is not None:
    warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


SKILL_DIR = Path(__file__).resolve().parents[2]
REFERENCES_DIR = SKILL_DIR / "references"
DEFAULT_OUTPUT_DIR = Path(os.environ.get("LOYALTY_INTEL_OUTPUT_DIR", "/private/tmp/loyalty-intel-digest"))
DEFAULT_TRANSLATION_CACHE = Path(
    os.environ.get(
        "LOYALTY_INTEL_TRANSLATION_CACHE",
        "/private/tmp/loyalty-intel-digest/translation-cache-zh-CN.json",
    )
)
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATION_FAILURE_TEXT = "翻译失败，请通过原文链接核对。"
NON_TEXT_SUMMARY = "原文摘要仅包含图片链接，请打开来源查看详情。"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Loyalty-Radar/0.1 "
    "(+https://github.com/lonelydoctor/loyalty-radar)"
)
MAX_RESPONSE_BYTES = int(os.environ.get("LOYALTY_RADAR_MAX_RESPONSE_BYTES", 5 * 1024 * 1024))
MOJIBAKE_REPLACEMENTS = {
    "\u00c2\u0092": "'",
    "\u0092": "'",
    "\u00e2\u0080\u0099": "'",
    "\u00e2\u0080\u0098": "'",
    "\u00e2\u0080\u009c": '"',
    "\u00e2\u0080\u009d": '"',
    "\u00e2\u0080\u0093": "-",
    "\u00e2\u0080\u0094": "-",
    "\u00c2\u00a0": " ",
    "\u00c2": "",
}

DISPLAY_LABELS: dict[str, dict[str, str]] = {
    "vertical": {
        "hotel": "酒店",
        "airline": "航空",
        "credit_card": "信用卡",
        "rental_car": "租车",
        "loyalty": "忠诚计划",
    },
    "topic": {
        "policy_change": "政策或权益变化",
        "offer": "优惠活动",
        "datapoint": "用户实测",
        "bug": "系统异常",
        "clawback": "权益追回",
        "lounge": "休息室",
        "transfer_bonus": "转点奖励",
        "trip_report": "体验报告",
        "status_match": "会籍匹配",
        "portal_stack": "门户叠加",
        "statement_credit": "账单报销",
        "devaluation": "积分贬值",
        "industry_signal": "行业生态信号",
    },
    "ecosystem_signal": {
        "revenue_shift": "收益转移",
        "cost_reimbursement_conflict": "成本补偿冲突",
        "benefit_capacity_pressure": "权益容量压力",
        "devaluation_or_inflation": "积分贬值或通胀",
        "qualification_gatekeeping": "资格门槛收紧",
        "partner_contract_shift": "合作关系变化",
        "regulatory_or_legal_pressure": "监管或法律压力",
        "operational_reliability": "运营可靠性",
        "supply_demand_stress": "供需压力",
        "consumer_backlash": "用户反弹",
    },
    "stakeholder": {
        "member": "会员",
        "hotel_owner": "酒店业主",
        "franchisee": "加盟商",
        "airline_partner": "航司伙伴",
        "issuer": "发卡机构",
        "merchant": "商户",
        "regulator": "监管机构",
        "rental_location": "租车门店",
    },
    "program": {
        "Air China PhoenixMiles": "凤凰知音",
        "Air China": "中国国航",
        "Star Alliance": "星空联盟",
        "Marriott Bonvoy": "万豪旅享家",
        "Marriott": "万豪",
        "World of Hyatt": "凯悦天地",
        "Hyatt": "凯悦",
        "Hilton Honors": "希尔顿荣誉客会",
        "Hilton": "希尔顿",
        "IHG One Rewards": "IHG 优悦会",
        "IHG": "IHG",
        "American Express": "美国运通",
        "Amex Travel": "美国运通旅行",
        "Amex": "美国运通",
        "Amex Membership Rewards": "美国运通会员奖励",
        "Chase": "大通银行",
        "Chase Ultimate Rewards": "大通终极奖励",
        "Ultimate Rewards": "终极奖励积分",
        "Membership Rewards": "会员奖励积分",
        "MileagePlus": "前程万里",
        "Bonvoy": "万豪旅享家",
        "Capital One": "第一资本",
        "Citi": "花旗银行",
        "American Airlines": "美国航空",
        "United": "美联航",
        "Delta": "达美航空",
        "Cathay": "国泰航空",
        "Wyndham": "温德姆",
        "Flying Blue": "蓝天飞行",
        "Miles & More": "Miles & More",
    },
    "card_family": {
        "Platinum": "白金卡",
        "Gold": "金卡",
        "Green": "绿卡",
        "Sapphire": "蓝宝石卡",
        "Ink": "Ink 商务卡",
        "Offers": "卡片优惠",
        "Hilton": "希尔顿联名卡",
        "Marriott": "万豪联名卡",
        "Delta": "达美联名卡",
        "United": "美联航联名卡",
        "Hyatt": "凯悦联名卡",
        "IHG": "IHG 联名卡",
        "American Express": "美国运通卡",
        "Chase": "大通卡",
        "Freedom": "自由卡",
        "Southwest": "西南航空联名卡",
    },
    "status": {
        "ok": "成功",
        "failed": "失败",
        "skipped": "受限",
        "disabled": "已禁用",
    },
    "confidence": {
        "多用户 DP": "多用户实测",
        "评论 DP": "评论实测",
        "单帖线索": "单帖线索",
        "博客整理": "博客整理",
        "多源重复": "多源重复",
        "多源证实": "多源证实",
    },
    "risk": {
        "正常权益": "正常权益",
        "YMMV": "因人而异",
        "可能 clawback": "可能追回",
        "高风控风险": "高风控风险",
    },
    "action": {
        "需报名": "需报名",
        "可直接用": "可直接使用",
        "定向/YMMV": "定向或因人而异",
        "只观察": "只观察",
        "高风险勿操作": "高风险，勿操作",
    },
    "consumer_impact": {
        "直接可用": "直接可用",
        "需避坑": "需要避坑",
        "可能贬值": "可能贬值",
        "权益履约风险": "权益履约风险",
        "长期观察": "长期观察",
    },
    "mode": {"daily": "每日情报", "weekly": "每周情报"},
    "focus": {
        "all": "全部",
        "credit-card": "信用卡",
        "air-china": "中国国航",
        "hotel": "酒店",
        "bug": "异常与风险",
    },
}


@dataclasses.dataclass
class IntelItem:
    source: str
    source_id: str
    source_type: str
    priority: str
    program: list[str]
    card_family: list[str]
    topic_type: str
    title: str
    url: str
    published_at: str | None
    summary: str
    why_it_matters: str
    confidence_label: str
    risk_label: str
    score: int
    vertical: list[str]
    ecosystem_signal_type: list[str]
    stakeholders: list[str]
    consumer_impact: str
    impact_horizon: str
    action_label: str
    metric_snippets: list[str]
    future_event_dates: list[str]
    raw_tags: list[str]
    author: str = ""


@dataclasses.dataclass(frozen=True)
class Evidence:
    source_id: str
    source: str
    source_type: str
    title: str
    summary: str
    url: str
    published_at: str | None
    author: str = ""
    title_zh: str = ""
    summary_zh: str = ""

    @property
    def source_name(self) -> str:
        return self.source


@dataclasses.dataclass
class IntelEvent:
    title: str
    url: str
    source: str
    source_id: str
    source_type: str
    priority: str
    program: list[str]
    card_family: list[str]
    topic_type: str
    published_at: str | None
    summary: str
    why_it_matters: str
    confidence_label: str
    risk_label: str
    score: int
    vertical: list[str]
    ecosystem_signal_type: list[str]
    stakeholders: list[str]
    consumer_impact: str
    impact_horizon: str
    action_label: str
    metric_snippets: list[str]
    future_event_dates: list[str]
    raw_tags: list[str]
    event_id: str
    evidence: list[Evidence]
    priority_tier: str = "P4 线索库"
    score_breakdown: dict[str, int] = dataclasses.field(default_factory=dict)
    title_zh: str = ""
    summary_zh: str = ""


@dataclasses.dataclass
class SourceHealth:
    source_id: str
    source: str
    status: str
    items: int
    detail: str
    url: str
    fetched: int = 0
    dated: int = 0
    eligible: int = 0
    rejected: int = 0
    duplicate: int = 0
    selected: int = 0


@dataclasses.dataclass
class TranslationHealth:
    provider: str = "Google 翻译公共端点"
    requested: int = 0
    cache_hits: int = 0
    translated: int = 0
    skipped_chinese: int = 0
    skipped_non_text: int = 0
    failed: int = 0
    request_attempts: int = 0
    cache_path: str = ""
    errors: list[str] = dataclasses.field(default_factory=list)


class FetchError(RuntimeError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to read configuration files.")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def clean_text(value: str | None, max_len: int = 600) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    if BeautifulSoup:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    else:
        text = re.sub(r"<[^>]+>", " ", text)
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "..."
    return text


def normalize_url(url: str, base: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(url))


def is_placeholder_title(title: str) -> bool:
    return not title or "_文章标题" in title or title in {"最后发表", "lastpost"}


def http_get(url: str, encoding: str | None = None, timeout: int = 25) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/rss+xml,*/*"}
    if requests:
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        except Exception as exc:  # noqa: BLE001
            raise FetchError(str(exc)) from exc
        with response:
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}")
            try:
                content_length = int(response.headers.get("content-length", "0") or 0)
            except ValueError:
                content_length = 0
            if content_length > MAX_RESPONSE_BYTES:
                raise FetchError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise FetchError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
                chunks.append(chunk)
            charset = encoding or response.encoding or "utf-8"
            return b"".join(chunks).decode(charset, errors="ignore")

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            content_type = response.headers.get("content-type", "")
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise FetchError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    charset = encoding or "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    if not encoding and match:
        charset = match.group(1)
    return raw.decode(charset, errors="ignore")


def display_label(value: str, category: str) -> str:
    """Return the Simplified Chinese display label for an internal value."""
    return DISPLAY_LABELS.get(category, {}).get(value, value)


def display_list(values: list[str], category: str, limit: int | None = None) -> list[str]:
    rows = values if limit is None else values[:limit]
    return [display_label(value, category) for value in rows]


def needs_translation(value: str | None) -> bool:
    """Treat Chinese-dominant text as display-ready while translating English-dominant text."""
    if not value or not value.strip():
        return False
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", value))
    latin_count = len(re.findall(r"[A-Za-z]", value))
    if cjk_count == 0:
        return latin_count > 0
    return latin_count > cjk_count


def is_url_only_text(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"https?://\S+", value.strip(), flags=re.I))


def display_title(item: Any) -> str:
    localized = str(getattr(item, "title_zh", "") or "").strip()
    if localized:
        return display_generated_text(localized)
    original = str(getattr(item, "title", "") or "").strip()
    if original and not needs_translation(original):
        return display_generated_text(original)
    return TRANSLATION_FAILURE_TEXT


def display_summary(item: Any) -> str:
    localized = str(getattr(item, "summary_zh", "") or "").strip()
    if localized:
        return display_generated_text(localized)
    original = str(getattr(item, "summary", "") or "").strip()
    if original and not needs_translation(original):
        return display_generated_text(original)
    return display_title(item)


def translation_cache_key(value: str) -> str:
    cache_input = "v2|en-to-zh-CN|" + value.strip()
    return hashlib.sha256(cache_input.encode("utf-8")).hexdigest()


def load_translation_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return {}
    return {
        str(key): value
        for key, value in entries.items()
        if isinstance(value, dict) and isinstance(value.get("translation"), str)
    }


def save_translation_cache(path: Path, entries: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "target_language": "zh-CN",
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        "entries": entries,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def google_translate_request(batch: str) -> Any:
    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": batch,
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,*/*"}
    if requests:
        try:
            response = requests.get(GOOGLE_TRANSLATE_URL, params=params, headers=headers, timeout=35)
        except Exception as exc:  # noqa: BLE001
            raise FetchError(str(exc)) from exc
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}")
        return response.json()

    url = GOOGLE_TRANSLATE_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)) from exc


def translation_payload_text(payload: Any) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return payload
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ValueError("unexpected translation response")
    parts = []
    for segment in payload[0]:
        if isinstance(segment, list) and segment and isinstance(segment[0], str):
            parts.append(segment[0])
    if not parts:
        raise ValueError("translation response contains no text")
    return "".join(parts)


def marker_batch(texts: list[str]) -> str:
    return "\n".join(f"[[[LID_{index:04d}]]]\n{text}" for index, text in enumerate(texts))


def parse_marker_translation(payload: Any, expected_count: int) -> list[str]:
    translated = translation_payload_text(payload)
    matches = list(re.finditer(r"\[\[\[LID_(\d{4})\]\]\]", translated))
    recovered: dict[int, str] = {}
    for index, match in enumerate(matches):
        marker_index = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(translated)
        recovered[marker_index] = translated[match.end() : end].strip()
    if set(recovered) != set(range(expected_count)) or any(not recovered[index] for index in recovered):
        raise ValueError("translation markers are incomplete")
    return [recovered[index] for index in range(expected_count)]


def translation_batches(texts: list[str], max_chars: int) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    max_chars = max(400, max_chars)
    for value in texts:
        estimated = len(value) + 24
        if current and current_size + estimated > max_chars:
            batches.append(current)
            current = []
            current_size = 0
        current.append(value)
        current_size += estimated
    if current:
        batches.append(current)
    return batches


def localize_events(
    events: list[IntelEvent],
    cache_path: Path,
    *,
    request_fn: Any = google_translate_request,
    batch_chars: int = 3000,
    delay: float = 0.0,
    provider: str = "Google 翻译公共端点",
) -> TranslationHealth:
    health = TranslationHealth(provider=provider, cache_path=cache_path.name)
    unique_texts: list[str] = []
    seen: set[str] = set()
    for event in events:
        candidates = [event.title, event.summary]
        for evidence in event.evidence:
            candidates.extend([evidence.title, evidence.summary])
        for value in candidates:
            normalized = (value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_texts.append(normalized)
    health.requested = len(unique_texts)

    cache = load_translation_cache(cache_path)
    localized: dict[str, str] = {}
    pending: list[str] = []
    for value in unique_texts:
        if is_url_only_text(value):
            localized[value] = NON_TEXT_SUMMARY
            health.skipped_non_text += 1
            continue
        if not needs_translation(value):
            localized[value] = value
            health.skipped_chinese += 1
            continue
        cached = cache.get(translation_cache_key(value), {}).get("translation", "").strip()
        if cached:
            localized[value] = cached
            health.cache_hits += 1
        else:
            pending.append(value)

    def translate_group(group: list[str], can_split: bool) -> None:
        if not group:
            return
        try:
            health.request_attempts += 1
            payload = request_fn(marker_batch(group))
            translated_rows = parse_marker_translation(payload, len(group))
            unresolved: list[str] = []
            for source, translated in zip(group, translated_rows, strict=True):
                if needs_translation(source) and translated.strip().casefold() == source.strip().casefold():
                    unresolved.append(source)
                    continue
                localized[source] = translated
                cache[translation_cache_key(source)] = {
                    "source": source,
                    "translation": translated,
                }
                health.translated += 1
            if unresolved:
                if can_split:
                    translate_group(unresolved, False)
                else:
                    if len(health.errors) < 8:
                        health.errors.append("translation output was unchanged")
                    for source in unresolved:
                        localized[source] = TRANSLATION_FAILURE_TEXT
                        health.failed += 1
            if delay > 0:
                time.sleep(delay)
        except Exception as exc:  # noqa: BLE001
            if can_split and len(group) > 1:
                midpoint = max(1, len(group) // 2)
                translate_group(group[:midpoint], False)
                translate_group(group[midpoint:], False)
                return
            message = str(exc) or exc.__class__.__name__
            if len(health.errors) < 8:
                health.errors.append(message)
            for source in group:
                localized[source] = TRANSLATION_FAILURE_TEXT
                health.failed += 1

    for group in translation_batches(pending, batch_chars):
        translate_group(group, True)
    if health.translated:
        save_translation_cache(cache_path, cache)

    for event in events:
        event.title_zh = localized.get((event.title or "").strip(), "")
        event.summary_zh = localized.get((event.summary or "").strip(), "")
        if event.title and event.title_zh and event.title != event.title_zh:
            event.summary_zh = event.summary_zh.replace(event.title, event.title_zh)
        event.evidence = [
            dataclasses.replace(
                evidence,
                title_zh=localized.get((evidence.title or "").strip(), ""),
                summary_zh=localized.get((evidence.summary or "").strip(), "").replace(
                    evidence.title,
                    localized.get((evidence.title or "").strip(), ""),
                )
                if evidence.title
                else localized.get((evidence.summary or "").strip(), ""),
            )
            for evidence in event.evidence
        ]
    return health


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    except (TypeError, ValueError):
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    except Exception:
        return None


def iso_or_none(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def rss_item_text(item: ET.Element, path: str, namespaces: dict[str, str]) -> str:
    node = item.find(path, namespaces)
    return node.text.strip() if node is not None and node.text else ""


def parse_rss_feed(xml_text: str, source_cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    ns = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "wfw": "http://wellformedweb.org/CommentAPI/",
        "slash": "http://purl.org/rss/1.0/modules/slash/",
    }
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:limit]:
        categories = [node.text.strip() for node in item.findall("category") if node.text]
        content = rss_item_text(item, "content:encoded", ns) or rss_item_text(item, "description", ns)
        rows.append(
            {
                "title": clean_text(rss_item_text(item, "title", ns), max_len=260),
                "url": rss_item_text(item, "link", ns),
                "published_at": iso_or_none(parse_datetime(rss_item_text(item, "pubDate", ns))),
                "summary": clean_text(content),
                "author": clean_text(rss_item_text(item, "dc:creator", ns), max_len=100),
                "raw_tags": categories,
                "comment_rss": rss_item_text(item, "wfw:commentRss", ns),
                "source_type": source_cfg.get("source_type", "rss"),
            }
        )
    return [row for row in rows if row["title"] and row["url"]]


def parse_flyert_local_datetime(value: str) -> dt.datetime | None:
    cleaned = clean_text(value, max_len=80)
    if not cleaned:
        return None
    if re.fullmatch(r"\d{10}(?:\d{3})?", cleaned):
        timestamp = int(cleaned[:10])
        try:
            return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None
    match = re.search(
        r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})(?:日)?"
        r"(?:[ T]+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?",
        cleaned,
    )
    if not match:
        return None
    try:
        local_value = dt.datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour") or 0),
            int(match.group("minute") or 0),
            int(match.group("second") or 0),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
    except ValueError:
        return None
    return local_value.astimezone(dt.UTC)


def flyert_thread_datetime(anchor: Any) -> str | None:
    container = anchor.find_parent(id=re.compile(r"^normalthread_")) or anchor.find_parent("tr")
    if container is None:
        return None
    attribute_names = ("datetime", "title", "data-time", "data-timestamp", "data-dateline")
    candidates: list[str] = []
    for node in [container, *container.find_all(["time", "span", "em", "td"])]:
        for attribute in attribute_names:
            value = node.get(attribute)
            if value:
                candidates.append(str(value))
        text_value = node.get_text(" ", strip=True)
        if text_value:
            candidates.append(text_value)
    for candidate in candidates:
        parsed = parse_flyert_local_datetime(candidate)
        if parsed:
            return iso_or_none(parsed)
    return None


def parse_flyert_forum(html_text: str, source_cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    base = source_cfg["url"]

    if BeautifulSoup:
        soup = BeautifulSoup(html_text, "html.parser")
        anchors = soup.find_all("a", href=lambda href: href and "mod=viewthread" in href and "tid=" in href)
        for anchor in anchors:
            href = anchor.get("href") or ""
            tid_match = re.search(r"tid=(\d+)", href)
            if not tid_match:
                continue
            tid = tid_match.group(1)
            if tid in seen:
                continue
            title_candidates = [
                anchor.get_text(" ", strip=True),
                anchor.get("title") or "",
                anchor.get("data-title") or "",
            ]
            title = ""
            for candidate in title_candidates:
                cleaned = clean_text(candidate, max_len=260)
                if len(cleaned) >= 4 and not is_placeholder_title(cleaned):
                    title = cleaned
                    break
            if not title:
                continue
            seen.add(tid)
            rows.append(
                {
                    "title": title,
                    "url": normalize_url(href, base),
                    "published_at": flyert_thread_datetime(anchor),
                    "summary": title,
                    "author": "",
                    "raw_tags": [source_cfg.get("name", "")],
                    "source_type": "forum",
                }
            )
            if len(rows) >= limit:
                break
        return rows

    pattern = re.compile(
        r"<a[^>]+href=[\"']([^\"']*mod=viewthread[^\"']*tid=(\d+)[^\"']*)[\"'][^>]*>(.*?)</a>",
        re.I | re.S,
    )
    for href, tid, title_html in pattern.findall(html_text):
        if tid in seen:
            continue
        title = clean_text(title_html, max_len=260)
        if title and len(title) >= 4:
            seen.add(tid)
            rows.append(
                {
                    "title": title,
                    "url": normalize_url(href, base),
                    "published_at": None,
                    "summary": title,
                    "author": "",
                    "raw_tags": [source_cfg.get("name", "")],
                    "source_type": "forum",
                }
            )
        if len(rows) >= limit:
            break
    return rows


def parse_generic_html_keyword(html_text: str, source_cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    keywords = [kw.lower() for kw in source_cfg.get("keywords", [])]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    base = source_cfg["url"]
    if not BeautifulSoup:
        return rows
    soup = BeautifulSoup(html_text, "html.parser")
    for anchor in soup.find_all("a", href=True):
        title = clean_text(anchor.get_text(" ", strip=True), max_len=260)
        if len(title) < 6:
            continue
        haystack = title.lower()
        if keywords and not any(keyword.lower() in haystack for keyword in keywords):
            continue
        url = normalize_url(anchor["href"], base)
        if url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "title": title,
                "url": url,
                "published_at": None,
                "summary": title,
                "author": "",
                "raw_tags": [source_cfg.get("name", "")],
                "source_type": source_cfg.get("source_type", "forum"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def filter_rows_by_source_keywords(rows: list[dict[str, Any]], source_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = source_cfg.get("keywords", [])
    if not keywords:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join([row.get("title", ""), row.get("summary", ""), " ".join(row.get("raw_tags", []))]).lower()
        if any(keyword_matches(haystack, keyword) for keyword in keywords):
            filtered.append(row)
    return filtered


def fetch_flyert_detail(url: str, encoding: str | None = "gbk") -> str:
    detail_html = http_get(url, encoding=encoding)
    if BeautifulSoup:
        soup = BeautifulSoup(detail_html, "html.parser")
        meta = soup.find("meta", attrs={"name": "description"})
        meta_text = meta.get("content", "") if meta else ""
        posts = soup.find_all(id=re.compile(r"postmessage_\d+"))
        post_texts = [clean_text(post.get_text(" ", strip=True), max_len=500) for post in posts[:3]]
        return clean_text(" ".join([meta_text, *post_texts]), max_len=800)
    meta_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', detail_html, re.I)
    return clean_text(meta_match.group(1) if meta_match else "", max_len=800)


def flatten_profile_keywords(profile_cfg: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    loyalty = profile_cfg.get("loyalty_profile", {})
    for group in ("airline", "hotel"):
        for entry in loyalty.get(group, []):
            program = entry.get("program") or entry.get("display_name")
            result[program] = entry.get("keywords", [])
    result["Chase"] = ["Chase", "Ultimate Rewards", "UR", "Sapphire", "Ink", "大通"]
    result["American Express"] = ["American Express", "Amex", "AMEX", "Membership Rewards", "MR", "美国运通"]
    for program, keywords in GLOBAL_PROGRAM_KEYWORDS.items():
        result.setdefault(program, keywords)
    return result


def flatten_card_keywords(cards_cfg: dict[str, Any]) -> dict[str, list[str]]:
    families: dict[str, list[str]] = {}
    for issuer in cards_cfg.get("issuers", []):
        issuer_name = issuer.get("issuer", "")
        families[issuer_name] = issuer.get("keywords", [])
        for family in issuer.get("families", []):
            families[family.get("name", "")] = family.get("keywords", [])
    return families


GLOBAL_PROGRAM_KEYWORDS: dict[str, list[str]] = {
    "Marriott": ["Marriott", "Marriott Bonvoy", "Bonvoy", "万豪", "旅享家"],
    "Hyatt": ["Hyatt", "World of Hyatt", "凯悦"],
    "Hilton": ["Hilton", "Hilton Honors", "希尔顿"],
    "IHG": ["IHG", "IHG One Rewards", "InterContinental", "洲际"],
    "Accor": ["Accor", "ALL Accor", "雅高"],
    "Wyndham": ["Wyndham", "温德姆"],
    "Choice": ["Choice Privileges"],
    "Best Western": ["Best Western", "BWH"],
    "GHA": ["GHA Discovery"],
    "Radisson": ["Radisson Rewards"],
    "United": ["United", "MileagePlus"],
    "Delta": ["Delta", "SkyMiles"],
    "American Airlines": ["American Airlines", "AAdvantage", "AA miles", "AA business", "AA里程", "AA商业"],
    "Air Canada": ["Air Canada", "Aeroplan"],
    "ANA": ["ANA", "All Nippon"],
    "Japan Airlines": ["Japan Airlines", "JAL", "JMB", "JAL Mileage Bank"],
    "Singapore Airlines": ["Singapore Airlines", "KrisFlyer", "SQ"],
    "Lufthansa": ["Lufthansa", "Miles & More"],
    "Turkish Airlines": ["Turkish Airlines", "Miles&Smiles"],
    "Avios": ["Avios", "British Airways", "Iberia", "Qatar Airways"],
    "Flying Blue": ["Flying Blue", "Air France", "KLM"],
    "Emirates": ["Emirates", "Skywards"],
    "Cathay": ["Cathay", "Asia Miles", "国泰"],
    "Qantas": ["Qantas"],
    "Avianca LifeMiles": ["Avianca", "LifeMiles"],
    "Aegean Miles+Bonus": ["Aegean", "Miles+Bonus"],
    "Alaska Mileage Plan": ["Alaska Airlines", "Mileage Plan"],
    "Southwest Rapid Rewards": ["Southwest Airlines", "Rapid Rewards"],
    "JetBlue TrueBlue": ["JetBlue", "TrueBlue"],
    "Virgin Atlantic Flying Club": ["Virgin Atlantic", "Flying Club"],
    "Etihad Guest": ["Etihad", "Etihad Guest"],
    "Korean Air SKYPASS": ["Korean Air", "SKYPASS"],
    "Hawaiian Airlines": ["Hawaiian Airlines", "HawaiianMiles"],
    "oneworld": ["oneworld", "寰宇一家"],
    "SkyTeam": ["SkyTeam", "天合联盟"],
    "Citi": ["Citi", "ThankYou"],
    "Capital One": ["Capital One", "Venture X"],
    "Bilt": ["Bilt"],
    "Wells Fargo": ["Wells Fargo"],
    "Bank of America": ["Bank of America", "BofA"],
    "Barclays": ["Barclays", "Barclaycard"],
    "HSBC": ["HSBC"],
    "US Bank": ["US Bank", "U.S. Bank", "Altitude Reserve"],
    "OCBC": ["OCBC"],
    "Hertz": ["Hertz", "Gold Plus Rewards"],
    "Avis": ["Avis", "Avis Preferred"],
    "Budget": ["Budget Fastbreak"],
    "National": ["National Car Rental", "National Emerald Club", "Emerald Club"],
    "Enterprise": ["Enterprise Plus"],
    "Alamo": ["Alamo Insiders"],
    "Sixt": ["Sixt"],
    "Europcar": ["Europcar"],
    "Dollar": ["Dollar Express", "Dollar Rent A Car", "Dollar rental"],
    "Thrifty": ["Thrifty Blue Chip", "Thrifty rental"],
}

EVENT_TITLE_PROGRAM_KEYWORDS: dict[str, list[str]] = {
    "Chase": ["Chase", "Ultimate Rewards", "Sapphire", "Ink", "大通"],
    "American Express": [
        "American Express",
        "Amex",
        "Membership Rewards",
        "美国运通",
    ],
    **GLOBAL_PROGRAM_KEYWORDS,
}


VERTICAL_KEYWORDS: dict[str, list[str]] = {
    "hotel": [
        "hotel",
        "resort",
        "suite",
        "breakfast",
        "late checkout",
        "Marriott",
        "Bonvoy",
        "Hyatt",
        "Hilton",
        "IHG",
        "Accor",
        "Wyndham",
        "Choice",
        "Best Western",
        "Radisson",
        "酒店",
        "万豪",
        "凯悦",
        "希尔顿",
        "洲际",
    ],
    "airline": [
        "airline",
        "flight",
        "award ticket",
        "lounge",
        "airport",
        "Star Alliance",
        "oneworld",
        "SkyTeam",
        "United",
        "Delta",
        "American Airlines",
        "Air Canada",
        "ANA",
        "Japan Airlines",
        "JAL",
        "Singapore",
        "Lufthansa",
        "Turkish",
        "Avios",
        "Flying Blue",
        "Emirates",
        "Qatar",
        "Cathay",
        "Qantas",
        "Avianca",
        "LifeMiles",
        "Aegean",
        "Miles+Bonus",
        "Alaska Airlines",
        "Mileage Plan",
        "Southwest Airlines",
        "Rapid Rewards",
        "JetBlue",
        "TrueBlue",
        "Virgin Atlantic",
        "Flying Club",
        "Etihad",
        "Korean Air",
        "SKYPASS",
        "Hawaiian Airlines",
        "HawaiianMiles",
        "航司",
        "航班",
        "里程",
        "休息室",
        "贵宾厅",
    ],
    "credit_card": [
        "credit card",
        "credit-card",
        "rewards card",
        "business card",
        "personal card",
        "Bank of Hawaii card",
        "cardholder",
        "issuer",
        "interchange",
        "statement credit",
        "annual fee",
        "Chase",
        "Sapphire",
        "Ultimate Rewards",
        "Amex",
        "American Express",
        "Membership Rewards",
        "Citi",
        "Capital One",
        "Bilt",
        "Wells Fargo",
        "Bank of America",
        "Barclays",
        "HSBC",
        "US Bank",
        "信用卡",
        "美卡",
        "返现",
        "年费",
    ],
    "rental_car": [
        "rental car",
        "car rental",
        "fleet",
        "upgrade car",
        "Hertz",
        "Avis",
        "Budget",
        "National Car Rental",
        "Emerald Club",
        "Enterprise",
        "Alamo",
        "Sixt",
        "Europcar",
        "Dollar Express",
        "Dollar Rent A Car",
        "Thrifty Blue Chip",
        "租车",
        "租車",
        "门店",
    ],
}


TOPIC_KEYWORDS: list[tuple[str, list[str]]] = [
    ("clawback", ["clawback", "claw back", "clawed back", "clawing back", "deducted", "扣回", "追回", "收回", "取消后", "cancelled reservation"]),
    ("bug", ["not working", "transfer failed", "redemption failed", "points failed to post", "bug", "glitch", "system error", "not posting", "missing points", "无法", "转点失败", "兑换失败", "系统错误", "系统异常", "不到账", "没到账", "不能用"]),
    ("status_match", ["status match", "status challenge", "match challenge", "elite match", "状态匹配", "会籍匹配", "会籍挑战"]),
    ("transfer_bonus", ["transfer bonus", "transfer bonuses", "转点 bonus", "转点", "转分", "transfer ratio", "4:3", "1:1", "bonus to", "bonuses to", "Membership Rewards to", "Ultimate Rewards to"]),
    ("portal_stack", ["portal stack", "Chase Travel", "Amex Travel", "The Edit", "Fine Hotels", "FHR", "hotel collection", "travel portal", "叠加", "门户"]),
    ("statement_credit", ["statement credit", "hotel credit", "airline credit", "travel credit", "resort credit", "dining credit", "报销"]),
    ("lounge", ["lounge", "Centurion", "Sapphire Lounge", "Priority Pass", "贵宾厅", "休息室", "候机楼"]),
    ("devaluation", ["devaluation", "dynamic pricing", "points inflation", "fewer miles", "贬值", "动态定价", "兑换成本"]),
    ("policy_change", ["annual fee", "年费", "eligibility", "lifetime", "5/24", "benefit", "权益", "刷新", "改版", "changes", "changing", "no longer", "ending"]),
    ("offer", ["offer", "bonus", "promo", "promotion", "sale", "discount", "bid on", "auction", "Amex Offers", "Chase Offers", "优惠", "活动", "返现", "报名", "限时"]),
    ("industry_signal", ["owner", "owners", "franchisee", "reimbursement", "regulator", "regulators", "DOT", "CFPB", "lawsuit", "scrutiny", "bait-and-switch", "ecosystem", "业主", "加盟商", "监管", "诉讼", "抗议"]),
    ("trip_report", ["master thread", "report", "review", "入住报告", "飞行报告", "体验", "stay report"]),
]

RISK_KEYWORDS = {
    "高风控风险": ["shutdown", "financial review", "FR", "manufactured spend", "MS", "风控", "关卡", "封号", "高风险"],
    "可能 clawback": ["clawback", "claw back", "clawed back", "扣回", "追回", "收回"],
    "YMMV": ["YMMV", "targeted", "定向", "DP", "data point", "可能", "疑似"],
}

ECOSYSTEM_SIGNAL_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "revenue_shift",
        [
            "loyalty revenue",
            "loyalty income",
            "profit engine",
            "co-branded",
            "cobrand",
            "credit-card revenue",
            "points-sale",
            "sell miles",
            "sell points",
            "interchange",
            "breakage",
            "royalty",
            "联名卡收入",
            "积分销售",
            "积分负债",
        ],
    ),
    (
        "cost_reimbursement_conflict",
        [
            "hotel owner",
            "owners",
            "franchisee",
            "franchisees",
            "reimbursement",
            "reimbursed",
            "bigger cut",
            "cost burden",
            "costs are not aligned",
            "too low",
            "业主",
            "加盟商",
            "报销",
            "补偿",
            "利益太少",
        ],
    ),
    (
        "benefit_capacity_pressure",
        [
            "overcrowding",
            "crowded",
            "capacity controlled",
            "capacity-control",
            "reduced upgrades",
            "upgrade space limited",
            "restricted lounge access",
            "reduced breakfast benefit",
            "suite upgrades unavailable",
            "benefits cut",
            "benefit capacity",
            "容量",
            "权益缩水",
            "升级受限",
        ],
    ),
    (
        "devaluation_or_inflation",
        [
            "devaluation",
            "dynamic pricing",
            "points inflation",
            "cost more",
            "fewer miles",
            "10% fewer",
            "higher award",
            "raises points prices",
            "raises prices",
            "price increase",
            "price increases",
            "award chart increase",
            "increases award pricing",
            "increased award pricing",
            "raises award prices",
            "raised award prices",
            "award prices increased",
            "贬值",
            "动态定价",
            "兑换成本上升",
        ],
    ),
    (
        "qualification_gatekeeping",
        [
            "higher-spend",
            "higher spend",
            "spend threshold",
            "access restricted",
            "reserve elite benefits",
            "reserved for cardholders",
            "new qualification rules",
            "status match ending",
            "status challenge ending",
            "门槛",
            "保级",
            "高消费",
            "仅限持卡人",
            "限制进入",
        ],
    ),
    (
        "partner_contract_shift",
        [
            "co-brand contract",
            "issuer change",
            "partnership",
            "franchise agreement",
            "transfer partner",
            "conversion partner",
            "conversion partners",
            "removed partner",
            "alliance",
            "status reciprocal",
            "contract",
            "joining hilton honors",
            "join the hilton honors",
            "leaving marriott",
            "rebranding as",
            "联名卡",
            "伙伴关系",
            "转点伙伴",
        ],
    ),
    (
        "regulatory_or_legal_pressure",
        [
            "DOT",
            "CFPB",
            "EU",
            "regulator",
            "regulators",
            "scrutiny",
            "investigation",
            "lawsuit",
            "sued",
            "suing",
            "court",
            "legal",
            "bait-and-switch",
            "监管",
            "调查",
            "诉讼",
            "法院",
        ],
    ),
    (
        "operational_reliability",
        [
            "not posting",
            "missing points",
            "credit clawback",
            "clawback",
            "system bug",
            "transfer failed",
            "account shutdown",
            "downtime",
            "不到账",
            "扣回",
            "追回",
            "系统异常",
            "失败",
        ],
    ),
    (
        "supply_demand_stress",
        [
            "peak travel",
            "high occupancy",
            "sold out",
            "fleet shortage",
            "high load factor",
            "limited availability",
            "旺季",
            "供给紧张",
            "库存紧张",
        ],
    ),
    (
        "consumer_backlash",
        [
            "complaints",
            "protest",
            "rebel",
            "backlash",
            "outrage",
            "rollback",
            "forum reports",
            "many users",
            "用户投诉",
            "抗议",
            "回滚",
            "多用户",
        ],
    ),
]

STAKEHOLDER_KEYWORDS: dict[str, list[str]] = {
    "member": ["member", "cardholder", "consumer", "guest", "customer", "会员", "用户", "客人"],
    "hotel_owner": ["hotel owner", "owners", "业主"],
    "franchisee": ["franchisee", "franchisees", "加盟商"],
    "airline_partner": ["airline partner", "partner airline", "partner carriers", "联盟伙伴", "伙伴航司"],
    "issuer": ["issuer", "bank", "Chase", "Amex", "Citi", "Capital One", "发卡行", "银行"],
    "merchant": ["merchant", "vendor", "商户"],
    "regulator": ["DOT", "CFPB", "regulator", "regulators", "EU", "court", "lawsuit", "监管", "法院"],
    "rental_location": ["rental location", "airport location", "airport locations", "branch", "locations", "门店"],
}

C_END_TOPICS = {
    "offer",
    "transfer_bonus",
    "statement_credit",
    "portal_stack",
    "status_match",
    "lounge",
    "policy_change",
    "devaluation",
}
TITLE_AUTHORITATIVE_TOPICS = {
    "bug",
    "clawback",
    "offer",
    "transfer_bonus",
    "portal_stack",
    "statement_credit",
    "lounge",
    "status_match",
    "policy_change",
    "devaluation",
    "industry_signal",
}
RISK_TOPICS = {"bug", "clawback"}
LOW_VALUE_ACTION_PHRASES = {
    "give it a miss",
    "skip this offer",
    "poor value",
    "not worth it",
    "avoid this offer",
    "不值得",
    "不建议转",
}
NOISE_KEYWORDS = ["有奖征文", "回帖奖励", "广告", "飞米", "置顶", "灌水", "best cards", "best credit cards", "best business cards", "how to "]
KNOWN_CROSS_BOARD_AD_PHRASES = ["兴业三款白金卡火热申办中"]
LOW_SIGNAL_ROUNDUP_MARKERS = ["[roundup]", "daily roundup", "news roundup", "bits:"]
LOW_SIGNAL_EVERGREEN_PATTERNS = [
    r"^should you get\b",
    r"\breasons (?:it(?:'s| is) )?worth it\b",
    r"\bis .+ worth it\??$",
    r"\bcomplete guide\b",
    r"\beverything you need to know\b",
    r"\bsweet spots?\b",
]
FRESH_EVENT_TITLE_TERMS = [
    "new",
    "increased",
    "decreased",
    "changed",
    "changing",
    "ending",
    "ends",
    "limited",
    "targeted",
    "devaluation",
    "clawback",
    "bug",
    "failed",
    "now",
    "today",
    "this week",
    "新增",
    "提高",
    "降低",
    "变化",
    "即将结束",
    "限时",
    "定向",
    "贬值",
    "追回",
    "异常",
]
FORUM_QUESTION_PATTERNS = [
    r"\?$",
    r"\bquestions?\s*$",
    r"^(?:why|how|when|where|will|would|can|could|should|is|are|do|does|did)\b",
    r"\b(?:why|how|will|would|can|could|should|does|did)\b[^?]*\?$",
    r"^no .+ - why\??$",
]
FORUM_CHANGE_EVIDENCE_TERMS = [
    "announced",
    "announcement",
    "changed",
    "changing",
    "new rule",
    "new policy",
    "no longer",
    "ending",
    "increased",
    "decreased",
    "devaluation",
    "clawback",
    "not working",
    "failed",
    "missing points",
    "multiple users",
    "many users",
    "data points",
    "dp thread",
    "公告",
    "规则变化",
    "不再",
    "即将结束",
    "提高",
    "降低",
    "贬值",
    "追回",
    "失败",
    "不到账",
    "多用户",
]
FORUM_SIGNAL_TITLE_TERMS = [
    "points",
    "miles",
    "award",
    "reward",
    "elite",
    "status",
    "upgrade",
    "benefit",
    "promo",
    "promotion",
    "bonus",
    "offer",
    "credit",
    "cashback",
    "clawback",
    "bug",
    "breakfast",
    "lounge",
    "transfer",
    "register",
    "registration",
    "booking",
    "pricing",
    "price",
    "ota",
    "积分",
    "里程",
    "兑换",
    "会籍",
    "升级",
    "权益",
    "优惠",
    "活动",
    "返现",
    "休息室",
    "早餐",
    "价格",
]
GENERIC_TRAVEL_NEWS_TITLE_PATTERNS = [
    r"\bceo\b",
    r"chief executive",
    r"\bdebut\b",
    r"\bwill open\b",
    r"\bopening (?:in|on|next)\b",
    r"\bnew hotel\b",
    r"\bnew route\b",
    r"launch(?:es|ing)? (?:a )?new route",
    r"flight schedule",
]
GENERIC_TRAVEL_NEWS_EXEMPT_TERMS = [
    "loyalty",
    "rewards program",
    "honors program",
    "points",
    "miles",
    "award",
    "status",
    "lounge",
    "credit card",
    "co-brand",
    "积分",
    "里程",
    "会籍",
    "休息室",
]
CONSUMER_BACKLASH_SCALE_ANCHORS = [
    "many users",
    "multiple users",
    "dozens",
    "hundreds",
    "thousands",
    "widespread",
    "mass complaints",
    "class action",
    "petition",
    "owners",
    "franchisees",
    "多用户",
    "多名",
    "大量",
    "数十",
    "集体投诉",
    "业主",
    "加盟商",
]
LOYALTY_TRAVEL_TERMS = [
    "loyalty",
    "rewards",
    "points",
    "miles",
    "award",
    "elite",
    "status",
    "transfer",
    "travel",
    "hotel",
    "airline",
    "flight",
    "lounge",
    "airport",
    "rental car",
    "bonvoy",
    "hyatt",
    "hilton",
    "ihg",
    "sapphire",
    "ultimate rewards",
    "membership rewards",
    "platinum",
    "flying blue",
    "avios",
    "skymiles",
    "mileageplus",
    "积分",
    "里程",
    "兑换",
    "会籍",
    "酒店",
    "航司",
    "航班",
    "休息室",
    "租车",
]
CREDIT_CARD_TRAVEL_TERMS = [
    "transfer",
    "travel",
    "hotel",
    "airline",
    "flight",
    "miles",
    "award",
    "lounge",
    "airport",
    "rental car",
    "bonvoy",
    "hyatt",
    "hilton",
    "ihg",
    "sapphire",
    "ultimate rewards",
    "membership rewards",
    "platinum",
    "bilt",
    "flying blue",
    "avios",
    "skymiles",
    "mileageplus",
    "积分转点",
    "里程",
    "酒店",
    "航司",
    "休息室",
    "租车",
]
LOYALTY_REWARDS_ANCHORS = [
    "loyalty",
    "reward",
    "rewards",
    "points",
    "miles",
    "award",
    "redemption",
    "redeem",
    "elite",
    "status match",
    "status challenge",
    "co-brand",
    "co-branded",
    "cobrand",
    "Bonvoy",
    "World of Hyatt",
    "Hilton Honors",
    "IHG One Rewards",
    "SkyMiles",
    "MileagePlus",
    "AAdvantage",
    "Aeroplan",
    "Avios",
    "Flying Blue",
    "Ultimate Rewards",
    "Membership Rewards",
    "忠诚计划",
    "奖励计划",
    "积分",
    "里程",
    "兑换",
    "会员",
    "会籍",
    "保级",
    "联名卡",
]
MAJOR_LOYALTY_BRAND_ANCHORS = [
    # Hotels
    "Marriott",
    "Hyatt",
    "Hilton",
    "IHG",
    "Accor",
    "Wyndham",
    "Choice Privileges",
    "Radisson Rewards",
    # Airlines
    "United Airlines",
    "Delta Air Lines",
    "American Airlines",
    "Air Canada",
    "Air China",
    "British Airways",
    "Lufthansa",
    "Singapore Airlines",
    "Cathay Pacific",
    "Qantas",
    # Card rewards
    "Chase",
    "American Express",
    "Amex",
    "Capital One",
    "Citi ThankYou",
    "Bilt Rewards",
    "U.S. Bank",
    "US Bank",
    # Rental cars
    "Hertz",
    "Avis",
    "National Car Rental",
    "Enterprise Rent-A-Car",
    "Sixt",
]
ECOSYSTEM_ANCHORS = LOYALTY_REWARDS_ANCHORS + MAJOR_LOYALTY_BRAND_ANCHORS
REGULATORY_REWARDS_ANCHORS = [
    "DOT",
    "CFPB",
    "regulator",
    "regulators",
    "regulatory",
    "investigation",
    "scrutiny",
    "bait-and-switch",
    "reward program",
    "rewards program",
    "loyalty program",
    "frequent flyer program",
    "devaluation",
    "points value",
    "point value",
    "miles value",
    "mile value",
    "award pricing",
    "redemption value",
    "监管",
    "调查",
    "忠诚计划",
    "奖励计划",
    "贬值",
    "积分价值",
    "里程价值",
]
METRIC_PATTERN = re.compile(
    r"(?i)(?:"
    r"[$€£]\s?\d[\d,]*(?:\.\d+)?(?:(?:\s?(?:bn|b|m|k)\b)|(?:\s+(?:million|billion)\b))?"
    r"|\b\d[\d,]*(?:\.\d+)?(?:k|m)?\s+(?:bonus\s+)?"
    r"(?:[a-z][a-z0-9+&.-]*\s+){0,2}(?:points?|pts|miles?|avios|sqcs?)\b"
    r"|\b\d+(?:\.\d+)?\s?%"
    r"|\b\d+\s?:\s?\d+\b"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:k|m|points|pts|miles|avios|sqcs?|x|owners|users|nights|credits|fewer miles|per\s+stay)\b"
    r")"
)
MONTH_LOOKUP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def keyword_matches(text_lower: str, keyword: str) -> bool:
    keyword_lower = keyword.strip().lower()
    if not keyword_lower:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 -]{0,48}", keyword_lower):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword_lower)}(?![a-z0-9])", text_lower) is not None
    return keyword_lower in text_lower


def detect_values(text: str, keyword_map: dict[str, list[str]], fallback: list[str] | None = None) -> list[str]:
    lower = text.lower()
    values: list[str] = []
    for value, keywords in keyword_map.items():
        for keyword in keywords:
            if keyword_matches(lower, keyword):
                if value not in values:
                    values.append(value)
                break
    if not values:
        for item in fallback or []:
            if item not in values:
                values.append(item)
    return values


def detect_topic(text: str) -> str:
    lower = text.lower()
    for topic, keywords in TOPIC_KEYWORDS:
        if any(keyword_matches(lower, keyword) for keyword in keywords):
            return topic
    return "datapoint"


def title_has_offer_intent(title: str) -> bool:
    lower = normalize_event_text(title)
    has_offer_anchor = any(
        keyword_matches(lower, keyword)
        for keyword in [
            "offer",
            "bonus",
            "welcome offer",
            "welcome bonus",
            "signup bonus",
            "sign-up bonus",
            "promotion",
            "优惠",
            "奖励",
            "活动",
        ]
    )
    numeric_reward_offer = bool(
        re.search(r"\b\d[\d,]*(?:\.\d+)?\s*(?:k\s*)?(?:points?|miles?)\b", lower)
        and any(
            keyword_matches(lower, keyword)
            for keyword in ["card", "spend", "apply", "open", "earn", "消费", "开卡"]
        )
    )
    has_offer_anchor = has_offer_anchor or numeric_reward_offer
    has_offer_timing = any(
        keyword_matches(lower, keyword)
        for keyword in [
            "ending soon",
            "ends soon",
            "apply now",
            "best ever",
            "limited-time",
            "limited time",
            "限时",
            "即将结束",
        ]
    )
    structural_change = any(
        keyword_matches(lower, keyword)
        for keyword in [
            "annual fee",
            "benefits changing",
            "benefit changes",
            "eligibility rule",
            "new eligibility",
            "no longer eligible",
            "refresh",
            "revamp",
            "年费",
            "权益变化",
            "资格规则",
            "改版",
        ]
    )
    return has_offer_anchor and (has_offer_timing or not structural_change)


def title_has_strong_offer_intent(title: str) -> bool:
    lower = normalize_event_text(title)
    explicit = any(
        keyword_matches(lower, keyword)
        for keyword in [
            "bonus",
            "welcome offer",
            "welcome bonus",
            "signup bonus",
            "sign-up bonus",
            "promotion",
            "ending soon",
            "ends soon",
            "apply now",
            "best ever",
            "开卡奖励",
            "即将结束",
            "限时",
        ]
    )
    quantified = bool(
        re.search(r"\b\d[\d,]*(?:\.\d+)?\s*(?:k\s*)?(?:points?|miles?)\b", lower)
        and any(
            keyword_matches(lower, keyword)
            for keyword in ["card", "spend", "apply", "open", "earn", "消费", "开卡"]
        )
    )
    return explicit or quantified


def title_has_portal_stack_intent(title: str) -> bool:
    lower = normalize_event_text(title)
    stack_anchor = any(
        keyword_matches(lower, keyword)
        for keyword in ["stack", "stacking", "portal stack", "shopping portal", "rakuten", "叠加", "返利门户"]
    )
    commerce_anchor = any(
        keyword_matches(lower, keyword)
        for keyword in ["purchase", "purchases", "cashback", "cash back", "offer", "points", "返现", "消费"]
    )
    return stack_anchor and commerce_anchor


def title_has_transfer_bonus_intent(title: str) -> bool:
    lower = normalize_event_text(title)
    has_transfer = any(
        keyword_matches(lower, keyword)
        for keyword in ["transfer", "convert", "转点", "转分"]
    )
    has_bonus = any(
        keyword_matches(lower, keyword)
        for keyword in ["bonus", "boost", "奖励", "加赠"]
    )
    has_loyalty_unit = any(
        keyword_matches(lower, keyword)
        for keyword in ["points", "miles", "rewards", "积分", "里程"]
    )
    return has_transfer and has_bonus and has_loyalty_unit


def text_has_award_devaluation_intent(text: str) -> bool:
    lower = normalize_event_text(text)
    if any(
        keyword_matches(lower, keyword)
        for keyword in ["points devaluation", "miles devaluation", "积分贬值", "里程贬值"]
    ):
        return True
    award_anchor = any(
        keyword_matches(lower, keyword)
        for keyword in ["award", "redemption", "redeem", "points price", "points cost", "兑换", "积分房"]
    )
    higher_cost = any(
        keyword_matches(lower, keyword)
        for keyword in [
            "devaluation",
            "devalued",
            "cost more",
            "higher cost",
            "higher price",
            "prices increased",
            "pricing increased",
            "raised prices",
            "increased cost",
            "widespread increase",
            "raises points prices",
            "raises prices",
            "price increase",
            "price increases",
            "award chart increase",
            "increases award pricing",
            "increased award pricing",
            "raises award prices",
            "raised award prices",
            "award prices increased",
            "贬值",
            "兑换成本上升",
            "积分上涨",
        ]
    )
    return award_anchor and higher_cost


def detect_item_topic(title: str, summary: str, source_type: str = "rss") -> str:
    title_topic = detect_topic(title)
    combined_topic = detect_topic(" ".join([title, summary]))
    if title_has_portal_stack_intent(title):
        return "portal_stack"
    if text_has_award_devaluation_intent(" ".join([title, summary])):
        return "devaluation"
    if title_topic in RISK_TOPICS:
        return title_topic
    if title_has_transfer_bonus_intent(title):
        return "transfer_bonus"
    if combined_topic in RISK_TOPICS and not title_has_strong_offer_intent(title):
        return combined_topic
    if title_topic in {"transfer_bonus", "status_match", "statement_credit", "lounge"}:
        return title_topic
    if title_has_offer_intent(title) and (
        combined_topic not in RISK_TOPICS or title_has_strong_offer_intent(title)
    ):
        return "offer"
    if source_type == "blog_comment":
        if title_topic != "datapoint":
            return title_topic
        return detect_topic(summary)
    if title_topic != "datapoint":
        return title_topic
    return combined_topic


def extract_metric_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for match in METRIC_PATTERN.finditer(text):
        snippet = re.sub(r"\s+", " ", match.group(0).strip())
        snippet = snippet.replace(" :", ":").replace(": ", ":")
        if re.fullmatch(r"\d+:\d+", snippet):
            before = text[max(0, match.start() - 16) : match.start()]
            after = text[match.end() : match.end() + 12]
            if re.search(r"\b(?:at|by|before|until)\s*$", before, re.I) or re.match(
                r"\s*(?:a\.?m\.?|p\.?m\.?|ET|PT|UTC)\b", after, re.I
            ):
                continue
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 8:
            break
    return snippets


def reference_date_or_today(reference_date: dt.datetime | dt.date | None = None) -> dt.date:
    if isinstance(reference_date, dt.datetime):
        return reference_date.date()
    if isinstance(reference_date, dt.date):
        return reference_date
    return dt.datetime.now(dt.UTC).date()


def normalize_future_date(year: int | None, month: int, day: int, reference_date: dt.date) -> dt.date | None:
    candidate_year = year or reference_date.year
    try:
        candidate = dt.date(candidate_year, month, day)
    except ValueError:
        return None
    if year is None and candidate < reference_date:
        try:
            candidate = dt.date(candidate_year + 1, month, day)
        except ValueError:
            return None
    return candidate


def detect_future_event_dates(
    text: str,
    reference_date: dt.datetime | dt.date | None = None,
    window_days: int = 60,
) -> list[str]:
    """Extract explicit dates within the next two months from a source item."""
    ref_date = reference_date_or_today(reference_date)
    found: list[str] = []

    def add_candidate(candidate: dt.date | None) -> None:
        if not candidate:
            return
        days = (candidate - ref_date).days
        if 0 <= days <= window_days:
            value = candidate.isoformat()
            if value not in found:
                found.append(value)

    for year, month, day in re.findall(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text):
        add_candidate(normalize_future_date(int(year), int(month), int(day), ref_date))

    for month, day, year in re.findall(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b", text):
        add_candidate(normalize_future_date(int(year) if year else None, int(month), int(day), ref_date))

    month_names = "|".join(sorted(MONTH_LOOKUP, key=len, reverse=True))
    month_pattern = re.compile(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:,\s*(20\d{{2}}))?\b", re.I)
    for month_name, day, year in month_pattern.findall(text):
        month = MONTH_LOOKUP[month_name.lower().rstrip(".")]
        add_candidate(normalize_future_date(int(year) if year else None, month, int(day), ref_date))

    for month, day in re.findall(r"(\d{1,2})月(\d{1,2})日", text):
        add_candidate(normalize_future_date(None, int(month), int(day), ref_date))

    return found


def detect_verticals(text: str, programs: list[str], cards: list[str], source_cfg: dict[str, Any]) -> list[str]:
    verticals = detect_values(text, VERTICAL_KEYWORDS, fallback=source_cfg.get("verticals", []))
    program_text = " ".join(programs + cards)
    if any(keyword_matches(program_text.lower(), kw) for kw in VERTICAL_KEYWORDS["hotel"]):
        if "hotel" not in verticals:
            verticals.append("hotel")
    if any(keyword_matches(program_text.lower(), kw) for kw in VERTICAL_KEYWORDS["airline"]):
        if "airline" not in verticals:
            verticals.append("airline")
    if any(keyword_matches(program_text.lower(), kw) for kw in VERTICAL_KEYWORDS["credit_card"]):
        if "credit_card" not in verticals:
            verticals.append("credit_card")
    if any(keyword_matches(program_text.lower(), kw) for kw in VERTICAL_KEYWORDS["rental_car"]):
        if "rental_car" not in verticals:
            verticals.append("rental_car")
    return verticals


def detect_ecosystem_signals(text: str) -> list[str]:
    lower = text.lower()
    if not any(keyword_matches(lower, keyword) for keyword in ECOSYSTEM_ANCHORS):
        return []
    signals: list[str] = []
    for signal, keywords in ECOSYSTEM_SIGNAL_KEYWORDS:
        if not any(keyword_matches(lower, keyword) for keyword in keywords):
            continue
        if signal == "regulatory_or_legal_pressure" and not any(
            keyword_matches(lower, keyword) for keyword in REGULATORY_REWARDS_ANCHORS
        ):
            continue
        if signal == "consumer_backlash" and not any(
            keyword_matches(lower, keyword) for keyword in CONSUMER_BACKLASH_SCALE_ANCHORS
        ):
            continue
        signals.append(signal)
    return signals


def detect_stakeholders(text: str, verticals: list[str], programs: list[str]) -> list[str]:
    stakeholders = detect_values(text, STAKEHOLDER_KEYWORDS)
    if programs or verticals:
        if "member" not in stakeholders:
            stakeholders.append("member")
    if "credit_card" in verticals and "issuer" not in stakeholders:
        stakeholders.append("issuer")
    if "rental_car" in verticals and "rental_location" not in stakeholders:
        stakeholders.append("rental_location")
    return stakeholders


def detect_action_label(text: str, topic: str, risk: str, signals: list[str]) -> str:
    lower = text.lower()
    if risk in {"可能 clawback", "高风控风险"} or topic == "clawback":
        return "高风险勿操作"
    if topic == "bug":
        return "高风险勿操作"
    if topic == "devaluation":
        return "只观察"
    if any(keyword_matches(lower, keyword) for keyword in LOW_VALUE_ACTION_PHRASES):
        return "只观察"
    if signals and topic not in {
        "offer",
        "transfer_bonus",
        "statement_credit",
        "portal_stack",
        "status_match",
        "lounge",
    }:
        return "只观察"
    if any(keyword_matches(lower, keyword) for keyword in ["register", "registration", "enroll", "activate", "报名", "激活", "领取"]):
        return "需报名"
    if any(keyword_matches(lower, keyword) for keyword in ["targeted", "ymmv", "your mileage may vary", "定向", "部分账户"]):
        return "定向/YMMV"
    if topic in C_END_TOPICS:
        return "可直接用"
    if signals:
        return "只观察"
    return "只观察"


def detect_consumer_impact(topic: str, risk: str, signals: list[str], action_label: str) -> str:
    if risk in {"可能 clawback", "高风控风险"} or topic in RISK_TOPICS:
        return "需避坑"
    if topic in {"transfer_bonus", "offer", "statement_credit", "portal_stack", "status_match"}:
        if action_label == "只观察":
            return "长期观察"
        return "直接可用"
    if "devaluation_or_inflation" in signals or topic == "devaluation":
        return "可能贬值"
    if "benefit_capacity_pressure" in signals or "operational_reliability" in signals:
        return "权益履约风险"
    if action_label in {"需报名", "可直接用", "定向/YMMV"}:
        return "直接可用"
    return "长期观察"


def detect_impact_horizon(text: str, topic: str, risk: str, action_label: str, signals: list[str]) -> str:
    lower = text.lower()
    if risk in {"可能 clawback", "高风控风险"} or topic in RISK_TOPICS:
        return "today"
    if action_label in {"需报名", "可直接用", "定向/YMMV"}:
        return "this_week"
    if any(keyword in lower for keyword in ["today", "now", "ends", "expires", "through", "until", "截止", "结束"]):
        return "this_week"
    if signals:
        return "watchlist"
    return "this_week"


def detect_risk(text: str, topic: str) -> str:
    lower = text.lower()
    if topic == "clawback":
        return "可能 clawback"
    if topic == "bug":
        return "YMMV"
    for label, keywords in RISK_KEYWORDS.items():
        if any(keyword_matches(lower, keyword) for keyword in keywords):
            return label
    return "正常权益"


def confidence_for(source_cfg: dict[str, Any], source_type: str) -> str:
    site = source_cfg.get("site", "")
    if source_type == "blog_comment":
        return "多用户 DP"
    if site in {
        "Doctor of Credit",
        "Frequent Miler",
        "US Credit Card Guide",
        "LoyaltyLobby",
        "One Mile at a Time",
        "View from the Wing",
        "Skift",
        "HospitalityNet",
        "The Points Guy",
        "AwardWallet",
        "DannyDealGuru",
        "MilesTalk",
        "DansDeals",
        "Google News",
    }:
        return "博客整理"
    return "单帖线索"


def build_why(
    programs: list[str],
    cards: list[str],
    topic: str,
    risk: str,
    verticals: list[str],
    signals: list[str],
    consumer_impact: str,
) -> str:
    targets = []
    for value in programs + cards:
        if value and value not in targets:
            targets.append(value)
    target_text = "、".join(targets[:4]) if targets else "你的常旅客/信用卡组合"
    if signals:
        signal_text = "、".join(signals[:3])
        vertical_text = "、".join(verticals[:3]) if verticals else "忠诚计划"
        return f"属于 {vertical_text} 的结构性信号（{signal_text}），对你的影响判断为：{consumer_impact}。"
    if topic == "policy_change":
        return f"可能改变 {target_text} 的长期持有价值、权益使用方式或保级/兑换策略。"
    if topic == "transfer_bonus":
        return f"可能影响 {target_text} 的转点价值和兑换窗口，尤其涉及 Hyatt、Marriott、Flying Blue 等伙伴时。"
    if topic == "lounge":
        return f"可能影响 {target_text} 的机场休息室进入、携伴或路线选择。"
    if topic == "status_match":
        return f"可能影响 {target_text} 的会籍匹配、挑战或租车/酒店权益获取窗口。"
    if topic == "portal_stack":
        return f"可能影响 {target_text} 的订房门户叠加、返现或酒店权益兑现。"
    if topic == "statement_credit":
        return f"可能影响 {target_text} 的 statement credit、酒店 credit 或旅行报销使用方式。"
    if topic == "devaluation":
        return f"可能削弱 {target_text} 的积分/里程兑换价值，需要观察兑换成本变化。"
    if topic == "clawback":
        return f"涉及权益扣回或积分/credit 收回，使用 {target_text} 时需要保守处理。"
    if topic == "bug":
        return f"涉及系统异常或到账失败，可能影响 {target_text} 的短期操作。"
    if topic == "offer":
        return f"可能是 {target_text} 可用的限时收益、报名活动或叠加机会。"
    if risk != "正常权益":
        return f"与 {target_text} 相关，但存在 {risk}，应先当作论坛线索处理。"
    return f"与 {target_text} 相关，值得作为后续决策线索保留。"


def score_item(
    source_cfg: dict[str, Any],
    programs: list[str],
    cards: list[str],
    topic: str,
    risk: str,
    title: str,
    summary: str,
    verticals: list[str],
    signals: list[str],
    action_label: str,
    metric_snippets: list[str],
    future_event_dates: list[str],
) -> int:
    score = {"P0": 40, "P1": 25, "P2": 8}.get(source_cfg.get("priority", ""), 10)
    score += {
        "policy_change": 38,
        "clawback": 38,
        "bug": 34,
        "transfer_bonus": 34,
        "statement_credit": 32,
        "portal_stack": 30,
        "status_match": 30,
        "devaluation": 36,
        "lounge": 28,
        "offer": 24,
        "industry_signal": 30,
        "datapoint": 12,
        "trip_report": 2,
    }.get(topic, 8)
    score += min(len(programs), 3) * 8
    score += min(len(cards), 3) * 8
    score += min(len(verticals), 2) * 4
    if signals:
        score += 18
    if any(signal in signals for signal in {"regulatory_or_legal_pressure", "cost_reimbursement_conflict", "devaluation_or_inflation"}):
        score += 8
    if action_label in {"需报名", "高风险勿操作"}:
        score += 8
    elif action_label == "定向/YMMV":
        score += 4
    if risk in {"可能 clawback", "高风控风险"}:
        score += 12
    if metric_snippets:
        score += 8
    if future_event_dates:
        score += 10
    if topic == "trip_report":
        score -= 18
    item_text_lower = f"{title} {summary}".lower()
    if any(keyword in item_text_lower for keyword in NOISE_KEYWORDS):
        score -= 25
    if any(keyword_matches(item_text_lower, keyword) for keyword in LOW_VALUE_ACTION_PHRASES):
        score -= 20
    return max(score, 0)


def classify_row(
    row: dict[str, Any],
    source_cfg: dict[str, Any],
    profile_keywords: dict[str, list[str]],
    card_keywords: dict[str, list[str]],
    reference_date: dt.datetime | dt.date | None = None,
) -> IntelItem:
    title_text = row.get("title", "")
    summary_text = row.get("summary", "")
    main_text = " ".join([title_text, summary_text])
    text = " ".join([main_text, " ".join(row.get("raw_tags", []))])
    source_type = row.get("source_type") or source_cfg.get("source_type", "rss")
    fallback_programs = source_cfg.get("programs", []) if source_cfg.get("program_fallback") else []
    topic = detect_item_topic(title_text, summary_text, source_type)
    title_programs = detect_values(title_text, profile_keywords)
    title_cards = detect_values(title_text, card_keywords)
    title_is_authoritative = source_type == "blog_comment" or topic in TITLE_AUTHORITATIVE_TOPICS
    if title_is_authoritative:
        programs = title_programs or list(fallback_programs)
        cards = title_cards
    else:
        programs = detect_values(text, profile_keywords, fallback=fallback_programs)
        cards = detect_values(text, card_keywords)
    vertical_text = title_text if topic in TITLE_AUTHORITATIVE_TOPICS else text
    vertical_source_cfg = source_cfg if source_cfg.get("program_fallback") else {**source_cfg, "verticals": []}
    verticals = detect_verticals(vertical_text, programs, cards, vertical_source_cfg)
    signal_text = title_text if topic in {
        "offer",
        "transfer_bonus",
        "portal_stack",
        "statement_credit",
        "lounge",
    } else main_text
    signals = detect_ecosystem_signals(signal_text)
    if topic == "datapoint" and signals:
        topic = "industry_signal"
    elif topic == "policy_change" and "regulatory_or_legal_pressure" in signals:
        topic = "industry_signal"
    elif topic == "industry_signal" and not signals:
        topic = "datapoint"
    risk = detect_risk(main_text, topic)
    stakeholders = detect_stakeholders(text, verticals, programs)
    metric_snippets = extract_metric_snippets(main_text)
    future_event_dates = detect_future_event_dates(main_text, reference_date=reference_date)
    action_label = detect_action_label(main_text, topic, risk, signals)
    consumer_impact = detect_consumer_impact(topic, risk, signals, action_label)
    impact_horizon = detect_impact_horizon(main_text, topic, risk, action_label, signals)
    if future_event_dates:
        impact_horizon = "next_60_days"
    score = score_item(
        source_cfg,
        programs,
        cards,
        topic,
        risk,
        row.get("title", ""),
        row.get("summary", ""),
        verticals,
        signals,
        action_label,
        metric_snippets,
        future_event_dates,
    )
    return IntelItem(
        source=source_cfg.get("name") or source_cfg.get("site") or source_cfg["id"],
        source_id=source_cfg["id"],
        source_type=source_type,
        priority=source_cfg.get("priority", ""),
        program=programs,
        card_family=cards,
        topic_type=topic,
        title=row.get("title", ""),
        url=row.get("url", ""),
        published_at=row.get("published_at"),
        summary=row.get("summary", ""),
        why_it_matters=build_why(programs, cards, topic, risk, verticals, signals, consumer_impact),
        confidence_label=confidence_for(source_cfg, source_type),
        risk_label=risk,
        score=score,
        vertical=verticals,
        ecosystem_signal_type=signals,
        stakeholders=stakeholders,
        consumer_impact=consumer_impact,
        impact_horizon=impact_horizon,
        action_label=action_label,
        metric_snippets=metric_snippets,
        future_event_dates=future_event_dates,
        raw_tags=row.get("raw_tags", []),
        author=row.get("author", ""),
    )


def apply_multisource_confidence(items: list[IntelItem]) -> None:
    buckets: dict[tuple[str, str], list[IntelItem]] = {}
    for item in items:
        key_program = item.program[0] if item.program else ""
        if key_program:
            buckets.setdefault((item.topic_type, key_program), []).append(item)
    for bucket_items in buckets.values():
        sources = {item.source_id for item in bucket_items}
        if len(bucket_items) >= 2 and len(sources) >= 2:
            for item in bucket_items:
                if item.confidence_label != "多用户 DP":
                    item.confidence_label = "多源重复"
                item.score += 10


def merge_unique(values: list[str]) -> list[str]:
    merged: list[str] = []
    for value in values:
        if value and value not in merged:
            merged.append(value)
    return merged


def canonical_item_key(item: IntelItem) -> str:
    if item.url:
        parsed = urllib.parse.urlparse(item.url)
        params = urllib.parse.parse_qs(parsed.query)
        tid = params.get("tid", [""])[0]
        if "flyert.com" in parsed.netloc and tid:
            return f"flyert:{tid}"
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
    return re.sub(r"\s+", " ", item.title.lower()).strip()


def dedupe_items(items: list[IntelItem]) -> list[IntelItem]:
    kept: dict[str, IntelItem] = {}
    for item in items:
        key = canonical_item_key(item)
        existing = kept.get(key)
        if not existing:
            kept[key] = item
            continue
        primary, secondary = (item, existing) if item.score > existing.score else (existing, item)
        primary.source = " / ".join(merge_unique(primary.source.split(" / ") + secondary.source.split(" / ")))
        primary.program = merge_unique(primary.program + secondary.program)
        primary.card_family = merge_unique(primary.card_family + secondary.card_family)
        primary.vertical = merge_unique(primary.vertical + secondary.vertical)
        primary.ecosystem_signal_type = merge_unique(primary.ecosystem_signal_type + secondary.ecosystem_signal_type)
        primary.stakeholders = merge_unique(primary.stakeholders + secondary.stakeholders)
        primary.metric_snippets = merge_unique(primary.metric_snippets + secondary.metric_snippets)
        primary.future_event_dates = merge_unique(primary.future_event_dates + secondary.future_event_dates)
        primary.raw_tags = merge_unique(primary.raw_tags + secondary.raw_tags)
        if primary.confidence_label != "多用户 DP":
            primary.confidence_label = "多源重复"
        primary.score = max(primary.score, secondary.score) + 5
        kept[key] = primary
    return list(kept.values())


EVENT_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "the",
    "this",
    "to",
    "with",
    "again",
    "another",
    "many",
    "more",
    "new",
    "now",
    "points",
    "program",
    "rewards",
}
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def canonical_event_url(url: str) -> str:
    """Return a stable article URL while preserving forum thread identity."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if "flyert.com" in parsed.netloc.lower():
        tid = next((value for key, value in query if key == "tid"), "")
        if tid:
            return f"flyert:{tid}"
    kept_query = [
        (key, value)
        for key, value in query
        if key.lower() not in TRACKING_QUERY_KEYS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urllib.parse.urlencode(sorted(kept_query)),
            "",
        )
    )


def normalize_event_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value, max_len=4000)).casefold()
    text = re.sub(r"^评论\s*dp\s*[:：]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def event_tokens(value: str) -> set[str]:
    """Build conservative English tokens and Chinese bigrams for event matching."""
    normalized = normalize_event_text(value)
    tokens: set[str] = set()
    for part in re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*|[\u3400-\u9fff]+", normalized):
        if re.search(r"[\u3400-\u9fff]", part):
            if len(part) == 1:
                tokens.add(part)
            else:
                tokens.update(part[index : index + 2] for index in range(len(part) - 1))
            continue
        token = part.strip("-'")
        if len(token) <= 2 or token in EVENT_STOP_WORDS:
            continue
        aliases = {
            "prices": "price",
            "pricing": "price",
            "priced": "price",
            "costs": "cost",
            "raised": "increase",
            "raises": "increase",
            "increases": "increase",
            "increased": "increase",
            "properties": "property",
            "hotels": "hotel",
            "promotion": "offer",
            "promotions": "offer",
            "promo": "offer",
            "offers": "offer",
            "elites": "elite",
            "flight": "trip",
            "flights": "trip",
            "trips": "trip",
            "sqcs": "sqc",
            "yul": "montreal",
        }
        tokens.add(aliases.get(token, token))
    return tokens


def normalized_values(values: list[str]) -> set[str]:
    return {normalize_event_text(value) for value in values if value}


def normalized_metric_values(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        compact = re.sub(r"[\s,]+", "", normalize_event_text(value))
        if not compact:
            continue
        normalized.add(compact)
        match = re.fullmatch(
            r"[$€£]?([0-9]+(?:\.[0-9]+)?)([kmb])?"
            r"(?:points?|pts|miles?|owners?|users?|nights?|credits?|%)?",
            compact,
        )
        if not match:
            continue
        number = float(match.group(1))
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(match.group(2), 1)
        scaled = number * multiplier
        normalized.add(f"number:{scaled:g}")
    return normalized


def items_represent_same_event(left: IntelItem, right: IntelItem) -> bool:
    left_url = canonical_event_url(left.url)
    right_url = canonical_event_url(right.url)
    if left_url and left_url == right_url:
        return True

    left_title = normalize_event_text(left.title)
    right_title = normalize_event_text(right.title)
    if left_title and left_title == right_title:
        return True
    shared_programs = normalized_values(left.program) & normalized_values(right.program)
    shared_cards = normalized_values(left.card_family) & normalized_values(right.card_family)
    shared_verticals = set(left.vertical) & set(right.vertical)
    shared_signals = set(left.ecosystem_signal_type) & set(right.ecosystem_signal_type)
    left_title_tokens = event_tokens(left.title)
    right_title_tokens = event_tokens(right.title)
    shared_title_tokens = left_title_tokens & right_title_tokens
    title_union = left_title_tokens | right_title_tokens
    title_similarity = len(shared_title_tokens) / len(title_union) if title_union else 0.0
    shared_metrics = normalized_metric_values(left.metric_snippets) & normalized_metric_values(right.metric_snippets)
    shared_dates = set(left.future_event_dates) & set(right.future_event_dates)
    if "partner_contract_shift" in shared_signals and shared_programs:
        generic_partner_tokens = {
            "airline",
            "benefit",
            "club",
            "elite",
            "expanded",
            "hilton",
            "hotel",
            "launch",
            "marriott",
            "offer",
            "partner",
            "partnership",
            "perk",
            "program",
        }
        program_tokens = event_tokens(" ".join(shared_programs))
        distinctive_tokens = shared_title_tokens - generic_partner_tokens - program_tokens
        if any(len(token) >= 5 for token in distinctive_tokens):
            return True
    if shared_programs and text_has_award_devaluation_intent(f"{left.title} {left.summary}") and text_has_award_devaluation_intent(
        f"{right.title} {right.summary}"
    ):
        return True
    topic_pair = {left.topic_type, right.topic_type}
    if (
        topic_pair == {"status_match", "industry_signal"}
        and len(shared_programs) >= 2
        and len(shared_title_tokens) >= 2
    ):
        return True
    if left.topic_type != right.topic_type:
        return False
    has_entity_anchor = bool(shared_programs or shared_cards or (shared_verticals and shared_signals))
    if not has_entity_anchor:
        return False

    if left.topic_type in RISK_TOPICS and shared_programs and shared_metrics:
        return True

    if left.topic_type == "offer":
        product_variants = {
            "schwab",
            "morgan stanley",
            "business",
            "personal",
            "preferred",
            "reserve",
            "resy",
        }
        left_variants = {value for value in product_variants if keyword_matches(left_title, value)}
        right_variants = {value for value in product_variants if keyword_matches(right_title, value)}
        if left_variants and right_variants and not (left_variants & right_variants):
            return False

        if shared_programs and (shared_metrics or shared_dates):
            generic_offer_tokens = {
                "bonus",
                "buy",
                "card",
                "earn",
                "ending",
                "offer",
                "points",
                "soon",
                "spend",
                "with",
            }
            program_tokens = event_tokens(" ".join(shared_programs))
            distinctive_tokens = shared_title_tokens - generic_offer_tokens - program_tokens
            if len(distinctive_tokens) >= 2 and title_similarity >= 0.25:
                return True

    if left.topic_type == "transfer_bonus" and len(shared_programs) >= 2 and len(shared_metrics) >= 2:
        return True

    if left.topic_type == "devaluation" and shared_programs:
        def has_award_price_signature(item: IntelItem) -> bool:
            tokens = event_tokens(f"{item.title} {item.summary}")
            return bool(
                tokens & {"award", "redemption", "redeem"}
                and tokens & {"price", "cost", "rate"}
                and tokens & {"devaluation", "increase", "higher", "rose", "inflation"}
            )

        if has_award_price_signature(left) and has_award_price_signature(right):
            return True

    if (shared_metrics or shared_dates) and len(shared_title_tokens) >= 3 and title_similarity >= 0.45:
        return True
    if (
        left.topic_type == "offer"
        and len(shared_programs) >= 2
        and len(shared_title_tokens) >= 3
        and title_similarity >= 0.22
    ):
        return True
    if (
        left.topic_type == "offer"
        and shared_programs
        and shared_cards
        and len(shared_title_tokens) >= 4
        and title_similarity >= 0.20
    ):
        return True
    if (
        left.topic_type == "industry_signal"
        and shared_programs
        and shared_signals
        and len(shared_title_tokens) >= 3
        and title_similarity >= 0.30
    ):
        return True
    if (
        left.topic_type == "policy_change"
        and shared_programs
        and len(shared_title_tokens) >= 5
        and title_similarity >= 0.50
    ):
        return True
    return len(shared_title_tokens) >= 5 and title_similarity >= 0.74


def evidence_from_item(item: IntelItem) -> Evidence:
    return Evidence(
        source_id=item.source_id,
        source=item.source,
        source_type=item.source_type,
        title=item.title,
        summary=item.summary,
        url=item.url,
        published_at=item.published_at,
        author=item.author,
    )


def representative_item(items: list[IntelItem]) -> IntelItem:
    def key(item: IntelItem) -> tuple[int, int, int, int, str]:
        return (
            int(item.source_type != "blog_comment"),
            int(parse_datetime(item.published_at) is not None),
            item.score,
            len(item.summary or ""),
            item.published_at or "",
        )

    return max(items, key=key)


def event_confidence(items: list[IntelItem]) -> str:
    source_ids = {item.source_id for item in items}
    if len(source_ids) >= 2:
        return "多源证实"
    authors = {item.author.strip().casefold() for item in items if item.author.strip()}
    if len(items) >= 2 and (len(authors) >= 2 or any(item.source_type == "blog_comment" for item in items)):
        return "多用户 DP"
    if items[0].source_type in {"rss", "blog"}:
        return "博客整理"
    return "单帖线索"


def event_fingerprint(items: list[IntelItem]) -> str:
    representative = representative_item(items)
    taxonomy_items = [item for item in items if item.source_type != "blog_comment"] or items
    return "|".join(
        [
            canonical_event_url(representative.url)
            or normalize_event_text(representative.title),
            representative.topic_type,
            *sorted(
                normalized_values(
                    merge_unique(
                        [value for item in taxonomy_items for value in item.program]
                    )
                )
            ),
        ]
    )


def event_from_items(items: list[IntelItem]) -> IntelEvent:
    representative = representative_item(items)
    taxonomy_items = [item for item in items if item.source_type != "blog_comment"] or items
    merged_programs = merge_unique(
        [value for item in taxonomy_items for value in item.program]
    )
    merged_cards = merge_unique(
        [value for item in taxonomy_items for value in item.card_family]
    )
    merged_verticals = merge_unique(
        [value for item in taxonomy_items for value in item.vertical]
    )
    title_text = " ".join(item.title for item in taxonomy_items)
    title_programs = detect_values(title_text, EVENT_TITLE_PROGRAM_KEYWORDS)
    if representative.topic_type in TITLE_AUTHORITATIVE_TOPICS or representative.ecosystem_signal_type:
        title_program_set = set(title_programs)
        event_programs = (
            [value for value in merged_programs if value in title_program_set]
            + [value for value in title_programs if value not in merged_programs]
            if title_programs
            else merged_programs
        )
        title_verticals = detect_verticals(
            title_text,
            event_programs,
            merged_cards,
            {"verticals": []},
        )
        event_verticals = title_verticals or merged_verticals
    else:
        event_programs = merged_programs
        event_verticals = merged_verticals
    evidence = [evidence_from_item(item) for item in items]
    evidence.sort(
        key=lambda row: (
            row.url != representative.url,
            row.source_type == "blog_comment",
            row.published_at or "",
            row.source,
        )
    )
    sources = merge_unique([item.source for item in items])
    fingerprint = event_fingerprint(items)
    return IntelEvent(
        title=representative.title,
        url=representative.url,
        source=" / ".join(sources[:4]),
        source_id=representative.source_id,
        source_type=representative.source_type,
        priority=representative.priority,
        program=event_programs,
        card_family=merged_cards,
        topic_type=representative.topic_type,
        published_at=representative.published_at,
        summary=representative.summary,
        why_it_matters=representative.why_it_matters,
        confidence_label=event_confidence(items),
        risk_label=representative.risk_label,
        score=max(item.score for item in items),
        vertical=event_verticals,
        ecosystem_signal_type=merge_unique(
            [value for item in taxonomy_items for value in item.ecosystem_signal_type]
        ),
        stakeholders=merge_unique([value for item in taxonomy_items for value in item.stakeholders]),
        consumer_impact=representative.consumer_impact,
        impact_horizon=representative.impact_horizon,
        action_label=representative.action_label,
        metric_snippets=merge_unique([value for item in items for value in item.metric_snippets]),
        future_event_dates=merge_unique([value for item in items for value in item.future_event_dates]),
        raw_tags=merge_unique([value for item in items for value in item.raw_tags]),
        event_id=hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:14],
        evidence=evidence,
    )


def cluster_items(items: list[IntelItem]) -> list[IntelEvent]:
    """Cluster corroborating rows without allowing loose transitive merges."""
    clusters: list[list[IntelItem]] = []
    ordered = sorted(
        items,
        key=lambda item: (
            item.source_type == "blog_comment",
            -(item.score or 0),
            item.published_at or "",
        ),
    )
    for item in ordered:
        target = None
        if item.source_type == "blog_comment":
            comment_url = canonical_event_url(item.url)
            comment_title = normalize_event_text(item.title)
            target = next(
                (
                    cluster
                    for cluster in clusters
                    if any(
                        (comment_url and comment_url == canonical_event_url(member.url))
                        or (
                            comment_title
                            and comment_title == normalize_event_text(member.title)
                        )
                        for member in cluster
                    )
                ),
                None,
            )
        if target is None:
            target = next(
                (
                    cluster
                    for cluster in clusters
                    if all(items_represent_same_event(item, member) for member in cluster)
                ),
                None,
            )
        if target is None:
            clusters.append([item])
        else:
            target.append(item)

    # Cross-language evidence can split otherwise identical clusters under the all-members rule.
    # Merge only when the two cluster representatives satisfy the same conservative matcher used
    # by the public duplicate gate.
    representative_merged: list[list[IntelItem]] = []
    for cluster in clusters:
        representative = representative_item(cluster)
        target = next(
            (
                existing
                for existing in representative_merged
                if items_represent_same_event(representative, representative_item(existing))
            ),
            None,
        )
        if target is None:
            representative_merged.append(cluster)
        else:
            target.extend(cluster)
    clusters = representative_merged

    # The all-members rule intentionally avoids transitive over-merges. Two clusters can
    # still have the exact same canonical URL/topic/program fingerprint (most commonly a
    # parent article and its comment feed); those are the same auditable event.
    consolidated: dict[str, list[IntelItem]] = {}
    for cluster in clusters:
        fingerprint = event_fingerprint(cluster)
        consolidated.setdefault(fingerprint, []).extend(cluster)
    return [event_from_items(cluster) for cluster in consolidated.values()]


def event_matches_config(event: IntelEvent, configured_values: list[str]) -> bool:
    detected = normalized_values(event.program + event.card_family)
    for configured in configured_values:
        normalized = normalize_event_text(configured)
        if any(
            normalized == value
            or (len(normalized) >= 5 and normalized in value)
            or (len(value) >= 5 and value in normalized)
            for value in detected
        ):
            return True
    return False


def event_title_matches_config(event: IntelEvent, configured_values: list[str]) -> bool:
    title = normalize_event_text(event.title)
    aliases = {
        "american express": ["american express", "amex", "membership rewards"],
        "chase": ["chase", "ultimate rewards", "sapphire"],
    }
    for value in configured_values:
        normalized = normalize_event_text(value)
        candidates = aliases.get(normalized, [normalized])
        if any(len(candidate) >= 4 and candidate in title for candidate in candidates):
            return True
    return False


def event_has_high_value(event: IntelEvent) -> bool:
    title = normalize_event_text(event.title)
    dollar_matches = []
    for match in re.finditer(r"\$\s?([\d,]+(?:\.\d+)?)", title):
        amount = float(match.group(1).replace(",", ""))
        context = title[max(0, match.start() - 18) : match.end() + 42]
        if re.search(r"\b(back|cashback|credit|benefit|bonus|saving|off)\b", context):
            dollar_matches.append(amount)
    if any(amount >= 100 for amount in dollar_matches):
        return True
    for match in re.finditer(r"\b([\d,]+(?:\.\d+)?)\s*k\s*(?:points|miles|offer|bonus)?\b", title):
        if float(match.group(1).replace(",", "")) >= 30:
            return True
    for match in re.finditer(r"\b([\d,]+)\s*(?:points|miles)\b", title):
        if int(match.group(1).replace(",", "")) >= 30000:
            return True
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*%", title):
        if float(match.group(1)) >= 20 and re.search(r"\b(bonus|back|cashback|off)\b", title):
            return True
    return False


def event_is_foreign_market_card_offer(event: IntelEvent) -> bool:
    if "credit_card" not in event.vertical or event.action_label == "只观察":
        return False
    text = normalize_event_text(f"{event.title} {event.summary}")
    markers = [
        "£",
        "uk amex",
        "uk american express",
        "united kingdom card",
        "british-issued",
        "bapp",
        "fee-free hsbc premier credit card",
    ]
    return any(marker in text for marker in markers) or event.source == "Head for Points"


def event_is_expired(event: IntelEvent, reference_date: dt.datetime | dt.date) -> bool:
    if re.search(r"(?:^|[\[(])expired(?:$|[\])])", event.title, re.I):
        return True
    reference = reference_date_or_today(reference_date)
    numeric = re.search(r"\bends?\s+(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?", event.title, re.I)
    if numeric:
        month, day, year = numeric.groups()
        candidate = normalize_future_date(int(year) if year else reference.year, int(month), int(day), reference)
        return bool(candidate and candidate < reference)
    month_names = "|".join(sorted(MONTH_LOOKUP, key=len, reverse=True))
    named = re.search(rf"\bends?\s+({month_names})\.?\s+(\d{{1,2}})(?:,\s*(20\d{{2}}))?", event.title, re.I)
    if named:
        month_name, day, year = named.groups()
        month = MONTH_LOOKUP[month_name.lower().rstrip(".")]
        candidate = normalize_future_date(int(year) if year else reference.year, month, int(day), reference)
        return bool(candidate and candidate < reference)
    return False


def rank_events(
    events: list[IntelEvent],
    profile: dict[str, Any],
    reference_date: dt.datetime | dt.date | None = None,
) -> list[IntelEvent]:
    ranking = profile.get("ranking", {})
    weights = ranking.get("weights", {})
    direct_programs = ranking.get("direct_programs", [])
    direct_issuers = ranking.get("direct_issuers", [])
    direct_cards = ranking.get("direct_cards", [])
    dated_events = [parse_datetime(event.published_at) for event in events if event.published_at]
    rank_reference = reference_date or max((value for value in dated_events if value), default=reference_datetime_or_now())
    for event in events:
        base_score = event.score_breakdown.get("base_item", event.score)
        direct_profile = int(event_matches_config(event, direct_programs)) * int(weights.get("direct_profile", 42))
        direct_card_match = event_matches_config(event, direct_issuers + direct_cards) or event_title_matches_config(
            event, direct_cards
        )
        direct_card = int(direct_card_match) * int(weights.get("direct_card", 34))
        urgent = bool(
            event.future_event_dates
            or event.impact_horizon in {"today", "next_60_days"}
            or event.action_label == "需报名"
        )
        urgency = int(urgent) * int(weights.get("urgency", 24))
        high_value = event_has_high_value(event)
        value = int(high_value) * int(weights.get("value", 16))
        severe_risk = bool(
            event.topic_type in RISK_TOPICS
            or event.risk_label in {"可能 clawback", "高风控风险"}
            or event.action_label == "高风险勿操作"
        )
        risk_weight = int(weights.get("risk", 22))
        risk = risk_weight if severe_risk else round(risk_weight * 0.25) if event.risk_label == "YMMV" else 0
        confidence_weight = int(weights.get("confidence", 16))
        confidence_factor = {
            "多源证实": 1.0,
            "多用户 DP": 0.8,
            "博客整理": 0.5,
            "单帖线索": 0.15,
        }.get(event.confidence_label, 0.25)
        confidence = round(confidence_weight * confidence_factor)
        novelty = min(len(event.evidence) - 1, 3) * max(1, int(weights.get("novelty", 8)) // 3)
        ecosystem = int(bool(event.ecosystem_signal_type)) * int(weights.get("ecosystem", 12))
        undated = -int(weights.get("undated_penalty", 55)) if not event.published_at else 0
        expired = event_is_expired(event, rank_reference)
        expired_penalty = -60 if expired else 0
        foreign_market = event_is_foreign_market_card_offer(event)
        foreign_market_penalty = -45 if foreign_market else 0
        event.score_breakdown = {
            "base_item": int(base_score),
            "direct_profile": direct_profile,
            "direct_card": direct_card,
            "urgency": urgency,
            "value": value,
            "risk": risk,
            "confidence": confidence,
            "novelty": novelty,
            "ecosystem": ecosystem,
            "undated_penalty": undated,
            "expired_penalty": expired_penalty,
            "foreign_market_penalty": foreign_market_penalty,
        }
        event.score = sum(event.score_breakdown.values())
        direct = direct_profile + direct_card > 0
        explicit_direct = event_title_matches_config(event, direct_programs + direct_issuers + direct_cards)
        direct_critical = explicit_direct or (severe_risk and direct) or (direct and event.source_type == "forum")
        material_topic = event.topic_type not in {"datapoint", "trip_report"}
        material_policy = event.topic_type in {"policy_change", "devaluation"}
        major_ecosystem = bool(
            set(event.ecosystem_signal_type)
            & {
                "cost_reimbursement_conflict",
                "devaluation_or_inflation",
                "partner_contract_shift",
                "regulatory_or_legal_pressure",
                "consumer_backlash",
            }
        )
        if not event.published_at:
            event.priority_tier = "P4 线索库"
        elif expired:
            event.priority_tier = "P3 补充信息"
            event.action_label = "只观察"
        elif foreign_market:
            event.priority_tier = "P2 值得阅读" if event.score >= 110 else "P3 补充信息"
            event.action_label = "只观察"
            event.consumer_impact = "长期观察"
        elif (
            (direct_critical and urgent and event.action_label == "需报名")
            or (direct_critical and event.score >= 160 and severe_risk)
            or (explicit_direct and event.score >= 180 and high_value)
            or (explicit_direct and event.score >= 190 and material_policy)
            or (event.confidence_label == "多源证实" and event.score >= 220 and major_ecosystem)
        ):
            event.priority_tier = "P0 必须关注"
        elif event.score >= 190 or (direct_critical and material_topic and event.score >= 130) or (major_ecosystem and event.score >= 135):
            event.priority_tier = "P1 高价值"
        elif event.score >= 120:
            event.priority_tier = "P2 值得阅读"
        elif event.score >= 85:
            event.priority_tier = "P3 补充信息"
        else:
            event.priority_tier = "P4 线索库"
    tier_order = {
        "P0 必须关注": 0,
        "P1 高价值": 1,
        "P2 值得阅读": 2,
        "P3 补充信息": 3,
        "P4 线索库": 4,
    }
    return sorted(
        events,
        key=lambda event: (
            tier_order.get(event.priority_tier, 9),
            -event.score,
            event.published_at or "",
            event.title.casefold(),
        ),
    )


def select_diverse_events(
    events: list[IntelEvent],
    limit: int,
    quotas: dict[str, int] | None = None,
) -> list[IntelEvent]:
    if limit <= 0:
        return []
    quotas = quotas or {"ecosystem": 1, "rental_car": 1}
    selected: list[IntelEvent] = []

    def add_matches(predicate: Any, count: int) -> None:
        for event in events:
            if len(selected) >= limit or count <= 0:
                return
            if event not in selected and predicate(event):
                selected.append(event)
                count -= 1

    predicates = {
        "c_end": lambda event: is_c_end_play(event),
        "risk": lambda event: is_risk_item(event),
        "ecosystem": lambda event: bool(event.ecosystem_signal_type),
        "hotel": lambda event: "hotel" in event.vertical,
        "airline": lambda event: "airline" in event.vertical,
        "credit_card": lambda event: "credit_card" in event.vertical,
        "rental_car": lambda event: "rental_car" in event.vertical,
    }
    for lane, quota in quotas.items():
        predicate = predicates.get(lane)
        if predicate:
            add_matches(predicate, min(int(quota), limit))
    for event in events:
        if len(selected) >= limit:
            break
        if event not in selected:
            selected.append(event)
    order = {event.event_id: index for index, event in enumerate(events)}
    return sorted(selected, key=lambda event: order.get(event.event_id, len(events)))


def reference_datetime_or_now(reference_date: dt.datetime | dt.date | None = None) -> dt.datetime:
    if isinstance(reference_date, dt.datetime):
        value = reference_date
    elif isinstance(reference_date, dt.date):
        value = dt.datetime.combine(reference_date, dt.time.max, tzinfo=dt.UTC)
    else:
        value = dt.datetime.now(dt.UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def within_window(
    item: IntelItem,
    hours: int,
    reference_date: dt.datetime | dt.date | None = None,
    allow_undated: bool = True,
) -> bool:
    if not item.published_at:
        return allow_undated
    try:
        published = dt.datetime.fromisoformat(item.published_at)
        if published.tzinfo is None:
            published = published.replace(tzinfo=dt.UTC)
        age = reference_datetime_or_now(reference_date) - published.astimezone(dt.UTC)
        return dt.timedelta(0) <= age <= dt.timedelta(hours=hours)
    except (TypeError, ValueError):
        return allow_undated


def title_has_explicit_loyalty_context(item: IntelItem) -> bool:
    """Require title-level evidence before accepting broad ecosystem query matches."""
    if item.program or item.card_family or set(item.vertical) & {"hotel", "airline", "rental_car"}:
        return True
    title = normalize_event_text(item.title)
    anchors = [
        "loyalty program",
        "rewards program",
        "reward points",
        "bonus points",
        "airline miles",
        "bonus miles",
        "frequent flyer",
        "award ticket",
        "award travel",
        "points redemption",
        "redeem points",
        "elite status",
        "status match",
        "status challenge",
        "transfer bonus",
        "transfer partner",
        "credit card rewards",
        "co-brand card",
        "co-branded card",
        "忠诚计划",
        "奖励计划",
        "积分兑换",
        "奖励积分",
        "航空里程",
        "常旅客",
        "会籍匹配",
        "转点奖励",
        "联名卡",
    ]
    return any(keyword_matches(title, anchor) for anchor in anchors)


def loyalty_relevance_reason(item: IntelItem) -> str | None:
    title_lower = normalize_event_text(item.title)
    if any(marker in title_lower for marker in LOW_SIGNAL_ROUNDUP_MARKERS):
        return "low_signal_roundup"
    if any(re.search(pattern, title_lower) for pattern in LOW_SIGNAL_EVERGREEN_PATTERNS) and not any(
        keyword_matches(title_lower, term) for term in FRESH_EVENT_TITLE_TERMS
    ):
        return "low_signal_roundup"
    if any(re.search(pattern, title_lower) for pattern in GENERIC_TRAVEL_NEWS_TITLE_PATTERNS) and not any(
        keyword_matches(title_lower, term) for term in GENERIC_TRAVEL_NEWS_EXEMPT_TERMS
    ):
        return "generic_travel_news"
    is_forum_source = item.source_type == "forum" or item.source_id.startswith(("ft-", "flyert-"))
    is_question = any(re.search(pattern, title_lower) for pattern in FORUM_QUESTION_PATTERNS)
    if is_forum_source and is_question and not any(
        keyword_matches(title_lower, term) for term in FORUM_CHANGE_EVIDENCE_TERMS
    ):
        return "low_signal_forum"
    if is_forum_source and set(item.vertical) & {"hotel", "airline"} and not any(
        keyword_matches(title_lower, term) for term in FORUM_SIGNAL_TITLE_TERMS
    ):
        return "low_signal_forum"
    verticals = set(item.vertical)
    if verticals & {"hotel", "airline", "rental_car"}:
        return None
    if item.ecosystem_signal_type:
        if title_has_explicit_loyalty_context(item):
            return None
        return "non_loyalty_ecosystem"
    lead_text = normalize_event_text(f"{item.title} {(item.summary or '')[:320]}")
    travel_card_families = {
        "sapphire",
        "ink",
        "united",
        "hyatt",
        "ihg",
        "marriott",
        "southwest",
        "lounge",
        "platinum",
        "gold",
        "green",
        "blue business",
        "hilton",
        "delta",
    }
    issuers = normalized_values(item.program + item.card_family)
    if "credit_card" in verticals:
        has_travel_card_context = any(
            keyword_matches(lead_text, term) for term in CREDIT_CARD_TRAVEL_TERMS
        )
        if normalized_values(item.card_family) & travel_card_families:
            return None
        if item.topic_type in RISK_TOPICS and issuers & {"chase", "american express"}:
            return None
        if has_travel_card_context:
            return None
        return "non_travel_finance"
    has_loyalty_context = any(keyword_matches(lead_text, term) for term in LOYALTY_TRAVEL_TERMS)
    if has_loyalty_context:
        return None
    if not item.program and not item.card_family:
        return "non_loyalty"
    pure_issuers = {
        "chase",
        "american express",
        "citi",
        "capital one",
        "bilt",
        "wells fargo",
        "bank of america",
        "barclays",
        "hsbc",
        "us bank",
    }
    if issuers and issuers <= pure_issuers:
        return "non_travel_finance"
    return None


def qualification_reason(
    item: IntelItem,
    strict_dates: bool = True,
    hours: int = 336,
    reference_date: dt.datetime | dt.date | None = None,
) -> str | None:
    text_lower = f"{item.title} {item.summary}".lower()
    if any(keyword_matches(text_lower, keyword) for keyword in NOISE_KEYWORDS):
        return "noise"
    if item.source_id.startswith("flyert-") and any(
        phrase.lower() in text_lower for phrase in KNOWN_CROSS_BOARD_AD_PHRASES
    ):
        return "noise"
    relevance_reason = loyalty_relevance_reason(item)
    if relevance_reason:
        return relevance_reason
    if strict_dates and not within_window(
        item,
        hours,
        reference_date=reference_date,
        allow_undated=False,
    ):
        return "date"
    return None


def focus_match(item: IntelItem, focus: str) -> bool:
    if focus == "all":
        return True
    programs = {p.lower() for p in item.program}
    cards = {c.lower() for c in item.card_family}
    verticals = set(item.vertical)
    if focus == "credit-card":
        return bool("credit_card" in verticals or programs & {"chase", "american express", "citi", "capital one", "bilt"} or cards)
    if focus == "air-china":
        return bool(programs & {"air china", "star alliance"})
    if focus == "hotel":
        return bool(
            "hotel" in verticals
            or programs
            & {
                "marriott",
                "hyatt",
                "hilton",
                "ihg",
                "marriott bonvoy",
                "world of hyatt",
                "hilton honors",
                "ihg one rewards",
                "accor",
                "wyndham",
                "choice",
            }
        )
    if focus == "bug":
        return item.topic_type in RISK_TOPICS or item.risk_label != "正常权益" or "operational_reliability" in item.ecosystem_signal_type
    return True


def collect_source(
    source_cfg: dict[str, Any],
    profile_keywords: dict[str, list[str]],
    card_keywords: dict[str, list[str]],
    args: argparse.Namespace,
) -> tuple[list[IntelItem], SourceHealth]:
    source_id = source_cfg["id"]
    source_name = source_cfg.get("name", source_id)
    method = source_cfg.get("fetch_method")
    url = source_cfg.get("url", "")

    if not source_cfg.get("enabled", True):
        return [], SourceHealth(source_id, source_name, "skipped", 0, "disabled in sources.yaml", url)
    if source_cfg.get("priority") == "P2" and not args.include_p2:
        return [], SourceHealth(source_id, source_name, "skipped", 0, "P2 source skipped by default; rerun with --include-p2", url)
    if method == "browser_only":
        return [], SourceHealth(source_id, source_name, "skipped", 0, source_cfg.get("note", "browser-only source"), url)

    limit = min(args.per_source_limit or source_cfg.get("default_limit", 15), source_cfg.get("default_limit", 15))
    try:
        body = http_get(url, encoding=source_cfg.get("encoding"))
        if method == "rss":
            rows = parse_rss_feed(body, source_cfg, limit)
        elif method == "flyert_forum":
            rows = parse_flyert_forum(body, source_cfg, limit)
            if args.fetch_details:
                detailed_rows = []
                for row in rows:
                    try:
                        detail = fetch_flyert_detail(row["url"], encoding=source_cfg.get("encoding", "gbk"))
                        if detail:
                            row["summary"] = detail
                    except FetchError:
                        pass
                    detailed_rows.append(row)
                    time.sleep(args.detail_delay)
                rows = detailed_rows
        elif method == "html_keyword":
            rows = parse_generic_html_keyword(body, source_cfg, limit)
        else:
            return [], SourceHealth(source_id, source_name, "failed", 0, f"unsupported fetch_method={method}", url)
    except Exception as exc:  # noqa: BLE001
        return [], SourceHealth(source_id, source_name, "failed", 0, str(exc), url)

    rows = filter_rows_by_source_keywords(rows, source_cfg)
    items = [
        classify_row(row, source_cfg, profile_keywords, card_keywords, reference_date=getattr(args, "reference_date", None))
        for row in rows
    ]

    if source_cfg.get("include_comments"):
        comment_items = collect_comment_items(rows, source_cfg, profile_keywords, card_keywords, args)
        items.extend(comment_items)

    dated = sum(1 for item in items if parse_datetime(item.published_at) is not None)
    return items, SourceHealth(
        source_id,
        source_name,
        "ok",
        len(items),
        "parsed",
        url,
        fetched=len(items),
        dated=dated,
    )


def collect_comment_items(
    rows: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    profile_keywords: dict[str, list[str]],
    card_keywords: dict[str, list[str]],
    args: argparse.Namespace,
) -> list[IntelItem]:
    items: list[IntelItem] = []
    max_threads = source_cfg.get("max_comment_threads", 2)
    for row in rows[:max_threads]:
        comment_url = row.get("comment_rss")
        if not comment_url:
            continue
        try:
            xml_text = http_get(comment_url)
            comment_rows = parse_rss_feed(xml_text, {**source_cfg, "source_type": "blog_comment"}, min(8, args.per_source_limit or 8))
        except Exception:
            continue
        for comment in comment_rows:
            comment["title"] = f"评论 DP: {row['title']}"
            comment["source_type"] = "blog_comment"
            items.append(
                classify_row(
                    comment,
                    source_cfg,
                    profile_keywords,
                    card_keywords,
                    reference_date=getattr(args, "reference_date", None),
                )
            )
        time.sleep(args.detail_delay)
    return items


def collect_all(args: argparse.Namespace) -> tuple[list[IntelEvent], list[SourceHealth]]:
    profile_cfg = load_yaml(Path(args.profile))
    cards_cfg = load_yaml(Path(args.cards))
    sources_cfg = load_yaml(Path(args.sources))
    profile_keywords = flatten_profile_keywords(profile_cfg)
    card_keywords = flatten_card_keywords(cards_cfg)

    all_sources = sources_cfg.get("sources", [])
    health: list[SourceHealth] = []
    if args.source_id:
        known_ids = {source.get("id") for source in all_sources}
        wanted = set(args.source_id)
        for missing_id in sorted(wanted - known_ids):
            health.append(SourceHealth(missing_id, missing_id, "failed", 0, "unknown source id; check sources.yaml", ""))
        all_sources = [source for source in all_sources if source.get("id") in wanted]
    if args.max_sources:
        all_sources = all_sources[: args.max_sources]

    items: list[IntelItem] = []
    quiet = bool(getattr(args, "quiet", False)) or os.environ.get("LOYALTY_RADAR_QUIET") == "1"
    collection_started = time.monotonic()
    if not quiet:
        print(f"[collect 0/{len(all_sources)}] starting public-source scan", file=sys.stderr, flush=True)
    for index, source_cfg in enumerate(all_sources, start=1):
        source_started = time.monotonic()
        source_items, source_health = collect_source(source_cfg, profile_keywords, card_keywords, args)
        health.append(source_health)
        items.extend(source_items)
        if not quiet:
            print(
                f"[collect {index}/{len(all_sources)}] {source_health.source}: "
                f"{source_health.status}, {source_health.fetched} rows, "
                f"{time.monotonic() - source_started:.1f}s",
                file=sys.stderr,
                flush=True,
            )
        if source_health.status == "ok":
            time.sleep(max(float(args.source_delay), float(source_cfg.get("rate_limit_seconds", 0))))

    reference_date = getattr(args, "reference_date", None)
    ranking_cfg = profile_cfg.get("ranking", {})
    allow_undated = bool(ranking_cfg.get("allow_undated_fallback", True))
    max_undated = max(0, int(ranking_cfg.get("max_undated", 8)))
    eligible: list[IntelItem] = []
    undated: list[IntelItem] = []
    for item in items:
        if qualification_reason(item, strict_dates=False) is not None or not focus_match(item, args.focus):
            continue
        if within_window(item, args.hours, reference_date=reference_date, allow_undated=False):
            eligible.append(item)
        elif allow_undated and not item.published_at:
            undated.append(item)

    undated.sort(key=lambda item: item.score, reverse=True)
    eligible.extend(undated[:max_undated])
    eligible_counts = Counter(item.source_id for item in eligible)
    for row in health:
        row.eligible = eligible_counts.get(row.source_id, 0)
        row.rejected = max(row.fetched - row.eligible, 0)

    events = rank_events(cluster_items(eligible), profile_cfg, reference_date=reference_date)
    quotas = ranking_cfg.get("diversity_quotas", {})
    selected = select_diverse_events(events, args.max_items, quotas=quotas)

    source_event_ids: dict[str, set[str]] = {}
    source_evidence_counts: Counter[str] = Counter()
    for event in events:
        for evidence in event.evidence:
            source_evidence_counts[evidence.source_id] += 1
            source_event_ids.setdefault(evidence.source_id, set()).add(event.event_id)
    selected_counts: Counter[str] = Counter()
    for event in selected:
        for source_id in {evidence.source_id for evidence in event.evidence}:
            selected_counts[source_id] += 1
    for row in health:
        row.duplicate = max(
            source_evidence_counts.get(row.source_id, 0) - len(source_event_ids.get(row.source_id, set())),
            0,
        )
        row.selected = selected_counts.get(row.source_id, 0)
        if row.status == "ok":
            row.detail = (
                f"parsed; fetched {row.fetched}, dated {row.dated}, eligible {row.eligible}, "
                f"rejected {row.rejected}, duplicate {row.duplicate}, selected {row.selected}"
            )
    if not quiet:
        print(
            f"[collect done] {len(items)} rows -> {len(events)} events -> {len(selected)} selected "
            f"in {time.monotonic() - collection_started:.1f}s",
            file=sys.stderr,
            flush=True,
        )
    return selected, health


def item_line(item: IntelItem | IntelEvent) -> str:
    tags = []
    if item.program:
        tags.append("项目: " + " / ".join(display_list(item.program, "program", 3)))
    if item.card_family:
        tags.append("卡族: " + " / ".join(display_list(item.card_family, "card_family", 3)))
    tags.append("行业: " + (" / ".join(display_list(item.vertical, "vertical", 3)) if item.vertical else "-"))
    tags.append(
        "生态信号: "
        + (" / ".join(display_list(item.ecosystem_signal_type, "ecosystem_signal", 3)) if item.ecosystem_signal_type else "-")
    )
    tags.append(f"类型: {display_label(item.topic_type, 'topic')}")
    tags.append(f"行动: {display_label(item.action_label, 'action')}")
    tags.append(f"影响: {display_label(item.consumer_impact, 'consumer_impact')}")
    if item.metric_snippets:
        tags.append("数字: " + " / ".join(item.metric_snippets[:4]))
    if item.future_event_dates:
        tags.append("未来: " + " / ".join(item.future_event_dates[:3]))
    tag_text = "；".join(tags)
    published = f" · {item.published_at[:10]}" if item.published_at else ""
    priority = f" · {item.priority_tier}" if isinstance(item, IntelEvent) else ""
    evidence_lines = ""
    if isinstance(item, IntelEvent):
        evidence_lines = "\n" + "\n".join(
            f"  - 证据: [{row.source} · {display_title(row)}]({row.url})"
            + (f" · {row.published_at[:10]}" if row.published_at else " · 时间未提供")
            for row in item.evidence
        )
    return (
        f"- **[{display_title(item)}]({item.url})** · {item.source}{published}{priority} · 评分 {item.score}\n"
        f"  - 摘要: {display_summary(item)}\n"
        f"  - 影响: {display_generated_text(item.why_it_matters)}\n"
        f"  - 标记: {display_label(item.confidence_label, 'confidence')} / "
        f"{display_label(item.risk_label, 'risk')} / {tag_text}"
        f"{evidence_lines}"
    )


def render_section(title: str, items: list[IntelItem | IntelEvent]) -> str:
    if not items:
        return f"## {title}\n\n- 暂无高相关条目。\n"
    return f"## {title}\n\n" + "\n".join(item_line(item) for item in items) + "\n"


def render_markdown(items: list[IntelItem | IntelEvent], health: list[SourceHealth], args: argparse.Namespace) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = section_items(items, mode=args.mode)

    lines = [
        "# 全局忠诚计划生态雷达 + C端玩法雷达",
        "",
        f"- 生成时间: {now}",
        f"- 模式: {display_label(args.mode, 'mode')}",
        f"- 关注范围: {display_label(args.focus, 'focus')}",
        f"- 时间窗: {args.hours} 小时",
        "- 说明: 仅汇总公开论坛、信息订阅与评论实测，不做官网确认；对文本中提到的未来 60 天节点单独进入后续观察。",
        f"- {translation_health_summary(getattr(args, 'translation_health', None))}",
        "",
        *(render_section(title, section_rows) for title, section_rows in sections.items()),
        "## 抓取健康检查",
        "",
        "| 来源 | 状态 | 抓取 | 有日期 | 合格 | 剔除 | 重复 | 入选 | 说明 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in health:
        detail = source_health_detail_zh(row).replace("|", "/")
        lines.append(
            f"| [{row.source}]({row.url}) | {display_label(row.status, 'status')} | {row.fetched} | {row.dated} | "
            f"{row.eligible} | {row.rejected} | {row.duplicate} | {row.selected} | {detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def timezone_or_utc(tz_name: str | None) -> dt.tzinfo:
    try:
        return ZoneInfo(tz_name or "Asia/Shanghai")
    except Exception:
        return dt.UTC


def now_in_timezone(tz_name: str | None) -> dt.datetime:
    return dt.datetime.now(timezone_or_utc(tz_name))


def date_range_label(generated_at: dt.datetime, hours: int) -> str:
    start = generated_at - dt.timedelta(hours=hours)
    return f"{start:%m%d}-{generated_at:%m%d}"


def timezone_label(tz_name: str | None) -> str:
    return {
        "Asia/Shanghai": "中国标准时间",
        "Asia/Singapore": "新加坡时间",
        "UTC": "协调世界时",
    }.get(tz_name or "", "当地时间")


def parse_item_datetime(item: IntelItem, tz_name: str | None) -> dt.datetime | None:
    if not item.published_at:
        return None
    try:
        parsed = dt.datetime.fromisoformat(item.published_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(timezone_or_utc(tz_name))
    except Exception:
        return None


def item_time_label(item: IntelItem, tz_name: str | None) -> str:
    parsed = parse_item_datetime(item, tz_name)
    if not parsed:
        return "列表页未提供时间"
    return parsed.strftime("%m-%d %H:%M")


def source_type_label(source_type: str) -> str:
    return {
        "forum": "论坛",
        "rss": "信息订阅",
        "blog": "博客",
        "blog_comment": "评论实测",
        "reddit_fallback": "浏览器辅助",
    }.get(source_type, source_type or "来源")


def display_generated_text(value: str) -> str:
    text = value or ""
    replacements: dict[str, str] = {}
    for category in ("card_family", "program", "vertical", "ecosystem_signal", "risk"):
        replacements.update(DISPLAY_LABELS.get(category, {}))
    for original in sorted(replacements, key=len, reverse=True):
        replacement = replacements[original]
        if original != replacement:
            text = text.replace(original, replacement)
    jargon = [
        (r"\bstatement credit\b", "账单报销"),
        (r"\bhotel credit\b", "酒店报销"),
        (r"\bcredit\b", "报销额度"),
        (r"\bclawback\b", "权益追回"),
        (r"\bDP\b", "实测"),
        (r"\bYMMV\b", "因人而异"),
    ]
    for pattern, replacement in jargon:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def source_health_detail_zh(row: SourceHealth) -> str:
    detail = (row.detail or "").casefold()
    if row.status == "ok":
        return (
            f"解析成功；抓取 {row.fetched} 条，有日期 {row.dated} 条，合格 {row.eligible} 条，"
            f"剔除 {row.rejected} 条，重复 {row.duplicate} 条，入选 {row.selected} 条"
        )
    if row.status == "disabled" or "disabled" in detail:
        return "已在来源配置中禁用"
    if row.status == "skipped":
        if "cloudflare" in detail:
            return "受访问保护限制，需浏览器辅助读取"
        if "403" in detail:
            return "脚本访问常返回 403，需浏览器辅助读取"
        return "脚本抓取受限，需浏览器辅助读取"
    status_match = re.search(r"http\s*(\d{3})", detail)
    if status_match:
        return f"抓取失败（HTTP {status_match.group(1)}）"
    if "unknown source id" in detail:
        return "来源配置中未找到该来源"
    return "抓取失败（网络或解析错误）"


def translation_health_summary(health: TranslationHealth | None) -> str:
    if health is None:
        return "中文化状态：未提供统计；英文正文不会回退显示"
    return (
        f"中文化状态：需处理 {health.requested} 段，缓存命中 {health.cache_hits} 段，"
        f"新翻译 {health.translated} 段，中文直用 {health.skipped_chinese} 段，"
        f"非文本摘要 {health.skipped_non_text} 段，失败 {health.failed} 段"
    )


def url_label(url: str, max_len: int = 64) -> str:
    if not url:
        return "无链接"
    parsed = urllib.parse.urlparse(url)
    label = parsed.netloc.replace("www.", "") + parsed.path
    if len(label) > max_len:
        label = label[: max_len - 1].rstrip("/") + "..."
    return label


def short_text(value: str, max_len: int) -> str:
    text = clean_text(value, max_len=max_len)
    return text


def item_meta_line(item: IntelItem, tz_name: str | None) -> str:
    tags = []
    if item.program:
        tags.append("项目 " + "/".join(display_list(item.program, "program", 3)))
    if item.card_family:
        tags.append("卡族 " + "/".join(display_list(item.card_family, "card_family", 3)))
    tags.append("行业 " + ("/".join(display_list(item.vertical, "vertical", 3)) if item.vertical else "-"))
    tags.append(
        "信号 "
        + ("/".join(display_list(item.ecosystem_signal_type, "ecosystem_signal", 2)) if item.ecosystem_signal_type else "-")
    )
    tags.append("类型 " + display_label(item.topic_type, "topic"))
    tags.append("行动 " + display_label(item.action_label, "action"))
    tags.append("影响 " + display_label(item.consumer_impact, "consumer_impact"))
    if item.metric_snippets:
        tags.append("数字 " + "/".join(item.metric_snippets[:3]))
    if item.future_event_dates:
        tags.append("未来 " + "/".join(item.future_event_dates[:2]))
    return (
        f"时间 {item_time_label(item, tz_name)} | 来源 {item.source} | "
        f"{source_type_label(item.source_type)} | {display_label(item.confidence_label, 'confidence')} / "
        f"{display_label(item.risk_label, 'risk')} | "
        + " · ".join(tags)
    )


def is_c_end_play(item: IntelItem) -> bool:
    if item.topic_type in C_END_TOPICS and item.action_label != "只观察":
        return True
    return item.action_label in {"需报名", "可直接用", "定向/YMMV"}


def is_risk_item(item: IntelItem) -> bool:
    return (
        item.topic_type in RISK_TOPICS
        or item.risk_label != "正常权益"
        or item.action_label == "高风险勿操作"
        or "operational_reliability" in item.ecosystem_signal_type
    )


def section_items(items: list[IntelItem], mode: str = "daily") -> dict[str, list[IntelItem]]:
    top_title = "今日必看" if mode == "daily" else "本周必看"
    top = items[: 5 if mode == "daily" else 8]
    c_end = [item for item in items if is_c_end_play(item)][:12]
    risky = [item for item in items if is_risk_item(item)][:10]
    ecosystem = [item for item in items if item.ecosystem_signal_type][:14]
    watchlist = [
        item
        for item in items
        if item.impact_horizon in {"watchlist", "next_60_days"}
        or item.consumer_impact in {"可能贬值", "权益履约风险", "长期观察"}
    ][:10]
    return {
        top_title: top,
        "C端玩法雷达": c_end,
        "系统异常 / 权益追回 / 风控": risky,
        "忠诚计划生态雷达": ecosystem,
        "后续观察": watchlist,
    }


def image_font(size: int, bold: bool = False) -> Any:
    if ImageFont is None:
        raise RuntimeError("Pillow is required for image output.")
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def unique_items_by_url(items: list[IntelItem]) -> list[IntelItem]:
    seen: set[str] = set()
    unique: list[IntelItem] = []
    for item in items:
        key = canonical_item_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def notebook_infographic_groups(items: list[IntelItem], mode: str = "daily") -> dict[str, list[IntelItem]]:
    top_title = "今日必看" if mode == "daily" else "本周必看"
    unique = unique_items_by_url(items)
    return {
        top_title: unique[:5],
        "未来节点时间线": sorted(
            [item for item in unique if item.future_event_dates],
            key=lambda item: item.future_event_dates[0],
        ),
        "C端行动板": [item for item in unique if is_c_end_play(item)],
        "风险与异常": [item for item in unique if is_risk_item(item)],
        "行业生态信号": [item for item in unique if item.ecosystem_signal_type],
        "完整情报索引": unique,
    }


def item_badges(item: IntelItem) -> list[str]:
    badges = [
        f"类型 {display_label(item.topic_type, 'topic')}",
        f"行动 {display_label(item.action_label, 'action')}",
        f"影响 {display_label(item.consumer_impact, 'consumer_impact')}",
        f"风险 {display_label(item.risk_label, 'risk')}",
    ]
    if item.vertical:
        badges.append("行业 " + " / ".join(display_list(item.vertical, "vertical")))
    if item.ecosystem_signal_type:
        badges.append("信号 " + " / ".join(display_list(item.ecosystem_signal_type, "ecosystem_signal")))
    if item.metric_snippets:
        badges.append("数字 " + " / ".join(item.metric_snippets[:5]))
    if item.future_event_dates:
        badges.append("未来 " + " / ".join(item.future_event_dates[:4]))
    return badges


def item_html_card(item: IntelItem, index: int, *, compact: bool = False) -> str:
    badges = "".join(f"<span>{html_escape(badge)}</span>" for badge in item_badges(item))
    programs = " / ".join(display_list(item.program, "program", 5)) if item.program else "未识别项目"
    cards = " / ".join(display_list(item.card_family, "card_family", 4)) if item.card_family else "无特定卡族"
    summary = display_summary(item)
    why = display_generated_text(item.why_it_matters)
    compact_class = " compact" if compact else ""
    summary_html = "" if compact else f"<p class='summary'>{html_escape(summary)}</p>"
    why_html = "" if compact else f"<p class='why'>{html_escape(why)}</p>"
    return f"""
      <article class="intel-card{compact_class}">
        <div class="card-number">{index}</div>
        <div class="card-body">
          <h3>{html_escape(display_title(item))}</h3>
          <div class="meta">{html_escape(item_time_label(item, None))} · {html_escape(item.source)} · {html_escape(display_label(item.confidence_label, 'confidence'))}</div>
          <div class="programs">项目：{html_escape(programs)} ｜ 卡族：{html_escape(cards)}</div>
          <div class="badges">{badges}</div>
          {summary_html}
          {why_html}
          <div class="link">{html_escape(item.url)}</div>
        </div>
      </article>
    """


def empty_html_card(label: str) -> str:
    return f"<div class='empty-card'>{html_escape(label)}</div>"


def coerce_events(items: list[IntelItem | IntelEvent]) -> list[IntelEvent]:
    events: list[IntelEvent] = []
    for item in items:
        if isinstance(item, IntelEvent):
            events.append(item)
            continue
        event = event_from_items([item])
        event.score = item.score
        event.confidence_label = item.confidence_label
        if item.score >= 140:
            event.priority_tier = "P0 必须关注"
        elif item.score >= 110:
            event.priority_tier = "P1 高价值"
        elif item.score >= 80:
            event.priority_tier = "P2 值得阅读"
        elif item.score >= 50:
            event.priority_tier = "P3 补充信息"
        events.append(event)
    return events


def priority_code(event: IntelEvent) -> str:
    return (event.priority_tier or "P4").split()[0]


def event_lane(event: IntelEvent) -> str:
    structural_signals = {
        "revenue_shift",
        "cost_reimbursement_conflict",
        "benefit_capacity_pressure",
        "devaluation_or_inflation",
        "qualification_gatekeeping",
        "partner_contract_shift",
        "regulatory_or_legal_pressure",
        "supply_demand_stress",
        "consumer_backlash",
    }
    if event.ecosystem_signal_type and (
        event.topic_type in {"industry_signal", "devaluation"}
        or event.action_label == "只观察"
        or (
            bool(set(event.ecosystem_signal_type) & structural_signals)
            and event.topic_type not in {"offer", "transfer_bonus", "statement_credit", "portal_stack", "status_match", "lounge"}
        )
    ):
        return "industry"
    if is_c_end_play(event) or is_risk_item(event):
        return "consumer"
    if event.ecosystem_signal_type:
        return "industry"
    return "watch"


def evidence_rows_html(event: IntelEvent) -> str:
    rows = []
    for evidence in event.evidence:
        published = evidence.published_at[:16].replace("T", " ") if evidence.published_at else "时间未提供"
        author = f" · {evidence.author}" if evidence.author else ""
        link = (
            f'<a class="source-link" href="{html_escape(evidence.url)}" target="_blank" rel="noreferrer">'
            f"{html_escape(evidence.source)} · {html_escape(display_title(evidence))}</a>"
            if evidence.url
            else f'<span class="source-link">{html_escape(evidence.source)} · {html_escape(display_title(evidence))}</span>'
        )
        summary = display_summary(evidence)
        rows.append(
            f"""<div class="evidence-row">
              {link}
              <div class="evidence-meta">{html_escape(published)} · {html_escape(source_type_label(evidence.source_type))}{html_escape(author)}</div>
              <p>{html_escape(summary)}</p>
            </div>"""
        )
    return "\n".join(rows)


def event_card_html(event: IntelEvent, index: int) -> str:
    priority = priority_code(event)
    lane = event_lane(event)
    programs = " / ".join(display_list(event.program, "program", 5)) or "跨项目"
    vertical = " / ".join(display_list(event.vertical, "vertical")) or "忠诚计划"
    signals = " / ".join(display_list(event.ecosystem_signal_type, "ecosystem_signal")) or "无结构性信号"
    metrics = "".join(f"<span>{html_escape(value)}</span>" for value in event.metric_snippets[:6])
    future = "".join(f"<time>{html_escape(value)}</time>" for value in event.future_event_dates)
    search_text = " ".join(
        [
            display_title(event),
            display_summary(event),
            display_generated_text(event.why_it_matters),
            *display_list(event.program, "program"),
            *display_list(event.card_family, "card_family"),
            *display_list(event.vertical, "vertical"),
            *display_list(event.ecosystem_signal_type, "ecosystem_signal"),
            display_label(event.topic_type, "topic"),
        ]
    ).casefold()
    return f"""<article class="event-card" id="event-{html_escape(event.event_id)}"
      data-search="{html_escape(search_text)}" data-vertical="{html_escape(' '.join(event.vertical))}"
      data-priority="{html_escape(priority)}" data-lane="{html_escape(lane)}"
      data-score="{event.score}" data-date="{html_escape(event.published_at or '')}">
      <header class="event-head">
        <div class="event-rank"><span class="priority {priority.lower()}">{html_escape(event.priority_tier)}</span><span>#{index:02d}</span></div>
        <div class="event-meta">{html_escape(item_time_label(event, None))} · {html_escape(event.source)} · {html_escape(display_label(event.confidence_label, 'confidence'))}</div>
        <h3>{html_escape(display_title(event))}</h3>
      </header>
      <div class="event-classification">
        <span>{html_escape("C端" if lane == "consumer" else "行业" if lane == "industry" else "观察")}</span>
        <span>{html_escape(vertical)}</span><span>{html_escape(display_label(event.topic_type, 'topic'))}</span>
        <span>{html_escape(display_label(event.action_label, 'action'))}</span><span>{html_escape(display_label(event.risk_label, 'risk'))}</span>
      </div>
      <p class="event-summary">{html_escape(display_summary(event))}</p>
      <p class="event-impact"><b>与你的关系</b>{html_escape(display_generated_text(event.why_it_matters))}</p>
      <div class="event-context"><b>项目</b> {html_escape(programs)} <span>·</span> <b>生态信号</b> {html_escape(signals)}</div>
      {f'<div class="metric-strip">{metrics}</div>' if metrics else ''}
      {f'<div class="future-strip"><b>未来 60 天</b>{future}</div>' if future else ''}
      <details class="evidence">
        <summary>证据 {len(event.evidence)} 条 · {len({row.source_id for row in event.evidence})} 个独立来源</summary>
        <div class="evidence-list">{evidence_rows_html(event)}</div>
      </details>
    </article>"""


def render_infographic_html(
    items: list[IntelItem | IntelEvent],
    health: list[SourceHealth],
    args: argparse.Namespace,
    generated_at: dt.datetime,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
) -> str:
    events = coerce_events(items)
    counts = Counter(row.status for row in health)
    future_events = [event for event in events if event.future_event_dates]
    ecosystem_events = [event for event in events if event.ecosystem_signal_type]
    p0_count = sum(priority_code(event) == "P0" for event in events)
    raw_count = sum(row.fetched for row in health)
    evidence_count = sum(len(event.evidence) for event in events)
    cards = "\n".join(event_card_html(event, index) for index, event in enumerate(events, 1))
    if not cards:
        cards = '<div class="empty-state">本期没有通过时间和质量门槛的事件。</div>'
    future_links = "\n".join(
        f'<a href="#event-{html_escape(event.event_id)}"><time>{html_escape(" / ".join(event.future_event_dates))}</time><span>{html_escape(display_title(event))}</span></a>'
        for event in sorted(future_events, key=lambda row: row.future_event_dates[0])
    ) or "<p class='empty-note'>过去两周信息中未识别未来 60 天明确节点。</p>"
    health_rows = "\n".join(
        f"""<tr class="status-{html_escape(row.status)}">
          <td><a href="{html_escape(row.url)}" target="_blank" rel="noreferrer">{html_escape(row.source)}</a></td>
          <td>{html_escape(display_label(row.status, 'status'))}</td><td>{row.fetched}</td><td>{row.dated}</td>
          <td>{row.eligible}</td><td>{row.rejected}</td><td>{row.duplicate}</td><td>{row.selected}</td>
          <td>{html_escape(source_health_detail_zh(row))}</td>
        </tr>"""
        for row in health
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>忠诚计划情报雷达 · {html_escape(date_range_label(generated_at, args.hours))}</title>
  <style>
    :root {{
      --paper: #f3f2ee; --surface: #fff; --ink: #1d252c; --muted: #68737d;
      --line: #d8dad8; --blue: #2458a6; --green: #167357; --amber: #9a5a12;
      --red: #a83232; --violet: #6550a5; --soft-blue: #eaf1fb; --soft-green: #e9f4ef;
      --soft-amber: #fbf1df; --soft-red: #faeaea; --soft-violet: #efecf8;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.55; letter-spacing: 0; }}
    a {{ color: var(--blue); }}
    .report-header {{ background: #17232c; color: #fff; border-bottom: 5px solid #d7b96b; }}
    .header-inner, .page {{ width: min(1480px, calc(100% - 48px)); margin: 0 auto; }}
    .header-inner {{ padding: 48px 0 38px; display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(420px, .8fr); gap: 48px; align-items: end; }}
    .eyebrow {{ margin: 0 0 10px; color: #d7b96b; font-size: 13px; font-weight: 800; text-transform: uppercase; }}
    h1 {{ margin: 0; font-size: 48px; line-height: 1.08; letter-spacing: 0; }}
    .deck {{ margin: 16px 0 0; color: #cad1d5; font-size: 18px; }}
    .headline-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid #4a555d; }}
    .headline-stats div {{ padding: 17px 18px; border-right: 1px solid #4a555d; }}
    .headline-stats div:last-child {{ border-right: 0; }}
    .headline-stats b {{ display: block; font-size: 29px; line-height: 1; color: #fff; }}
    .headline-stats span {{ display: block; margin-top: 8px; color: #adb8bf; font-size: 12px; }}
    .report-nav {{ position: sticky; top: 0; z-index: 20; background: rgba(255,255,255,.98); border-bottom: 1px solid var(--line); }}
    .nav-inner {{ width: min(1480px, calc(100% - 48px)); margin: 0 auto; padding: 12px 0; display: grid; grid-template-columns: minmax(240px, 1.5fr) repeat(4, minmax(130px, .55fr)); gap: 10px; align-items: end; }}
    .control label {{ display: block; margin-bottom: 4px; color: var(--muted); font-size: 11px; font-weight: 750; }}
    input, select {{ width: 100%; height: 40px; border: 1px solid #bfc4c5; border-radius: 4px; background: #fff; color: var(--ink); padding: 0 11px; font: inherit; font-size: 14px; }}
    .page {{ padding: 32px 0 72px; }}
    .brief-strip {{ display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid var(--line); background: var(--surface); }}
    .brief-stat {{ padding: 18px 20px; border-right: 1px solid var(--line); }}
    .brief-stat:last-child {{ border-right: 0; }}
    .brief-stat b {{ display: block; font-size: 24px; line-height: 1; }}
    .brief-stat span {{ display: block; margin-top: 7px; color: var(--muted); font-size: 12px; }}
    .report-section {{ margin-top: 38px; border-top: 2px solid var(--ink); padding-top: 16px; }}
    .section-heading {{ display: flex; justify-content: space-between; gap: 24px; align-items: baseline; margin-bottom: 16px; }}
    h2 {{ margin: 0; font-size: 25px; letter-spacing: 0; }}
    .section-meta {{ color: var(--muted); font-size: 13px; }}
    .future-list {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--line); background: #fff; }}
    .future-list a {{ display: grid; grid-template-columns: 118px minmax(0, 1fr); gap: 14px; padding: 14px 16px; border-bottom: 1px solid var(--line); text-decoration: none; color: var(--ink); }}
    .future-list a:nth-child(odd) {{ border-right: 1px solid var(--line); }}
    .future-list time {{ color: var(--amber); font-weight: 800; font-size: 13px; }}
    .events-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: start; }}
    .event-card {{ background: var(--surface); border: 1px solid var(--line); border-top: 5px solid var(--blue); border-radius: 6px; padding: 22px; box-shadow: 0 5px 16px rgba(29,37,44,.045); }}
    .event-card[data-lane="industry"] {{ border-top-color: var(--violet); }}
    .event-card[data-priority="P0"] {{ border-color: var(--red); border-top-width: 6px; }}
    .event-head {{ border-bottom: 1px solid var(--line); padding-bottom: 16px; }}
    .event-rank {{ display: flex; justify-content: space-between; align-items: center; color: var(--muted); font-size: 12px; }}
    .priority {{ display: inline-flex; padding: 4px 8px; border-radius: 3px; font-weight: 850; }}
    .priority.p0 {{ color: var(--red); background: var(--soft-red); }} .priority.p1 {{ color: var(--amber); background: var(--soft-amber); }}
    .priority.p2 {{ color: var(--blue); background: var(--soft-blue); }} .priority.p3, .priority.p4 {{ color: var(--muted); background: #eef0ef; }}
    .event-meta {{ margin-top: 11px; color: var(--muted); font-size: 12px; }}
    h3 {{ margin: 8px 0 0; font-size: 22px; line-height: 1.33; letter-spacing: 0; overflow-wrap: anywhere; }}
    .event-classification, .metric-strip, .future-strip {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 13px; }}
    .event-classification span, .metric-strip span, .future-strip time {{ padding: 4px 8px; border-radius: 3px; background: var(--soft-blue); color: var(--blue); font-size: 11px; font-weight: 750; }}
    .event-card[data-lane="industry"] .event-classification span {{ background: var(--soft-violet); color: var(--violet); }}
    .event-summary {{ margin: 15px 0 0; font-size: 15px; }}
    .event-impact {{ margin: 14px 0 0; padding: 12px 14px; border-left: 4px solid var(--green); background: var(--soft-green); font-size: 14px; }}
    .event-impact b {{ margin-right: 10px; color: var(--green); }}
    .event-context {{ margin-top: 13px; color: var(--muted); font-size: 12px; }}
    .event-context span {{ margin: 0 6px; }}
    .metric-strip span {{ background: var(--soft-amber); color: var(--amber); }}
    .future-strip {{ align-items: center; font-size: 12px; }} .future-strip b {{ margin-right: 4px; }}
    .future-strip time {{ background: var(--soft-amber); color: var(--amber); }}
    details.evidence {{ margin-top: 16px; border-top: 1px solid var(--line); padding-top: 12px; }}
    details.evidence summary {{ cursor: pointer; color: var(--blue); font-size: 13px; font-weight: 750; }}
    .evidence-list {{ margin-top: 12px; }}
    .evidence-row {{ padding: 12px 0; border-top: 1px dotted #c9cecd; }}
    .source-link {{ font-size: 13px; font-weight: 750; overflow-wrap: anywhere; }}
    .evidence-meta {{ margin-top: 4px; color: var(--muted); font-size: 11px; }}
    .evidence-row p {{ margin: 6px 0 0; color: #424c54; font-size: 12px; }}
    .empty-state, .empty-note {{ padding: 24px; border: 1px dashed #bfc4c5; color: var(--muted); background: #fafafa; }}
    .translation-note {{ margin: 0 0 12px; padding: 10px 12px; border-left: 4px solid var(--green); background: var(--soft-green); color: #405049; font-size: 12px; }}
    .health-wrap {{ width: 100%; overflow-x: auto; border: 1px solid var(--line); background: #fff; }}
    table {{ width: 100%; min-width: 1120px; border-collapse: collapse; font-size: 12px; }}
    th, td {{ padding: 10px 11px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); background: #f7f8f7; }}
    .status-failed td:nth-child(2) {{ color: var(--red); font-weight: 800; }} .status-skipped td:nth-child(2) {{ color: var(--amber); font-weight: 800; }}
    .result-line {{ color: var(--muted); font-size: 13px; }}
    .report-footer {{ margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }}
    [hidden] {{ display: none !important; }}
    @media (max-width: 980px) {{
      .header-inner {{ grid-template-columns: 1fr; gap: 28px; }} .headline-stats {{ max-width: 620px; }}
      .nav-inner {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .control:first-child {{ grid-column: 1 / -1; }}
      .brief-strip {{ grid-template-columns: repeat(2, 1fr); }} .brief-stat {{ border-bottom: 1px solid var(--line); }}
      .events-grid, .future-list {{ grid-template-columns: 1fr; }} .future-list a:nth-child(odd) {{ border-right: 0; }}
    }}
    @media (max-width: 620px) {{
      .header-inner, .page, .nav-inner {{ width: min(100% - 28px, 1480px); }} h1 {{ font-size: 35px; }}
      .headline-stats {{ grid-template-columns: 1fr; }} .headline-stats div {{ border-right: 0; border-bottom: 1px solid #4a555d; }}
      .nav-inner {{ grid-template-columns: 1fr; max-height: 54vh; overflow-y: auto; }} .control:first-child {{ grid-column: auto; }}
      .brief-strip {{ grid-template-columns: 1fr; }} .section-heading {{ display: block; }} .section-meta {{ margin-top: 6px; }}
      .event-card {{ padding: 17px; }} h3 {{ font-size: 19px; }} .future-list a {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
  <header class="report-header">
    <div class="header-inner">
      <div><p class="eyebrow">忠诚计划情报 · 过去两周信号窗口</p><h1>常旅客与忠诚计划情报雷达</h1>
        <p class="deck">{html_escape(date_range_label(generated_at, args.hours))} · 未来 60 天事件观察 · {html_escape(generated_at.strftime('%Y-%m-%d %H:%M'))} {html_escape(timezone_label(args.timezone))}</p></div>
      <div class="headline-stats"><div><b>{p0_count}</b><span>P0 必须关注</span></div><div><b>{len(events)}</b><span>合格事件</span></div><div><b>{len(ecosystem_events)}</b><span>生态信号</span></div></div>
    </div>
  </header>
  <nav class="report-nav" aria-label="情报筛选">
    <div class="nav-inner">
      <div class="control"><label for="intel-search">搜索</label><input id="intel-search" type="search" placeholder="项目、卡族、事件、来源"></div>
      <div class="control"><label for="lane-filter">信息层</label><select id="lane-filter"><option value="all">全部</option><option value="consumer">C端玩法与风险</option><option value="industry">行业生态</option><option value="watch">观察线索</option></select></div>
      <div class="control"><label for="vertical-filter">行业</label><select id="vertical-filter"><option value="all">全部</option><option value="hotel">酒店</option><option value="airline">航司</option><option value="credit_card">信用卡</option><option value="rental_car">租车</option></select></div>
      <div class="control"><label for="priority-filter">优先级</label><select id="priority-filter"><option value="all">全部</option><option value="P0">P0</option><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3/P4</option></select></div>
      <div class="control"><label for="sort-control">排序</label><select id="sort-control"><option value="priority">优先级</option><option value="newest">最新发布</option><option value="evidence">证据强度</option></select></div>
    </div>
  </nav>
  <main class="page">
    <section class="brief-strip" aria-label="本期概览">
      <div class="brief-stat"><b>{raw_count}</b><span>抓取条目</span></div><div class="brief-stat"><b>{evidence_count}</b><span>入选证据</span></div>
      <div class="brief-stat"><b>{len(future_events)}</b><span>未来节点</span></div><div class="brief-stat"><b>{counts.get('ok', 0)}</b><span>成功来源</span></div>
      <div class="brief-stat"><b>{counts.get('failed', 0) + counts.get('skipped', 0)}</b><span>失败或受限来源</span></div>
    </section>
    <section class="report-section" id="future"><div class="section-heading"><h2>未来节点时间线 · 60 天</h2><span class="section-meta">仅来自过去两周公开内容</span></div><div class="future-list">{future_links}</div></section>
    <section class="report-section" id="events"><div class="section-heading"><h2>C端玩法雷达 + 忠诚计划生态雷达</h2><span id="result-count" class="result-line" aria-live="polite">显示 {len(events)} / {len(events)} 个事件</span></div><div id="events-grid" class="events-grid">{cards}</div></section>
    <section class="report-section" id="health"><div class="section-heading"><h2>抓取健康检查</h2><span class="section-meta">抓取 → 日期 → 合格 → 剔除 → 去重 → 入选</span></div>
      <p class="translation-note">{html_escape(translation_health_summary(getattr(args, 'translation_health', None)))}</p>
      <div class="health-wrap"><table><thead><tr><th>来源</th><th>状态</th><th>抓取</th><th>有日期</th><th>合格</th><th>剔除</th><th>重复</th><th>入选</th><th>说明</th></tr></thead><tbody>{health_rows}</tbody></table></div>
    </section>
    <footer class="report-footer">摘要文件与审计数据已同步生成 · 仅汇总公开论坛、信息订阅与评论实测，不做官网确认。</footer>
  </main>
  <script>
    const grid = document.getElementById('events-grid');
    const cards = [...grid.querySelectorAll('.event-card')];
    const controls = ['intel-search', 'lane-filter', 'vertical-filter', 'priority-filter', 'sort-control'].map(id => document.getElementById(id));
    const priorityOrder = {{P0: 0, P1: 1, P2: 2, P3: 3, P4: 4}};
    function refresh() {{
      const query = document.getElementById('intel-search').value.trim().toLocaleLowerCase();
      const lane = document.getElementById('lane-filter').value;
      const vertical = document.getElementById('vertical-filter').value;
      const priority = document.getElementById('priority-filter').value;
      const sort = document.getElementById('sort-control').value;
      let visible = 0;
      cards.forEach(card => {{
        const priorityMatch = priority === 'all' || card.dataset.priority === priority || (priority === 'P3' && ['P3','P4'].includes(card.dataset.priority));
        const match = (!query || card.dataset.search.includes(query)) && (lane === 'all' || card.dataset.lane === lane) && (vertical === 'all' || card.dataset.vertical.split(' ').includes(vertical)) && priorityMatch;
        card.hidden = !match; if (match) visible += 1;
      }});
      cards.sort((a, b) => {{
        if (sort === 'newest') return (b.dataset.date || '').localeCompare(a.dataset.date || '');
        if (sort === 'evidence') return Number(b.querySelector('.evidence summary').textContent.match(/\\d+/)?.[0] || 0) - Number(a.querySelector('.evidence summary').textContent.match(/\\d+/)?.[0] || 0);
        return (priorityOrder[a.dataset.priority] - priorityOrder[b.dataset.priority]) || (Number(b.dataset.score) - Number(a.dataset.score));
      }}).forEach(card => grid.appendChild(card));
      document.getElementById('result-count').textContent = `显示 ${{visible}} / ${{cards.length}} 个事件`;
    }}
    controls.forEach(control => control.addEventListener(control.type === 'search' ? 'input' : 'change', refresh));
  </script>
</body>
</html>"""


def render_overview_html(
    items: list[IntelItem | IntelEvent],
    health: list[SourceHealth],
    args: argparse.Namespace,
    generated_at: dt.datetime,
) -> str:
    all_events = coerce_events(items)
    consumer = [event for event in all_events if event_lane(event) == "consumer"][:6]
    industry = [event for event in all_events if event_lane(event) != "consumer"][:6]
    events = consumer + industry

    def overview_cards(rows: list[IntelEvent], offset: int) -> str:
        parts = []
        for index, event in enumerate(rows, offset):
            priority = priority_code(event)
            metric = " · ".join(event.metric_snippets[:2])
            future = " / ".join(event.future_event_dates[:2])
            context = " · ".join(
                value
                for value in [
                    display_label(event.action_label, "action"),
                    display_label(event.risk_label, "risk"),
                    metric,
                    future,
                ]
                if value
            )
            parts.append(
                f"""<article class="overview-card" data-priority="{html_escape(priority)}">
                  <div class="overview-meta"><span>{html_escape(event.priority_tier)}</span><b>#{index:02d}</b></div>
                  <h3>{html_escape(display_title(event))}</h3>
                  <p>{html_escape(short_text(display_summary(event), 220))}</p>
                  <div class="overview-impact">{html_escape(display_generated_text(event.why_it_matters))}</div>
                  <div class="overview-source">{html_escape(item_time_label(event, None))} · {html_escape(event.source)} · 证据 {len(event.evidence)}</div>
                  <div class="overview-context">{html_escape(context)}</div>
                </article>"""
            )
        return "\n".join(parts) or '<div class="overview-empty">本期暂无对应事件</div>'

    counts = Counter(row.status for row in health)
    p0_count = sum(priority_code(event) == "P0" for event in all_events)
    raw_count = sum(row.fetched for row in health)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=2400, initial-scale=1">
<title>忠诚计划情报雷达概览</title><style>
  * {{ box-sizing: border-box; }} html, body {{ margin: 0; width: 2400px; height: 1800px; background: #f1f0ec; color: #1c252c; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif; letter-spacing: 0; }}
  .overview {{ width: 2400px; height: 1800px; padding: 54px 62px 42px; border-top: 16px solid #d0b15f; display: grid; grid-template-rows: 210px minmax(0, 1fr) 68px; gap: 24px; }}
  .overview-header {{ display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(760px, .75fr); gap: 44px; align-items: end; border-bottom: 2px solid #1c252c; padding-bottom: 28px; }}
  .eyebrow {{ margin: 0 0 9px; color: #8e651a; font-size: 18px; font-weight: 850; }} h1 {{ margin: 0; font-size: 58px; line-height: 1.08; }} .subtitle {{ margin: 12px 0 0; color: #65717a; font-size: 21px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid #cfd2d0; background: #fff; }} .metrics div {{ padding: 18px; border-right: 1px solid #cfd2d0; }} .metrics div:last-child {{ border-right: 0; }} .metrics b {{ display: block; font-size: 34px; }} .metrics span {{ color: #68737b; font-size: 14px; }}
  .lanes {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; min-height: 0; }} .lane {{ display: grid; grid-template-rows: 72px minmax(0, 1fr); min-height: 0; }}
  .lane-head {{ display: flex; justify-content: space-between; align-items: baseline; border-bottom: 4px solid #1f6f57; padding: 8px 2px 12px; }} .lane.industry .lane-head {{ border-bottom-color: #6953a3; }} .lane h2 {{ margin: 0; font-size: 31px; }} .lane-head span {{ color: #68737b; font-size: 15px; }}
  .overview-grid {{ padding-top: 15px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-rows: minmax(0, 1fr); gap: 14px; min-height: 0; }}
  .overview-card {{ background: #fff; border: 1px solid #d6d9d7; border-top: 5px solid #2458a6; border-radius: 5px; padding: 16px 17px 14px; display: flex; flex-direction: column; min-height: 0; }} .overview-card[data-priority="P0"] {{ border-color: #a83232; border-top-width: 6px; }}
  .overview-meta {{ display: flex; justify-content: space-between; color: #68737b; font-size: 12px; }} .overview-meta span {{ padding: 3px 6px; color: #a83232; background: #faeaea; font-weight: 850; }}
  .overview-card h3 {{ margin: 9px 0 0; font-size: 20px; line-height: 1.28; overflow-wrap: anywhere; }} .overview-card p {{ margin: 9px 0 0; font-size: 13px; line-height: 1.38; color: #37434b; }}
  .overview-impact {{ margin-top: 9px; padding-left: 9px; border-left: 3px solid #1f6f57; font-size: 12px; line-height: 1.38; color: #3e4b52; }} .lane.industry .overview-impact {{ border-left-color: #6953a3; }}
  .overview-source {{ margin-top: auto; padding-top: 10px; color: #68737b; font-size: 11px; }} .overview-context {{ margin-top: 5px; color: #8e651a; font-size: 11px; font-weight: 750; }} .overview-empty {{ padding: 30px; border: 1px dashed #adb3b3; color: #68737b; background: #fff; }}
  .overview-footer {{ display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #cfd2d0; color: #68737b; font-size: 14px; }} .overview-footer b {{ color: #2458a6; }}
</style></head><body><main class="overview">
  <header class="overview-header"><div><p class="eyebrow">忠诚计划情报 · 过去两周 / 未来 60 天</p><h1>常旅客与忠诚计划情报雷达</h1><p class="subtitle">{html_escape(date_range_label(generated_at, args.hours))} · 生成于 {html_escape(generated_at.strftime('%Y-%m-%d %H:%M'))} {html_escape(timezone_label(args.timezone))}</p></div>
  <div class="metrics"><div><b>{p0_count}</b><span>P0 必看</span></div><div><b>{len(events)}</b><span>概览事件</span></div><div><b>{raw_count}</b><span>抓取条目</span></div><div><b>{counts.get('ok', 0)}</b><span>成功来源</span></div></div></header>
  <div class="lanes"><section class="lane consumer"><div class="lane-head"><h2>C端行动与风险</h2><span>促销 · 转点 · 账单报销 · 系统异常 · 权益追回</span></div><div class="overview-grid">{overview_cards(consumer, 1)}</div></section>
  <section class="lane industry"><div class="lane-head"><h2>忠诚计划生态与观察</h2><span>酒店 · 航司 · 信用卡 · 租车</span></div><div class="overview-grid">{overview_cards(industry, len(consumer) + 1)}</div></section></div>
  <footer class="overview-footer"><span>抓取健康：成功 {counts.get('ok', 0)} · 失败/受限 {counts.get('failed', 0) + counts.get('skipped', 0)} · 事件证据 {sum(len(event.evidence) for event in events)} · {html_escape(translation_health_summary(getattr(args, 'translation_health', None)))}</span><b>完整交互报告含全部事件、来源链接与证据</b></footer>
</main></body></html>"""


def chrome_executable_path() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def render_html_file_to_png(
    html_path: Path,
    output_path: Path,
    width: int,
    height: int = 1800,
    full_page: bool = False,
) -> None:
    from playwright.sync_api import sync_playwright

    launch_args = {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}
    chrome_path = chrome_executable_path()
    if chrome_path:
        launch_args["executable_path"] = chrome_path
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_args)
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(500)
        page.screenshot(path=str(output_path), type="png", full_page=full_page)
        browser.close()


def render_digest_html_image(
    items: list[IntelItem],
    health: list[SourceHealth],
    args: argparse.Namespace,
    output_path: Path,
    generated_at: dt.datetime,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
) -> Path:
    html_path = Path(args.html_output) if getattr(args, "html_output", None) else output_path.with_suffix(".html")
    width = max(args.image_width, 2400)
    html_text = render_infographic_html(items, health, args, generated_at, markdown_path, json_path)
    overview_path = output_path.with_name(f"{output_path.stem}-overview.html")
    overview_text = render_overview_html(items, health, args, generated_at)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_text, encoding="utf-8")
    overview_path.write_text(overview_text, encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render_html_file_to_png(overview_path, output_path, width, height=1800, full_page=False)
    return html_path


def infographic_layout_profile(item_count: int) -> dict[str, Any]:
    if item_count <= 6:
        return {
            "name": "compact",
            "width": 2400,
            "height": 1500,
            "top": 3,
            "c_end": 2,
            "risk": 2,
            "ecosystem": 2,
            "watch": 2,
        }
    if item_count <= 16:
        return {
            "name": "standard",
            "width": 2400,
            "height": 2200,
            "top": 3,
            "c_end": 4,
            "risk": 3,
            "ecosystem": 4,
            "watch": 3,
        }
    return {
        "name": "dense",
        "width": 2400,
        "height": 3200,
        "top": 4,
        "c_end": 6,
        "risk": 4,
        "ecosystem": 6,
        "watch": 4,
    }


def render_digest_image(
    items: list[IntelItem],
    health: list[SourceHealth],
    args: argparse.Namespace,
    output_path: Path,
    generated_at: dt.datetime,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
) -> None:
    try:
        render_digest_html_image(items, health, args, output_path, generated_at, markdown_path, json_path)
        return
    except Exception as exc:  # noqa: BLE001
        print(f"HTML infographic renderer failed; falling back to PIL renderer: {exc}", file=sys.stderr)

    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required for image output. Re-run with --no-image or install Pillow.")

    layout = infographic_layout_profile(len(items))
    width = max(args.image_width, layout["width"])
    height = 1800
    margin = 36
    bg = "#fbfaf7"
    text = "#252a33"
    muted = "#697180"
    blue = "#4b69c6"
    red = "#bd3f3f"
    orange = "#b66b16"
    green = "#1f9d6a"
    purple = "#7a55c7"
    border = "#e7e4dc"
    card_bg = "#ffffff"
    soft_blue = "#eef3ff"
    soft_green = "#edf7f1"
    soft_orange = "#fff4e5"
    soft_purple = "#f0eefb"
    font_title = image_font(36, True)
    font_h2 = image_font(25, True)
    font_h3 = image_font(19, True)
    font_body = image_font(17)
    font_small = image_font(14)
    font_tiny = image_font(12)
    font_tag = image_font(13, True)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    def text_width(value: str, font_obj: Any) -> int:
        return int(draw.textbbox((0, 0), value, font=font_obj)[2])

    def wrap(value: str, font_obj: Any, max_width: int, max_lines: int | None = None) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in value:
            candidate = current + char
            if text_width(candidate, font_obj) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            while lines[-1] and text_width(lines[-1] + "...", font_obj) > max_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] = lines[-1].rstrip() + "..."
        return lines or [""]

    def draw_wrapped(
        x: int,
        y_pos: int,
        value: str,
        font_obj: Any,
        fill: str,
        max_width: int,
        gap: int = 5,
        max_lines: int | None = None,
    ) -> int:
        for line in wrap(value, font_obj, max_width, max_lines=max_lines):
            draw.text((x, y_pos), line, font=font_obj, fill=fill)
            y_pos += font_obj.size + gap
        return y_pos

    def pill(x: int, y_pos: int, value: str, fill: str, fg: str) -> int:
        pad_x, pad_y = 11, 5
        pill_width = text_width(value, font_tag) + pad_x * 2
        pill_height = font_tag.size + pad_y * 2
        draw.rounded_rectangle((x, y_pos, x + pill_width, y_pos + pill_height), radius=13, fill=fill)
        draw.text((x + pad_x, y_pos + pad_y - 1), value, font=font_tag, fill=fg)
        return x + pill_width + 10

    def metric_box(x: int, y_pos: int, box_w: int, label: str, value: str, color: str) -> None:
        draw.rounded_rectangle((x, y_pos, x + box_w, y_pos + 58), radius=14, fill=card_bg, outline=border)
        draw.text((x + 16, y_pos + 10), value, font=image_font(24, True), fill=color)
        draw.text((x + 16, y_pos + 36), label, font=font_tiny, fill=muted)

    def item_tag_text(item: IntelItem) -> str:
        vertical = "/".join(display_list(item.vertical, "vertical", 2)) if item.vertical else "-"
        signal = "/".join(display_list(item.ecosystem_signal_type, "ecosystem_signal", 1)) if item.ecosystem_signal_type else "-"
        future = f" | 未来 {'/'.join(item.future_event_dates[:2])}" if item.future_event_dates else ""
        return (
            f"{vertical} | {signal} | {display_label(item.action_label, 'action')}/"
            f"{display_label(item.risk_label, 'risk')}{future}"
        )

    def draw_card(x: int, y_pos: int, card_w: int, card_h: int, item: IntelItem, index: int, accent: str) -> None:
        draw.rounded_rectangle((x, y_pos, x + card_w, y_pos + card_h), radius=13, fill=card_bg, outline=border)
        draw.rounded_rectangle((x, y_pos, x + 7, y_pos + card_h), radius=4, fill=accent)
        inner_x = x + 17
        inner_w = card_w - 28
        cy = y_pos + 12
        title_lines = 2 if card_h >= 125 else 1
        summary_lines = 2 if card_h >= 150 else 1
        cy = draw_wrapped(inner_x, cy, f"{index}. {display_title(item)}", font_h3, text, inner_w, 4, title_lines)
        cy += 2
        summary = short_text(display_summary(item), min(args.image_summary_chars, 150))
        cy = draw_wrapped(inner_x, cy, summary, font_small, text, inner_w, 4, summary_lines)
        meta = f"{item_time_label(item, args.timezone)} | {item.source}"
        cy = draw_wrapped(inner_x, cy + 3, meta, font_tiny, muted, inner_w, 3, 1)
        cy = draw_wrapped(inner_x, cy, item_tag_text(item), font_tiny, muted, inner_w, 3, 1)
        link_y = min(y_pos + card_h - 20, cy + 1)
        draw_wrapped(inner_x, link_y, url_label(item.url, max_len=90), font_tiny, blue, inner_w, 3, 1)

    def draw_placeholder(x: int, y_pos: int, box_w: int, box_h: int, label: str) -> None:
        draw.rounded_rectangle((x, y_pos, x + box_w, y_pos + box_h), radius=13, fill="#f6f4ef", outline=border)
        draw.text((x + 18, y_pos + 18), label, font=font_small, fill=muted)

    def draw_item_grid(
        x: int,
        y_pos: int,
        box_w: int,
        box_h: int,
        title: str,
        rows: list[IntelItem],
        max_items: int,
        accent: str,
        cols: int,
    ) -> None:
        draw.text((x, y_pos), title, font=font_h3, fill=text)
        display = rows[:max_items]
        top_y = y_pos + 31
        grid_h = box_h - 36
        if not display:
            draw_placeholder(x, top_y, box_w, min(88, grid_h), "暂无高相关条目")
            return
        cols = max(1, min(cols, len(display)))
        row_count = (len(display) + cols - 1) // cols
        gap = 10
        card_w = int((box_w - gap * (cols - 1)) / cols)
        overflow_h = 18 if len(rows) > len(display) else 0
        card_h = max(96, int((grid_h - overflow_h - gap * (row_count - 1)) / row_count))
        for idx, item in enumerate(display, 1):
            col = (idx - 1) % cols
            row = (idx - 1) // cols
            draw_card(x + col * (card_w + gap), top_y + row * (card_h + gap), card_w, card_h, item, idx, accent)
        if len(rows) > len(display):
            draw.text((x, y_pos + box_h - 15), f"另有 {len(rows) - len(display)} 条见完整报告", font=font_tiny, fill=muted)

    def draw_group(
        x: int,
        y_pos: int,
        group_w: int,
        group_h: int,
        title: str,
        subtitle: str,
        top_title: str,
        top_rows: list[IntelItem],
        top_max: int,
        bottom_title: str,
        bottom_rows: list[IntelItem],
        bottom_max: int,
        accent_top: str,
        accent_bottom: str,
    ) -> None:
        draw.rounded_rectangle((x, y_pos, x + group_w, y_pos + group_h), radius=18, fill="#fffefd", outline=border)
        draw.text((x + 18, y_pos + 16), title, font=font_h2, fill=text)
        draw.text((x + 18, y_pos + 47), subtitle, font=font_small, fill=muted)
        inner_x = x + 18
        inner_y = y_pos + 76
        inner_w = group_w - 36
        inner_h = group_h - 94
        gap = 16
        half_h = int((inner_h - gap) / 2)
        cols = 2 if layout["name"] != "compact" else 1
        draw_item_grid(inner_x, inner_y, inner_w, half_h, top_title, top_rows, top_max, accent_top, cols)
        draw_item_grid(inner_x, inner_y + half_h + gap, inner_w, half_h, bottom_title, bottom_rows, bottom_max, accent_bottom, cols)

    counts = Counter(row.status for row in health)
    sections = section_items(items, mode=args.mode)
    top_title = "今日必看" if args.mode == "daily" else "本周必看"
    top_rows = sections.get(top_title, [])
    c_end_rows = sections.get("C端玩法雷达", [])
    risk_rows = sections.get("系统异常 / 权益追回 / 风控", [])
    eco_rows = sections.get("忠诚计划生态雷达", [])
    watch_rows = sections.get("后续观察", [])

    draw.text((margin, 30), "忠诚计划情报雷达", font=font_title, fill=text)
    draw.text(
        (margin, 74),
        f"{date_range_label(generated_at, args.hours)}  |  过去两周信号 + 未来60天观察  |  生成 {generated_at:%Y-%m-%d %H:%M} {timezone_label(args.timezone)}",
        font=font_body,
        fill=muted,
    )
    x = width - margin - 620
    metric_box(x, 31, 134, "抓取成功源", str(counts.get("ok", 0)), green)
    metric_box(x + 146, 31, 134, "跳过/失败", str(counts.get("skipped", 0) + counts.get("failed", 0)), orange)
    metric_box(x + 292, 31, 134, "C端条目", str(len(c_end_rows) + len(risk_rows)), blue)
    metric_box(x + 438, 31, 134, "行业/观察", str(len(eco_rows) + len(watch_rows)), purple)
    px = margin
    py = 108
    layout_name = {"compact": "精简版", "standard": "标准版", "dense": "高密度版"}.get(layout["name"], "信息图")
    px = pill(px, py, layout_name, soft_purple, purple)
    px = pill(px, py, f"{len(items)} 条入选", soft_green, green)
    px = pill(px, py, "无官网确认", soft_orange, orange)
    pill(px, py, "横版信息图", soft_blue, blue)

    top_y = 147
    top_h = 177
    draw.rounded_rectangle((margin, top_y, width - margin, top_y + top_h), radius=18, fill="#fffefd", outline=border)
    draw.text((margin + 18, top_y + 16), top_title, font=font_h2, fill=text)
    draw_wrapped(margin + 18, top_y + 47, "全局最高优先级，右侧两栏按 C端信息 / 行业信息展开。", font_small, muted, 150, 4, 2)
    top_grid_x = margin + 190
    top_grid_w = width - margin - top_grid_x - 18
    top_display = top_rows[: layout["top"]]
    if top_display:
        top_cols = len(top_display)
        gap = 12
        card_w = int((top_grid_w - gap * (top_cols - 1)) / top_cols)
        for idx, item in enumerate(top_display, 1):
            draw_card(top_grid_x + (idx - 1) * (card_w + gap), top_y + 18, card_w, top_h - 36, item, idx, blue)
    else:
        draw_placeholder(top_grid_x, top_y + 24, top_grid_w, top_h - 48, "暂无高相关条目")

    group_y = top_y + top_h + 20
    footer_h = 72
    group_h = height - group_y - footer_h - 20
    group_w = int((width - 3 * margin) / 2)
    draw_group(
        margin,
        group_y,
        group_w,
        group_h,
        "C端信息",
        "可操作、需报名、可避坑、风控和异常实测。",
        "玩法 / 促销 / 转点 / 账单报销",
        c_end_rows,
        layout["c_end"],
        "系统异常 / 权益追回 / 风控",
        risk_rows,
        layout["risk"],
        green,
        red,
    )
    draw_group(
        margin * 2 + group_w,
        group_y,
        group_w,
        group_h,
        "行业信息",
        "全球忠诚计划生态、权益供给、监管和未来两个月节点。",
        "忠诚计划生态",
        eco_rows,
        layout["ecosystem"],
        "未来两个月 / 后续观察",
        watch_rows,
        layout["watch"],
        purple,
        orange,
    )

    footer_y = height - footer_h + 8
    draw.line((margin, footer_y, width - margin, footer_y), fill=border, width=2)
    ok_sources = [row for row in health if row.status == "ok"]
    skipped_sources = [row for row in health if row.status != "ok"]
    raw_items = sum(row.items for row in ok_sources)
    health_text = f"抓取健康：成功源 {len(ok_sources)}；跳过/失败 {len(skipped_sources)}；原始条目 {raw_items}。"
    if skipped_sources:
        health_text += " 受限源：" + " / ".join(row.source for row in skipped_sources[:4])
    draw.text((margin, footer_y + 12), health_text, font=font_small, fill=muted)
    file_bits = []
    if markdown_path:
        file_bits.append("摘要文件已生成")
    if json_path:
        file_bits.append("审计数据已生成")
    draw.text((margin, footer_y + 36), " | ".join(file_bits) or "由忠诚计划情报 Skill 生成", font=font_tiny, fill=muted)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=95)


def default_output_paths(args: argparse.Namespace, generated_at: dt.datetime) -> tuple[Path | None, Path | None, Path | None]:
    stamp = generated_at.strftime("%Y%m%d-%H%M")
    focus = args.focus.replace("-", "_")
    output_dir = Path(args.output_dir)
    markdown_path = Path(args.output) if args.output else output_dir / f"loyalty-intel-{args.mode}-{focus}-{stamp}.md"
    json_path = Path(args.json_output) if args.json_output else output_dir / f"loyalty-intel-{args.mode}-{focus}-{stamp}.json"
    image_path = None if args.no_image else Path(args.image_output) if args.image_output else output_dir / f"loyalty-intel-{args.mode}-{focus}-{stamp}.png"
    return markdown_path, json_path, image_path


def load_events_from_json(path: Path) -> tuple[list[IntelEvent], list[SourceHealth], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must contain an object")

    evidence_fields = {field.name for field in dataclasses.fields(Evidence)}
    event_fields = {field.name for field in dataclasses.fields(IntelEvent)}
    health_fields = {field.name for field in dataclasses.fields(SourceHealth)}
    events: list[IntelEvent] = []
    for row in payload.get("items", []):
        if not isinstance(row, dict):
            continue
        event_row = {key: value for key, value in row.items() if key in event_fields}
        evidence = []
        for evidence_row in row.get("evidence", []):
            if isinstance(evidence_row, dict):
                evidence.append(
                    Evidence(**{key: value for key, value in evidence_row.items() if key in evidence_fields})
                )
        event_row["evidence"] = evidence
        events.append(IntelEvent(**event_row))
    health = [
        SourceHealth(**{key: value for key, value in row.items() if key in health_fields})
        for row in payload.get("health", [])
        if isinstance(row, dict)
    ]
    return events, health, payload


def payload_generated_at(payload: dict[str, Any], tz_name: str) -> dt.datetime:
    value = payload.get("generated_at")
    try:
        parsed = dt.datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone_or_utc(tz_name))
        return parsed.astimezone(timezone_or_utc(tz_name))
    except (TypeError, ValueError):
        return now_in_timezone(tz_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect public loyalty and Chase/Amex intelligence.")
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--focus", choices=["all", "credit-card", "air-china", "hotel", "bug"], default="all")
    parser.add_argument("--hours", type=int, default=None, help="Override time window in hours.")
    parser.add_argument("--max-items", type=int, default=40)
    parser.add_argument("--per-source-limit", type=int, default=None)
    parser.add_argument("--max-sources", type=int, default=None, help="Debug/smoke-test only.")
    parser.add_argument("--source-id", action="append", help="Collect only specific source id. Can be repeated.")
    parser.add_argument("--include-p2", action="store_true")
    parser.add_argument("--fetch-details", action="store_true")
    parser.add_argument("--source-delay", type=float, default=0.8)
    parser.add_argument("--detail-delay", type=float, default=1.5)
    parser.add_argument("--quiet", action="store_true", help="Suppress per-source collection progress on stderr.")
    parser.add_argument("--profile", default=str(REFERENCES_DIR / "profile.yaml"))
    parser.add_argument("--cards", default=str(REFERENCES_DIR / "cards.yaml"))
    parser.add_argument("--sources", default=str(REFERENCES_DIR / "sources.yaml"))
    parser.add_argument("--input-json", help="Re-render a previously collected JSON report without fetching sources again.")
    parser.add_argument("--output", help="Write Markdown digest to this path.")
    parser.add_argument("--json-output", help="Write raw scored items and health as JSON.")
    parser.add_argument("--image-output", help="Write a horizontal PNG infographic digest to this path.")
    parser.add_argument("--html-output", help="Write the HTML/CSS infographic source to this path.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for default PNG/Markdown/JSON outputs.")
    parser.add_argument("--no-image", action="store_true", help="Disable PNG rendering.")
    parser.add_argument("--print-markdown", action="store_true", help="Also print the full Markdown digest to stdout.")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--image-width", type=int, default=2400)
    parser.add_argument("--image-summary-chars", type=int, default=280)
    parser.add_argument("--translation-provider", choices=["google"], default="google")
    parser.add_argument("--translation-cache", default=str(DEFAULT_TRANSLATION_CACHE))
    parser.add_argument("--translation-batch-chars", type=int, default=3000)
    parser.add_argument("--translation-delay", type=float, default=0.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    profile_cfg = load_yaml(Path(args.profile))
    args.timezone = profile_cfg.get("timezone", args.timezone)
    input_payload: dict[str, Any] | None = None
    if args.input_json:
        items, health, input_payload = load_events_from_json(Path(args.input_json))
        args.mode = str(input_payload.get("mode", args.mode))
        args.focus = str(input_payload.get("focus", args.focus))
        args.timezone = str(input_payload.get("timezone", args.timezone))
        if args.hours is None:
            args.hours = int(input_payload.get("hours", 336))
        generated_at = payload_generated_at(input_payload, args.timezone)
    else:
        if args.hours is None:
            defaults = profile_cfg.get("default_modes", {})
            args.hours = defaults.get("weekly_hours" if args.mode == "weekly" else "daily_hours", 336)
        generated_at = now_in_timezone(args.timezone)
        args.reference_date = generated_at
        items, health = collect_all(args)

    args.reference_date = generated_at
    markdown_path, json_path, image_path = default_output_paths(args, generated_at)
    translation_health = localize_events(
        items,
        Path(args.translation_cache),
        batch_chars=args.translation_batch_chars,
        delay=args.translation_delay,
        provider="Google 翻译公共端点",
    )
    args.translation_health = translation_health
    markdown = render_markdown(items, health, args)

    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
    if args.print_markdown:
        print(markdown)

    if json_path:
        payload = {
            "items": [dataclasses.asdict(item) for item in items],
            "health": [dataclasses.asdict(row) for row in health],
            "generated_at": generated_at.isoformat(),
            "mode": args.mode,
            "focus": args.focus,
            "hours": args.hours,
            "timezone": args.timezone,
            "localized_at": now_in_timezone(args.timezone).isoformat(),
            "translation_health": dataclasses.asdict(translation_health),
        }
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if image_path:
        render_digest_image(items, health, args, image_path, generated_at, markdown_path, json_path)

    print("已生成忠诚计划情报报告：")
    if image_path:
        print(f"信息图：{image_path}")
        html_path = Path(args.html_output) if args.html_output else image_path.with_suffix(".html")
        if html_path.exists():
            print(f"交互报告：{html_path}")
    if markdown_path:
        print(f"文字摘要：{markdown_path}")
    if json_path:
        print(f"审计数据：{json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
