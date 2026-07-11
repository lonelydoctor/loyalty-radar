#!/usr/bin/env python3
"""Render the bilingual public Source Catalog and reject obvious layout failures."""

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
LOCALES = ("en", "zh-CN")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def inspect_layout(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const heading = document.querySelector('h1');
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 1 && rect.height > 1;
          };
          const clipped = [...document.querySelectorAll('h1, h2, h3, button, [data-critical-text]')]
            .filter(visible)
            .filter((element) => element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2)
            .map((element) => ({
              tag: element.tagName,
              text: (element.textContent || element.tagName).trim().slice(0, 100),
              scrollWidth: element.scrollWidth,
              clientWidth: element.clientWidth,
              scrollHeight: element.scrollHeight,
              clientHeight: element.clientHeight,
            }));
          const candidates = [...document.querySelectorAll('[data-layout-check], main > section, main > article')]
            .filter(visible)
            .filter((element) => !['absolute', 'fixed'].includes(getComputedStyle(element).position));
          const overlaps = [];
          for (let left = 0; left < candidates.length; left += 1) {
            const a = candidates[left].getBoundingClientRect();
            for (let right = left + 1; right < candidates.length; right += 1) {
              const b = candidates[right].getBoundingClientRect();
              const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
              const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
              if (width > 4 && height > 4) {
                overlaps.push(`${candidates[left].tagName}:${candidates[right].tagName}`);
              }
            }
          }
          const headingRect = heading ? heading.getBoundingClientRect() : null;
          return {
            bodyTextLength: (document.body.innerText || '').trim().length,
            horizontalOverflow: root.scrollWidth - root.clientWidth,
            hasHeading: Boolean(heading),
            headingInViewport: Boolean(headingRect && headingRect.left >= -1 && headingRect.right <= innerWidth + 1 && headingRect.top >= -1),
            clipped,
            overlaps,
          };
        }
        """
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


def test_page(browser: Browser, base_url: str, locale: str, name: str, viewport: dict[str, int], output: Path) -> dict[str, Any]:
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
    response = page.goto(f"{base_url}/{locale}/", wait_until="networkidle", timeout=20_000)
    if response is None or response.status >= 400:
        raise AssertionError(f"{locale}/{name}: page did not load successfully")
    page.evaluate("document.fonts && document.fonts.ready")
    layout = inspect_layout(page)
    screenshot = output / f"{locale}-{name}.png"
    page.screenshot(path=str(screenshot), full_page=True, animations="disabled")
    context.close()

    failures: list[str] = []
    if layout["bodyTextLength"] < 300:
        failures.append("less than 300 visible text characters")
    if layout["horizontalOverflow"] > 2:
        failures.append(f"horizontal overflow of {layout['horizontalOverflow']}px")
    if not layout["hasHeading"]:
        failures.append("missing h1")
    elif not layout["headingInViewport"]:
        failures.append("h1 is clipped or outside the first viewport")
    if layout["clipped"]:
        failures.append(f"clipped critical text: {layout['clipped'][:5]}")
    if layout["overlaps"]:
        failures.append(f"overlapping layout blocks: {layout['overlaps'][:5]}")
    if console_errors:
        failures.append(f"console errors: {console_errors[:3]}")
    if blocked_requests:
        failures.append(f"external runtime requests: {blocked_requests[:3]}")
    assert_nonblank(screenshot)
    if failures:
        raise AssertionError(f"{locale}/{name}: " + "; ".join(failures))
    return {"locale": locale, "viewport": name, "screenshot": screenshot.name, "layout": layout}


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
                for locale in LOCALES:
                    for name, viewport in VIEWPORTS.items():
                        try:
                            results.append(test_page(browser, base_url, locale, name, viewport, output))
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
    print(f"Validated {len(results)} locale/viewport combinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
