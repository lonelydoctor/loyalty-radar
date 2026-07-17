#!/usr/bin/env python3
"""Generate deterministic outreach drafts from an authoritative public report."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PUBLIC_SCHEMA_ID = "loyalty-radar-public-report/v1"
ANNOUNCEMENT_MARKER = "loyalty-radar-public-brief"
REPOSITORY_URL = "https://github.com/lonelydoctor/loyalty-radar"
LOCALES = ("en", "zh-CN")
FORBIDDEN_KEYS = {
    "author",
    "authors",
    "body",
    "cards",
    "content",
    "cookies",
    "evidence",
    "original",
    "path",
    "profile",
    "raw",
    "raw_tags",
}
PRIVATE_PATTERN = re.compile(
    r"(?:/" r"Users/[^/\s]+/|/home/[^/\s]+/|[A-Za-z]:\\" r"Users\\[^\\\s]+\\|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bsk-[A-Za-z0-9_-]{20,}\b)",
    re.IGNORECASE,
)
FORBIDDEN_MARKERS = (".invalid", "mock data", "synthetic demo", "fictional report", "合成演示", "虚构报告")


def is_http_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}"
            yield location, str(key), child
            yield from walk(child, location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def validate_public_report(report: dict[str, Any]) -> None:
    """Validate only the shared public-report contract; never sanitize full data here."""

    errors: list[str] = []
    if report.get("schema_id") != PUBLIC_SCHEMA_ID:
        errors.append(f"schema_id must be {PUBLIC_SCHEMA_ID}")
    publication = report.get("publication")
    if not isinstance(publication, dict):
        errors.append("publication must be an object")
        publication = {}
    if publication.get("policy") != "public":
        errors.append("publication.policy must be public")
    locales = publication.get("locales")
    if locales != ["en", "zh-CN"]:
        errors.append("publication.locales must be exactly en and zh-CN")
    items = report.get("items")
    if not isinstance(items, list):
        errors.append("items must be an array")
        items = []
    if publication.get("event_count") != len(items):
        errors.append("publication.event_count must equal the number of items")
    if not isinstance(report.get("health"), dict):
        errors.append("health must be an aggregate object")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{index}] must be an object")
            continue
        localized = item.get("localized")
        if not isinstance(localized, dict):
            errors.append(f"items[{index}].localized must be an object")
            localized = {}
        for locale in LOCALES:
            visible = localized.get(locale)
            if not isinstance(visible, dict) or not all(
                str(visible.get(field) or "").strip()
                for field in ("title", "summary", "why_it_matters")
            ):
                errors.append(f"items[{index}].localized.{locale} is incomplete")
        refs = item.get("source_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"items[{index}].source_refs must be non-empty")
        elif any(not isinstance(ref, dict) or not is_http_url(ref.get("url")) for ref in refs):
            errors.append(f"items[{index}].source_refs contains an invalid URL")
        if not isinstance(item.get("taxonomy"), dict):
            errors.append(f"items[{index}].taxonomy must be an object")

    serialized = json.dumps(report, ensure_ascii=False)
    if PRIVATE_PATTERN.search(serialized):
        errors.append("report contains a private path or secret-like token")
    lowered = serialized.casefold()
    errors.extend(
        f"report contains forbidden public marker: {marker}"
        for marker in FORBIDDEN_MARKERS
        if marker.casefold() in lowered
    )
    forbidden = [location for location, key, _ in walk(report) if key.casefold() in FORBIDDEN_KEYS]
    if forbidden:
        errors.append("report contains forbidden fields: " + ", ".join(forbidden[:5]))
    if errors:
        raise ValueError("; ".join(dict.fromkeys(errors)))


def localized(item: dict[str, Any], locale: str, field: str) -> str:
    return str(((item.get("localized") or {}).get(locale) or {}).get(field) or "").strip()


def primary_source(item: dict[str, Any]) -> dict[str, Any]:
    refs = item.get("source_refs") or []
    return refs[0] if refs else {}


def markdown_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def top_lines(report: dict[str, Any], locale: str, maximum: int = 5) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate((report.get("items") or [])[:maximum], 1):
        source = primary_source(item)
        lines.append(
            f"{index}. [{markdown_text(localized(item, locale, 'title'))}](<{source.get('url')}>) — "
            f"{markdown_text(localized(item, locale, 'summary'))}"
        )
    if lines:
        return lines
    return [
        "No event met the publication gate this week; the result is not padded."
        if locale == "en"
        else "本周没有事件通过公开门禁，报告保留空结果，不用低质量信息填充。"
    ]


def health_lines(report: dict[str, Any]) -> tuple[str, str]:
    health = report.get("health") or {}
    script_ok = int(health.get("script_ok_sources") or 0)
    script_total = int(health.get("script_eligible_sources") or 0)
    p0_ok = int(health.get("p0_ok_sources") or 0)
    p0_total = int(health.get("p0_script_sources") or 0)
    fallback_sources = int(health.get("fallback_sources") or 0)
    duplicate_rate = float(health.get("duplicate_rate") or 0.0)
    en = (
        f"The audited run passed {script_ok}/{script_total} script sources and "
        f"{p0_ok}/{p0_total} P0 sources; {fallback_sources} used a declared public-cache "
        f"fallback; duplicate rate {duplicate_rate:.1%}."
    )
    zh = (
        f"本次审计中，脚本来源成功 {script_ok}/{script_total}，P0 来源成功 "
        f"{p0_ok}/{p0_total}，其中 {fallback_sources} 个使用已声明的公开缓存回退，"
        f"重复率 {duplicate_rate:.1%}。"
    )
    return en, zh


def review_summary(report: dict[str, Any], week: str) -> str:
    publication = report["publication"]
    health = report["health"]
    return "\n".join(
        [
            "## Authoritative public-report gate",
            "",
            "- Result: **PASS**",
            f"- Report: `{week}`",
            f"- Generated: `{publication.get('generated_at')}`",
            f"- Audited: `{publication.get('audited_at')}`",
            f"- Events: {publication.get('event_count', 0)}",
            f"- Script source OK rate: {float(health.get('script_ok_rate') or 0):.1%}",
            f"- P0 source OK rate: {float(health.get('p0_ok_rate') or 0):.1%}",
            f"- Declared public-cache fallbacks: {int(health.get('fallback_sources') or 0)}",
            f"- Duplicate rate: {float(health.get('duplicate_rate') or 0):.1%}",
            "",
            "This summary is read from the sanitized `schema_id` report produced by `loyalty-radar audit --policy public`.",
            "",
        ]
    )


def build_drafts(report: dict[str, Any], week: str) -> dict[str, str]:
    validate_public_report(report)
    en = top_lines(report, "en")
    zh = top_lines(report, "zh-CN")
    health_en, health_zh = health_lines(report)
    announcement = "\n".join(
        [
            f"<!-- {ANNOUNCEMENT_MARKER}:{week} -->",
            f"# Loyalty Radar Public Weekly Brief · {week}",
            "",
            health_en,
            "",
            *en,
            "",
            "This source-linked brief uses real public data. It is not official verification and contains no fetched body text or personal profile.",
            "",
            f"Repository: {REPOSITORY_URL}",
        ]
    )
    return {
        "announcement.md": announcement + "\n",
        "hn.md": "\n".join(
            [
                f"# Show HN: Loyalty Radar – source-backed loyalty briefings ({week})",
                "",
                health_en,
                "",
                *en,
                "",
                "Loyalty Radar is an open-source Agent Skill and Python CLI with event clustering, source health and bilingual public-policy auditing. It has no product telemetry.",
                "",
                REPOSITORY_URL,
                "",
            ]
        ),
        "flyertalk.md": "\n".join(
            [
                f"# Loyalty Radar public brief for {week}",
                "",
                "Disclosure: I am the maintainer of Loyalty Radar, the open-source project that generated this report. This post contains the findings and methodology for feedback; there is no affiliate link or paid placement.",
                "",
                health_en,
                "",
                "The highest-priority findings:",
                *en,
                "",
                "Method: a 14-day public-source scan, a 60-day future-event watch, deterministic clustering and an audited publication allowlist. Reports are not checked against official program pages. Raw fetched text and personal profiles are not published.",
                "",
                f"Code and installation details: {REPOSITORY_URL}",
                "",
            ]
        ),
        "v2ex.md": "\n".join(
            [
                f"# 用 Agent Skill 聚合常旅客情报：Loyalty Radar {week}",
                "",
                health_zh,
                "",
                *zh,
                "",
                "项目重点是事件聚类、来源健康、时间窗口、风险标签和可追溯链接。无产品遥测，不公开抓取正文或个人画像。",
                "",
                REPOSITORY_URL,
                "",
            ]
        ),
        "flyert.md": "\n".join(
            [
                f"# Loyalty Radar 常旅客公开周报 · {week}",
                "",
                "披露：我是开源项目 Loyalty Radar 的维护者。本帖完整列出本周发现和方法，不含返利或付费推广。",
                "",
                health_zh,
                "",
                *zh,
                "",
                "口径：过去两周公开来源，关注未来 60 天；不做官网确认，不公开帖子正文和个人画像。",
                "",
                REPOSITORY_URL,
                "",
            ]
        ),
        "social-en.md": "\n".join(
            [f"Loyalty Radar {week}: {health_en}", *en[:3], f"Open source, source-linked, no product telemetry: {REPOSITORY_URL}", ""]
        ),
        "social-zh-CN.md": "\n".join(
            [f"Loyalty Radar {week}：{health_zh}", *zh[:3], f"开源、来源可追溯、无产品遥测：{REPOSITORY_URL}", ""]
        ),
        "review-summary.md": review_summary(report, week),
    }


def write_drafts(report: dict[str, Any], week: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in build_drafts(report, week).items():
        (directory / name).write_text(value, encoding="utf-8")


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "loyalty-radar-outreach/0.1.2",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub GraphQL returned {exc.code}") from exc
    if payload.get("errors"):
        raise RuntimeError("; ".join(str(value.get("message") or "GraphQL error") for value in payload["errors"][:3]))
    return payload.get("data") or {}


def publish_announcement(report: dict[str, Any], week: str, repository: str, token: str) -> str:
    validate_public_report(report)
    owner, separator, name = repository.partition("/")
    if not separator:
        raise ValueError("repository must use owner/name form")
    query = """
    query($owner:String!,$name:String!) {
      repository(owner:$owner,name:$name) {
        id
        discussionCategories(first:25) { nodes { id slug } }
        discussions(first:100,orderBy:{field:CREATED_AT,direction:DESC}) { nodes { body url } }
      }
    }
    """
    repo = (graphql(token, query, {"owner": owner, "name": name}).get("repository") or {})
    marker = f"<!-- {ANNOUNCEMENT_MARKER}:{week} -->"
    for discussion in (repo.get("discussions") or {}).get("nodes") or []:
        if marker in str(discussion.get("body") or ""):
            return str(discussion.get("url") or "")
    categories = (repo.get("discussionCategories") or {}).get("nodes") or []
    category = next((row for row in categories if str(row.get("slug") or "").casefold() == "announcements"), None)
    if category is None:
        raise RuntimeError("GitHub Discussions has no Announcements category")
    mutation = """
    mutation($repositoryId:ID!,$categoryId:ID!,$title:String!,$body:String!) {
      createDiscussion(input:{repositoryId:$repositoryId,categoryId:$categoryId,title:$title,body:$body}) {
        discussion { url }
      }
    }
    """
    data = graphql(
        token,
        mutation,
        {
            "repositoryId": repo["id"],
            "categoryId": category["id"],
            "title": f"Loyalty Radar Public Weekly Brief · {week}",
            "body": build_drafts(report, week)["announcement.md"],
        },
    )
    return str(((data.get("createDiscussion") or {}).get("discussion") or {}).get("url") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--publish-announcement", action="store_true")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    validate_public_report(report)
    write_drafts(report, args.week, args.output_dir)
    announcement_url = ""
    if args.publish_announcement:
        if not args.repository or not args.token:
            parser.error("announcement publishing requires GITHUB_REPOSITORY and GITHUB_TOKEN")
        announcement_url = publish_announcement(report, args.week, args.repository, args.token)
    print(json.dumps({"drafts": str(args.output_dir), "announcement_url": announcement_url}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"generate-outreach: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
