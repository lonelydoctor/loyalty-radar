#!/usr/bin/env python3
"""Validate the static bilingual public Source Catalog payload."""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

PRIVATE_PATTERNS = (
    re.compile(r"/" r"Users/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\" r"Users\\[^\\\s]+\\"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def parse_links(text: str) -> list[str]:
    parser = LinkCollector()
    parser.feed(text)
    return parser.links


def validate_html(path: Path, locale: str, catalog_term: str, errors: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path}: {exc}")
        return
    lower = text.lower()
    if not re.search(rf"<html[^>]+lang=[\"']{re.escape(locale)}[\"']", text, flags=re.IGNORECASE):
        errors.append(f"{path}: html lang must be {locale}")
    if "<title>" not in lower or "</title>" not in lower:
        errors.append(f"{path}: a complete title is required")
    if not re.search(r"<meta[^>]+name\s*=\s*[\"']viewport[\"']", text, flags=re.IGNORECASE):
        errors.append(f"{path}: responsive viewport metadata is required")
    if catalog_term.lower() not in lower:
        errors.append(f"{path}: the page must visibly identify itself as the public Source Catalog")
    if text.count('class="source-card"') != 59:
        errors.append(f"{path}: expected exactly 59 configured source cards")
    forbidden = ("example.invalid", "synthetic demo", "fictional report", "mock data", "合成演示", "虚构报告")
    for marker in forbidden:
        if marker in lower:
            errors.append(f"{path}: forbidden public mock-data marker: {marker}")
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            errors.append(f"{path}: possible private path or secret")
    other_locale = "zh-CN" if locale == "en" else "en"
    link_paths = [urlparse(urljoin(f"https://example.invalid/{locale}/", href)).path for href in parse_links(text)]
    if not any(f"/{other_locale}/" in link_path for link_path in link_paths):
        errors.append(f"{path}: missing language switch link to {other_locale}")


def validate_internal_links(site: Path, html_path: Path, errors: list[str]) -> None:
    try:
        links = parse_links(html_path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"{html_path}: {exc}")
        return
    page_url = "/" + html_path.relative_to(site).as_posix()
    for href in links:
        parsed = urlparse(href)
        if parsed.scheme or parsed.netloc or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        target_url = urlparse(urljoin(page_url, href)).path
        normalized = posixpath.normpath(target_url).lstrip("/")
        if normalized == "loyalty-radar" or normalized.startswith("loyalty-radar/"):
            normalized = normalized.removeprefix("loyalty-radar").lstrip("/")
        target = site / normalized
        if target_url.endswith("/"):
            target = target / "index.html"
        if not target.exists():
            errors.append(f"{html_path}: broken internal link {href}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    args = parser.parse_args()
    site = args.site.resolve()
    errors: list[str] = []

    required = (site / "index.html", site / "en" / "index.html", site / "zh-CN" / "index.html")
    for path in required:
        if not path.is_file():
            errors.append(f"missing required page: {path}")
    if (site / "en" / "index.html").is_file():
        validate_html(site / "en" / "index.html", "en", "public source catalog", errors)
    if (site / "zh-CN" / "index.html").is_file():
        validate_html(site / "zh-CN" / "index.html", "zh-CN", "公开来源目录", errors)

    if site.is_dir():
        for path in site.rglob("*"):
            if path.is_symlink():
                errors.append(f"symlinks are not allowed in Pages payload: {path}")
            if path.is_file() and path.stat().st_size > 25 * 1024 * 1024:
                errors.append(f"Pages asset exceeds 25 MiB: {path}")
            if path.is_file() and path.suffix.lower() in {".html", ".css", ".js", ".json", ".txt", ".xml"}:
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    errors.append(f"{path}: unreadable text asset: {exc}")
                    continue
                for pattern in PRIVATE_PATTERNS:
                    if pattern.search(text):
                        errors.append(f"{path}: possible private path or secret")
            if path.is_file() and path.suffix.lower() == ".html":
                validate_internal_links(site, path, errors)
            if path.is_file() and path.suffix.lower() == ".json":
                errors.append(f"{path}: Pages must not publish report or event JSON")

    if errors:
        print(f"Pages validation failed with {len(errors)} issue(s):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Pages payload is a bilingual 59-source catalog with no report data, mock data, private paths, or secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
