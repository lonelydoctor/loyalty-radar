#!/usr/bin/env python3
"""Build the bilingual public Source Catalog and release visuals.

The public site contains only source metadata read from committed Source Packs.
It never creates or publishes a news, offer, datapoint, or loyalty-event snapshot.
"""

from __future__ import annotations

import argparse
import html
import shutil
import sys
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPTS = ROOT / "plugins/loyalty-radar/skills/loyalty-radar/scripts"
if str(PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SCRIPTS))

from loyalty_radar.engine import chrome_executable_path  # noqa: E402
from loyalty_radar.i18n import Catalog, load_catalog  # noqa: E402
from loyalty_radar.sources import list_packs, validate_all_packs  # noqa: E402

SITE_DIR = ROOT / "docs/site"
ASSETS_DIR = ROOT / "docs/assets"
PLUGIN_ASSETS_DIR = ROOT / "plugins/loyalty-radar/assets"
PACK_DIR = ROOT / "plugins/loyalty-radar/skills/loyalty-radar/references/source-packs"
LOCALES = ("en", "zh-CN")
COLORS = {
    "ink": "#17212B",
    "muted": "#66717E",
    "paper": "#F3F3EF",
    "surface": "#FFFFFF",
    "line": "#D4D7D3",
    "blue": "#2458A6",
    "green": "#14715A",
    "coral": "#B74B3D",
    "gold": "#956414",
}


def load_catalog_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors = validate_all_packs(PACK_DIR)
    if errors:
        raise ValueError("; ".join(errors))
    packs: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for pack in list_packs(PACK_DIR):
        pack_row = {
            "id": pack.pack_id,
            "name": pack.name,
            "description": pack.description,
            "default_enabled": pack.default_enabled,
            "count": len(pack.sources),
        }
        packs.append(pack_row)
        for source in pack.sources:
            row = dict(source)
            row["pack_id"] = pack.pack_id
            row["pack_default"] = pack.default_enabled
            sources.append(row)
    if len(sources) != 59:
        raise ValueError(f"Expected the v0.1.0 59-source baseline, found {len(sources)}")
    return packs, sources


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def source_card(source: dict[str, Any], catalog: Catalog) -> str:
    enabled = bool(source.get("enabled", True))
    status_label = catalog.text("catalog.enabled") if enabled else catalog.text("catalog.disabled")
    method = str(source.get("fetch_method") or "")
    programs = " / ".join(str(value) for value in source.get("programs", [])[:5]) or "-"
    fields = (
        (catalog.text("catalog.pack"), source.get("pack_id")),
        (catalog.text("catalog.priority"), source.get("priority")),
        (catalog.text("catalog.method"), catalog.get(f"fetch_method.{method}", method)),
        (catalog.text("catalog.language"), source.get("language")),
        (catalog.text("catalog.region"), source.get("region")),
        (catalog.text("catalog.programs"), programs),
    )
    facts = "".join(f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>" for label, value in fields)
    search = " ".join(
        str(value)
        for value in (
            source.get("name"),
            source.get("site"),
            source.get("pack_id"),
            source.get("region"),
            source.get("language"),
            programs,
        )
    ).lower()
    return f"""<article class="source-card" data-search="{esc(search)}"
 data-pack="{esc(source.get('pack_id'))}" data-method="{esc(method)}" data-priority="{esc(source.get('priority'))}">
 <div class="source-head"><span class="source-priority">{esc(source.get('priority'))}</span><span class="source-status {'disabled' if not enabled else ''}">{esc(status_label)}</span></div>
 <h2>{esc(source.get('name'))}</h2>
 <p class="publisher">{esc(source.get('site'))}</p>
 <dl>{facts}</dl>
 <a class="source-link" href="{esc(source.get('url'))}" target="_blank" rel="noreferrer">{esc(catalog.text('catalog.open_source'))}</a>
</article>"""


def source_page(locale: str, packs: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
    catalog = load_catalog(locale)
    lang = "zh-CN" if locale == "zh-CN" else "en"
    other = "en" if locale == "zh-CN" else "zh-CN"
    script_eligible = sum(
        bool(source.get("enabled", True)) and source.get("fetch_method") != "browser_only" for source in sources
    )
    browser_assisted = sum(source.get("fetch_method") == "browser_only" for source in sources)
    pack_options = "".join(
        f'<option value="{esc(pack["id"])}">{esc(pack["id"])} ({pack["count"]})</option>' for pack in packs
    )
    method_options = "".join(
        f'<option value="{method}">{esc(catalog.get(f"fetch_method.{method}", method))}</option>'
        for method in ("rss", "flyert_forum", "html_keyword", "browser_only")
    )
    pack_rows = "".join(
        f'<button type="button" class="pack-button" data-pack-button="{esc(pack["id"])}"><strong>{esc(pack["id"])}</strong><span>{pack["count"]}</span><small>{esc(catalog.text("catalog.default_enabled") if pack["default_enabled"] else catalog.text("catalog.optional"))}</small></button>'
        for pack in packs
    )
    cards = "".join(source_card(source, catalog) for source in sources)
    locale_name = catalog.get(f"languages.{locale}", locale)
    other_name = catalog.get(f"languages.{other}", other)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(catalog.text('catalog.title'))} · Loyalty Radar</title>
<meta name="description" content="{esc(catalog.text('catalog.subtitle'))}">
<meta property="og:type" content="website"><meta property="og:title" content="Loyalty Radar · {esc(catalog.text('catalog.title'))}">
<meta property="og:description" content="{esc(catalog.text('catalog.notice'))}"><meta property="og:image" content="../assets/social-preview.png">
<link rel="icon" type="image/png" href="../assets/icon-128.png">
<style>
:root{{--ink:#17212b;--muted:#66717e;--paper:#f3f3ef;--surface:#fff;--line:#d4d7d3;--blue:#2458a6;--green:#14715a;--coral:#b74b3d;--gold:#956414}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;letter-spacing:0}}
a{{color:inherit}}.topbar{{height:58px;padding:0 4vw;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);background:rgba(243,243,239,.96);position:sticky;top:0;z-index:10}}.brand{{font-weight:800;text-decoration:none}}.language{{display:flex;gap:5px;align-items:center;font-size:13px}}.language a{{padding:7px 9px;text-decoration:none;border-bottom:2px solid transparent}}.language a.current{{color:var(--blue);border-color:var(--blue)}}
header{{background:var(--surface);padding:50px 4vw 36px;border-bottom:1px solid var(--line)}}.eyebrow{{font-size:12px;font-weight:800;color:var(--blue);text-transform:uppercase}}h1{{font-size:clamp(40px,5vw,72px);line-height:1.32;margin:8px 0 11px;letter-spacing:0}}.subtitle{{font-size:18px;color:var(--muted);line-height:1.6;max-width:940px;margin:0}}.notice{{margin:24px 0 0;border-left:4px solid var(--gold);padding:10px 14px;background:#fffaf0;max-width:1000px;font-size:13px;line-height:1.55}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);background:var(--surface);border-bottom:1px solid var(--line)}}.metric{{padding:21px 4vw;border-right:1px solid var(--line)}}.metric:last-child{{border-right:0}}.metric strong{{display:block;font-size:30px}}.metric span{{font-size:13px;color:var(--muted)}}
main{{width:min(1680px,92vw);margin:0 auto;padding:38px 0 72px}}.section-heading{{display:flex;align-items:end;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:8px;margin-bottom:14px}}.section-heading h2{{font-size:24px;margin:0}}.section-heading span{{font-size:13px;color:var(--muted)}}
.pack-strip{{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line);background:var(--surface);margin-bottom:34px}}.pack-button{{appearance:none;border:0;border-right:1px solid var(--line);background:var(--surface);padding:16px;text-align:left;color:var(--ink);cursor:pointer;min-height:96px}}.pack-button:last-child{{border-right:0}}.pack-button:hover,.pack-button:focus{{background:#f4f7fc;outline:2px solid var(--blue);outline-offset:-2px}}.pack-button strong,.pack-button span,.pack-button small{{display:block}}.pack-button span{{font-size:25px;margin:5px 0}}.pack-button small{{color:var(--muted)}}
.controls{{display:grid;grid-template-columns:minmax(260px,2fr) repeat(3,minmax(150px,1fr));gap:10px;position:sticky;top:58px;z-index:8;background:var(--paper);padding:12px 0}}input,select{{width:100%;min-height:43px;border:1px solid #b7bcb8;border-radius:4px;background:var(--surface);color:var(--ink);font:inherit;font-size:14px;padding:8px 11px}}
.source-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.source-card{{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:17px;min-width:0;display:flex;flex-direction:column}}.source-card[hidden]{{display:none}}.source-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}}.source-priority{{font-weight:800;color:var(--coral);font-size:11px}}.source-status{{font-size:11px;color:var(--green);font-weight:700}}.source-status.disabled{{color:var(--gold)}}.source-card h2{{font-size:18px;line-height:1.3;margin:0;overflow-wrap:anywhere;letter-spacing:0}}.publisher{{font-size:12px;color:var(--muted);margin:5px 0 14px}}.source-card dl{{display:grid;grid-template-columns:1fr 1fr;margin:0 0 14px;border-top:1px solid var(--line);border-left:1px solid var(--line)}}.source-card dl div{{padding:8px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-width:0}}.source-card dt{{font-size:10px;color:var(--muted);margin-bottom:2px}}.source-card dd{{margin:0;font-size:12px;overflow-wrap:anywhere}}.source-link{{margin-top:auto;color:var(--blue);font-size:12px;font-weight:800;text-decoration:none}}.source-link:hover{{text-decoration:underline}}.empty{{display:none;padding:34px;text-align:center;border:1px solid var(--line);background:var(--surface);color:var(--muted)}}.empty.visible{{display:block}}
footer{{padding:25px 4vw 38px;border-top:1px solid var(--line);background:var(--surface);color:var(--muted);font-size:12px;line-height:1.7}}footer a{{color:var(--blue)}}
@media(max-width:1050px){{.source-grid{{grid-template-columns:1fr 1fr}}.pack-strip{{grid-template-columns:repeat(3,1fr)}}.pack-button{{border-bottom:1px solid var(--line)}}}}
@media(max-width:680px){{header{{padding-top:34px}}h1{{font-size:42px}}.metrics{{grid-template-columns:1fr 1fr}}.metric:nth-child(2){{border-right:0}}main{{width:94vw;padding-top:24px}}.pack-strip{{grid-template-columns:1fr 1fr}}.pack-button:nth-child(2n){{border-right:0}}.controls{{position:static;grid-template-columns:1fr}}.source-grid{{grid-template-columns:1fr}}.source-card dl{{grid-template-columns:1fr 1fr}}.topbar{{padding:0 3vw}}}}
</style></head><body>
<div class="topbar"><a class="brand" href="#top">Loyalty Radar</a><nav class="language" aria-label="{esc(catalog.text('navigation.language'))}"><a class="current" href="../{locale}/">{esc(locale_name)}</a><a href="../{other}/">{esc(other_name)}</a></nav></div>
<header id="top"><div class="eyebrow">{esc(catalog.text('catalog.version'))}</div><h1>{esc(catalog.text('catalog.title'))}</h1><p class="subtitle">{esc(catalog.text('catalog.subtitle'))}</p><p class="notice" data-critical-text>{esc(catalog.text('catalog.notice'))}</p></header>
<section class="metrics" data-layout-check><div class="metric"><strong>{len(sources)}</strong><span>{esc(catalog.text('catalog.configured_sources'))}</span></div><div class="metric"><strong>{len(packs)}</strong><span>{esc(catalog.text('catalog.source_packs'))}</span></div><div class="metric"><strong>{script_eligible}</strong><span>{esc(catalog.text('catalog.script_collectors'))}</span></div><div class="metric"><strong>{browser_assisted}</strong><span>{esc(catalog.text('catalog.browser_assisted'))}</span></div></section>
<main><section data-layout-check><div class="section-heading"><h2>{esc(catalog.text('catalog.source_packs'))}</h2><span>{len(packs)}</span></div><div class="pack-strip">{pack_rows}</div></section>
<section data-layout-check><div class="section-heading"><h2>{esc(catalog.text('catalog.configured_sources'))}</h2><span><span id="visible-count">{len(sources)}</span> / {len(sources)}</span></div>
<div class="controls"><input id="search" type="search" placeholder="{esc(catalog.text('catalog.search'))}" aria-label="{esc(catalog.text('catalog.search'))}"><select id="pack" aria-label="{esc(catalog.text('catalog.pack_filter'))}"><option value="all">{esc(catalog.text('catalog.all'))}</option>{pack_options}</select><select id="method" aria-label="{esc(catalog.text('catalog.method_filter'))}"><option value="all">{esc(catalog.text('catalog.all'))}</option>{method_options}</select><select id="priority" aria-label="{esc(catalog.text('catalog.priority_filter'))}"><option value="all">{esc(catalog.text('catalog.all'))}</option><option>P0</option><option>P1</option><option>P2</option></select></div>
<div class="source-grid" id="source-grid">{cards}</div><div class="empty" id="empty">{esc(catalog.text('catalog.no_results'))}</div></section></main>
<footer><div>{esc(catalog.text('catalog.collection_boundary'))}</div><div>{esc(catalog.text('catalog.notice'))}</div><a href="https://github.com/lonelydoctor/loyalty-radar">Loyalty Radar</a></footer>
<script>
const cards=[...document.querySelectorAll('.source-card')];const search=document.getElementById('search');const pack=document.getElementById('pack');const method=document.getElementById('method');const priority=document.getElementById('priority');
function apply(){{const query=search.value.trim().toLowerCase();let visible=0;cards.forEach(card=>{{card.hidden=!!((query&&!card.dataset.search.includes(query))||(pack.value!=='all'&&card.dataset.pack!==pack.value)||(method.value!=='all'&&card.dataset.method!==method.value)||(priority.value!=='all'&&card.dataset.priority!==priority.value));if(!card.hidden)visible+=1}});document.getElementById('visible-count').textContent=visible;document.getElementById('empty').classList.toggle('visible',visible===0)}}
[search,pack,method,priority].forEach(control=>control.addEventListener(control===search?'input':'change',apply));document.querySelectorAll('[data-pack-button]').forEach(button=>button.addEventListener('click',()=>{{pack.value=button.dataset.packButton;apply();document.querySelector('.controls').scrollIntoView({{behavior:'smooth'}})}}));apply();
</script></body></html>"""


def write_site(packs: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for locale in LOCALES:
        path = SITE_DIR / locale / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source_page(locale, packs, sources), encoding="utf-8")
        paths[locale] = path
    chooser = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Loyalty Radar</title><link rel="icon" type="image/png" href="assets/icon-128.png"><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f3ef;color:#17212b;font-family:Inter,"Noto Sans SC","PingFang SC",system-ui,sans-serif;letter-spacing:0}.chooser{width:min(680px,92vw);border-top:3px solid #17212b;padding:30px 0}h1{font-size:48px;line-height:1;margin:20px 0 8px}p{color:#66717e}.links{display:grid;grid-template-columns:1fr 1fr;border:1px solid #d4d7d3;background:#fff;margin-top:28px}.links a{padding:24px;text-decoration:none;font-weight:800;font-size:19px}.links a+a{border-left:1px solid #d4d7d3}@media(max-width:520px){.links{grid-template-columns:1fr}.links a+a{border-left:0;border-top:1px solid #d4d7d3}}</style></head><body><main class="chooser"><img src="assets/icon-128.png" width="64" height="64" alt=""><h1>Loyalty Radar</h1><p>Public source catalog · 公开来源目录</p><nav class="links" aria-label="Language / 语言"><a href="en/">English</a><a href="zh-CN/">简体中文</a></nav></main></body></html>"""
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(chooser, encoding="utf-8")
    (SITE_DIR / ".nojekyll").write_text("", encoding="ascii")
    return paths


@lru_cache(maxsize=64)
def font(size: int, locale: str = "en", bold: bool = False) -> Any:
    candidates = []
    if locale == "zh-CN":
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "C:/Windows/Fonts/msyh.ttc",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        ]
    )
    path = next((value for value in candidates if Path(value).exists()), None)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def measure(draw: Any, value: str, font_object: Any) -> int:
    box = draw.textbbox((0, 0), value, font=font_object)
    return int(box[2] - box[0])


def wrap(draw: Any, value: str, font_object: Any, width: int, locale: str) -> list[str]:
    tokens = list(value) if locale == "zh-CN" else value.split()
    separator = "" if locale == "zh-CN" else " "
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = token if not current else current + separator + token
        if measure(draw, candidate, font_object) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def draw_lines(draw: Any, lines: list[str], x: int, y: int, font_object: Any, fill: str, gap: int = 5) -> int:
    height = int(getattr(font_object, "size", 14) * 1.25) + gap
    for line in lines:
        draw.text((x, y), line, font=font_object, fill=fill)
        y += height
    return y


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="PNG", optimize=False)


def draw_icon(size: int, path: Path) -> None:
    scale = 4
    canvas = size * scale
    image = Image.new("RGB", (canvas, canvas), COLORS["blue"])
    draw = ImageDraw.Draw(image)
    center = canvas // 2
    for radius, color in ((0.34, "#9DB7DF"), (0.23, "#C6D6EE"), (0.12, "#E7EEF8")):
        value = int(canvas * radius)
        draw.ellipse((center - value, center - value, center + value, center + value), outline=color, width=max(2, canvas // 90))
    draw.line((center, center, int(canvas * 0.82), int(canvas * 0.25)), fill="#FFFFFF", width=max(3, canvas // 52))
    dot = max(5, canvas // 25)
    draw.ellipse((center - dot, center - dot, center + dot, center + dot), fill="#FFFFFF")
    signal = max(6, canvas // 21)
    x, y = int(canvas * 0.73), int(canvas * 0.33)
    draw.ellipse((x - signal, y - signal, x + signal, y + signal), fill="#F2B84B")
    save_png(image.resize((size, size), Image.Resampling.LANCZOS), path)


def draw_overview(locale: str, packs: list[dict[str, Any]], sources: list[dict[str, Any]], path: Path) -> None:
    catalog = load_catalog(locale)
    image = Image.new("RGB", (2400, 1800), COLORS["paper"])
    draw = ImageDraw.Draw(image)
    margin = 62
    draw.text((margin, 43), catalog.text("catalog.version"), font=font(18, locale, True), fill=COLORS["blue"])
    draw.text((margin, 80), catalog.text("catalog.title"), font=font(64, locale, True), fill=COLORS["ink"])
    draw.text((margin, 157), catalog.text("catalog.subtitle"), font=font(22, locale), fill=COLORS["muted"])
    draw.line((margin, 210, 2338, 210), fill=COLORS["ink"], width=3)
    script_count = sum(source.get("enabled", True) and source.get("fetch_method") != "browser_only" for source in sources)
    browser_count = sum(source.get("fetch_method") == "browser_only" for source in sources)
    metrics = [
        (len(sources), catalog.text("catalog.configured_sources")),
        (len(packs), catalog.text("catalog.source_packs")),
        (script_count, catalog.text("catalog.script_collectors")),
        (browser_count, catalog.text("catalog.browser_assisted")),
    ]
    metric_width = (2338 - margin) // 4
    for index, (value, label) in enumerate(metrics):
        x0 = margin + index * metric_width
        x1 = margin + (index + 1) * metric_width
        draw.rectangle((x0, 232, x1, 330), fill=COLORS["surface"], outline=COLORS["line"])
        draw.text((x0 + 18, 246), str(value), font=font(31, locale, True), fill=COLORS["ink"])
        draw.text((x0 + 18, 293), label, font=font(14, locale), fill=COLORS["muted"])

    placements = [(62, 370, 782, 1015), (810, 370, 1530, 1015), (1558, 370, 2338, 1015), (62, 1043, 1150, 1718), (1178, 1043, 2338, 1718)]
    sources_by_pack = {pack["id"]: [source for source in sources if source["pack_id"] == pack["id"]] for pack in packs}
    for pack, box in zip(packs, placements, strict=True):
        x0, y0, x1, y1 = box
        draw.rounded_rectangle(box, radius=7, fill=COLORS["surface"], outline=COLORS["line"])
        draw.text((x0 + 20, y0 + 18), pack["id"], font=font(25, locale, True), fill=COLORS["ink"])
        count = str(pack["count"])
        draw.text((x1 - 20 - measure(draw, count, font(24, locale, True)), y0 + 20), count, font=font(24, locale, True), fill=COLORS["blue"])
        posture = catalog.text("catalog.default_enabled") if pack["default_enabled"] else catalog.text("catalog.optional")
        draw.text((x0 + 20, y0 + 58), posture, font=font(13, locale, True), fill=COLORS["green"] if pack["default_enabled"] else COLORS["gold"])
        description = catalog.get(f"source_pack_description.{pack['id']}", pack["description"])
        y = draw_lines(draw, wrap(draw, description, font(15, locale), x1 - x0 - 40, locale), x0 + 20, y0 + 91, font(15, locale), COLORS["muted"], 5) + 15
        draw.line((x0 + 20, y, x1 - 20, y), fill=COLORS["line"])
        y += 14
        available = y1 - y - 25
        source_font = font(15, locale, True)
        line_height = 27
        max_rows = max(1, available // line_height)
        rows = sources_by_pack[pack["id"]]
        visible_rows = rows[: max_rows - 1] if len(rows) > max_rows else rows
        for source in visible_rows:
            lines = wrap(draw, str(source["name"]), source_font, x1 - x0 - 80, locale)
            draw.text((x0 + 22, y), str(source["priority"]), font=font(11, locale, True), fill=COLORS["coral"])
            y = draw_lines(draw, lines[:2], x0 + 64, y - 2, source_font, COLORS["ink"], 3) + 7
        remaining = len(rows) - len(visible_rows)
        if remaining > 0:
            draw.text((x0 + 22, min(y, y1 - 32)), f"+ {remaining}", font=font(14, locale, True), fill=COLORS["blue"])
    draw.text((margin, 1760), catalog.text("catalog.notice"), font=font(13, locale), fill=COLORS["muted"])
    save_png(image, path)


def draw_social(packs: list[dict[str, Any]], sources: list[dict[str, Any]], path: Path) -> None:
    image = Image.new("RGB", (1280, 640), COLORS["paper"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 20, 640), fill=COLORS["blue"])
    draw.text((70, 58), "PUBLIC SOURCE CATALOG", font=font(15, "en", True), fill=COLORS["blue"])
    draw.text((70, 98), "Loyalty Radar", font=font(58, "en", True), fill=COLORS["ink"])
    draw.text((70, 184), "Loyalty intelligence with\nsource health and audit trails.", font=font(23, "en"), fill=COLORS["muted"], spacing=9)
    draw.text((70, 302), str(len(sources)), font=font(38, "en", True), fill=COLORS["ink"])
    draw.text((70, 350), "configured public sources", font=font(14, "en"), fill=COLORS["muted"])
    draw.text((70, 407), "PLUGIN  ·  AGENT SKILL  ·  CLI", font=font(13, "en", True), fill=COLORS["green"])
    draw.text((70, 461), "English + 简体中文", font=font(20, "zh-CN"), fill=COLORS["ink"])
    draw.text((70, 512), "Public beta v0.1.0", font=font(16, "en"), fill=COLORS["muted"])
    draw.rounded_rectangle((610, 48, 1225, 592), radius=7, fill=COLORS["surface"], outline=COLORS["line"])
    y = 78
    for pack in packs:
        draw.text((640, y), pack["id"], font=font(18, "en", True), fill=COLORS["ink"])
        draw.text((1120, y), str(pack["count"]), font=font(18, "en", True), fill=COLORS["blue"])
        draw.line((640, y + 39, 1195, y + 39), fill=COLORS["line"])
        y += 96
    save_png(image, path)


def draw_fallback_screenshot(locale: str, packs: list[dict[str, Any]], sources: list[dict[str, Any]], path: Path, size: tuple[int, int]) -> None:
    catalog = load_catalog(locale)
    width, height = size
    image = Image.new("RGB", size, COLORS["paper"])
    draw = ImageDraw.Draw(image)
    margin = 16 if width < 600 else 54
    draw.rectangle((0, 0, width, 54), fill=COLORS["paper"])
    draw.text((margin, 17), "Loyalty Radar", font=font(16, locale, True), fill=COLORS["ink"])
    draw.rectangle((0, 54, width, 245 if width < 600 else 284), fill=COLORS["surface"])
    draw.text((margin, 79), catalog.text("catalog.version"), font=font(11 if width < 600 else 13, locale, True), fill=COLORS["blue"])
    title_size = 34 if width < 600 else 50
    y = draw_lines(draw, wrap(draw, catalog.text("catalog.title"), font(title_size, locale, True), width - margin * 2, locale), margin, 108, font(title_size, locale, True), COLORS["ink"], 4) + 8
    draw_lines(draw, wrap(draw, catalog.text("catalog.notice"), font(12 if width < 600 else 15, locale), width - margin * 2, locale), margin, y, font(12 if width < 600 else 15, locale), COLORS["muted"], 4)
    metric_top = 245 if width < 600 else 284
    metric_values = (len(sources), len(packs), sum(source.get("enabled", True) and source.get("fetch_method") != "browser_only" for source in sources), sum(source.get("fetch_method") == "browser_only" for source in sources))
    metric_labels = (catalog.text("catalog.configured_sources"), catalog.text("catalog.source_packs"), catalog.text("catalog.script_collectors"), catalog.text("catalog.browser_assisted"))
    columns = 2 if width < 600 else 4
    cell_w = width // columns
    cell_h = 78
    for index, (value, label) in enumerate(zip(metric_values, metric_labels, strict=True)):
        row, column = divmod(index, columns)
        x0, y0 = column * cell_w, metric_top + row * cell_h
        draw.rectangle((x0, y0, x0 + cell_w, y0 + cell_h), fill=COLORS["surface"], outline=COLORS["line"])
        draw.text((x0 + margin, y0 + 9), str(value), font=font(24, locale, True), fill=COLORS["ink"])
        draw.text((x0 + margin, y0 + 45), label, font=font(10, locale), fill=COLORS["muted"])
    y = metric_top + (2 if width < 600 else 1) * cell_h + 30
    draw.text((margin, y), catalog.text("catalog.source_packs"), font=font(20, locale, True), fill=COLORS["ink"])
    y += 38
    for pack in packs:
        if y + 76 > height - 20:
            break
        draw.rounded_rectangle((margin, y, width - margin, y + 68), radius=5, fill=COLORS["surface"], outline=COLORS["line"])
        draw.text((margin + 13, y + 11), pack["id"], font=font(14, locale, True), fill=COLORS["ink"])
        draw.text((width - margin - 42, y + 11), str(pack["count"]), font=font(15, locale, True), fill=COLORS["blue"])
        description = catalog.get(f"source_pack_description.{pack['id']}", pack["description"])
        draw_lines(draw, wrap(draw, description, font(10, locale), width - margin * 2 - 26, locale)[:2], margin + 13, y + 35, font(10, locale), COLORS["muted"], 2)
        y += 77
    save_png(image, path)


def gif_frame(packs: list[dict[str, Any]], sources: list[dict[str, Any]], active_pack: str) -> Image.Image:
    image = Image.new("RGB", (960, 600), COLORS["paper"])
    draw = ImageDraw.Draw(image)
    draw.text((28, 20), "Loyalty Radar", font=font(17, "en", True), fill=COLORS["ink"])
    draw.rectangle((0, 55, 960, 151), fill=COLORS["surface"])
    draw.text((28, 72), "Public source catalog", font=font(31, "en", True), fill=COLORS["ink"])
    draw.text((28, 116), "Repository configuration · no news snapshot", font=font(13, "en"), fill=COLORS["muted"])
    x = 28
    for pack in packs:
        active = pack["id"] == active_pack
        box_width = 165
        draw.rounded_rectangle((x, 170, x + box_width, 208), radius=4, fill="#F1F5FC" if active else COLORS["surface"], outline=COLORS["blue"] if active else COLORS["line"])
        draw.text((x + 10, 182), f"{pack['id']} {pack['count']}", font=font(11, "en", active), fill=COLORS["blue"] if active else COLORS["muted"])
        x += box_width + 10
    rows = [source for source in sources if source["pack_id"] == active_pack][:4]
    y = 230
    for source in rows:
        draw.rounded_rectangle((28, y, 932, y + 76), radius=5, fill=COLORS["surface"], outline=COLORS["line"])
        draw.text((43, y + 14), str(source["priority"]), font=font(11, "en", True), fill=COLORS["coral"])
        draw.text((91, y + 11), str(source["name"]), font=font(16, "en", True), fill=COLORS["ink"])
        draw.text((91, y + 43), f"{source['fetch_method']} · {source['language']} · {source['region']}", font=font(11, "en"), fill=COLORS["muted"])
        y += 87
    return image


def save_gif(frames: list[Image.Image], path: Path) -> None:
    palette = [frame.quantize(colors=96, method=Image.Quantize.MEDIANCUT) for frame in frames]
    duration = round(15_000 / len(palette))
    palette[0].save(path, save_all=True, append_images=palette[1:], duration=duration, loop=0, disposal=2, optimize=False)


def playwright_assets(site_paths: dict[str, Path], packs: list[dict[str, Any]]) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        launch: dict[str, Any] = {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}
        chrome = chrome_executable_path()
        if chrome:
            launch["executable_path"] = chrome
        browser = playwright.chromium.launch(**launch)
        for locale in LOCALES:
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
            page.goto(site_paths[locale].resolve().as_uri(), wait_until="load")
            page.screenshot(path=str(ASSETS_DIR / f"report-desktop-{locale}.png"), full_page=False)
            page.close()
            page = browser.new_page(viewport={"width": 390, "height": 1320}, device_scale_factor=1)
            page.goto(site_paths[locale].resolve().as_uri(), wait_until="load")
            page.screenshot(path=str(ASSETS_DIR / f"report-mobile-{locale}.png"), full_page=False)
            page.close()
        page = browser.new_page(viewport={"width": 960, "height": 600}, device_scale_factor=1)
        page.goto(site_paths["en"].resolve().as_uri(), wait_until="load")
        frame_paths: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="loyalty-radar-catalog-") as directory:
            temporary = Path(directory)
            for index, pack in enumerate(packs[:4]):
                page.select_option("#pack", pack["id"])
                page.evaluate("window.scrollTo(0, document.querySelector('.controls').offsetTop - 70)")
                page.wait_for_timeout(100)
                frame = temporary / f"frame-{index}.png"
                page.screenshot(path=str(frame), full_page=False)
                frame_paths.append(frame)
            frames = [Image.open(frame).convert("RGB").resize((960, 600), Image.Resampling.LANCZOS) for frame in frame_paths]
            save_gif(frames, ASSETS_DIR / "catalog-en.gif")
        page.close()
        browser.close()


def fallback_assets(packs: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    for locale in LOCALES:
        draw_fallback_screenshot(locale, packs, sources, ASSETS_DIR / f"report-desktop-{locale}.png", (1440, 1100))
        draw_fallback_screenshot(locale, packs, sources, ASSETS_DIR / f"report-mobile-{locale}.png", (390, 1320))
    save_gif([gif_frame(packs, sources, pack["id"]) for pack in packs[:4]], ASSETS_DIR / "catalog-en.gif")


def build_assets(packs: list[dict[str, Any]], sources: list[dict[str, Any]], site_paths: dict[str, Path], renderer: str) -> tuple[str, str | None]:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for locale in LOCALES:
        draw_overview(locale, packs, sources, ASSETS_DIR / f"overview-{locale}.png")
    draw_social(packs, sources, ASSETS_DIR / "social-preview.png")
    draw_icon(128, ASSETS_DIR / "icon-128.png")
    draw_icon(512, ASSETS_DIR / "icon-512.png")
    backend = "pillow"
    fallback: str | None = None
    if renderer in {"auto", "playwright"}:
        try:
            playwright_assets(site_paths, packs)
            backend = "playwright"
        except Exception as exc:  # noqa: BLE001
            fallback = f"{type(exc).__name__}: {str(exc).splitlines()[0][:180]}"
            if renderer == "playwright":
                raise
            fallback_assets(packs, sources)
    else:
        fallback_assets(packs, sources)
    site_assets = SITE_DIR / "assets"
    site_assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ASSETS_DIR / "icon-128.png", site_assets / "icon-128.png")
    shutil.copyfile(ASSETS_DIR / "social-preview.png", site_assets / "social-preview.png")
    PLUGIN_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    plugin_assets = {
        "icon-128.png": "icon-128.png",
        "icon-512.png": "logo.png",
        "overview-en.png": "screenshot-overview.png",
        "report-desktop-zh-CN.png": "screenshot-desktop-zh-CN.png",
        "report-mobile-en.png": "screenshot-mobile-en.png",
    }
    for source_name, destination_name in plugin_assets.items():
        shutil.copyfile(ASSETS_DIR / source_name, PLUGIN_ASSETS_DIR / destination_name)
    return backend, fallback


def validate_public_output(packs: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    forbidden = ("example.invalid", "synthetic demo", "fictional report", "mock data", "合成演示", "虚构报告")
    for locale in LOCALES:
        path = SITE_DIR / locale / "index.html"
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        if any(term in lower for term in forbidden):
            raise AssertionError(f"Non-production content marker in {path}")
        if text.count('class="source-card"') != len(sources):
            raise AssertionError(f"Source count mismatch in {path}")
    expected_images = {
        "overview-en.png": (2400, 1800),
        "overview-zh-CN.png": (2400, 1800),
        "report-desktop-en.png": (1440, 1100),
        "report-desktop-zh-CN.png": (1440, 1100),
        "report-mobile-en.png": (390, 1320),
        "report-mobile-zh-CN.png": (390, 1320),
        "social-preview.png": (1280, 640),
        "icon-128.png": (128, 128),
        "icon-512.png": (512, 512),
    }
    for name, size in expected_images.items():
        with Image.open(ASSETS_DIR / name) as image:
            if image.size != size or image.getexif():
                raise AssertionError(f"Invalid public asset: {name}")
    with Image.open(ASSETS_DIR / "catalog-en.gif") as image:
        total = 0
        for index in range(image.n_frames):
            image.seek(index)
            total += int(image.info.get("duration", 0))
        if image.size != (960, 600) or not 14_000 <= total <= 16_000:
            raise AssertionError("Catalog GIF must be 960x600 and about 15 seconds")
    if Counter(source["pack_id"] for source in sources) != Counter({pack["id"]: pack["count"] for pack in packs}):
        raise AssertionError("Rendered pack counts do not match source configuration")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer", choices=("auto", "playwright", "pillow"), default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    packs, sources = load_catalog_sources()
    site_paths = write_site(packs, sources)
    backend, fallback = build_assets(packs, sources, site_paths, args.renderer)
    validate_public_output(packs, sources)
    print(f"Built bilingual public Source Catalog from {len(sources)} configured sources using {backend}.")
    if fallback:
        print(f"Playwright unavailable; Pillow fallback used: {fallback}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
