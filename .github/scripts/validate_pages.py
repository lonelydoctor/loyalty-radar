#!/usr/bin/env python3
"""Validate the offline bilingual report-first GitHub Pages payload."""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

SCHEMA_ID = "loyalty-radar-public-report/v1"
PRIVATE_PATTERNS = (
    re.compile(r"/" r"Users/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\" r"Users\\[^\\\s]+\\"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)
FORBIDDEN_MARKERS = (
    "example.invalid",
    "synthetic demo",
    "fictional report",
    "mock data",
    "demo-report",
    "合成演示",
    "虚构报告",
    "data-original",
    "original_member_",
    "original_evidence_",
    "translation failed",
    "翻译失败",
)
TRUNCATION_MARKERS = ("line-clamp", "text-overflow:ellipsis", "text-overflow: ellipsis")


class PageAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []
        self.hreflangs: set[str] = set()
        self.html_lang = ""
        self.h1_count = 0
        self.source_cards = 0
        self.event_cards = 0
        self.event_locales: list[str] = []
        self.event_titles = 0
        self.source_references = 0
        self.report_state = ""
        self.report_contract = ""
        self.window_hours = ""
        self.future_days = ""
        self.health_bands = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        lowered = tag.lower()
        if lowered == "html":
            self.html_lang = values.get("lang", "")
        if lowered == "h1":
            self.h1_count += 1
        if lowered == "a":
            href = values.get("href")
            if href:
                self.references.append(href)
            if values.get("hreflang"):
                self.hreflangs.add(values["hreflang"])
        elif lowered in {"link", "img", "script"}:
            reference = values.get("href") or values.get("src")
            if reference:
                self.references.append(reference)
        classes = set(values.get("class", "").split())
        if "source-card" in classes:
            self.source_cards += 1
        if "event" in classes:
            self.event_cards += 1
            self.event_locales.append(values.get("data-event-locale", ""))
        if "event-title" in classes:
            self.event_titles += 1
        if "source-reference" in classes:
            self.source_references += 1
        if "health-band" in classes:
            self.health_bands += 1
        if "report-page" in classes:
            self.report_state = values.get("data-report-state", "")
            self.report_contract = values.get("data-report-contract", "")
            self.window_hours = values.get("data-window-hours", "")
            self.future_days = values.get("data-future-days", "")


def read_page(path: Path, errors: list[str]) -> tuple[str, PageAudit] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{path}: unreadable HTML: {exc}")
        return None
    audit = PageAudit()
    try:
        audit.feed(text)
    except Exception as exc:  # HTMLParser errors are rare, but should remain visible.
        errors.append(f"{path}: HTML parse failure: {exc}")
        return None
    return text, audit


def validate_common(path: Path, expected_locale: str, errors: list[str]) -> tuple[str, PageAudit] | None:
    result = read_page(path, errors)
    if result is None:
        return None
    text, audit = result
    lower = text.lower()
    if audit.html_lang != expected_locale:
        errors.append(f"{path}: html lang must be {expected_locale}")
    if audit.h1_count != 1:
        errors.append(f"{path}: expected exactly one h1, found {audit.h1_count}")
    if not re.search(r"<title>[^<]+</title>", text, flags=re.IGNORECASE):
        errors.append(f"{path}: a complete non-empty title is required")
    if not re.search(r"<meta[^>]+name=[\"']viewport[\"']", text, flags=re.IGNORECASE):
        errors.append(f"{path}: responsive viewport metadata is required")
    for marker in FORBIDDEN_MARKERS:
        if marker in lower:
            errors.append(f"{path}: forbidden public-data marker {marker!r}")
    for marker in TRUNCATION_MARKERS:
        if marker in lower:
            errors.append(f"{path}: text truncation is forbidden ({marker})")
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            errors.append(f"{path}: possible private path or secret")
    if expected_locale in {"en", "zh-CN"} and not {"en", "zh-CN"}.issubset(audit.hreflangs):
        errors.append(f"{path}: bilingual hreflang links are required")
    return result


def validate_report_page(path: Path, locale: str, errors: list[str], *, allow_empty: bool) -> None:
    result = validate_common(path, locale, errors)
    if result is None:
        return
    text, audit = result
    if audit.report_contract != SCHEMA_ID:
        errors.append(f"{path}: report contract must be {SCHEMA_ID}")
    if audit.report_state not in {"empty", "published"}:
        errors.append(f"{path}: report state must be empty or published")
        return
    if audit.report_state == "empty":
        if not allow_empty:
            errors.append(f"{path}: archived report pages cannot use the empty state")
        expected = "No reviewed public report has been published yet." if locale == "en" else "尚未发布经过审核的公开报告。"
        if expected not in text:
            errors.append(f"{path}: truthful localized empty-state text is required")
        if audit.event_cards or audit.source_references:
            errors.append(f"{path}: empty state must not contain report events or source references")
        return
    if audit.window_hours != "336" or audit.future_days != "60":
        errors.append(f"{path}: published reports must expose a 336-hour window and 60-day horizon")
    if audit.health_bands != 1:
        errors.append(f"{path}: published report must include exactly one collection-health band")
    if audit.event_cards != audit.event_titles:
        errors.append(f"{path}: every event must display one complete event title")
    if audit.event_cards and audit.source_references < audit.event_cards:
        errors.append(f"{path}: every event must show at least one linked source reference")
    if any(value != locale for value in audit.event_locales):
        errors.append(f"{path}: event locale markers must match the page locale; fallback is forbidden")


def validate_catalog_page(path: Path, locale: str, errors: list[str]) -> None:
    result = validate_common(path, locale, errors)
    if result is None:
        return
    text, audit = result
    if audit.source_cards != 59:
        errors.append(f"{path}: expected exactly 59 source cards, found {audit.source_cards}")
    expected = "Public 59-source catalog" if locale == "en" else "公开 59 来源目录"
    if expected not in text:
        errors.append(f"{path}: localized public source-catalog title is required")
    if "data-catalog-count=\"59\"" not in text:
        errors.append(f"{path}: catalog count must be generated from the committed 59-source configuration")


def validate_internal_references(site: Path, html_path: Path, errors: list[str]) -> None:
    result = read_page(html_path, errors)
    if result is None:
        return
    _, audit = result
    page_url = "/" + html_path.relative_to(site).as_posix()
    for reference in audit.references:
        parsed = urlparse(reference)
        if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        target_url = urlparse(urljoin(page_url, reference)).path
        normalized = posixpath.normpath(target_url).lstrip("/")
        if normalized == "loyalty-radar" or normalized.startswith("loyalty-radar/"):
            normalized = normalized.removeprefix("loyalty-radar").lstrip("/")
        target = site / normalized
        if target_url.endswith("/"):
            target = target / "index.html"
        if not target.exists():
            errors.append(f"{html_path}: broken internal reference {reference}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    args = parser.parse_args()
    site = args.site.resolve()
    errors: list[str] = []

    required_reports = {
        site / "index.html": "en",
        site / "en" / "index.html": "en",
        site / "zh-CN" / "index.html": "zh-CN",
        site / "en" / "latest" / "index.html": "en",
        site / "zh-CN" / "latest" / "index.html": "zh-CN",
    }
    required_catalogs = {
        site / "sources" / "index.html": "en",
        site / "en" / "sources" / "index.html": "en",
        site / "zh-CN" / "sources" / "index.html": "zh-CN",
    }
    for path in (*required_reports, *required_catalogs):
        if not path.is_file():
            errors.append(f"missing required page: {path}")
    for path, locale in required_reports.items():
        if path.is_file():
            validate_report_page(path, locale, errors, allow_empty=True)
    for path, locale in required_catalogs.items():
        if path.is_file():
            validate_catalog_page(path, locale, errors)

    for locale in ("en", "zh-CN"):
        report_dir = site / locale / "reports"
        if report_dir.is_dir():
            for path in sorted(report_dir.glob("*/index.html")):
                validate_report_page(path, locale, errors, allow_empty=False)

    if site.is_dir():
        for path in site.rglob("*"):
            if path.is_symlink():
                errors.append(f"symlinks are not allowed in Pages payload: {path}")
                continue
            if not path.is_file():
                continue
            if path.stat().st_size > 25 * 1024 * 1024:
                errors.append(f"Pages asset exceeds 25 MiB: {path}")
            if path.suffix.lower() == ".json":
                errors.append(f"{path}: Pages must never publish report or event JSON")
            if path.suffix.lower() in {".html", ".css", ".js", ".txt", ".xml"}:
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    errors.append(f"{path}: unreadable text asset: {exc}")
                    continue
                lower = text.lower()
                for marker in FORBIDDEN_MARKERS:
                    if marker in lower:
                        errors.append(f"{path}: forbidden public-data marker {marker!r}")
                for pattern in PRIVATE_PATTERNS:
                    if pattern.search(text):
                        errors.append(f"{path}: possible private path or secret")
            if path.suffix.lower() == ".html":
                validate_internal_references(site, path, errors)

    if errors:
        unique = list(dict.fromkeys(errors))
        print(f"Pages validation failed with {len(unique)} issue(s):", file=sys.stderr)
        for error in unique:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Pages payload is bilingual, report-first, source-config-backed, and free of public JSON, raw source text, test news, private paths, and text truncation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
