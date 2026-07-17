#!/usr/bin/env python3
"""Render report and catalog Pages at required viewports and reject layout failures."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageStat
from playwright.sync_api import Browser, Page, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SCRIPTS = ROOT / "plugins/loyalty-radar/skills/loyalty-radar/scripts"
if str(PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SCRIPTS))

from loyalty_radar.engine import chrome_executable_path  # noqa: E402

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1100},
    "mobile": {"width": 390, "height": 844},
    "overview": {"width": 2400, "height": 1800},
}
PAGES = {
    "root": {"path": "/", "locale": "en", "kind": "report"},
    "en-report": {"path": "/en/", "locale": "en", "kind": "report"},
    "zh-CN-report": {"path": "/zh-CN/", "locale": "zh-CN", "kind": "report"},
    "en-sources": {"path": "/en/sources/", "locale": "en", "kind": "catalog"},
    "zh-CN-sources": {"path": "/zh-CN/sources/", "locale": "zh-CN", "kind": "catalog"},
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def inspect_layout(page: Page, expected_locale: str, kind: str) -> dict[str, Any]:
    return page.evaluate(
        """
        ([expectedLocale, kind]) => {
          const root = document.documentElement;
          const heading = document.querySelector('h1');
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 1 && rect.height > 1;
          };
          const critical = [...document.querySelectorAll('h1, h2, h3, .button, button, [data-critical-text]')]
            .filter(visible);
          const clipped = critical
            .filter((element) => element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2)
            .map((element) => ({
              tag: element.tagName,
              text: (element.textContent || element.tagName).trim().slice(0, 140),
              scrollWidth: element.scrollWidth,
              clientWidth: element.clientWidth,
              scrollHeight: element.scrollHeight,
              clientHeight: element.clientHeight,
            }));
          const truncation = critical
            .filter((element) => {
              const style = getComputedStyle(element);
              return style.textOverflow === 'ellipsis' ||
                !['', 'none', '0'].includes(style.getPropertyValue('-webkit-line-clamp'));
            })
            .map((element) => (element.textContent || element.tagName).trim().slice(0, 140));
          const candidates = [...document.querySelectorAll('[data-layout-check]')]
            .filter(visible)
            .filter((element) => !['absolute', 'fixed'].includes(getComputedStyle(element).position));
          const overlaps = [];
          for (let left = 0; left < candidates.length; left += 1) {
            for (let right = left + 1; right < candidates.length; right += 1) {
              const leftElement = candidates[left];
              const rightElement = candidates[right];
              if (leftElement.contains(rightElement) || rightElement.contains(leftElement)) continue;
              const a = leftElement.getBoundingClientRect();
              const b = rightElement.getBoundingClientRect();
              const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
              const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
              if (width > 4 && height > 4) overlaps.push(`${leftElement.tagName}:${rightElement.tagName}`);
            }
          }
          const headingRect = heading ? heading.getBoundingClientRect() : null;
          const eventLocaleMismatch = [...document.querySelectorAll('[data-event-locale]')]
            .filter((element) => element.dataset.eventLocale !== expectedLocale).length;
          const reportState = document.querySelector('[data-report-state]')?.dataset.reportState || '';
          const sourceCards = document.querySelectorAll('.source-card').length;
          return {
            bodyTextLength: (document.body.innerText || '').trim().length,
            documentLocale: document.documentElement.lang,
            horizontalOverflow: root.scrollWidth - root.clientWidth,
            hasHeading: Boolean(heading),
            headingInViewport: Boolean(headingRect && headingRect.left >= -1 && headingRect.right <= innerWidth + 1 && headingRect.top >= -1 && headingRect.top <= innerHeight),
            clipped,
            truncation,
            overlaps,
            eventLocaleMismatch,
            reportState,
            sourceCards,
            kind,
          };
        }
        """,
        [expected_locale, kind],
    )


def assert_nonblank(path: Path) -> None:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail((400, 400))
        stats = ImageStat.Stat(rgb)
        if max(stats.stddev) < 5:
            raise AssertionError(f"Screenshot appears blank or monochrome: {path}")
        pixels = list(rgb.get_flattened_data() if hasattr(rgb, "get_flattened_data") else rgb.getdata())
        nonwhite = sum(1 for pixel in pixels if min(pixel) < 245)
        if nonwhite / max(1, len(pixels)) < 0.03:
            raise AssertionError(f"Screenshot has too little visible content: {path}")


def test_page(
    browser: Browser,
    base_url: str,
    page_name: str,
    page_spec: dict[str, str],
    viewport_name: str,
    viewport: dict[str, int],
    output: Path,
) -> dict[str, Any]:
    context = browser.new_context(viewport=viewport, device_scale_factor=1, reduced_motion="reduce")
    page = context.new_page()
    console_errors: list[str] = []
    blocked_requests: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    def route_request(route: Route) -> None:
        parsed = urlparse(route.request.url)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            route.continue_()
        else:
            blocked_requests.append(route.request.url)
            route.abort()

    context.route("**/*", route_request)
    response = page.goto(f"{base_url}{page_spec['path']}", wait_until="networkidle", timeout=20_000)
    if response is None or response.status >= 400:
        raise AssertionError(f"{page_name}/{viewport_name}: page did not load successfully")
    page.evaluate("async () => { if (document.fonts) await document.fonts.ready; }")
    layout = inspect_layout(page, page_spec["locale"], page_spec["kind"])
    screenshot = output / f"{page_name}-{viewport_name}.png"
    page.screenshot(path=str(screenshot), full_page=True, animations="disabled")
    context.close()

    failures: list[str] = []
    minimum_text = 250 if page_spec["kind"] == "report" else 2_000
    if layout["bodyTextLength"] < minimum_text:
        failures.append(f"less than {minimum_text} visible text characters")
    if layout["documentLocale"] != page_spec["locale"]:
        failures.append(f"document locale is {layout['documentLocale']!r}")
    if layout["horizontalOverflow"] > 2:
        failures.append(f"horizontal overflow of {layout['horizontalOverflow']}px")
    if not layout["hasHeading"]:
        failures.append("missing h1")
    elif not layout["headingInViewport"]:
        failures.append("h1 is clipped or outside the first viewport")
    if layout["clipped"]:
        failures.append(f"clipped critical text: {layout['clipped'][:5]}")
    if layout["truncation"]:
        failures.append(f"line clamp or ellipsis detected: {layout['truncation'][:5]}")
    if layout["overlaps"]:
        failures.append(f"overlapping layout blocks: {layout['overlaps'][:5]}")
    if layout["eventLocaleMismatch"]:
        failures.append(f"{layout['eventLocaleMismatch']} event locale mismatch(es)")
    if page_spec["kind"] == "report" and layout["reportState"] not in {"empty", "published"}:
        failures.append("missing report state")
    if page_spec["kind"] == "catalog" and layout["sourceCards"] != 59:
        failures.append(f"expected 59 source cards, found {layout['sourceCards']}")
    if console_errors:
        failures.append(f"console errors: {console_errors[:3]}")
    if blocked_requests:
        failures.append(f"external runtime requests: {blocked_requests[:3]}")
    assert_nonblank(screenshot)
    if failures:
        raise AssertionError(f"{page_name}/{viewport_name}: " + "; ".join(failures))
    return {"page": page_name, "viewport": viewport_name, "screenshot": screenshot.name, "layout": layout}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    site = args.site.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    handler = partial(QuietHandler, directory=str(site))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            launch_args: dict[str, Any] = {"headless": True}
            chrome_path = chrome_executable_path()
            if chrome_path:
                launch_args["executable_path"] = chrome_path
            browser = playwright.chromium.launch(**launch_args)
            try:
                for page_name, page_spec in PAGES.items():
                    for viewport_name, viewport in VIEWPORTS.items():
                        try:
                            results.append(test_page(browser, base_url, page_name, page_spec, viewport_name, viewport, output))
                        except Exception as exc:  # Preserve all viewport evidence before failing.
                            errors.append(str(exc))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    payload = {"results": results, "errors": errors}
    (output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Validated {len(results)} report/catalog viewport combinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
