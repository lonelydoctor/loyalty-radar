"""Locale-safe HTML, Markdown, and overview image rendering."""

from __future__ import annotations

import datetime as dt
import html
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .health import localized_health_detail
from .i18n import Catalog, load_catalog, normalize_locale

REPOSITORY_URL = "https://github.com/lonelydoctor/loyalty-radar"
NORMAL_RISKS = {"正常权益", "Normal benefit"}
RISK_TOPICS = {"bug", "clawback"}


@dataclass(frozen=True)
class RenderedArtifacts:
    locale: str
    html: Path
    overview_html: Path
    markdown: Path
    png: Path | None


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_url(value: Any, fallback: str = "#") -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return fallback


def _markdown_url(value: Any) -> str:
    return _safe_url(value).replace("(", "%28").replace(")", "%29")


def _localized(event: dict[str, Any], locale: str, field: str, catalog: Catalog) -> str:
    value = event.get("localized", {}).get(locale, {}).get(field)
    if value is None or not str(value).strip():
        return catalog.text("fallback.translation_failed")
    return str(value).strip()


def _label(catalog: Catalog, category: str, value: Any) -> str:
    if value is None or value == "":
        return "-"
    return catalog.get(f"{category}.{value}", str(value))


def _labels(catalog: Catalog, category: str, values: Iterable[Any]) -> str:
    rows = [_label(catalog, category, value) for value in values if value]
    return " / ".join(rows) if rows else "-"


def _priority_code(event: dict[str, Any]) -> str:
    tier = str(event.get("priority_tier") or event.get("priority") or "P4")
    match = re.match(r"P[0-4]", tier)
    return match.group(0) if match else "P4"


def _product_version(payload: dict[str, Any]) -> str:
    product = payload.get("product")
    if isinstance(product, dict) and str(product.get("version") or "").strip():
        return str(product["version"]).strip()
    return __version__


def _lane(event: dict[str, Any]) -> str:
    if event.get("ecosystem_signal_type") or event.get("topic_type") == "industry_signal":
        return "industry"
    return "c-end"


def _is_risk(event: dict[str, Any]) -> bool:
    risk_label = str(event.get("risk_label") or "")
    return event.get("topic_type") in RISK_TOPICS or bool(risk_label and risk_label not in NORMAL_RISKS)


def _published_timestamp(event: dict[str, Any]) -> float:
    value = event.get("published_at")
    if not value:
        return 0.0
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _event_search_text(event: dict[str, Any], locale: str, catalog: Catalog) -> str:
    localized = event.get("localized", {}).get(locale, {})
    values = [
        localized.get("title", ""),
        localized.get("summary", ""),
        event.get("source", ""),
        " ".join(event.get("program", [])),
        " ".join(event.get("card_family", [])),
        " ".join(event.get("vertical", [])),
        _label(catalog, "topic", event.get("topic_type")),
    ]
    return " ".join(str(value) for value in values).lower()


def _badges(event: dict[str, Any], catalog: Catalog) -> list[tuple[str, str]]:
    rows = [
        ("priority", _label(catalog, "priority", event.get("priority_tier") or event.get("priority"))),
        ("action", _label(catalog, "action", event.get("action_label"))),
        ("risk", _label(catalog, "risk", event.get("risk_label"))),
    ]
    if event.get("consumer_impact"):
        rows.append(("impact", _label(catalog, "consumer_impact", event["consumer_impact"])))
    return rows


def _event_card(event: dict[str, Any], locale: str, catalog: Catalog, index: int) -> str:
    title = _localized(event, locale, "title", catalog)
    summary = _localized(event, locale, "summary", catalog)
    why = _localized(event, locale, "why_it_matters", catalog)
    priority = _priority_code(event)
    lane = _lane(event)
    risk_flag = "true" if _is_risk(event) else "false"
    watch_flag = "true" if event.get("future_event_dates") or event.get("impact_horizon") in {"watchlist", "next_60_days"} else "false"
    verticals = event.get("vertical", []) or ["loyalty"]
    published = str(event.get("published_at") or "")[:16].replace("T", " ") or catalog.text("labels.unknown_time")
    badge_html = "".join(
        f'<span class="badge badge-{_escape(kind)}">{_escape(value)}</span>' for kind, value in _badges(event, catalog)
    )
    metrics = event.get("metric_snippets", [])
    future_dates = event.get("future_event_dates", [])
    detail_rows = [
        (catalog.text("labels.vertical"), _labels(catalog, "vertical", verticals)),
        (catalog.text("labels.topic"), _label(catalog, "topic", event.get("topic_type"))),
        (catalog.text("labels.signal"), _labels(catalog, "ecosystem_signal", event.get("ecosystem_signal_type", []))),
        (catalog.text("labels.stakeholders"), _labels(catalog, "stakeholder", event.get("stakeholders", []))),
        (catalog.text("labels.confidence"), _label(catalog, "confidence", event.get("confidence_label"))),
    ]
    if metrics:
        detail_rows.append((catalog.text("labels.metrics"), " / ".join(str(value) for value in metrics)))
    if future_dates:
        detail_rows.append((catalog.text("labels.future_dates"), " / ".join(str(value) for value in future_dates)))
    detail_html = "".join(
        f'<div class="fact"><dt>{_escape(label)}</dt><dd>{_escape(value)}</dd></div>' for label, value in detail_rows
    )

    evidence_rows = []
    for evidence in event.get("evidence", []):
        evidence_title = _localized(evidence, locale, "title", catalog)
        evidence_summary = _localized(evidence, locale, "summary", catalog)
        evidence_time = str(evidence.get("published_at") or "")[:16].replace("T", " ") or catalog.text("labels.unknown_time")
        evidence_rows.append(
            '<li class="evidence-row">'
            f'<a href="{_escape(_safe_url(evidence.get("url")))}" target="_blank" rel="noreferrer">{_escape(evidence_title)}</a>'
            f'<span>{_escape(evidence.get("source"))} · {_escape(evidence_time)}</span>'
            f'<p>{_escape(evidence_summary)}</p>'
            "</li>"
        )
    evidence_html = "".join(evidence_rows) or f'<li>{_escape(catalog.text("labels.no_items"))}</li>'
    search = _event_search_text(event, locale, catalog)
    vertical_attr = " ".join(str(value) for value in verticals)
    source_link = _safe_url(event.get("url"))
    score = int(event.get("score") or 0)
    evidence_count = len(event.get("evidence", []))

    return f"""
<article class="event-card" id="event-{_escape(event.get('event_id') or index)}"
  data-lane="{lane}" data-risk="{risk_flag}" data-watch="{watch_flag}" data-vertical="{_escape(vertical_attr)}" data-priority="{priority}"
  data-score="{score}" data-time="{_published_timestamp(event)}" data-evidence="{evidence_count}"
  data-search="{_escape(search)}">
  <div class="event-index">{index:02d}</div>
  <div class="event-main">
    <div class="badges">{badge_html}</div>
    <h3><a href="{_escape(source_link)}" target="_blank" rel="noreferrer">{_escape(title)}</a></h3>
    <p class="summary">{_escape(summary)}</p>
    <div class="why"><strong>{_escape(catalog.text('labels.why'))}</strong><span>{_escape(why)}</span></div>
    <dl class="facts">{detail_html}</dl>
    <div class="source-line">
      <span>{_escape(catalog.text('labels.source'))}: {_escape(event.get('source'))}</span>
      <span>{_escape(catalog.text('labels.published'))}: {_escape(published)}</span>
      <span>{_escape(catalog.text('labels.evidence_count'))}: {evidence_count}</span>
    </div>
    <details class="evidence"><summary>{_escape(catalog.text('sections.evidence'))} ({evidence_count})</summary><ol>{evidence_html}</ol></details>
  </div>
</article>"""


def _language_links(stem: str, locales: list[str], current: str, catalog: Catalog) -> str:
    if len(locales) < 2:
        return ""
    links = []
    for locale in locales:
        class_name = "active" if locale == current else ""
        links.append(
            f'<a class="{class_name}" href="{_escape(stem)}-{_escape(locale)}.html">'
            f'{_escape(catalog.get(f"languages.{locale}", locale))}</a>'
        )
    return f'<nav class="language-switch" aria-label="{_escape(catalog.text("navigation.language"))}">' + "".join(links) + "</nav>"


def render_html(payload: dict[str, Any], locale: str, stem: str, locales: list[str]) -> str:
    locale = normalize_locale(locale)
    catalog = load_catalog(locale)
    events = list(payload.get("items", []))
    health = list(payload.get("health", []))
    status_counts = Counter(str(row.get("status")) for row in health)
    urgent = sum(1 for event in events if _priority_code(event) in {"P0", "P1"})
    days = max(1, math.ceil(int(payload.get("hours", 336)) / 24))
    generated = str(payload.get("generated_at") or "").replace("T", " ")[:19]
    language_links = _language_links(stem, locales, locale, catalog)

    must_read = sorted(events, key=lambda row: (-int(row.get("score") or 0), -_published_timestamp(row)))[:5]
    must_read_html = "".join(
        f'<a href="#event-{_escape(event.get("event_id") or index)}"><span>{_priority_code(event)}</span>{_escape(_localized(event, locale, "title", catalog))}</a>'
        for index, event in enumerate(must_read, 1)
    ) or f'<p>{_escape(catalog.text("labels.no_items"))}</p>'

    timeline_rows = []
    for event in events:
        for date in event.get("future_event_dates", []):
            timeline_rows.append((str(date), event))
    timeline_rows.sort(key=lambda row: row[0])
    timeline_html = "".join(
        f'<a href="#event-{_escape(event.get("event_id"))}"><time>{_escape(date)}</time><span>{_escape(_localized(event, locale, "title", catalog))}</span></a>'
        for date, event in timeline_rows[:12]
    ) or f'<p>{_escape(catalog.text("labels.no_items"))}</p>'

    cards_html = "".join(_event_card(event, locale, catalog, index) for index, event in enumerate(events, 1))
    if not cards_html:
        cards_html = f'<p class="empty-state">{_escape(catalog.text("labels.no_items"))}</p>'

    health_rows = []
    for row in health:
        status = str(row.get("status") or "failed")
        health_rows.append(
            "<tr>"
            f'<th scope="row"><a href="{_escape(_safe_url(row.get("url")))}" target="_blank" rel="noreferrer">{_escape(row.get("source") or row.get("source_id"))}</a></th>'
            f'<td><span class="status status-{_escape(status)}">{_escape(_label(catalog, "health", status))}</span></td>'
            + "".join(f"<td>{int(row.get(field) or 0)}</td>" for field in ("fetched", "dated", "eligible", "rejected", "duplicate", "selected"))
            + f'<td>{_escape(localized_health_detail(row, catalog))}</td></tr>'
        )
    health_html = "".join(health_rows)
    locale_tag = "zh-CN" if locale == "zh-CN" else "en"

    return f"""<!doctype html>
<html lang="{locale_tag}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(catalog.text('meta.title'))}</title>
<style>
:root {{ --ink:#17202a; --muted:#667085; --paper:#f5f5f1; --surface:#fff; --line:#d8d9d5; --blue:#2458a6; --green:#18765b; --coral:#b94d3e; --gold:#9a6a14; --radius:6px; }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }}
body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Inter,"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif; letter-spacing:0; }}
a {{ color:inherit; }}
.topbar {{ min-height:58px; border-bottom:1px solid var(--line); background:rgba(245,245,241,.96); position:sticky; top:0; z-index:10; display:flex; align-items:center; justify-content:space-between; gap:20px; padding:0 4vw; }}
.brand {{ font-weight:800; text-decoration:none; letter-spacing:0; }}
.language-switch {{ display:flex; gap:4px; }} .language-switch a {{ padding:7px 10px; text-decoration:none; border-bottom:2px solid transparent; font-size:13px; }} .language-switch a.active {{ border-color:var(--blue); color:var(--blue); }}
header {{ padding:54px 4vw 38px; background:var(--surface); border-bottom:1px solid var(--line); }}
.eyebrow {{ color:var(--blue); font-weight:800; text-transform:uppercase; font-size:12px; }}
h1 {{ font-size:clamp(38px,5vw,72px); margin:8px 0 10px; line-height:1.02; max-width:1100px; letter-spacing:0; }}
.subtitle {{ margin:0; max-width:920px; color:var(--muted); font-size:18px; line-height:1.6; }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px 20px; margin-top:24px; font-size:13px; color:var(--muted); }}
.metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border-bottom:1px solid var(--line); background:var(--surface); }}
.metric {{ padding:22px 4vw; border-right:1px solid var(--line); }} .metric:last-child {{ border-right:0; }} .metric strong {{ display:block; font-size:30px; }} .metric span {{ color:var(--muted); font-size:13px; }}
main {{ width:min(1600px,92vw); margin:0 auto; padding:42px 0 80px; }}
.section-heading {{ display:flex; align-items:end; justify-content:space-between; border-bottom:2px solid var(--ink); margin:0 0 18px; padding-bottom:9px; }}
.section-heading h2 {{ margin:0; font-size:24px; }}
.must-read {{ margin-bottom:38px; }} .must-grid {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:var(--surface); }}
.must-grid a {{ min-height:132px; padding:18px; border-right:1px solid var(--line); text-decoration:none; font-weight:700; line-height:1.42; }} .must-grid a:last-child {{ border-right:0; }} .must-grid a span {{ display:block; color:var(--coral); font-size:12px; margin-bottom:8px; }}
.timeline {{ margin-bottom:38px; }} .timeline-strip {{ display:flex; overflow:auto; border-top:1px solid var(--line); border-bottom:1px solid var(--line); background:var(--surface); }} .timeline-strip a {{ min-width:260px; padding:16px; border-right:1px solid var(--line); text-decoration:none; }} .timeline-strip time {{ display:block; color:var(--green); font-weight:800; margin-bottom:6px; }}
.controls {{ display:grid; grid-template-columns:minmax(260px,2fr) repeat(4,minmax(145px,1fr)); gap:10px; margin:0 0 22px; position:sticky; top:58px; z-index:8; background:var(--paper); padding:12px 0; }}
input,select {{ width:100%; min-height:42px; border:1px solid #b8bbb8; border-radius:4px; background:var(--surface); color:var(--ink); padding:8px 10px; font:inherit; font-size:14px; }}
.event-list {{ display:grid; gap:14px; }}
.event-card {{ display:grid; grid-template-columns:70px minmax(0,1fr); background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; }}
.event-card[hidden] {{ display:none; }} .event-index {{ padding:20px 14px; border-right:1px solid var(--line); color:var(--muted); font:700 18px ui-monospace,SFMono-Regular,monospace; }} .event-main {{ padding:20px 24px 22px; min-width:0; }}
.badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }} .badge {{ border:1px solid var(--line); border-radius:999px; padding:4px 8px; font-size:11px; font-weight:750; }} .badge-priority {{ color:var(--coral); border-color:#e3b7b0; background:#fff7f5; }} .badge-action {{ color:var(--blue); border-color:#b9cae7; background:#f5f8ff; }} .badge-risk {{ color:var(--gold); border-color:#dec99f; background:#fffaf0; }} .badge-impact {{ color:var(--green); border-color:#b5d7ca; background:#f3fbf7; }}
.event-card h3 {{ font-size:22px; line-height:1.32; margin:0 0 10px; letter-spacing:0; overflow-wrap:anywhere; }} .event-card h3 a {{ text-decoration:none; }} .event-card h3 a:hover {{ color:var(--blue); text-decoration:underline; }}
.summary {{ font-size:15px; line-height:1.68; margin:0 0 14px; }} .why {{ display:grid; grid-template-columns:130px minmax(0,1fr); gap:12px; padding:12px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); font-size:14px; line-height:1.55; }} .why strong {{ color:var(--blue); }}
.facts {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0; margin:14px 0; border:1px solid var(--line); }} .fact {{ padding:10px 12px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); min-width:0; }} .fact:nth-child(3n) {{ border-right:0; }} .fact dt {{ color:var(--muted); font-size:11px; margin-bottom:3px; }} .fact dd {{ margin:0; font-size:13px; overflow-wrap:anywhere; }}
.source-line {{ display:flex; flex-wrap:wrap; gap:6px 18px; color:var(--muted); font-size:12px; }}
.evidence {{ margin-top:12px; border-top:1px solid var(--line); padding-top:10px; }} .evidence summary {{ cursor:pointer; font-weight:750; color:var(--blue); }} .evidence ol {{ padding-left:22px; }} .evidence-row {{ margin:14px 0; }} .evidence-row a {{ font-weight:700; }} .evidence-row span {{ display:block; color:var(--muted); font-size:12px; margin-top:3px; }} .evidence-row p {{ margin:6px 0; font-size:13px; line-height:1.55; }}
.health {{ margin-top:54px; }} .table-wrap {{ overflow:auto; border:1px solid var(--line); background:var(--surface); }} table {{ border-collapse:collapse; width:100%; min-width:1120px; font-size:12px; }} th,td {{ border-bottom:1px solid var(--line); padding:10px 9px; text-align:left; }} thead th {{ background:#eceeea; position:sticky; top:0; }} tbody th {{ min-width:260px; }} .status {{ font-weight:800; }} .status-ok {{ color:var(--green); }} .status-failed {{ color:var(--coral); }} .status-skipped {{ color:var(--gold); }}
.empty-state {{ padding:40px; text-align:center; color:var(--muted); background:var(--surface); border:1px solid var(--line); }}
footer {{ border-top:1px solid var(--line); background:var(--surface); padding:28px 4vw 42px; color:var(--muted); font-size:12px; line-height:1.7; }} footer a {{ color:var(--blue); }}
@media (max-width:980px) {{ .metrics {{ grid-template-columns:repeat(2,1fr); }} .metric:nth-child(2) {{ border-right:0; }} .must-grid {{ grid-template-columns:1fr 1fr; }} .must-grid a {{ border-bottom:1px solid var(--line); }} .controls {{ grid-template-columns:1fr 1fr; top:58px; }} .controls input {{ grid-column:1/-1; }} .facts {{ grid-template-columns:1fr 1fr; }} .fact:nth-child(3n) {{ border-right:1px solid var(--line); }} .fact:nth-child(2n) {{ border-right:0; }} }}
@media (max-width:600px) {{ header {{ padding-top:34px; }} h1 {{ font-size:42px; }} .metrics {{ grid-template-columns:1fr 1fr; }} main {{ width:94vw; padding-top:24px; }} .must-grid {{ display:block; }} .must-grid a {{ display:block; min-height:0; border-right:0; }} .controls {{ position:static; grid-template-columns:1fr; }} .controls input {{ grid-column:auto; }} .event-card {{ grid-template-columns:1fr; }} .event-index {{ border-right:0; border-bottom:1px solid var(--line); padding:10px 16px; }} .event-main {{ padding:17px 16px; }} .event-card h3 {{ font-size:19px; }} .why {{ grid-template-columns:1fr; gap:4px; }} .facts {{ grid-template-columns:1fr; }} .fact,.fact:nth-child(3n) {{ border-right:0; }} .topbar {{ padding:0 3vw; }} }}
</style>
</head>
<body>
<div class="topbar"><a class="brand" href="#top">Loyalty Radar</a>{language_links}</div>
<header id="top">
  <div class="eyebrow">{_escape(catalog.text('meta.window', days=days))} · {_escape(catalog.text('meta.future', days=payload.get('future_watch_days', 60)))}</div>
  <h1>{_escape(catalog.text('meta.title'))}</h1>
  <p class="subtitle">{_escape(catalog.text('meta.subtitle'))}</p>
  <div class="meta"><span>{_escape(catalog.text('meta.generated', value=generated))}</span><span>{_escape(catalog.text('meta.unverified'))}</span><span>{_escape(catalog.text('meta.schema', value=payload.get('schema_version', '1.0')))}</span></div>
</header>
<section class="metrics" aria-label="metrics">
  <div class="metric"><strong>{len(events)}</strong><span>{_escape(catalog.text('metrics.events'))}</span></div>
  <div class="metric"><strong>{status_counts.get('ok', 0)}</strong><span>{_escape(catalog.text('metrics.sources_ok'))}</span></div>
  <div class="metric"><strong>{status_counts.get('failed', 0) + status_counts.get('skipped', 0)}</strong><span>{_escape(catalog.text('metrics.sources_limited'))}</span></div>
  <div class="metric"><strong>{urgent}</strong><span>{_escape(catalog.text('metrics.urgent'))}</span></div>
</section>
<main>
  <section class="must-read"><div class="section-heading"><h2>{_escape(catalog.text('sections.must_read'))}</h2></div><div class="must-grid">{must_read_html}</div></section>
  <section class="timeline"><div class="section-heading"><h2>{_escape(catalog.text('sections.timeline'))}</h2></div><div class="timeline-strip">{timeline_html}</div></section>
  <section class="events"><div class="section-heading"><h2>{_escape(catalog.text('navigation.report'))}</h2><span id="visible-count">{len(events)}</span></div>
    <div class="controls">
      <input id="search" type="search" placeholder="{_escape(catalog.text('filters.search'))}" aria-label="{_escape(catalog.text('filters.search'))}">
      <select id="lane" aria-label="{_escape(catalog.text('filters.lane'))}"><option value="all">{_escape(catalog.text('filters.all'))}</option><option value="c-end">{_escape(catalog.text('filters.c_end'))}</option><option value="risk">{_escape(catalog.text('filters.risk'))}</option><option value="industry">{_escape(catalog.text('filters.industry'))}</option><option value="watch">{_escape(catalog.text('filters.watch'))}</option></select>
      <select id="vertical" aria-label="{_escape(catalog.text('filters.vertical'))}"><option value="all">{_escape(catalog.text('filters.all'))}</option><option value="hotel">{_escape(catalog.text('filters.hotel'))}</option><option value="airline">{_escape(catalog.text('filters.airline'))}</option><option value="credit_card">{_escape(catalog.text('filters.credit_card'))}</option><option value="rental_car">{_escape(catalog.text('filters.rental_car'))}</option></select>
      <select id="priority" aria-label="{_escape(catalog.text('filters.priority'))}"><option value="all">{_escape(catalog.text('filters.all'))}</option><option value="P0">P0</option><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3</option><option value="P4">P4</option></select>
      <select id="sort" aria-label="{_escape(catalog.text('filters.sort'))}"><option value="priority">{_escape(catalog.text('filters.priority_order'))}</option><option value="newest">{_escape(catalog.text('filters.newest'))}</option><option value="evidence">{_escape(catalog.text('filters.evidence'))}</option></select>
    </div>
    <div class="event-list" id="event-list">{cards_html}</div>
  </section>
  <section class="health"><div class="section-heading"><h2>{_escape(catalog.text('sections.health'))}</h2></div><div class="table-wrap"><table><thead><tr><th>{_escape(catalog.text('labels.source'))}</th><th>{_escape(catalog.text('labels.status'))}</th><th>{_escape(catalog.text('labels.fetched'))}</th><th>{_escape(catalog.text('labels.dated'))}</th><th>{_escape(catalog.text('labels.eligible'))}</th><th>{_escape(catalog.text('labels.rejected'))}</th><th>{_escape(catalog.text('labels.duplicate'))}</th><th>{_escape(catalog.text('labels.selected'))}</th><th>{_escape(catalog.text('labels.reason'))}</th></tr></thead><tbody>{health_html}</tbody></table></div></section>
</main>
<footer><div>{_escape(catalog.text('footer.disclosure'))}</div><div>{_escape(catalog.text('footer.privacy'))}</div><div><a href="{REPOSITORY_URL}">{_escape(catalog.text('footer.project'))}: Loyalty Radar</a></div></footer>
<script>
const list=document.getElementById('event-list'); const cards=[...list.querySelectorAll('.event-card')];
const controls=['search','lane','vertical','priority','sort'].map(id=>document.getElementById(id));
function applyFilters() {{
  const search=document.getElementById('search').value.trim().toLowerCase();
  const lane=document.getElementById('lane').value; const vertical=document.getElementById('vertical').value; const priority=document.getElementById('priority').value;
  cards.forEach(card=>{{ const moduleMismatch=lane==='c-end'?card.dataset.lane!=='c-end':lane==='industry'?card.dataset.lane!=='industry':lane==='risk'?card.dataset.risk!=='true':lane==='watch'?card.dataset.watch!=='true':false; card.hidden=!!((search&&!card.dataset.search.includes(search))||moduleMismatch||(vertical!=='all'&&!card.dataset.vertical.split(' ').includes(vertical))||(priority!=='all'&&card.dataset.priority!==priority)); }});
  const mode=document.getElementById('sort').value; const field=mode==='newest'?'time':mode==='evidence'?'evidence':'score';
  cards.sort((a,b)=>Number(b.dataset[field])-Number(a.dataset[field])).forEach(card=>list.appendChild(card));
  document.getElementById('visible-count').textContent=cards.filter(card=>!card.hidden).length;
}}
controls.forEach(control=>control.addEventListener(control.tagName==='INPUT'?'input':'change',applyFilters)); applyFilters();
</script>
</body></html>"""


def _overview_complexity(event: dict[str, Any], locale: str, catalog: Catalog) -> float:
    title = len(_localized(event, locale, "title", catalog))
    summary = len(_localized(event, locale, "summary", catalog))
    why = len(_localized(event, locale, "why_it_matters", catalog))
    return 1.0 + title / 70 + summary / 260 + why / 180


def select_overview_events(events: list[dict[str, Any]], locale: str, catalog: Catalog, maximum: int = 12) -> list[dict[str, Any]]:
    ordered = sorted(events, key=lambda row: (-int(row.get("score") or 0), -_published_timestamp(row)))
    selected: list[dict[str, Any]] = []
    lane_counts = Counter()
    budget = 22.0
    for event in ordered:
        cost = _overview_complexity(event, locale, catalog)
        lane = _lane(event)
        if len(selected) >= maximum:
            break
        if selected and budget - cost < 0 and lane_counts["c-end"] and lane_counts["industry"]:
            continue
        if lane_counts[lane] >= 6:
            continue
        selected.append(event)
        lane_counts[lane] += 1
        budget -= cost
    for lane in ("c-end", "industry"):
        if lane_counts[lane]:
            continue
        candidate = next((event for event in ordered if _lane(event) == lane and event not in selected), None)
        if candidate:
            selected.append(candidate)
    return selected[:maximum]


def _overview_card(event: dict[str, Any], locale: str, catalog: Catalog) -> str:
    title = _localized(event, locale, "title", catalog)
    summary = _localized(event, locale, "summary", catalog)
    why = _localized(event, locale, "why_it_matters", catalog)
    signals = _labels(catalog, "ecosystem_signal", event.get("ecosystem_signal_type", []))
    topic = _label(catalog, "topic", event.get("topic_type"))
    source_time = str(event.get("published_at") or "")[:10] or catalog.text("labels.unknown_time")
    badges = "".join(f'<span class="mini mini-{_escape(kind)}">{_escape(value)}</span>' for kind, value in _badges(event, catalog)[:3])
    metrics = " / ".join(str(value) for value in event.get("metric_snippets", [])[:4])
    metric_html = f'<div class="anchor">{_escape(catalog.text("labels.metrics"))}: {_escape(metrics)}</div>' if metrics else ""
    return f"""<article class="overview-card">
<div class="overview-badges">{badges}</div>
<h3>{_escape(title)}</h3>
<p>{_escape(summary)}</p>
<div class="overview-why"><strong>{_escape(catalog.text('labels.why'))}</strong> {_escape(why)}</div>
{metric_html}
<div class="overview-meta">{_escape(topic)} · {_escape(signals)} · {_escape(event.get('source'))} · {_escape(source_time)}</div>
</article>"""


def render_overview_html(payload: dict[str, Any], locale: str) -> str:
    locale = normalize_locale(locale)
    catalog = load_catalog(locale)
    events = select_overview_events(list(payload.get("items", [])), locale, catalog)
    lanes = {"c-end": [], "industry": []}
    for event in events:
        lanes[_lane(event)].append(event)
    days = max(1, math.ceil(int(payload.get("hours", 336)) / 24))
    generated = str(payload.get("generated_at") or "").replace("T", " ")[:16]
    product_version = _product_version(payload)
    health = payload.get("health", [])
    healthy = sum(1 for row in health if row.get("status") == "ok")
    limited = len(health) - healthy
    c_cards = "".join(_overview_card(event, locale, catalog) for event in lanes["c-end"]) or f'<p class="none">{_escape(catalog.text("labels.no_items"))}</p>'
    i_cards = "".join(_overview_card(event, locale, catalog) for event in lanes["industry"]) or f'<p class="none">{_escape(catalog.text("labels.no_items"))}</p>'
    lang = "zh-CN" if locale == "zh-CN" else "en"
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>
:root{{--ink:#16212c;--muted:#64707d;--paper:#f3f3ef;--surface:#fff;--line:#d4d6d2;--blue:#2458a6;--green:#14715a;--coral:#b74b3d;--scale:1;}}
*{{box-sizing:border-box}} html,body{{width:2400px;height:1800px;margin:0;overflow:hidden}} body{{background:var(--paper);color:var(--ink);font-family:Inter,"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;letter-spacing:0;padding:44px 52px 38px}}
header{{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;border-bottom:3px solid var(--ink);padding-bottom:24px}} .kicker{{color:var(--blue);font-weight:800;font-size:18px;margin-bottom:8px}} h1{{font-size:68px;line-height:1;margin:0;letter-spacing:0}} .subtitle{{font-size:23px;color:var(--muted);margin:13px 0 0}} .stamp{{text-align:right;color:var(--muted);font-size:18px;line-height:1.7}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);margin:20px 0 24px;border:1px solid var(--line);background:var(--surface)}} .metric{{padding:13px 18px;border-right:1px solid var(--line)}} .metric:last-child{{border-right:0}} .metric strong{{display:block;font-size:31px}} .metric span{{font-size:15px;color:var(--muted)}}
.lanes{{display:grid;grid-template-columns:1fr 1fr;gap:24px;height:1370px}} .lane{{min-width:0;display:flex;flex-direction:column}} .lane-title{{display:flex;align-items:baseline;justify-content:space-between;border-bottom:2px solid var(--ink);padding:0 2px 10px;margin-bottom:12px}} .lane-title h2{{margin:0;font-size:31px}} .lane-title span{{font-size:16px;color:var(--muted)}} .cards{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;align-content:start;min-height:0}}
.overview-card{{background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:15px 17px;min-width:0}} .overview-badges{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px}} .mini{{font-size:11px;font-weight:800;border:1px solid var(--line);border-radius:999px;padding:3px 6px}} .mini-priority{{color:var(--coral)}} .mini-action{{color:var(--blue)}} .mini-risk{{color:#8b6112}}
.overview-card h3{{font-size:20px;line-height:1.28;margin:0 0 8px;overflow-wrap:anywhere;letter-spacing:0}} .overview-card p{{font-size:13px;line-height:1.48;margin:0 0 8px}} .overview-why{{border-top:1px solid var(--line);padding-top:7px;font-size:12px;line-height:1.43}} .overview-why strong{{color:var(--blue)}} .anchor{{font-size:12px;color:var(--green);font-weight:750;margin-top:7px}} .overview-meta{{font-size:10.5px;color:var(--muted);margin-top:7px;line-height:1.35}} .none{{background:var(--surface);border:1px solid var(--line);padding:30px;color:var(--muted)}}
footer{{position:absolute;left:52px;right:52px;bottom:17px;display:flex;justify-content:space-between;color:var(--muted);font-size:12px}}
body.tight h1{{font-size:61px}} body.tight .lanes{{height:1395px}} body.tight .overview-card{{padding:12px 14px}} body.tight .overview-card h3{{font-size:18px}} body.tight .overview-card p{{font-size:12px}} body.tight .overview-why{{font-size:11px}} body.tighter header{{padding-bottom:17px}} body.tighter .metrics{{margin:14px 0 17px}} body.tighter .overview-card h3{{font-size:17px}} body.tighter .overview-card p{{font-size:11px;line-height:1.38}} body.tighter .cards{{gap:8px}}
</style></head><body>
<header><div><div class="kicker">{_escape(catalog.text('meta.window',days=days))} · {_escape(catalog.text('meta.future',days=payload.get('future_watch_days',60)))}</div><h1>{_escape(catalog.text('meta.title'))}</h1><p class="subtitle">{_escape(catalog.text('meta.subtitle'))}</p></div><div class="stamp">{_escape(catalog.text('meta.generated',value=generated))}<br>{_escape(catalog.text('meta.unverified'))}</div></header>
<section class="metrics"><div class="metric"><strong>{len(events)}</strong><span>{_escape(catalog.text('metrics.events'))}</span></div><div class="metric"><strong>{healthy}</strong><span>{_escape(catalog.text('metrics.sources_ok'))}</span></div><div class="metric"><strong>{limited}</strong><span>{_escape(catalog.text('metrics.sources_limited'))}</span></div><div class="metric"><strong>{sum(1 for e in events if _priority_code(e) in {'P0','P1'})}</strong><span>{_escape(catalog.text('metrics.urgent'))}</span></div></section>
<main class="lanes"><section class="lane"><div class="lane-title"><h2>{_escape(catalog.text('sections.c_end'))}</h2><span>{len(lanes['c-end'])}</span></div><div class="cards">{c_cards}</div></section><section class="lane"><div class="lane-title"><h2>{_escape(catalog.text('sections.ecosystem'))}</h2><span>{len(lanes['industry'])}</span></div><div class="cards">{i_cards}</div></section></main>
<footer><span>Loyalty Radar v{_escape(product_version)}</span><span>{_escape(catalog.text('footer.disclosure'))}</span></footer>
<script>function fit(){{const b=document.body;if(b.scrollHeight>1800)b.classList.add('tight');if(b.scrollHeight>1800)b.classList.add('tighter');}}window.addEventListener('load',fit);</script></body></html>"""


def render_markdown(payload: dict[str, Any], locale: str) -> str:
    locale = normalize_locale(locale)
    catalog = load_catalog(locale)
    events = list(payload.get("items", []))
    days = max(1, math.ceil(int(payload.get("hours", 336)) / 24))
    lines = [
        f"# {catalog.text('meta.title')}",
        "",
        f"- {catalog.text('meta.window', days=days)}",
        f"- {catalog.text('meta.future', days=payload.get('future_watch_days', 60))}",
        f"- {catalog.text('meta.generated', value=payload.get('generated_at', ''))}",
        f"- {catalog.text('meta.unverified')}",
        "",
    ]
    for index, event in enumerate(events, 1):
        title = _localized(event, locale, "title", catalog)
        summary = _localized(event, locale, "summary", catalog)
        why = _localized(event, locale, "why_it_matters", catalog)
        lines.extend(
            [
                f"## {index}. [{title}]({_markdown_url(event.get('url'))})",
                "",
                f"- {catalog.text('labels.priority')}: {_label(catalog, 'priority', event.get('priority_tier') or event.get('priority'))}",
                f"- {catalog.text('labels.source')}: {event.get('source', '')}",
                f"- {catalog.text('labels.published')}: {event.get('published_at') or catalog.text('labels.unknown_time')}",
                f"- {catalog.text('labels.vertical')}: {_labels(catalog, 'vertical', event.get('vertical', []))}",
                f"- {catalog.text('labels.topic')}: {_label(catalog, 'topic', event.get('topic_type'))}",
                f"- {catalog.text('labels.action')}: {_label(catalog, 'action', event.get('action_label'))}",
                f"- {catalog.text('labels.risk')}: {_label(catalog, 'risk', event.get('risk_label'))}",
                "",
                summary,
                "",
                f"**{catalog.text('labels.why')}** {why}",
                "",
            ]
        )
        if event.get("evidence"):
            lines.append(f"**{catalog.text('sections.evidence')}**")
            lines.append("")
            for evidence in event["evidence"]:
                evidence_title = _localized(evidence, locale, "title", catalog)
                lines.append(f"- [{evidence_title}]({_markdown_url(evidence.get('url'))}) · {evidence.get('source', '')} · {evidence.get('published_at') or catalog.text('labels.unknown_time')}")
            lines.append("")
    lines.extend(["---", "", catalog.text("footer.disclosure"), "", f"[{catalog.text('footer.project')}]({REPOSITORY_URL})", ""])
    return "\n".join(lines)


def _render_png(
    overview_html: Path,
    output: Path,
    payload: dict[str, Any],
    locale: str,
    width: int = 2400,
    height: int = 1800,
) -> bool:
    try:
        from playwright.sync_api import sync_playwright

        from .engine import chrome_executable_path

        with sync_playwright() as playwright:
            launch_args: dict[str, Any] = {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}
            chrome_path = chrome_executable_path()
            if chrome_path:
                launch_args["executable_path"] = chrome_path
            browser = playwright.chromium.launch(**launch_args)
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(overview_html.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(250)
            page.screenshot(path=str(output), type="png", full_page=False)
            browser.close()
        return True
    except Exception:  # noqa: BLE001
        return _render_png_with_pillow(payload, locale, output, width, height)


def _render_png_with_pillow(payload: dict[str, Any], locale: str, output: Path, width: int, height: int) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    catalog = load_catalog(locale)
    image = Image.new("RGB", (width, height), "#f3f3ef")
    draw = ImageDraw.Draw(image)
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    font_path = next((path for path in candidates if Path(path).exists()), None)

    def font(size: int) -> Any:
        return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    def wrap(value: str, font_object: Any, max_width: int) -> list[str]:
        lines: list[str] = []
        current = ""
        tokens = list(value) if locale == "zh-CN" else re.findall(r"\S+\s*", value)
        for token in tokens:
            candidate = current + token
            if draw.textbbox((0, 0), candidate, font=font_object)[2] <= max_width:
                current = candidate
                continue
            if current.strip():
                lines.append(current.rstrip())
            current = token.lstrip()
        if current.strip():
            lines.append(current.rstrip())
        return lines or [""]

    def draw_lines(x: int, y: int, lines: list[str], font_object: Any, fill: str, gap: int = 5) -> int:
        line_height = int(font_object.size * 1.25) if hasattr(font_object, "size") else 18
        for line in lines:
            draw.text((x, y), line, font=font_object, fill=fill)
            y += line_height + gap
        return y

    margin = 62
    draw.text((margin, 38), catalog.text("meta.window", days=max(1, math.ceil(int(payload.get("hours", 336)) / 24))), fill="#2458a6", font=font(18))
    draw.text((margin, 76), catalog.text("meta.title"), fill="#17202a", font=font(62))
    draw.text((margin, 154), catalog.text("meta.subtitle"), fill="#667085", font=font(22))
    draw.line((margin, 208, width - margin, 208), fill="#17202a", width=3)

    events = select_overview_events(list(payload.get("items", [])), locale, catalog)
    lane_events = {
        "c-end": [event for event in events if _lane(event) == "c-end"],
        "industry": [event for event in events if _lane(event) == "industry"],
    }
    # The deterministic fallback favors complete text over event count.
    for lane in lane_events:
        lane_events[lane] = lane_events[lane][:2]

    lane_gap = 28
    lane_width = (width - margin * 2 - lane_gap) // 2
    lane_top = 246
    card_top = 302
    card_bottom = height - 68
    for lane_index, (lane, heading_key) in enumerate(
        (("c-end", "sections.c_end"), ("industry", "sections.ecosystem"))
    ):
        x0 = margin + lane_index * (lane_width + lane_gap)
        x1 = x0 + lane_width
        draw.text((x0, lane_top), catalog.text(heading_key), fill="#17202a", font=font(29))
        draw.line((x0, lane_top + 43, x1, lane_top + 43), fill="#17202a", width=2)
        rows = lane_events[lane]
        if not rows:
            draw.rectangle((x0, card_top, x1, card_top + 120), outline="#d4d6d2", fill="#ffffff")
            draw.text((x0 + 20, card_top + 35), catalog.text("labels.no_items"), fill="#667085", font=font(18))
            continue
        gap = 14
        card_height = (card_bottom - card_top - gap * (len(rows) - 1)) // len(rows)
        for index, event in enumerate(rows):
            y0 = card_top + index * (card_height + gap)
            y1 = y0 + card_height
            draw.rounded_rectangle((x0, y0, x1, y1), radius=6, outline="#d4d6d2", fill="#ffffff")
            inner_x = x0 + 20
            inner_width = lane_width - 40
            y = y0 + 16
            badge = f"{_priority_code(event)} · {_label(catalog, 'action', event.get('action_label'))} · {_label(catalog, 'risk', event.get('risk_label'))}"
            y = draw_lines(inner_x, y, wrap(badge, font(14), inner_width), font(14), "#2458a6", 3) + 5
            title_text = _localized(event, locale, "title", catalog)
            summary_text = _localized(event, locale, "summary", catalog)
            why_text = f"{catalog.text('labels.why')}: {_localized(event, locale, 'why_it_matters', catalog)}"
            selected_layout = None
            for title_size, body_size, small_size in ((23, 17, 14), (20, 15, 13), (18, 13, 11)):
                title_lines = wrap(title_text, font(title_size), inner_width)
                summary_lines = wrap(summary_text, font(body_size), inner_width)
                why_lines = wrap(why_text, font(small_size), inner_width)
                required = (
                    len(title_lines) * (title_size + 8)
                    + len(summary_lines) * (body_size + 7)
                    + len(why_lines) * (small_size + 6)
                    + 96
                )
                if y + required <= y1:
                    selected_layout = (title_size, body_size, small_size, title_lines, summary_lines, why_lines)
                    break
            if selected_layout is None:
                selected_layout = (18, 11, 10, wrap(title_text, font(18), inner_width), wrap(summary_text, font(11), inner_width), wrap(why_text, font(10), inner_width))
            title_size, body_size, small_size, title_lines, summary_lines, why_lines = selected_layout
            y = draw_lines(inner_x, y, title_lines, font(title_size), "#17202a", 5) + 7
            y = draw_lines(inner_x, y, summary_lines, font(body_size), "#17202a", 4) + 7
            draw.line((inner_x, y, x1 - 20, y), fill="#d4d6d2", width=1)
            y = draw_lines(inner_x, y + 8, why_lines, font(small_size), "#2458a6", 3) + 6
            meta = f"{event.get('source', '')} · {str(event.get('published_at') or '')[:10]}"
            draw_lines(inner_x, y, wrap(meta, font(small_size), inner_width), font(small_size), "#667085", 3)
    draw.text((margin, height - 38), f"Loyalty Radar v{_product_version(payload)} · {catalog.text('meta.unverified')}", fill="#667085", font=font(13))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return True


def render_locale(
    payload: dict[str, Any],
    locale: str,
    output_dir: Path,
    stem: str,
    locales: list[str],
    *,
    image: bool = True,
) -> RenderedArtifacts:
    locale = normalize_locale(locale)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"{stem}-{locale}.html"
    overview_path = output_dir / f"{stem}-{locale}-overview.html"
    markdown_path = output_dir / f"{stem}-{locale}.md"
    png_path = output_dir / f"{stem}-{locale}.png" if image else None
    html_path.write_text(render_html(payload, locale, stem, locales), encoding="utf-8")
    overview_path.write_text(render_overview_html(payload, locale), encoding="utf-8")
    markdown_path.write_text(render_markdown(payload, locale), encoding="utf-8")
    if png_path is not None and not _render_png(overview_path, png_path, payload, locale):
        png_path = None
    return RenderedArtifacts(locale, html_path, overview_path, markdown_path, png_path)
