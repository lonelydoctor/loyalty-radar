"""Public-report allowlisting and publication quality gates."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .clustering import items_represent_same_event
from .engine import IntelItem, extract_metric_snippets, parse_datetime
from .i18n import load_catalog
from .sources import combine_packs

PUBLIC_REPORT_SCHEMA_ID = "loyalty-radar-public-report/v1"
PUBLIC_POLICY = "public"
PUBLIC_LOCALES = ("en", "zh-CN")
SCRIPT_OK_THRESHOLD = 0.70
P0_OK_THRESHOLD = 0.80
DUPLICATE_THRESHOLD = 0.10

_FORBIDDEN_TEXT_PATTERNS = (
    ("mock marker", re.compile(r"\bmock(?:ed|ing)?\b", re.IGNORECASE)),
    ("synthetic marker", re.compile(r"\bsynthetic\b", re.IGNORECASE)),
    ("reserved .invalid host", re.compile(r"\.invalid\b", re.IGNORECASE)),
    ("file URL", re.compile(r"\bfile://", re.IGNORECASE)),
    ("macOS home path", re.compile(r"(?:^|[\s'\"])/" r"Users/[^/\s]+/")),
    ("Linux home path", re.compile(r"(?:^|[\s'\"])/home/[^/\s]+/")),
    ("Windows home path", re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\", re.IGNORECASE)),
    ("macOS private path", re.compile(r"(?:^|[\s'\"])/private/(?:var|tmp)/")),
    ("application container path", re.compile(r"Library/Containers/", re.IGNORECASE)),
)
_FORBIDDEN_OUTPUT_KEYS = {
    "author",
    "authors",
    "cards",
    "cookies",
    "home",
    "original",
    "path",
    "profile",
    "raw",
    "raw_tags",
}
_FAILED_TRANSLATION_VALUES = {
    load_catalog(locale).text("fallback.translation_failed").strip() for locale in PUBLIC_LOCALES
}


class PublicAuditError(ValueError):
    """Raised when a full local report is not safe or complete enough to publish."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = tuple(dict.fromkeys(issues))
        super().__init__("Public audit failed: " + "; ".join(self.issues))


@dataclasses.dataclass(frozen=True)
class _SourceScope:
    configured: tuple[dict[str, Any], ...]
    script_eligible: tuple[dict[str, Any], ...]
    p0_script_eligible: tuple[dict[str, Any], ...]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return list(dict.fromkeys(rows))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _find_forbidden_text(value: Any, location: str = "report") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            issues.extend(_find_forbidden_text(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_find_forbidden_text(child, f"{location}[{index}]"))
    elif isinstance(value, str):
        for label, pattern in _FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(value):
                issues.append(f"{location} contains {label}")
    return issues


def _valid_timestamp(value: Any) -> bool:
    return bool(value and parse_datetime(str(value)) is not None)


def _valid_public_url(value: Any) -> bool:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").casefold()
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and hostname not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
        and not hostname.endswith((".invalid", ".local"))
    )


def _source_scope(payload: dict[str, Any], issues: list[str]) -> _SourceScope:
    pack_ids = _strings(payload.get("source_packs"))
    if not pack_ids:
        issues.append("source_packs is required for public source-health auditing")
        return _SourceScope((), (), ())
    try:
        configured, _packs = combine_packs(pack_ids)
    except (FileNotFoundError, ValueError) as exc:
        issues.append(f"source catalog cannot be resolved: {exc}")
        return _SourceScope((), (), ())

    requested_ids = _strings(payload.get("source_filter"))
    if requested_ids:
        known = {str(source.get("id") or "") for source in configured}
        unknown = sorted(set(requested_ids) - known)
        if unknown:
            issues.append("source_filter contains unknown source IDs: " + ", ".join(unknown))
        requested = set(requested_ids)
        configured = [source for source in configured if source.get("id") in requested]

    source_limit = payload.get("source_limit")
    if source_limit is not None:
        if not isinstance(source_limit, int) or source_limit <= 0:
            issues.append("source_limit must be a positive integer")
        else:
            configured = configured[:source_limit]

    eligible = tuple(
        source
        for source in configured
        if source.get("enabled", True) and source.get("fetch_method") != "browser_only"
    )
    return _SourceScope(
        configured=tuple(configured),
        script_eligible=eligible,
        p0_script_eligible=tuple(source for source in eligible if source.get("priority") == "P0"),
    )


def _health_aggregates(
    payload: dict[str, Any], scope: _SourceScope, issues: list[str]
) -> dict[str, Any]:
    rows = payload.get("health")
    if not isinstance(rows, list):
        issues.append("health must be an array")
        rows = []

    health_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"health[{index}] must be an object")
            continue
        source_id = _text(row.get("source_id"))
        if not source_id:
            issues.append(f"health[{index}] is missing source_id")
            continue
        if source_id in health_by_id:
            issues.append(f"health contains duplicate source_id {source_id}")
            continue
        health_by_id[source_id] = row

    expected_ids = {str(source.get("id")) for source in scope.configured}
    unknown_ids = sorted(set(health_by_id) - expected_ids)
    if unknown_ids:
        issues.append("health contains sources outside the audited scope: " + ", ".join(unknown_ids))

    def status(source: dict[str, Any]) -> str:
        row = health_by_id.get(str(source.get("id")))
        if not row:
            return "missing"
        return _text(row.get("status")) or "missing"

    script_ok = sum(status(source) == "ok" for source in scope.script_eligible)
    script_total = len(scope.script_eligible)
    script_rate = script_ok / script_total if script_total else 0.0
    p0_ok = sum(status(source) == "ok" for source in scope.p0_script_eligible)
    p0_total = len(scope.p0_script_eligible)
    p0_rate = p0_ok / p0_total if p0_total else 0.0
    fallback_sources = sum(
        status(source) == "ok"
        and _text(source.get("fallback_provider")) == "feedly-public"
        and _text(health_by_id.get(str(source.get("id")), {}).get("fallback_provider"))
        == "feedly-public"
        for source in scope.script_eligible
    )
    if script_rate < SCRIPT_OK_THRESHOLD:
        issues.append(
            f"script-eligible source ok rate {script_rate:.1%} is below {SCRIPT_OK_THRESHOLD:.0%}"
        )
    if p0_rate < P0_OK_THRESHOLD:
        issues.append(f"P0 source ok rate {p0_rate:.1%} is below {P0_OK_THRESHOLD:.0%}")

    statuses = Counter(status(source) for source in scope.configured)
    return {
        "configured_sources": len(scope.configured),
        "script_eligible_sources": script_total,
        "script_ok_sources": script_ok,
        "script_ok_rate": round(script_rate, 4),
        "p0_script_sources": p0_total,
        "p0_ok_sources": p0_ok,
        "p0_ok_rate": round(p0_rate, 4),
        "fallback_sources": fallback_sources,
        "status_counts": dict(sorted(statuses.items())),
    }


def _duplicate_item(row: dict[str, Any]) -> IntelItem:
    original_value = row.get("original")
    original: dict[str, Any] = original_value if isinstance(original_value, dict) else {}
    localized_value = row.get("localized")
    localized: dict[str, Any] = localized_value if isinstance(localized_value, dict) else {}
    en_value = localized.get("en")
    en: dict[str, Any] = en_value if isinstance(en_value, dict) else {}
    return IntelItem(
        source=str(row.get("source") or ""),
        source_id=str(row.get("source_id") or ""),
        source_type=str(row.get("source_type") or ""),
        priority=str(row.get("priority") or ""),
        program=_strings(row.get("program")),
        card_family=_strings(row.get("card_family")),
        topic_type=str(row.get("topic_type") or ""),
        title=str(original.get("title") or en.get("title") or ""),
        url=str(row.get("url") or ""),
        published_at=str(row.get("published_at")) if row.get("published_at") else None,
        summary=str(original.get("summary") or en.get("summary") or ""),
        why_it_matters="",
        confidence_label=str(row.get("confidence_label") or ""),
        risk_label=str(row.get("risk_label") or ""),
        score=int(row.get("score") or 0),
        vertical=_strings(row.get("vertical")),
        ecosystem_signal_type=_strings(row.get("ecosystem_signal_type")),
        stakeholders=_strings(row.get("stakeholders")),
        consumer_impact=str(row.get("consumer_impact") or ""),
        impact_horizon=str(row.get("impact_horizon") or ""),
        action_label=str(row.get("action_label") or ""),
        metric_snippets=_strings(row.get("metric_snippets")),
        future_event_dates=_strings(row.get("future_event_dates")),
        raw_tags=[],
    )


def _duplicate_aggregates(rows: list[dict[str, Any]], issues: list[str]) -> dict[str, Any]:
    representatives: list[IntelItem] = []
    duplicate_events = 0
    for row in rows:
        item = _duplicate_item(row)
        if any(items_represent_same_event(item, existing) for existing in representatives):
            duplicate_events += 1
        else:
            representatives.append(item)
    duplicate_rate = duplicate_events / len(rows) if rows else 0.0
    if duplicate_rate > DUPLICATE_THRESHOLD:
        issues.append(
            f"post-cluster duplicate rate {duplicate_rate:.1%} exceeds {DUPLICATE_THRESHOLD:.0%}"
        )
    return {
        "events_checked": len(rows),
        "duplicate_events": duplicate_events,
        "duplicate_rate": round(duplicate_rate, 4),
    }


def _source_refs(row: dict[str, Any], known_ids: set[str]) -> list[dict[str, Any]]:
    evidence = row.get("evidence")
    evidence_rows = [item for item in evidence if isinstance(item, dict)] if isinstance(evidence, list) else []
    row_source = _text(row.get("source"))
    candidates = list(evidence_rows)
    if not evidence_rows or " / " not in row_source:
        candidates.insert(0, row)
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        source_id = _text(candidate.get("source_id"))
        url = _text(candidate.get("url"))
        raw_published_at = _text(candidate.get("published_at"))
        published_at = raw_published_at if _valid_timestamp(raw_published_at) else ""
        if source_id not in known_ids or not _valid_public_url(url):
            continue
        canonical_url = urlparse(url)._replace(fragment="").geturl()
        key = (source_id, canonical_url)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "source_id": source_id,
                "source": _text(candidate.get("source")) or source_id,
                "source_type": _text(candidate.get("source_type")),
                "url": url,
                "published_at": published_at or None,
            }
        )
    return refs


def _localized_title(row: dict[str, Any], locale: str) -> str:
    localized = row.get("localized")
    if not isinstance(localized, dict):
        return ""
    current = localized.get(locale)
    if not isinstance(current, dict):
        return ""
    title = _text(current.get("title"))
    return "" if title in _FAILED_TRANSLATION_VALUES else title


def _metric_identity(value: str) -> tuple[str, str]:
    compact = re.sub(r"[\s,]+", "", value.casefold())
    ratio = re.fullmatch(r"(\d+):(\d+)", compact)
    if ratio:
        return f"ratio:{ratio.group(1)}:{ratio.group(2)}", "ratio"
    percent = re.fullmatch(r"(\d+(?:\.\d+)?)%", compact)
    if percent:
        return f"number:{float(percent.group(1)):g}:percent", "percent"
    match = re.fullmatch(
        r"([$€£])?(\d+(?:\.\d+)?)(k|m|b|bn|million|billion)?"
        r"(points?|pts|miles?|avios|sqcs?|x|owners?|users?|nights?|credits?|fewermiles|perstay)?",
        compact,
    )
    if not match:
        return compact, "text"
    symbol, number_text, multiplier_text, unit = match.groups()
    multiplier = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "bn": 1_000_000_000,
        "million": 1_000_000,
        "billion": 1_000_000_000,
    }.get(multiplier_text or "", 1)
    number = float(number_text) * multiplier
    if symbol:
        category = f"currency:{symbol}"
    elif unit in {"point", "points", "pt", "pts"}:
        category = "points"
    elif unit in {"mile", "miles", "avios", "fewermiles"}:
        category = "miles"
    elif unit:
        category = unit
    else:
        category = "generic"
    return f"number:{number:g}:{category}", category


def _dedupe_metrics(values: list[str], limit: int = 4) -> list[str]:
    selected: list[tuple[str, str, str]] = []
    for value in values:
        identity, category = _metric_identity(value)
        number_prefix = identity.rsplit(":", 1)[0] if identity.startswith("number:") else ""
        replacement_index: int | None = None
        duplicate = False
        for index, (_existing_value, existing_identity, existing_category) in enumerate(selected):
            if identity == existing_identity:
                duplicate = True
                break
            existing_prefix = (
                existing_identity.rsplit(":", 1)[0]
                if existing_identity.startswith("number:")
                else ""
            )
            if number_prefix and number_prefix == existing_prefix and {
                category,
                existing_category,
            } & {"generic"}:
                if existing_category == "generic" and category != "generic":
                    replacement_index = index
                else:
                    duplicate = True
                break
        if duplicate:
            continue
        if replacement_index is not None:
            selected[replacement_index] = (value, identity, category)
        else:
            selected.append((value, identity, category))
        if len(selected) >= limit:
            break
    return [value for value, _identity, _category in selected]


def _public_metrics(row: dict[str, Any]) -> list[str]:
    original = row.get("original") if isinstance(row.get("original"), dict) else {}
    localized = row.get("localized") if isinstance(row.get("localized"), dict) else {}
    trusted_parts = [_text(original.get("title")), _text(original.get("summary"))]
    for locale in PUBLIC_LOCALES:
        visible = localized.get(locale) if isinstance(localized.get(locale), dict) else {}
        trusted_parts.append(_text(visible.get("title")))
    evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
    for item in evidence:
        if not isinstance(item, dict) or _text(item.get("source_type")) == "blog_comment":
            continue
        evidence_original = item.get("original") if isinstance(item.get("original"), dict) else {}
        trusted_parts.append(_text(evidence_original.get("title")))

    candidates: list[str] = []
    for part in trusted_parts:
        if part:
            candidates.extend(extract_metric_snippets(part))
    if not candidates:
        candidates = _strings(row.get("metric_snippets"))
    if _text(row.get("topic_type")) not in {"transfer_bonus", "status_match"}:
        candidates = [value for value in candidates if not re.fullmatch(r"\d+:\d+", value)]
    return _dedupe_metrics(candidates)


def _taxonomy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "programs": _strings(row.get("program")),
        "card_families": _strings(row.get("card_family")),
        "topic_type": _text(row.get("topic_type")),
        "verticals": _strings(row.get("vertical")),
        "ecosystem_signal_types": _strings(row.get("ecosystem_signal_type")),
        "stakeholders": _strings(row.get("stakeholders")),
        "consumer_impact": _text(row.get("consumer_impact")),
        "impact_horizon": _text(row.get("impact_horizon")),
    }


def _priority_code(row: dict[str, Any]) -> str:
    raw = str(row.get("priority_tier") or row.get("priority") or "P4").strip().upper()
    match = re.match(r"P[0-4]", raw)
    return match.group(0) if match else "P4"


def _event_lane(taxonomy: dict[str, Any]) -> str:
    topic = taxonomy["topic_type"]
    signals = taxonomy["ecosystem_signal_types"]
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
    return "ecosystem" if topic == "industry_signal" or (signals and topic not in member_first_topics) else "c-end"


def _structured_visible_text(
    locale: str,
    taxonomy: dict[str, Any],
    metrics: list[str],
    published_at: str | None,
    source_count: int,
) -> tuple[str, str]:
    catalog = load_catalog(locale)
    programs = taxonomy["programs"] or taxonomy["card_families"]
    entity_text = " / ".join(programs) if programs else ("Loyalty programs" if locale == "en" else "忠诚计划")
    topic = catalog.get(f"topic.{taxonomy['topic_type']}", taxonomy["topic_type"] or "-")
    metric_text = " / ".join(metrics) if metrics else ("none extracted" if locale == "en" else "未抽取")
    date_text = published_at[:10] if published_at else ("time unavailable" if locale == "en" else "时间未提供")
    verticals = [catalog.get(f"vertical.{value}", value) for value in taxonomy["verticals"]]
    vertical_text = " / ".join(verticals) if verticals else ("Loyalty" if locale == "en" else "忠诚计划")
    signals = [
        catalog.get(f"ecosystem_signal.{value}", value)
        for value in taxonomy["ecosystem_signal_types"]
    ]
    signal_text = " / ".join(signals) if signals else ("none assigned" if locale == "en" else "未标记")
    if locale == "zh-CN":
        summary = f"{entity_text} · {topic}。指标：{metric_text}。发布于 {date_text}，共 {source_count} 个公开来源。"
        why = f"分类：{vertical_text}；生态信号：{signal_text}。"
    else:
        noun = "source" if source_count == 1 else "sources"
        summary = f"{entity_text} · {topic}. Metrics: {metric_text}. Published {date_text}; {source_count} public {noun}."
        why = f"Taxonomy: {vertical_text}; ecosystem signal: {signal_text}."
    return summary, why


def _public_event(
    row: dict[str, Any], known_ids: set[str], index: int, issues: list[str]
) -> dict[str, Any]:
    event_id = _text(row.get("event_id"))
    if not event_id or re.search(r"\s", event_id):
        issues.append(f"items[{index}] requires an explicit non-whitespace event_id")
    refs = _source_refs(row, known_ids)
    if not refs:
        issues.append(f"items[{index}] has no valid public source reference")
    raw_published_at = _text(row.get("published_at"))
    published_at = raw_published_at if _valid_timestamp(raw_published_at) else None
    taxonomy = _taxonomy(row)
    metrics = _public_metrics(row)
    localized: dict[str, dict[str, str]] = {}
    source_count = len({ref["source_id"] for ref in refs})
    for locale in PUBLIC_LOCALES:
        title = _localized_title(row, locale)
        summary, why = _structured_visible_text(
            locale, taxonomy, metrics, published_at, source_count
        )
        localized[locale] = {"title": title, "summary": summary, "why_it_matters": why}
    return {
        "event_id": event_id,
        "lane": _event_lane(taxonomy),
        "priority": _priority_code(row),
        "localized": localized,
        "source_refs": refs,
        "published_at": published_at,
        "future_event_dates": _strings(row.get("future_event_dates")),
        "taxonomy": taxonomy,
        "confidence_label": _text(row.get("confidence_label")),
        "risk_label": _text(row.get("risk_label")),
        "action_label": _text(row.get("action_label")),
        "metric_snippets": metrics,
    }


def _validate_language_completeness(
    public_rows: list[dict[str, Any]], issues: list[str]
) -> None:
    for index, public in enumerate(public_rows):
        for locale in PUBLIC_LOCALES:
            visible = public["localized"][locale]
            missing = [
                field
                for field in ("title", "summary", "why_it_matters")
                if not visible[field].strip()
            ]
            if missing:
                issues.append(
                    f"item {index + 1} has incomplete {locale} visible fields: {', '.join(missing)}"
                )


def _validate_top_events(
    original_rows: list[dict[str, Any]], issues: list[str]
) -> None:
    for index, original in enumerate(original_rows[:20]):
        if not _valid_timestamp(original.get("published_at")):
            issues.append(f"top item {index + 1} is missing a valid published_at timestamp")
        if not _valid_public_url(original.get("url")):
            issues.append(f"top item {index + 1} is missing a valid HTTP(S) source URL")


def _validate_output_allowlist(payload: dict[str, Any], issues: list[str]) -> None:
    def walk(value: Any, location: str = "public_report") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.casefold() in _FORBIDDEN_OUTPUT_KEYS:
                    issues.append(f"{location} contains forbidden field {key}")
                walk(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{location}[{index}]")

    walk(payload)
    issues.extend(_find_forbidden_text(payload, "public_report"))


def audit_public_report(
    payload: dict[str, Any], *, audited_at: str | None = None
) -> dict[str, Any]:
    """Apply the public policy and return a publication-safe report.

    The full input remains local. The returned mapping is built field-by-field and never copies
    original summaries, evidence text, authors, profiles, cards, or local filesystem metadata.
    """

    if not isinstance(payload, dict):
        raise PublicAuditError(["input JSON must contain an object"])
    issues = _find_forbidden_text(payload)
    generated_at = _text(payload.get("generated_at"))
    if not _valid_timestamp(generated_at):
        issues.append("generated_at must be a valid timestamp")

    scope = _source_scope(payload, issues)
    health = _health_aggregates(payload, scope, issues)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        issues.append("items must be an array")
        raw_items = []
    rows = [copy.deepcopy(row) for row in raw_items if isinstance(row, dict)]
    if len(rows) != len(raw_items):
        issues.append("every item must be an object")

    event_ids = [_text(row.get("event_id")) for row in rows]
    duplicates = [event_id for event_id, count in Counter(event_ids).items() if event_id and count > 1]
    if duplicates:
        issues.append("event_id values must be unique: " + ", ".join(sorted(duplicates)))

    duplicate_health = _duplicate_aggregates(rows, issues)
    known_ids = {str(source.get("id")) for source in scope.configured}
    public_items = [
        _public_event(row, known_ids, index, issues) for index, row in enumerate(rows)
    ]
    _validate_language_completeness(public_items, issues)
    _validate_top_events(rows, issues)

    audit_timestamp = audited_at or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    if not _valid_timestamp(audit_timestamp):
        issues.append("audited_at must be a valid timestamp")
    report = {
        "schema_id": PUBLIC_REPORT_SCHEMA_ID,
        "publication": {
            "policy": PUBLIC_POLICY,
            "product": {"name": "Loyalty Radar", "version": __version__},
            "generated_at": generated_at,
            "audited_at": audit_timestamp,
            "mode": _text(payload.get("mode")),
            "focus": _text(payload.get("focus")),
            "hours": int(payload.get("hours") or 0),
            "future_watch_days": int(payload.get("future_watch_days") or 60),
            "timezone": _text(payload.get("timezone")) or "UTC",
            "source_packs": _strings(payload.get("source_packs")),
            "locales": list(PUBLIC_LOCALES),
            "event_count": len(public_items),
        },
        "items": public_items,
        "health": health | duplicate_health | {"top_events_checked": min(20, len(public_items))},
    }
    _validate_output_allowlist(report, issues)
    if issues:
        raise PublicAuditError(issues)
    return report


def write_public_report(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
