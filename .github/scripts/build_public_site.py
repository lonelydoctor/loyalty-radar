#!/usr/bin/env python3
"""Build the offline bilingual Loyalty Radar public site.

The only accepted report input is the publication-safe output of
``loyalty-radar audit --policy public``:

* committed reports live at ``public-briefs/<ISO-WEEK>/report.json``;
* ``schema_id`` is exactly ``loyalty-radar-public-report/v1``;
* event text is present in both ``localized.en`` and ``localized.zh-CN``;
* event evidence uses the allowlisted ``source_refs`` and ``taxonomy`` fields;
* private audit fields and raw/original source text are rejected.

The source catalog is rebuilt from committed Source Pack YAML.  This module uses a
strict reader for the repository's small, declared YAML subset so the Pages build
does not install packages or make network requests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import struct
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SITE = ROOT / "docs" / "site"
DEFAULT_REPORTS_ROOT = ROOT / "public-briefs"
PACK_DIR = ROOT / "plugins" / "loyalty-radar" / "skills" / "loyalty-radar" / "references" / "source-packs"
ASSET_DIR = ROOT / "docs" / "assets"
SCHEMA_ID = "loyalty-radar-public-report/v1"
LOCALES = ("en", "zh-CN")

PRIVATE_PATTERNS = (
    re.compile(r"/" r"Users/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\" r"Users\\[^\\\s]+\\"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)
FORBIDDEN_REPORT_KEYS = {
    "original",
    "raw",
    "raw_body",
    "raw_content",
    "body",
    "content",
    "content_html",
    "source_body",
    "evidence",
    "translation_health",
    "profile",
    "cards",
    "memberships",
    "cookies",
}
FORBIDDEN_PUBLIC_MARKERS = (
    "example.invalid",
    "mock data",
    "synthetic demo",
    "fictional report",
    "demo-report",
    "合成演示",
    "虚构报告",
)
TOP_LEVEL_KEYS = {
    "schema_id",
    "publication",
    "items",
    "health",
}
PUBLICATION_KEYS = {
    "policy",
    "product",
    "generated_at",
    "audited_at",
    "mode",
    "focus",
    "hours",
    "future_watch_days",
    "timezone",
    "source_packs",
    "locales",
    "event_count",
}
PRODUCT_KEYS = {"name", "version"}
EVENT_KEYS = {
    "event_id",
    "lane",
    "priority",
    "localized",
    "source_refs",
    "published_at",
    "future_event_dates",
    "taxonomy",
    "confidence_label",
    "risk_label",
    "action_label",
    "metric_snippets",
}
LOCALIZED_KEYS = {"title", "summary", "why_it_matters"}
SOURCE_REF_KEYS = {"source_id", "source", "source_type", "url", "published_at"}
TAXONOMY_KEYS = {
    "programs",
    "card_families",
    "topic_type",
    "verticals",
    "ecosystem_signal_types",
    "stakeholders",
    "consumer_impact",
    "impact_horizon",
}
HEALTH_KEYS = {
    "configured_sources",
    "script_eligible_sources",
    "script_ok_sources",
    "script_ok_rate",
    "p0_script_sources",
    "p0_ok_sources",
    "p0_ok_rate",
    "status_counts",
    "events_checked",
    "duplicate_events",
    "duplicate_rate",
    "top_events_checked",
}
HEALTH_OPTIONAL_KEYS = {"fallback_sources"}
ISO_WEEK_RE = re.compile(r"\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])")


TEXT = {
    "en": {
        "description": "Reviewed, source-linked loyalty intelligence for members and the wider loyalty ecosystem.",
        "nav_latest": "Latest report",
        "nav_archive": "Archive",
        "nav_sources": "59-source catalog",
        "nav_github": "GitHub",
        "language": "Language",
        "skip": "Skip to content",
        "primary_nav": "Primary navigation",
        "eyebrow": "Public intelligence brief",
        "public_beta": "PUBLIC",
        "report_archive_mark": "REPORT ARCHIVE",
        "title": "Loyalty Radar",
        "subtitle": "Two evidence lanes: actions for members and structural signals across loyalty programs.",
        "empty_title": "No reviewed public report has been published yet.",
        "empty_body": "The public archive only accepts an approved, sanitized report. Private audit JSON and raw source text are never copied into this site.",
        "browse_sources": "Browse the real source catalog",
        "install": "Install Agent Skill",
        "github": "View on GitHub",
        "archive": "Report archive",
        "archive_eyebrow": "Archive",
        "awaiting_review": "00 / Awaiting review",
        "archive_empty": "There are no reviewed public reports in the archive.",
        "latest": "Latest reviewed report",
        "generated": "Generated",
        "audited": "Public audit completed",
        "window": "Evidence window",
        "future": "Forward watch",
        "future_value": "Next {days} days",
        "collection": "Collection health",
        "health_eyebrow": "Health",
        "configured": "Configured sources",
        "eligible": "Script-eligible",
        "script_ok": "Script sources healthy",
        "p0_ok": "P0 sources healthy",
        "events_checked": "Events audited",
        "duplicates": "Duplicate events",
        "duplicate_rate": "Duplicate rate",
        "top_checked": "Top events checked",
        "success_rate": "Script-source success",
        "fallbacks": "Public-cache fallbacks",
        "c_end": "Member action radar",
        "c_end_desc": "Promotions, transfer bonuses, credits, status, redemption, bugs, clawbacks, and operational datapoints.",
        "ecosystem": "Loyalty ecosystem radar",
        "ecosystem_desc": "Economics, devaluation, partner contracts, capacity pressure, regulation, and consumer backlash.",
        "no_lane": "No reviewed event was selected for this lane.",
        "why": "Why it matters",
        "published": "Published",
        "source": "Sources",
        "metrics": "Numeric anchors",
        "future_dates": "Future dates",
        "unknown_time": "Time unavailable",
        "vertical": "Vertical",
        "topic": "Topic",
        "signal": "Ecosystem signal",
        "consumer_impact": "Member impact",
        "programs_label": "Programs / card families",
        "event_count": "{count} events",
        "catalog_eyebrow": "v0.1.2 · Repository source configuration",
        "catalog_title": "Public 59-source catalog",
        "catalog_subtitle": "Configured public forums, feeds, publishers, and news queries used by Loyalty Radar.",
        "catalog_notice": "This catalog is generated from committed real source configuration. It does not claim that a source is currently healthy or that it published news today.",
        "source_packs": "Source packs",
        "configured_sources": "Configured sources",
        "script_collectors": "Script-eligible",
        "browser_assisted": "Browser-assisted",
        "search": "Search source, program, region, or language",
        "all": "All",
        "pack": "Source pack",
        "priority": "Priority",
        "method": "Collection method",
        "fallback": "Fallback",
        "region": "Region",
        "programs": "Programs",
        "status": "Default state",
        "enabled": "Enabled",
        "disabled": "Disabled",
        "open_source": "Open public source",
        "no_results": "No source matches these filters.",
        "footer": "Built offline from reviewed public-report data and committed source configuration. No telemetry.",
    },
    "zh-CN": {
        "description": "面向会员与忠诚计划生态、经过审核且可追溯来源的公开情报。",
        "nav_latest": "最新报告",
        "nav_archive": "报告归档",
        "nav_sources": "59 个来源",
        "nav_github": "GitHub",
        "language": "语言",
        "skip": "跳到主要内容",
        "primary_nav": "主导航",
        "eyebrow": "公开情报简报",
        "public_beta": "公开测试",
        "report_archive_mark": "报告归档",
        "title": "Loyalty Radar",
        "subtitle": "两条证据主线：会员可采取的行动，以及忠诚计划生态中的结构性信号。",
        "empty_title": "尚未发布经过审核的公开报告。",
        "empty_body": "公开归档只接收经过批准和清洗的报告。私有审计 JSON 与来源正文绝不会被复制到本站。",
        "browse_sources": "浏览真实来源目录",
        "install": "安装 Agent Skill",
        "github": "在 GitHub 查看",
        "archive": "报告归档",
        "archive_eyebrow": "归档",
        "awaiting_review": "00 / 等待审核",
        "archive_empty": "归档中暂无经过审核的公开报告。",
        "latest": "最新审核报告",
        "generated": "生成时间",
        "audited": "公开审计完成时间",
        "window": "证据窗口",
        "future": "后续关注",
        "future_value": "未来 {days} 天",
        "collection": "采集健康",
        "health_eyebrow": "健康检查",
        "configured": "配置来源",
        "eligible": "脚本可抓取来源",
        "script_ok": "脚本来源成功",
        "p0_ok": "P0 来源成功",
        "events_checked": "已审计事件",
        "duplicates": "重复事件",
        "duplicate_rate": "重复率",
        "top_checked": "已核查重点事件",
        "success_rate": "脚本来源成功率",
        "fallbacks": "公开缓存回退",
        "c_end": "C 端玩法雷达",
        "c_end_desc": "促销、转点奖励、抵扣、会籍、兑换、系统异常、追回与履约实测。",
        "ecosystem": "忠诚计划生态雷达",
        "ecosystem_desc": "经济模型、贬值、伙伴协议、容量压力、监管与消费者反弹。",
        "no_lane": "本期没有经过审核并入选该主线的事件。",
        "why": "为什么值得关注",
        "published": "发布时间",
        "source": "来源",
        "metrics": "数字锚点",
        "future_dates": "未来节点",
        "unknown_time": "时间未提供",
        "vertical": "行业",
        "topic": "主题",
        "signal": "生态信号",
        "consumer_impact": "会员影响",
        "programs_label": "项目 / 卡产品族",
        "event_count": "{count} 个事件",
        "catalog_eyebrow": "v0.1.2 · 仓库来源配置",
        "catalog_title": "公开 59 来源目录",
        "catalog_subtitle": "Loyalty Radar 配置的公开论坛、订阅源、媒体与新闻查询。",
        "catalog_notice": "本目录根据仓库中真实提交的来源配置生成，不代表来源当前可访问，也不代表它今天发布了新闻。",
        "source_packs": "来源包",
        "configured_sources": "配置来源",
        "script_collectors": "脚本可抓取",
        "browser_assisted": "浏览器辅助",
        "search": "搜索来源、项目、地区或语言",
        "all": "全部",
        "pack": "来源包",
        "priority": "优先级",
        "method": "采集方式",
        "fallback": "回退方式",
        "region": "地区",
        "programs": "项目",
        "status": "默认状态",
        "enabled": "启用",
        "disabled": "停用",
        "open_source": "打开公开来源",
        "no_results": "没有符合筛选条件的来源。",
        "footer": "仅使用经过审核的公开报告数据与仓库来源配置离线构建，不含遥测。",
    },
}

LABELS = {
    "action": {
        "enroll": ("Enrollment required", "需报名"),
        "需报名": ("Enrollment required", "需报名"),
        "ready": ("Ready to use", "可直接用"),
        "可直接用": ("Ready to use", "可直接用"),
        "targeted": ("Targeted / YMMV", "定向 / YMMV"),
        "定向/YMMV": ("Targeted / YMMV", "定向 / YMMV"),
        "watch": ("Watch only", "只观察"),
        "只观察": ("Watch only", "只观察"),
        "avoid": ("High risk: do not attempt", "高风险勿操作"),
        "高风险勿操作": ("High risk: do not attempt", "高风险勿操作"),
    },
    "risk": {
        "normal": ("Normal benefit", "正常权益"),
        "正常权益": ("Normal benefit", "正常权益"),
        "ymmv": ("YMMV", "YMMV"),
        "YMMV": ("YMMV", "YMMV"),
        "clawback": ("Possible clawback", "可能被追回"),
        "可能 clawback": ("Possible clawback", "可能被追回"),
        "high": ("High account-risk", "高风控风险"),
        "高风控风险": ("High account-risk", "高风控风险"),
    },
    "confidence": {
        "single": ("Single-post lead", "单帖线索"),
        "单帖线索": ("Single-post lead", "单帖线索"),
        "multi_user": ("Multiple user datapoints", "多用户实测"),
        "多用户 DP": ("Multiple user datapoints", "多用户实测"),
        "评论 DP": ("Comment datapoint", "评论实测"),
        "editorial": ("Editorial synthesis", "媒体整理"),
        "博客整理": ("Editorial synthesis", "媒体整理"),
        "multi_source": ("Corroborated across sources", "多来源印证"),
        "多源重复": ("Corroborated across sources", "多来源印证"),
        "多源证实": ("Corroborated across sources", "多来源印证"),
    },
    "vertical": {
        "hotel": ("Hotel", "酒店"),
        "airline": ("Airline", "航司"),
        "credit_card": ("Credit card", "信用卡"),
        "rental_car": ("Rental car", "租车"),
        "loyalty": ("Loyalty", "忠诚计划"),
    },
    "topic": {
        "policy_change": ("Policy change", "政策变化"),
        "offer": ("Offer", "优惠"),
        "datapoint": ("Datapoint", "用户实测"),
        "bug": ("Bug", "系统异常"),
        "clawback": ("Clawback", "权益追回"),
        "lounge": ("Lounge", "休息室"),
        "transfer_bonus": ("Transfer bonus", "转点奖励"),
        "trip_report": ("Trip report", "旅行报告"),
        "industry_signal": ("Industry signal", "行业信号"),
        "status_match": ("Status match", "会籍匹配"),
        "portal_stack": ("Portal stack", "门户叠加"),
        "statement_credit": ("Statement credit", "账单报销"),
        "devaluation": ("Devaluation", "积分贬值"),
        "redemption": ("Redemption", "积分兑换"),
    },
    "signal": {
        "revenue_shift": ("Revenue shift", "收入结构变化"),
        "cost_reimbursement_conflict": ("Cost and reimbursement conflict", "成本与补偿冲突"),
        "benefit_capacity_pressure": ("Benefit capacity pressure", "权益容量压力"),
        "devaluation_or_inflation": ("Devaluation or inflation", "积分贬值或通胀"),
        "qualification_gatekeeping": ("Qualification gatekeeping", "资格门槛收紧"),
        "partner_contract_shift": ("Partner contract shift", "伙伴协议变化"),
        "regulatory_or_legal_pressure": ("Regulatory or legal pressure", "监管或法律压力"),
        "operational_reliability": ("Operational reliability", "系统与履约可靠性"),
        "supply_demand_stress": ("Supply and demand stress", "供需压力"),
        "consumer_backlash": ("Consumer backlash", "消费者反弹"),
    },
    "consumer_impact": {
        "直接可用": ("Actionable now", "可直接使用"),
        "需避坑": ("Avoid or verify", "需要避坑"),
        "可能贬值": ("Possible devaluation", "可能贬值"),
        "权益履约风险": ("Benefit delivery risk", "权益履约风险"),
        "长期观察": ("Long-term watch", "长期观察"),
    },
}

METHODS = {
    "rss": ("RSS", "RSS"),
    "flyert_forum": ("Flyer forum HTML", "飞客论坛 HTML"),
    "html_keyword": ("Keyword-filtered HTML", "关键词过滤 HTML"),
    "browser_only": ("Browser-assisted", "浏览器辅助"),
}


@dataclass(frozen=True)
class Pack:
    pack_id: str
    name: str
    default_enabled: bool
    count: int


@dataclass(frozen=True)
class PublicReport:
    report_id: str
    generated_at: dt.datetime
    audited_at: dt.datetime
    window_start: dt.datetime
    window_end: dt.datetime
    hours: int
    future_watch_days: int
    collection_health: dict[str, Any]
    events: list[dict[str, Any]]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def read_source_pack(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pack: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section = ""
    list_key = ""
    scalar_key = ""
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw == "pack:":
            section, list_key, scalar_key = "pack", "", ""
            continue
        if raw == "sources:":
            section, list_key, scalar_key = "sources", "", ""
            continue
        if section == "pack" and raw.startswith("  ") and not raw.startswith("  - "):
            key, separator, value = raw.strip().partition(":")
            if not separator:
                raise ValueError(f"{path}:{number}: invalid pack field")
            pack[key] = parse_scalar(value)
            continue
        if section == "sources" and raw.startswith("- id:"):
            current = {"id": parse_scalar(raw.partition(":")[2])}
            sources.append(current)
            list_key, scalar_key = "", "id"
            continue
        if section == "sources" and current is not None and raw.startswith("  - "):
            if list_key:
                current.setdefault(list_key, []).append(parse_scalar(raw[4:]))
            continue
        if section == "sources" and current is not None and raw.startswith("    ") and ":" not in raw.strip():
            if not scalar_key or not isinstance(current.get(scalar_key), str):
                raise ValueError(f"{path}:{number}: unexpected folded scalar continuation")
            current[scalar_key] = f"{current[scalar_key]} {raw.strip()}"
            continue
        if section == "sources" and current is not None and raw.startswith("  "):
            key, separator, value = raw.strip().partition(":")
            if not separator:
                raise ValueError(f"{path}:{number}: invalid source field")
            value = value.strip()
            if not value or value.startswith("&"):
                current[key] = []
                list_key = key
                scalar_key = ""
            else:
                current[key] = parse_scalar(value)
                list_key = ""
                scalar_key = key
            continue
        raise ValueError(f"{path}:{number}: unsupported Source Pack YAML structure")
    return pack, sources


def load_source_catalog(pack_dir: Path) -> tuple[list[Pack], list[dict[str, Any]]]:
    packs: list[Pack] = []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(pack_dir.glob("*.yaml")):
        pack, rows = read_source_pack(path)
        pack_id = str(pack.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9-]+", pack_id):
            raise ValueError(f"{path}: invalid or missing pack id")
        packs.append(Pack(pack_id, str(pack.get("name") or pack_id), bool(pack.get("default_enabled")), len(rows)))
        for row in rows:
            source_id = str(row.get("id") or "").strip()
            if not source_id or source_id in seen:
                raise ValueError(f"{path}: duplicate or missing source id {source_id!r}")
            seen.add(source_id)
            for key in ("name", "priority", "fetch_method", "url", "region", "language"):
                if not str(row.get(key) or "").strip():
                    raise ValueError(f"{path}: {source_id} is missing {key}")
            if not is_http_url(str(row["url"])):
                raise ValueError(f"{path}: {source_id} has a non-HTTP URL")
            row["pack_id"] = pack_id
            sources.append(row)
    if len(packs) != 5 or len(sources) != 59:
        raise ValueError(f"Expected the committed 5-pack / 59-source catalog, found {len(packs)} / {len(sources)}")
    return packs, sources


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and host not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
        and not host.endswith((".invalid", ".local"))
    )


def parse_timestamp(value: Any, field: str) -> dt.datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} is required")
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def check_public_value(value: Any, path: str = "report") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_REPORT_KEYS:
                raise ValueError(f"{path}: private or raw field {key!r} is forbidden")
            check_public_value(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            check_public_value(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        lower = value.lower()
        for marker in FORBIDDEN_PUBLIC_MARKERS:
            if marker in lower:
                raise ValueError(f"{path}: public test/demo marker {marker!r} is forbidden")
        for pattern in PRIVATE_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"{path}: possible private path or secret")


def require_known_keys(row: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise ValueError(f"{path}: unsupported field(s): {', '.join(unknown)}")


def require_text(row: dict[str, Any], key: str, path: str) -> str:
    raw = row.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"{path}.{key} must be a string")
    value = raw.strip()
    if not value:
        raise ValueError(f"{path}.{key} is required")
    return value


def require_string(row: dict[str, Any], key: str, path: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{path}.{key} must be a string")
    return value.strip()


def require_string_list(
    row: dict[str, Any], key: str, path: str, *, unique: bool = False
) -> list[str]:
    value = row.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path}.{key} must be an array of strings")
    rendered = [item.strip() for item in value]
    if unique and len(set(rendered)) != len(rendered):
        raise ValueError(f"{path}.{key} must contain unique values")
    return rendered


def parse_optional_timestamp(value: Any, field: str) -> dt.datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp or null")
    return parse_timestamp(value, field)


def normalize_source_rows(event: dict[str, Any], event_path: str) -> list[dict[str, Any]]:
    rows = event.get("source_refs")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{event_path}.source_refs must contain at least one source reference")
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        path = f"{event_path}.source_refs[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{path} must be an object")
        require_known_keys(row, SOURCE_REF_KEYS, path)
        source_id = require_text(row, "source_id", path)
        name = require_text(row, "source", path)
        source_type = require_string(row, "source_type", path)
        url = require_text(row, "url", path)
        if not is_http_url(url):
            raise ValueError(f"{path}.url must be HTTP(S)")
        published = parse_optional_timestamp(row.get("published_at"), f"{path}.published_at")
        normalized.append(
            {
                "source_id": source_id,
                "name": name,
                "source_type": source_type,
                "url": url,
                "published_at": published.isoformat() if published else None,
            }
        )
    return normalized


def normalize_event(
    event: dict[str, Any], index: int, window_start: dt.datetime, window_end: dt.datetime
) -> dict[str, Any]:
    path = f"report.items[{index}]"
    require_known_keys(event, EVENT_KEYS, path)
    event_id = require_text(event, "event_id", path)
    if re.search(r"\s", event_id):
        raise ValueError(f"{path}.event_id must not contain whitespace")
    localized = event.get("localized")
    if not isinstance(localized, dict) or set(localized) != set(LOCALES):
        raise ValueError(f"{path}.localized must contain exactly en and zh-CN; locale fallback is forbidden")
    clean_localized: dict[str, dict[str, str]] = {}
    for locale in LOCALES:
        values = localized.get(locale)
        if not isinstance(values, dict):
            raise ValueError(f"{path}.localized.{locale} must be an object")
        require_known_keys(values, LOCALIZED_KEYS, f"{path}.localized.{locale}")
        clean_localized[locale] = {
            "title": require_text(values, "title", f"{path}.localized.{locale}"),
            "summary": require_text(values, "summary", f"{path}.localized.{locale}"),
            "why_it_matters": require_text(values, "why_it_matters", f"{path}.localized.{locale}"),
        }
    published = parse_optional_timestamp(event.get("published_at"), f"{path}.published_at")
    if published is not None:
        published_utc = published.astimezone(dt.UTC)
        if not window_start.astimezone(dt.UTC) <= published_utc <= window_end.astimezone(dt.UTC):
            raise ValueError(f"{path}.published_at falls outside the declared 14-day evidence window")
    taxonomy = event.get("taxonomy")
    if not isinstance(taxonomy, dict):
        raise ValueError(f"{path}.taxonomy must be an object")
    require_known_keys(taxonomy, TAXONOMY_KEYS, f"{path}.taxonomy")
    programs = require_string_list(taxonomy, "programs", f"{path}.taxonomy")
    card_families = require_string_list(taxonomy, "card_families", f"{path}.taxonomy")
    verticals = require_string_list(taxonomy, "verticals", f"{path}.taxonomy")
    signals = require_string_list(taxonomy, "ecosystem_signal_types", f"{path}.taxonomy")
    stakeholders = require_string_list(taxonomy, "stakeholders", f"{path}.taxonomy")
    topic_type = require_string(taxonomy, "topic_type", f"{path}.taxonomy")
    consumer_impact = require_string(taxonomy, "consumer_impact", f"{path}.taxonomy")
    impact_horizon = require_string(taxonomy, "impact_horizon", f"{path}.taxonomy")
    metrics = require_string_list(event, "metric_snippets", path)
    future_dates = require_string_list(event, "future_event_dates", path, unique=True)
    confidence = require_string(event, "confidence_label", path)
    risk = require_string(event, "risk_label", path)
    action = require_string(event, "action_label", path)
    declared_lane = require_text(event, "lane", path)
    if declared_lane not in {"c-end", "ecosystem"}:
        raise ValueError(f"{path}.lane must be c-end or ecosystem")
    member_first_topics = {
        "bug",
        "clawback",
        "offer",
        "transfer_bonus",
        "portal_stack",
        "statement_credit",
        "status_match",
        "lounge",
    }
    inferred_lane = (
        "ecosystem"
        if topic_type == "industry_signal" or (signals and topic_type not in member_first_topics)
        else "c-end"
    )
    if declared_lane != inferred_lane:
        raise ValueError(
            f"{path}.lane {declared_lane!r} conflicts with its audited taxonomy ({inferred_lane!r})"
        )
    priority = require_text(event, "priority", path)
    if priority not in {"P0", "P1", "P2", "P3", "P4"}:
        raise ValueError(f"{path}.priority must be P0, P1, P2, P3, or P4")
    return {
        "event_id": event_id,
        "lane": declared_lane,
        "priority": priority,
        "published_at": published.isoformat() if published else None,
        "sources": normalize_source_rows(event, path),
        "programs": programs,
        "card_families": card_families,
        "vertical": verticals or ["loyalty"],
        "topic_type": topic_type,
        "ecosystem_signal_type": signals,
        "stakeholders": stakeholders,
        "consumer_impact": consumer_impact,
        "impact_horizon": impact_horizon,
        "action_label": action,
        "risk_label": risk,
        "confidence_label": confidence,
        "metric_snippets": metrics,
        "future_event_dates": future_dates,
        "localized": clean_localized,
    }


def validate_health(value: Any, path: str, event_count: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    require_known_keys(value, HEALTH_KEYS | HEALTH_OPTIONAL_KEYS, path)
    missing = sorted(HEALTH_KEYS - set(value))
    if missing:
        raise ValueError(f"{path}: missing field(s): {', '.join(missing)}")
    integer_keys = (HEALTH_KEYS | HEALTH_OPTIONAL_KEYS) - {
        "script_ok_rate",
        "p0_ok_rate",
        "duplicate_rate",
        "status_counts",
    }
    clean: dict[str, Any] = {}
    for key in integer_keys:
        number = value.get(key, 0)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ValueError(f"{path}.{key} must be a non-negative integer")
        clean[key] = number
    if clean["top_events_checked"] > 20:
        raise ValueError(f"{path}.top_events_checked must not exceed 20")
    for key in ("script_ok_rate", "p0_ok_rate", "duplicate_rate"):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1:
            raise ValueError(f"{path}.{key} must be a number from 0 through 1")
        clean[key] = float(number)
    status_counts = value["status_counts"]
    if not isinstance(status_counts, dict) or not all(
        isinstance(key, str)
        and isinstance(number, int)
        and not isinstance(number, bool)
        and number >= 0
        for key, number in status_counts.items()
    ):
        raise ValueError(f"{path}.status_counts must map status strings to non-negative integers")
    clean["status_counts"] = dict(sorted(status_counts.items()))
    if clean["events_checked"] != event_count:
        raise ValueError(f"{path}.events_checked must match publication.event_count")
    if clean["top_events_checked"] != min(20, event_count):
        raise ValueError(f"{path}.top_events_checked must match the audited top-event count")
    return clean


def load_public_report(path: Path, report_id: str) -> PublicReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: unreadable public report: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: public report must be a JSON object")
    check_public_value(payload, path.name)
    require_known_keys(payload, TOP_LEVEL_KEYS, path.name)
    if set(payload) != TOP_LEVEL_KEYS:
        missing = sorted(TOP_LEVEL_KEYS - set(payload))
        raise ValueError(f"{path}: missing top-level field(s): {', '.join(missing)}")
    if payload.get("schema_id") != SCHEMA_ID:
        raise ValueError(f"{path}: schema_id must be {SCHEMA_ID!r}")
    if not ISO_WEEK_RE.fullmatch(report_id):
        raise ValueError(f"{path}: report week must be an ISO week such as 2026-W30")
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        raise ValueError(f"{path}: publication must be an object")
    require_known_keys(publication, PUBLICATION_KEYS, f"{path.name}.publication")
    missing_publication = sorted(PUBLICATION_KEYS - set(publication))
    if missing_publication:
        raise ValueError(f"{path.name}.publication: missing field(s): {', '.join(missing_publication)}")
    if publication.get("policy") != "public":
        raise ValueError(f"{path}: publication.policy must be 'public'")
    product = publication.get("product")
    if not isinstance(product, dict):
        raise ValueError(f"{path}: publication.product must be an object")
    require_known_keys(product, PRODUCT_KEYS, f"{path.name}.publication.product")
    if set(product) != PRODUCT_KEYS or product.get("name") != "Loyalty Radar" or not isinstance(product.get("version"), str):
        raise ValueError(f"{path}: publication.product must identify Loyalty Radar and include a string version")
    for key in ("mode", "focus", "timezone"):
        require_string(publication, key, f"{path.name}.publication")
    generated = parse_timestamp(publication.get("generated_at"), f"{path.name}.publication.generated_at")
    audited = parse_timestamp(publication.get("audited_at"), f"{path.name}.publication.audited_at")
    hours = publication.get("hours")
    if isinstance(hours, bool) or not isinstance(hours, int) or hours != 336:
        raise ValueError(f"{path}: publication.hours must be exactly 336")
    future_days = publication.get("future_watch_days")
    if isinstance(future_days, bool) or not isinstance(future_days, int):
        raise ValueError(f"{path}: publication.future_watch_days must be an integer")
    if future_days != 60:
        raise ValueError(f"{path}: publication.future_watch_days must be 60")
    require_string_list(publication, "source_packs", f"{path.name}.publication", unique=True)
    if publication.get("locales") != list(LOCALES):
        raise ValueError(f"{path}: publication.locales must be exactly ['en', 'zh-CN']")
    event_count = publication.get("event_count")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0:
        raise ValueError(f"{path}: publication.event_count must be a non-negative integer")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: items must be a list")
    if len(rows) != event_count:
        raise ValueError(f"{path}: publication.event_count must match the items array")
    window_end = generated
    window_start = generated - dt.timedelta(hours=hours)
    events = [normalize_event(row, index, window_start, window_end) for index, row in enumerate(rows) if isinstance(row, dict)]
    if len(events) != len(rows):
        raise ValueError(f"{path}: every item must be an object")
    event_ids = [event["event_id"] for event in events]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError(f"{path}: duplicate event_id values")
    clean_health = validate_health(payload.get("health"), f"{path.name}.health", event_count)
    return PublicReport(
        report_id,
        generated,
        audited,
        window_start,
        window_end,
        hours,
        future_days,
        clean_health,
        events,
    )


def load_public_reports(reports_root: Path) -> list[PublicReport]:
    if not reports_root.exists():
        return []
    if not reports_root.is_dir():
        raise ValueError(f"{reports_root}: reports root must be a directory")
    reports: list[PublicReport] = []
    for path in sorted(reports_root.glob("*/report.json")):
        report_id = path.parent.name
        reports.append(load_public_report(path, report_id))
    return sorted(reports, key=lambda report: report.generated_at, reverse=True)


def label(locale: str, category: str, value: str, localized: dict[str, str], override_key: str) -> str:
    override = str(localized.get(override_key) or "").strip()
    if override:
        return override
    if not value:
        return "—"
    pair = LABELS.get(category, {}).get(value)
    if pair is None:
        raise ValueError(f"Unknown {category} label {value!r}; update the public-site label catalog")
    return pair[0 if locale == "en" else 1]


def labels(locale: str, category: str, values: Iterable[str], localized: dict[str, str], override_key: str) -> str:
    override = str(localized.get(override_key) or "").strip()
    if override:
        return override
    rendered = [label(locale, category, value, {}, "") for value in values if value]
    return " / ".join(rendered) if rendered else "—"


def format_time(value: dt.datetime | str, locale: str) -> str:
    parsed = value if isinstance(value, dt.datetime) else parse_timestamp(value, "display timestamp")
    if locale == "zh-CN":
        return parsed.strftime("%Y-%m-%d %H:%M %Z").strip()
    return parsed.strftime("%d %b %Y, %H:%M %Z").strip()


def format_window(report: PublicReport, locale: str) -> str:
    if locale == "zh-CN":
        return f"{report.window_start:%Y-%m-%d} 至 {report.window_end:%Y-%m-%d}（14 天）"
    return f"{report.window_start:%d %b %Y} – {report.window_end:%d %b %Y} (14 days)"


def relative_prefix(path: Path, site: Path) -> str:
    depth = len(path.relative_to(site).parents) - 1
    return "../" * depth


def language_links(prefix: str, current: str, suffix: str = "") -> str:
    en_href = f"{prefix}en/{suffix}"
    zh_href = f"{prefix}zh-CN/{suffix}"
    return (
        '<nav class="language-switch" aria-label="Language / 语言">'
        f'<a class="{"current" if current == "en" else ""}" href="{esc(en_href)}" hreflang="en">English</a>'
        f'<a class="{"current" if current == "zh-CN" else ""}" href="{esc(zh_href)}" hreflang="zh-CN">简体中文</a>'
        "</nav>"
    )


def page_shell(locale: str, title: str, description: str, body: str, prefix: str, language_html: str) -> str:
    text = TEXT[locale]
    home = f"{prefix}{locale}/"
    sources = f"{prefix}{locale}/sources/"
    return f"""<!doctype html>
<html lang="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(description)}">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}">
<meta property="og:image" content="{esc(prefix)}assets/social-preview.png"><link rel="icon" type="image/png" href="{esc(prefix)}assets/icon-128.png">
<link rel="stylesheet" href="{esc(prefix)}assets/site.css"></head><body data-page-locale="{locale}">
<a class="skip-link" href="#content">{esc(text['skip'])}</a>
<header class="site-header"><a class="brand" href="{esc(home)}">Loyalty Radar</a><nav class="primary-nav" aria-label="{esc(text['primary_nav'])}"><a href="{esc(home)}">{esc(text['nav_latest'])}</a><a href="{esc(home)}#archive">{esc(text['nav_archive'])}</a><a href="{esc(sources)}">{esc(text['nav_sources'])}</a><a href="https://github.com/lonelydoctor/loyalty-radar">{esc(text['nav_github'])}</a></nav>{language_html}</header>
{body}
<footer class="site-footer"><p>{esc(text['footer'])}</p><a href="https://github.com/lonelydoctor/loyalty-radar">github.com/lonelydoctor/loyalty-radar</a></footer>
</body></html>"""


def ctas(locale: str, prefix: str) -> str:
    text = TEXT[locale]
    return (
        '<div class="cta-row" data-layout-check>'
        f'<a class="button primary" href="https://github.com/lonelydoctor/loyalty-radar#30-second-quick-start">{esc(text["install"])}</a>'
        f'<a class="button secondary" href="{esc(prefix)}{locale}/sources/">{esc(text["browse_sources"])}</a>'
        f'<a class="text-link" href="https://github.com/lonelydoctor/loyalty-radar">{esc(text["github"])}</a>'
        "</div>"
    )


def empty_report(locale: str, prefix: str) -> str:
    text = TEXT[locale]
    return f"""<main id="content" class="report-page" data-report-state="empty" data-report-contract="{SCHEMA_ID}">
<section class="report-hero" data-layout-check><div class="hero-copy"><p class="eyebrow">{esc(text['eyebrow'])}</p><h1>{esc(text['title'])}</h1><p class="hero-subtitle" data-critical-text>{esc(text['subtitle'])}</p></div><aside class="edition-mark" aria-label="{esc(text['public_beta'])}"><span>{esc(text['public_beta'])}</span><strong>v0.1.2</strong><small>{esc(text['report_archive_mark'])}</small></aside></section>
<section class="empty-report" data-layout-check><p class="section-number">{esc(text['awaiting_review'])}</p><h2 data-critical-text>{esc(text['empty_title'])}</h2><p>{esc(text['empty_body'])}</p>{ctas(locale, prefix)}</section>
<section class="archive-section" id="archive" data-layout-check><div class="section-heading"><p class="eyebrow">{esc(text['archive_eyebrow'])}</p><h2>{esc(text['archive'])}</h2></div><p class="archive-empty">{esc(text['archive_empty'])}</p></section>
</main>"""


def health_metrics(report: PublicReport, locale: str) -> str:
    text = TEXT[locale]
    health = report.collection_health
    eligible = health["script_eligible_sources"]
    successful = health["script_ok_sources"]
    p0_total = health["p0_script_sources"]
    p0_ok = health["p0_ok_sources"]
    metrics = (
        ("configured_sources", "configured", health["configured_sources"]),
        ("script_eligible_sources", "eligible", eligible),
        ("script_ok_sources", "script_ok", f"{successful} / {eligible}"),
        ("script_ok_rate", "success_rate", f"{health['script_ok_rate']:.1%}"),
        ("fallback_sources", "fallbacks", health.get("fallback_sources", 0)),
        ("p0_ok_sources", "p0_ok", f"{p0_ok} / {p0_total}"),
        ("events_checked", "events_checked", health["events_checked"]),
        ("duplicate_events", "duplicates", health["duplicate_events"]),
        ("duplicate_rate", "duplicate_rate", f"{health['duplicate_rate']:.1%}"),
    )
    rows = "".join(
        f'<div class="health-metric" data-health="{esc(key)}"><strong>{esc(value)}</strong><span>{esc(text[label_key])}</span></div>'
        for key, label_key, value in metrics
    )
    return f'<section class="health-band" aria-labelledby="health-title" data-layout-check><div class="section-heading compact"><p class="eyebrow">{esc(text["health_eyebrow"])}</p><h2 id="health-title">{esc(text["collection"])}</h2></div><div class="health-grid">{rows}</div></section>'


def event_card(event: dict[str, Any], locale: str, index: int) -> str:
    text = TEXT[locale]
    localized = event["localized"][locale]
    action = label(locale, "action", event["action_label"], localized, "action_label")
    risk = label(locale, "risk", event["risk_label"], localized, "risk_label")
    confidence = label(locale, "confidence", event["confidence_label"], localized, "confidence_label")
    vertical = labels(locale, "vertical", event["vertical"], localized, "vertical_label")
    topic = label(locale, "topic", event["topic_type"], localized, "topic_label")
    signal = labels(locale, "signal", event["ecosystem_signal_type"], localized, "signal_label")
    impact = label(locale, "consumer_impact", event["consumer_impact"], localized, "consumer_impact")
    programs = " / ".join(event["programs"] + event["card_families"]) or "—"
    sources = "".join(
        '<li>'
        + f'<a class="source-reference" href="{esc(source["url"])}" target="_blank" rel="noreferrer">{esc(source["name"])}</a>'
        + (
            f'<time datetime="{esc(source["published_at"])}">{esc(format_time(source["published_at"], locale))}</time>'
            if source["published_at"]
            else f'<span class="source-time-missing">{esc(text["unknown_time"])}</span>'
        )
        + "</li>"
        for source in event["sources"]
    )
    metrics = ""
    if event["metric_snippets"]:
        metrics = f'<div class="event-extra"><dt>{esc(text["metrics"])}</dt><dd>{esc(" / ".join(event["metric_snippets"]))}</dd></div>'
    future = ""
    if event["future_event_dates"]:
        future = f'<div class="event-extra"><dt>{esc(text["future_dates"])}</dt><dd>{esc(" / ".join(event["future_event_dates"]))}</dd></div>'
    return f"""<article class="event" data-event-id="{esc(event['event_id'])}" data-event-locale="{locale}" data-layout-check>
<div class="event-sequence">{index:02d}</div><div class="event-content"><div class="badges"><span class="badge priority">{esc(event['priority'])}</span><span class="badge action">{esc(action)}</span><span class="badge risk">{esc(risk)}</span><span class="badge confidence">{esc(confidence)}</span></div>
<h3 class="event-title" data-critical-text>{esc(localized['title'])}</h3><p class="event-summary">{esc(localized['summary'])}</p>
<div class="why"><span>{esc(text['why'])}</span><p>{esc(localized['why_it_matters'])}</p></div>
<dl class="event-facts"><div><dt>{esc(text['vertical'])}</dt><dd>{esc(vertical)}</dd></div><div><dt>{esc(text['topic'])}</dt><dd>{esc(topic)}</dd></div><div><dt>{esc(text['signal'])}</dt><dd>{esc(signal)}</dd></div><div><dt>{esc(text['consumer_impact'])}</dt><dd>{esc(impact)}</dd></div><div><dt>{esc(text['programs_label'])}</dt><dd>{esc(programs)}</dd></div>{metrics}{future}</dl>
<div class="source-block"><span class="source-label">{esc(text['source'])}</span><ol>{sources}</ol></div></div></article>"""


def lane(report: PublicReport, locale: str, lane_id: str) -> str:
    text = TEXT[locale]
    rows = [event for event in report.events if event["lane"] == lane_id]
    title_key = "c_end" if lane_id == "c-end" else "ecosystem"
    description_key = "c_end_desc" if lane_id == "c-end" else "ecosystem_desc"
    content = "".join(event_card(event, locale, index) for index, event in enumerate(rows, 1))
    if not content:
        content = f'<p class="lane-empty">{esc(text["no_lane"])}</p>'
    return f'<section class="lane lane-{esc(lane_id)}" aria-labelledby="lane-{esc(lane_id)}"><div class="lane-heading"><span>{len(rows):02d}</span><div><h2 id="lane-{esc(lane_id)}">{esc(text[title_key])}</h2><p>{esc(text[description_key])}</p></div></div>{content}</section>'


def archive(report_rows: list[PublicReport], locale: str, prefix: str, current_id: str = "") -> str:
    text = TEXT[locale]
    if not report_rows:
        body = f'<p class="archive-empty">{esc(text["archive_empty"])}</p>'
    else:
        body = '<ol class="archive-list">' + "".join(
            f'<li class="{"current" if report.report_id == current_id else ""}"><a href="{esc(prefix)}{locale}/reports/{esc(report.report_id)}/"><span>{esc(format_time(report.generated_at, locale))}</span><strong>{esc(format_window(report, locale))}</strong><small>{esc(text["event_count"].format(count=len(report.events)))}</small></a></li>'
            for report in report_rows
        ) + "</ol>"
    return f'<section class="archive-section" id="archive" data-layout-check><div class="section-heading"><p class="eyebrow">{esc(text["archive_eyebrow"])}</p><h2>{esc(text["archive"])}</h2></div>{body}</section>'


def report_body(report: PublicReport, reports: list[PublicReport], locale: str, prefix: str, include_archive: bool) -> str:
    text = TEXT[locale]
    archive_html = archive(reports, locale, prefix, report.report_id) if include_archive else ""
    return f"""<main id="content" class="report-page" data-report-state="published" data-report-contract="{SCHEMA_ID}" data-report-id="{esc(report.report_id)}" data-window-hours="{report.hours}" data-future-days="{report.future_watch_days}">
<section class="report-hero published" data-layout-check><div class="hero-copy"><p class="eyebrow">{esc(text['latest'])}</p><h1>{esc(text['title'])}</h1><p class="hero-subtitle" data-critical-text>{esc(text['subtitle'])}</p>{ctas(locale, prefix)}</div><dl class="report-meta"><div><dt>{esc(text['generated'])}</dt><dd><time datetime="{esc(report.generated_at.isoformat())}">{esc(format_time(report.generated_at, locale))}</time></dd></div><div><dt>{esc(text['audited'])}</dt><dd><time datetime="{esc(report.audited_at.isoformat())}">{esc(format_time(report.audited_at, locale))}</time></dd></div><div><dt>{esc(text['window'])}</dt><dd>{esc(format_window(report, locale))}</dd></div><div><dt>{esc(text['future'])}</dt><dd>{esc(text['future_value'].format(days=report.future_watch_days))}</dd></div></dl></section>
{health_metrics(report, locale)}<section class="lane-grid" data-layout-check>{lane(report, locale, 'c-end')}{lane(report, locale, 'ecosystem')}</section>{archive_html}</main>"""


def report_page(report: PublicReport, reports: list[PublicReport], locale: str, site: Path) -> tuple[Path, str]:
    path = site / locale / "reports" / report.report_id / "index.html"
    prefix = relative_prefix(path, site)
    language = language_links(prefix, locale, f"reports/{report.report_id}/")
    body = report_body(report, reports, locale, prefix, include_archive=False)
    title = f"{TEXT[locale]['latest']} · Loyalty Radar"
    return path, page_shell(locale, title, TEXT[locale]["description"], body, prefix, language)


def landing_page(locale: str, reports: list[PublicReport], site: Path, *, root_alias: bool = False) -> tuple[Path, str]:
    path = site / "index.html" if root_alias else site / locale / "index.html"
    prefix = relative_prefix(path, site)
    language = language_links(prefix, locale)
    if reports:
        body = report_body(reports[0], reports, locale, prefix, include_archive=True)
    else:
        body = empty_report(locale, prefix)
    return path, page_shell(locale, "Loyalty Radar · Public reports", TEXT[locale]["description"], body, prefix, language)


def latest_page(locale: str, reports: list[PublicReport], site: Path) -> tuple[Path, str]:
    path = site / locale / "latest" / "index.html"
    prefix = relative_prefix(path, site)
    language = language_links(prefix, locale, "latest/")
    body = report_body(reports[0], reports, locale, prefix, include_archive=False) if reports else empty_report(locale, prefix)
    return path, page_shell(locale, f"{TEXT[locale]['latest']} · Loyalty Radar", TEXT[locale]["description"], body, prefix, language)


def source_card(source: dict[str, Any], locale: str) -> str:
    text = TEXT[locale]
    enabled = bool(source.get("enabled", True))
    programs = " / ".join(str(value) for value in source.get("programs", [])[:8]) or "—"
    method = METHODS.get(str(source.get("fetch_method")), (str(source.get("fetch_method")),) * 2)[0 if locale == "en" else 1]
    facts = (
        (text["pack"], source.get("pack_id")),
        (text["priority"], source.get("priority")),
        (text["method"], method),
        (text["fallback"], source.get("fallback_provider") or "—"),
        (text["region"], source.get("region")),
        (text["programs"], programs),
        (text["status"], text["enabled"] if enabled else text["disabled"]),
    )
    fact_html = "".join(f"<div><dt>{esc(key)}</dt><dd>{esc(value)}</dd></div>" for key, value in facts)
    search = " ".join(str(value) for value in (source.get("name"), source.get("site"), source.get("pack_id"), source.get("region"), source.get("language"), programs)).lower()
    return f"""<article class="source-card" data-search="{esc(search)}" data-pack="{esc(source.get('pack_id'))}" data-method="{esc(source.get('fetch_method'))}" data-priority="{esc(source.get('priority'))}" data-layout-check>
<div class="source-card-head"><span>{esc(source.get('priority'))}</span><small>{esc(source.get('language'))}</small></div><h2>{esc(source.get('name'))}</h2><p>{esc(source.get('site'))}</p><dl>{fact_html}</dl><a href="{esc(source.get('url'))}" target="_blank" rel="noreferrer">{esc(text['open_source'])}</a></article>"""


def catalog_body(locale: str, packs: list[Pack], sources: list[dict[str, Any]], prefix: str) -> str:
    text = TEXT[locale]
    script_count = sum(source.get("fetch_method") != "browser_only" and bool(source.get("enabled", True)) for source in sources)
    browser_count = sum(source.get("fetch_method") == "browser_only" for source in sources)
    pack_buttons = "".join(f'<button type="button" data-pack-button="{esc(pack.pack_id)}"><strong>{esc(pack.pack_id)}</strong><span>{pack.count}</span></button>' for pack in packs)
    pack_options = "".join(f'<option value="{esc(pack.pack_id)}">{esc(pack.pack_id)} ({pack.count})</option>' for pack in packs)
    method_options = "".join(f'<option value="{esc(method)}">{esc(pair[0 if locale == "en" else 1])}</option>' for method, pair in METHODS.items())
    cards = "".join(source_card(source, locale) for source in sources)
    return f"""<main id="content" class="catalog-page" data-catalog-count="{len(sources)}">
<section class="catalog-hero" data-layout-check><p class="eyebrow">{esc(text['catalog_eyebrow'])}</p><h1>{esc(text['catalog_title'])}</h1><p class="hero-subtitle" data-critical-text>{esc(text['catalog_subtitle'])}</p><p class="catalog-notice">{esc(text['catalog_notice'])}</p></section>
<section class="catalog-metrics" data-layout-check><div><strong>{len(sources)}</strong><span>{esc(text['configured_sources'])}</span></div><div><strong>{len(packs)}</strong><span>{esc(text['source_packs'])}</span></div><div><strong>{script_count}</strong><span>{esc(text['script_collectors'])}</span></div><div><strong>{browser_count}</strong><span>{esc(text['browser_assisted'])}</span></div></section>
<section class="catalog-content"><div class="pack-strip" data-layout-check>{pack_buttons}</div><div class="catalog-controls" data-layout-check><label><span>{esc(text['search'])}</span><input id="source-search" type="search" placeholder="{esc(text['search'])}"></label><label><span>{esc(text['pack'])}</span><select id="source-pack"><option value="all">{esc(text['all'])}</option>{pack_options}</select></label><label><span>{esc(text['method'])}</span><select id="source-method"><option value="all">{esc(text['all'])}</option>{method_options}</select></label><label><span>{esc(text['priority'])}</span><select id="source-priority"><option value="all">{esc(text['all'])}</option><option>P0</option><option>P1</option><option>P2</option></select></label></div>
<div class="catalog-count"><strong id="visible-source-count">{len(sources)}</strong> / {len(sources)}</div><div class="source-grid">{cards}</div><p class="catalog-empty" id="catalog-empty">{esc(text['no_results'])}</p></section>
<script src="{esc(prefix)}assets/catalog.js" defer></script></main>"""


def catalog_page(locale: str, packs: list[Pack], sources: list[dict[str, Any]], site: Path, path: Path) -> tuple[Path, str]:
    prefix = relative_prefix(path, site)
    language = language_links(prefix, locale, "sources/")
    body = catalog_body(locale, packs, sources, prefix)
    title = f"{TEXT[locale]['catalog_title']} · Loyalty Radar"
    return path, page_shell(locale, title, TEXT[locale]["catalog_subtitle"], body, prefix, language)


SITE_CSS = r"""
:root{--ink:#18222b;--muted:#64717a;--paper:#f5f6f4;--surface:#fff;--line:#cfd5d2;--blue:#1557a6;--blue-soft:#e8f0fa;--green:#176c57;--green-soft:#e6f3ee;--amber:#8a5a08;--amber-soft:#fff4d9;--red:#a23b36;--red-soft:#fbeceb;--max:2200px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;letter-spacing:0;line-height:1.55}a{color:inherit}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #4f8bd6;outline-offset:3px}.skip-link{position:absolute;left:-9999px;top:8px;background:#fff;padding:8px;z-index:100}.skip-link:focus{left:8px}.site-header{min-height:68px;padding:0 max(24px,4vw);display:grid;grid-template-columns:auto 1fr auto;gap:28px;align-items:center;border-bottom:1px solid var(--line);background:rgba(245,246,244,.97);position:sticky;top:0;z-index:30}.brand{font-size:17px;font-weight:900;text-decoration:none}.primary-nav{display:flex;justify-content:center;gap:26px;font-size:13px;font-weight:700}.primary-nav a,.language-switch a{text-decoration:none;border-bottom:2px solid transparent;padding:6px 0}.primary-nav a:hover,.language-switch a:hover,.language-switch a.current{color:var(--blue);border-color:var(--blue)}.language-switch{display:flex;gap:13px;font-size:12px;white-space:normal}.report-page,.catalog-page{width:min(var(--max),100%);margin:0 auto}.report-hero,.catalog-hero{background:var(--surface);padding:62px max(24px,4vw) 54px;border-bottom:1px solid var(--line)}.report-hero{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,.7fr);gap:60px;align-items:end}.report-hero:not(.published){grid-template-columns:minmax(0,1fr) auto}.eyebrow{margin:0 0 10px;color:var(--blue);font-size:12px;font-weight:900;text-transform:uppercase}.report-hero h1,.catalog-hero h1{font-size:58px;line-height:1.08;margin:0 0 16px;letter-spacing:0;overflow-wrap:anywhere}.hero-subtitle{max-width:860px;font-size:20px;line-height:1.55;color:#44515b;margin:0}.edition-mark{border-left:5px solid var(--ink);padding:12px 0 12px 20px;min-width:210px}.edition-mark span,.edition-mark small,.edition-mark strong{display:block}.edition-mark span{color:var(--blue);font-size:12px;font-weight:900}.edition-mark strong{font-size:34px;margin:4px 0}.edition-mark small{color:var(--muted)}.report-meta{margin:0;border-top:3px solid var(--ink)}.report-meta div{display:grid;grid-template-columns:120px 1fr;gap:14px;padding:12px 0;border-bottom:1px solid var(--line)}.report-meta dt{font-size:11px;text-transform:uppercase;color:var(--muted);font-weight:800}.report-meta dd{margin:0;font-size:13px;font-weight:700;overflow-wrap:anywhere}.cta-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:28px}.button{min-height:44px;padding:10px 15px;border:1px solid var(--ink);text-decoration:none;font-size:13px;font-weight:800;display:inline-flex;align-items:center;justify-content:center}.button.primary{background:var(--ink);color:#fff}.button.secondary{background:#fff}.text-link{font-size:13px;font-weight:800;color:var(--blue);padding:10px}.empty-report{margin:44px max(24px,4vw) 72px;padding:40px 0;border-top:4px solid var(--ink);border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(160px,.45fr) minmax(0,1.45fr);column-gap:50px}.empty-report .section-number{grid-row:1/4;color:var(--blue);font-size:12px;font-weight:900;text-transform:uppercase}.empty-report h2{font-size:36px;line-height:1.22;margin:0 0 12px;overflow-wrap:anywhere}.empty-report>p:not(.section-number){max-width:760px;color:var(--muted);font-size:17px;margin:0}.health-band{padding:34px max(24px,4vw);background:#edf1f0;border-bottom:1px solid var(--line)}.section-heading{border-top:3px solid var(--ink);padding-top:12px;margin-bottom:18px}.section-heading.compact{display:flex;align-items:baseline;gap:18px}.section-heading h2{font-size:28px;margin:0;overflow-wrap:anywhere}.health-grid{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));border-top:1px solid var(--line);border-left:1px solid var(--line);background:var(--surface)}.health-metric{min-height:104px;padding:16px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.health-metric strong,.health-metric span{display:block}.health-metric strong{font-size:28px}.health-metric span{font-size:11px;color:var(--muted);margin-top:6px}.lane-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;padding:50px max(24px,4vw) 60px}.lane{min-width:0}.lane:first-child{padding-right:30px;border-right:1px solid var(--line)}.lane:last-child{padding-left:30px}.lane-heading{display:grid;grid-template-columns:52px 1fr;gap:14px;border-top:4px solid var(--ink);padding:14px 0 24px}.lane-heading>span{color:var(--blue);font-weight:900}.lane-heading h2{font-size:28px;line-height:1.2;margin:0;overflow-wrap:anywhere}.lane-heading p{margin:7px 0 0;color:var(--muted);font-size:14px;max-width:62ch}.lane-empty{padding:25px 0;border-top:1px solid var(--line);color:var(--muted)}.event{display:grid;grid-template-columns:44px minmax(0,1fr);gap:14px;padding:24px 0 30px;border-top:1px solid var(--line);min-width:0}.event-sequence{font-size:12px;font-weight:900;color:var(--blue);padding-top:5px}.event-content{min-width:0}.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}.badge{border:1px solid var(--line);padding:3px 7px;font-size:10px;font-weight:800;background:#fff;overflow-wrap:anywhere}.badge.priority{border-color:#7d9cc3;background:var(--blue-soft);color:#16497f}.badge.action{border-color:#82af9f;background:var(--green-soft);color:var(--green)}.badge.risk{border-color:#d5aa70;background:var(--amber-soft);color:var(--amber)}.badge.confidence{color:#44515b}.event-title{font-size:24px;line-height:1.3;margin:0;overflow-wrap:anywhere;word-break:normal;white-space:normal}.event-summary{font-size:15px;line-height:1.7;margin:11px 0;color:#3f4b55;overflow-wrap:anywhere}.why{border-left:3px solid var(--blue);padding:2px 0 2px 12px;margin:15px 0}.why span{font-size:10px;text-transform:uppercase;color:var(--blue);font-weight:900}.why p{margin:3px 0 0;font-size:13px;line-height:1.65}.event-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:18px 0 0;border-top:1px solid var(--line);border-left:1px solid var(--line)}.event-facts>div{padding:9px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-width:0}.event-facts dt{font-size:9px;text-transform:uppercase;color:var(--muted);font-weight:800}.event-facts dd{font-size:11px;margin:3px 0 0;overflow-wrap:anywhere}.source-block{margin-top:17px}.source-label{font-size:10px;text-transform:uppercase;color:var(--muted);font-weight:900}.source-block ol{list-style:none;padding:0;margin:6px 0 0}.source-block li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;padding:7px 0;border-top:1px dotted #b8c0bc;font-size:11px;min-width:0}.source-reference{color:var(--blue);font-weight:800;overflow-wrap:anywhere}.source-block time{color:var(--muted);text-align:right}.archive-section{padding:20px max(24px,4vw) 76px}.archive-empty{color:var(--muted);border-top:1px solid var(--line);padding:20px 0}.archive-list{list-style:none;padding:0;margin:0;border-top:1px solid var(--line)}.archive-list li{border-bottom:1px solid var(--line)}.archive-list li.current{border-left:4px solid var(--blue)}.archive-list a{display:grid;grid-template-columns:1fr 1.3fr auto;gap:20px;padding:16px;text-decoration:none}.archive-list a:hover{background:#fff}.archive-list span,.archive-list small{font-size:12px;color:var(--muted)}.site-footer{padding:26px max(24px,4vw) 42px;border-top:1px solid var(--line);background:#fff;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.site-footer p{margin:0}.site-footer a{color:var(--blue)}
.catalog-hero{padding-bottom:42px}.catalog-hero .catalog-notice{max-width:980px;margin:24px 0 0;padding:14px 16px;border-left:4px solid var(--amber);background:var(--amber-soft);font-size:13px}.catalog-metrics{display:grid;grid-template-columns:repeat(4,1fr);background:#edf1f0;border-bottom:1px solid var(--line)}.catalog-metrics>div{padding:22px max(20px,4vw);border-right:1px solid var(--line)}.catalog-metrics>div:last-child{border-right:0}.catalog-metrics strong,.catalog-metrics span{display:block}.catalog-metrics strong{font-size:30px}.catalog-metrics span{font-size:12px;color:var(--muted)}.catalog-content{padding:36px max(24px,4vw) 70px}.pack-strip{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line);background:#fff}.pack-strip button{min-height:82px;border:0;border-right:1px solid var(--line);background:#fff;text-align:left;padding:14px;color:var(--ink);cursor:pointer}.pack-strip button:last-child{border-right:0}.pack-strip button:hover{background:var(--blue-soft)}.pack-strip strong,.pack-strip span{display:block}.pack-strip strong{font-size:12px}.pack-strip span{font-size:25px;margin-top:4px}.catalog-controls{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:10px;padding:20px 0 12px;position:sticky;top:68px;background:var(--paper);z-index:20}.catalog-controls label span{display:block;font-size:10px;font-weight:800;color:var(--muted);margin-bottom:4px}.catalog-controls input,.catalog-controls select{width:100%;min-height:44px;background:#fff;border:1px solid #aeb8b3;padding:8px 10px;color:var(--ink);font:inherit;font-size:13px}.catalog-count{font-size:12px;color:var(--muted);margin:3px 0 12px}.source-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.source-card{background:#fff;border:1px solid var(--line);padding:17px;display:flex;flex-direction:column;min-width:0}.source-card[hidden]{display:none}.source-card-head{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}.source-card-head span{color:var(--red);font-weight:900}.source-card h2{font-size:18px;line-height:1.32;margin:10px 0 3px;overflow-wrap:anywhere}.source-card>p{font-size:11px;color:var(--muted);margin:0 0 14px}.source-card dl{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--line);border-left:1px solid var(--line);margin:0 0 15px}.source-card dl div{padding:8px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-width:0}.source-card dt{font-size:9px;color:var(--muted)}.source-card dd{font-size:11px;margin:2px 0 0;overflow-wrap:anywhere}.source-card>a{margin-top:auto;color:var(--blue);font-size:12px;font-weight:800}.catalog-empty{display:none;padding:30px;text-align:center;background:#fff;border:1px solid var(--line)}.catalog-empty.visible{display:block}
@media(max-width:1100px){.site-header{grid-template-columns:auto 1fr}.language-switch{grid-column:1/-1;justify-self:end;margin-top:-16px;margin-bottom:8px}.health-grid{grid-template-columns:repeat(4,1fr)}.lane-grid{grid-template-columns:1fr}.lane:first-child{padding-right:0;border-right:0}.lane:last-child{padding-left:0;margin-top:40px}.source-grid{grid-template-columns:1fr 1fr}.pack-strip{grid-template-columns:repeat(3,1fr)}}
@media(max-width:720px){.site-header{position:static;grid-template-columns:1fr auto;padding:13px 18px;gap:12px}.primary-nav{grid-column:1/-1;grid-row:2;justify-content:flex-start;overflow-x:auto;gap:18px;padding-bottom:3px}.language-switch{grid-column:2;grid-row:1;margin:0}.report-hero,.report-hero:not(.published){grid-template-columns:1fr;padding:38px 18px 34px;gap:30px}.report-hero h1,.catalog-hero h1{font-size:40px}.hero-subtitle{font-size:17px}.edition-mark{border-left:0;border-top:4px solid var(--ink);padding:12px 0}.report-meta div{grid-template-columns:105px 1fr}.empty-report{margin:28px 18px 58px;padding:25px 0;grid-template-columns:1fr}.empty-report .section-number{grid-row:auto}.empty-report h2{font-size:29px}.health-band{padding:28px 18px}.health-grid{grid-template-columns:1fr 1fr}.lane-grid{padding:34px 18px 48px}.lane-heading h2{font-size:25px}.event{grid-template-columns:34px minmax(0,1fr)}.event-title{font-size:20px}.event-facts{grid-template-columns:1fr}.source-block li{grid-template-columns:1fr}.source-block time{text-align:left}.archive-section{padding:20px 18px 55px}.archive-list a{grid-template-columns:1fr;gap:3px}.catalog-hero{padding:38px 18px 32px}.catalog-metrics{grid-template-columns:1fr 1fr}.catalog-metrics>div:nth-child(2){border-right:0}.catalog-content{padding:25px 18px 55px}.pack-strip{grid-template-columns:1fr 1fr}.catalog-controls{position:static;grid-template-columns:1fr}.source-grid{grid-template-columns:1fr}.site-footer{padding:25px 18px}}
@media(max-width:720px){.event-title{max-width:100%;overflow-wrap:anywhere;word-break:break-all}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""

CATALOG_JS = r"""
(() => {
  const cards = [...document.querySelectorAll('.source-card')];
  const search = document.querySelector('#source-search');
  const pack = document.querySelector('#source-pack');
  const method = document.querySelector('#source-method');
  const priority = document.querySelector('#source-priority');
  if (!cards.length || !search || !pack || !method || !priority) return;
  const apply = () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      card.hidden = Boolean(
        (query && !card.dataset.search.includes(query)) ||
        (pack.value !== 'all' && card.dataset.pack !== pack.value) ||
        (method.value !== 'all' && card.dataset.method !== method.value) ||
        (priority.value !== 'all' && card.dataset.priority !== priority.value)
      );
      if (!card.hidden) visible += 1;
    });
    document.querySelector('#visible-source-count').textContent = String(visible);
    document.querySelector('#catalog-empty').classList.toggle('visible', visible === 0);
  };
  search.addEventListener('input', apply);
  [pack, method, priority].forEach((control) => control.addEventListener('change', apply));
  document.querySelectorAll('[data-pack-button]').forEach((button) => button.addEventListener('click', () => {
    pack.value = button.dataset.packButton;
    apply();
    document.querySelector('.catalog-controls').scrollIntoView({behavior: 'smooth'});
  }));
  apply();
})();
"""


def chrome_executable() -> str:
    candidates = (
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
    )
    chrome = next((str(value) for value in candidates if value and Path(value).is_file()), None)
    if chrome is None:
        raise ValueError("Chrome or Chromium is required for visual-asset rendering")
    return chrome


def validate_png(path: Path, width: int, height: int) -> None:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise ValueError(f"Invalid PNG: {path}")
    actual = struct.unpack(">II", data[16:24])
    if actual != (width, height) or b"eXIf" in data:
        raise ValueError(
            f"PNG must be {width}x{height} without EXIF; got {actual[0]}x{actual[1]}: {path}"
        )


def capture_page(url: str, path: Path, width: int, height: int) -> None:
    """Capture one deterministic viewport with local Chrome and no external network need."""

    path.parent.mkdir(parents=True, exist_ok=True)
    chrome = chrome_executable()
    with tempfile.TemporaryDirectory(prefix="loyalty-radar-chrome-") as directory:
        command = [
            chrome,
            "--headless=new",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-gpu",
            "--force-device-scale-factor=1",
            "--hide-scrollbars",
            "--metrics-recording-only",
            "--no-first-run",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=1200",
            f"--user-data-dir={Path(directory) / 'profile'}",
            f"--window-size={width},{height}",
            f"--screenshot={path}",
            url,
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=45)
        if result.returncode != 0 or not path.is_file():
            detail = (result.stderr or result.stdout).strip().splitlines()
            message = detail[-1] if detail else str(result.returncode)
            raise ValueError(f"Chrome screenshot failed for {url}: {message}")
    validate_png(path, width, height)


def render_social_preview(path: Path) -> None:
    """Render a factual 1280x640 preview; no report event data is used."""

    document = """<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
*{box-sizing:border-box}html,body{margin:0;width:1280px;height:640px;overflow:hidden}body{font-family:Arial,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif;background:#f3f5f4;color:#18222b;border-top:10px solid #1557a6;display:grid;grid-template-columns:410px 870px;letter-spacing:0}.rail{height:630px;background:#18222b;color:#fff;padding:48px 60px}.radar{width:150px;height:150px;position:relative;margin-bottom:34px}.ring{position:absolute;border:3px solid #7891a3;border-radius:50%;inset:0}.ring.two{inset:24px;border-color:#93a8b6}.ring.three{inset:49px;border-color:#b4c2ca}.beam{position:absolute;width:94px;height:4px;background:#fff;left:75px;top:74px;transform:rotate(-39deg);transform-origin:left center}.dot{position:absolute;width:18px;height:18px;background:#f1b84b;border-radius:50%;right:-1px;top:22px}.center{position:absolute;width:14px;height:14px;background:#fff;border-radius:50%;left:68px;top:68px}.rail h1{font-size:50px;line-height:1.12;margin:0}.version{margin-top:20px;color:#afc0ca;font-size:16px;font-weight:800}.rail hr{border:0;border-top:1px solid #4e5b65;margin:34px 0 20px}.facts{display:grid;gap:8px;font-size:15px;font-weight:800}.content{height:630px;padding:48px 60px}.kicker{color:#1557a6;font-size:18px;font-weight:900}.content h2{font-size:46px;line-height:1.1;margin:17px 0 8px}.deck{font-size:21px;color:#59666f;margin:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:26px 48px;margin-top:47px}.cell{height:120px;border-top:2px solid #cbd2cf;border-left:8px solid var(--accent);padding:13px 20px}.metric{display:block;font-size:36px;font-weight:900;line-height:1}.caption{display:block;margin-top:15px;color:#59666f;font-size:14px;font-weight:800}.formats{border-top:2px solid #cbd2cf;margin-top:28px;padding-top:20px;font-size:18px;font-weight:900}.mit{float:right;color:#1557a6;font-size:13px;margin-top:6px}
</style></head><body><aside class="rail"><div class="radar"><div class="ring"></div><div class="ring two"></div><div class="ring three"></div><div class="beam"></div><div class="dot"></div><div class="center"></div></div><h1>LOYALTY<br>RADAR</h1><div class="version">v0.1.2 · PUBLIC BETA</div><hr><div class="facts"><span>SOURCE-BACKED</span><span>BILINGUAL</span><span>NO TELEMETRY</span></div></aside><main class="content"><div class="kicker">PUBLIC LOYALTY INTELLIGENCE / 公开忠诚计划情报</div><h2>Evidence first.</h2><p class="deck">From public signals to a reviewed, traceable brief.</p><section class="grid"><div class="cell" style="--accent:#1557a6"><span class="metric">59</span><span class="caption">SOURCE CATALOG / 59 个来源</span></div><div class="cell" style="--accent:#176c57"><span class="metric">14</span><span class="caption">DAY EVIDENCE WINDOW / 14 天窗口</span></div><div class="cell" style="--accent:#b64b40"><span class="metric">01</span><span class="caption">MEMBER RADAR / C 端玩法</span></div><div class="cell" style="--accent:#18222b"><span class="metric">02</span><span class="caption">ECOSYSTEM RADAR / 忠诚计划生态</span></div></section><div class="formats">CODEX PLUGIN · AGENT SKILL · PYTHON CLI <span class="mit">MIT</span></div></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="loyalty-radar-social-") as directory:
        temporary = Path(directory)
        page = temporary / "social-preview.html"
        page.write_text(document, encoding="utf-8")
        capture_page(page.as_uri(), path, 1280, 640)


def render_release_assets(pack_dir: Path) -> None:
    """Regenerate release screenshots from real source config and a forced empty report archive."""

    captures = (
        ("overview-en.png", "en/sources/index.html", 2400, 1800),
        ("overview-zh-CN.png", "zh-CN/sources/index.html", 2400, 1800),
        ("report-desktop-en.png", "en/index.html", 1440, 1100),
        ("report-desktop-zh-CN.png", "zh-CN/index.html", 1440, 1100),
        ("report-mobile-en.png", "en/index.html", 390, 1320),
        ("report-mobile-zh-CN.png", "zh-CN/index.html", 390, 1320),
    )
    with tempfile.TemporaryDirectory(prefix="loyalty-radar-release-assets-") as directory:
        temporary = Path(directory)
        site = temporary / "site"
        empty_reports = temporary / "empty-public-briefs"
        empty_reports.mkdir()
        report_count, source_count = build(site, empty_reports, pack_dir)
        if report_count != 0 or source_count != 59:
            raise ValueError("Release screenshots require a truthful empty state and the real 59-source catalog")
        for name, relative_page, width, height in captures:
            capture_page((site / relative_page).as_uri(), ASSET_DIR / name, width, height)

    plugin_assets = ROOT / "plugins" / "loyalty-radar" / "assets"
    plugin_assets.mkdir(parents=True, exist_ok=True)
    pairs = {
        "overview-en.png": "screenshot-overview.png",
        "report-desktop-zh-CN.png": "screenshot-desktop-zh-CN.png",
        "report-mobile-en.png": "screenshot-mobile-en.png",
    }
    for docs_name, plugin_name in pairs.items():
        shutil.copyfile(ASSET_DIR / docs_name, plugin_assets / plugin_name)


def prepare_output(site: Path) -> None:
    site = site.resolve()
    if site == Path(site.anchor) or len(site.parts) < 3:
        raise ValueError(f"Refusing to replace unsafe site path: {site}")
    if site.exists():
        shutil.rmtree(site)
    (site / "assets").mkdir(parents=True)
    (site / ".nojekyll").write_text("", encoding="ascii")
    (site / "assets" / "site.css").write_text(SITE_CSS.strip() + "\n", encoding="utf-8")
    (site / "assets" / "catalog.js").write_text(CATALOG_JS.strip() + "\n", encoding="utf-8")
    for name in ("icon-128.png", "social-preview.png"):
        source = ASSET_DIR / name
        if not source.is_file():
            raise ValueError(f"Missing committed site asset: {source}")
        shutil.copyfile(source, site / "assets" / name)


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(site: Path, report_dir: Path, pack_dir: Path) -> tuple[int, int]:
    packs, sources = load_source_catalog(pack_dir)
    reports = load_public_reports(report_dir)
    prepare_output(site)
    pages: list[tuple[Path, str]] = [landing_page("en", reports, site, root_alias=True)]
    for locale in LOCALES:
        pages.append(landing_page(locale, reports, site))
        pages.append(latest_page(locale, reports, site))
        pages.append(catalog_page(locale, packs, sources, site, site / locale / "sources" / "index.html"))
        for report in reports:
            pages.append(report_page(report, reports, locale, site))
    # /sources/ remains a direct, useful catalog URL while locale-prefixed routes
    # provide symmetrical navigation for the bilingual site.
    pages.append(catalog_page("en", packs, sources, site, site / "sources" / "index.html"))
    for path, content in pages:
        write_page(path, content)
    return len(reports), len(sources)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS_ROOT)
    parser.add_argument("--source-packs", type=Path, default=PACK_DIR)
    parser.add_argument(
        "--render-social-preview",
        type=Path,
        help="Regenerate the factual 1280x640 social preview with local Chrome before building the site.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.render_social_preview:
        render_social_preview(args.render_social_preview.resolve())
        print(f"Rendered factual 1280x640 social preview: {args.render_social_preview}")
    report_count, source_count = build(args.site.resolve(), args.reports.resolve(), args.source_packs.resolve())
    state = f"{report_count} approved report(s)" if report_count else "truthful empty report state"
    print(f"Built bilingual report-first Pages with {state} and {source_count} configured sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
