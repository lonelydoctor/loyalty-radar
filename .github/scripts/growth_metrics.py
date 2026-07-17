#!/usr/bin/env python3
"""Collect GitHub-native v0.1.2 growth metrics without product telemetry."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA = "loyalty-radar-doctor-receipt/v1"
SNAPSHOT_SCHEMA = "loyalty-radar-growth-snapshot/v1"
CAMPAIGN_TAG = "v0.1.2"
TRACKING_TITLE = "Loyalty Radar v0.1.2 30-Day Growth"
TRACKING_LABEL = "growth"
START_MARKER = "<!-- loyalty-radar-growth:start -->"
END_MARKER = "<!-- loyalty-radar-growth:end -->"
STATE_PATTERN = re.compile(
    r"<!-- loyalty-radar-growth-state:v1\s*(\{.*?\})\s*-->", re.DOTALL
)
WEEK_MARKER_PREFIX = "<!-- loyalty-radar-growth-week:"
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
PYTHON_PATTERN = re.compile(r"^3\.(?:1[1-9]|[2-9]\d)(?:\.\d+)?$")
PRIVATE_PATTERN = re.compile(
    r"(?:/" r"Users/[^/\s]+/|[A-Za-z]:\\" r"Users\\[^\\\s]+\\|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)
INVALID_FEEDBACK_LABELS = {"duplicate", "invalid", "spam"}
MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
SOURCE_PACK_PREFIX = "plugins/loyalty-radar/skills/loyalty-radar/references/source-packs/"


class GitHubAPIError(RuntimeError):
    """A bounded GitHub API error with no credential material."""


def parse_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def actor_login(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("login") or value.get("name") or "").strip()
    return str(value or "").strip()


def is_bot_actor(actor: Any) -> bool:
    if isinstance(actor, dict) and str(actor.get("type") or "").casefold() == "bot":
        return True
    login = actor_login(actor).casefold()
    return login.endswith("[bot]") or login.endswith("-bot") or login == "github-actions"


def is_external_human(actor: Any, owner: str) -> bool:
    login = actor_login(actor)
    return bool(login) and login.casefold() != owner.casefold() and not is_bot_actor(actor)


def _json_objects(text: str) -> Iterable[dict[str, Any]]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def parse_doctor_receipt(body: str) -> dict[str, Any] | None:
    """Return a validated, share-safe doctor receipt or ``None``.

    The receipt is a JSON object emitted by ``loyalty-radar doctor --share``:
    ``schema``, ``product``, ``version``, ``python``, ``os`` and ``surfaces``.
    Unknown fields and private-looking values are rejected so a copied local path
    cannot become part of the public installation metric.
    """

    allowed_keys = {"schema", "product", "version", "python", "os", "surfaces"}
    allowed_surfaces = {"skill", "plugin", "source_catalog", "render"}
    good_statuses = {"ok", "available", "degraded"}
    supported_os = {"linux", "macos", "windows"}
    for value in _json_objects(body):
        if value.get("schema") != RECEIPT_SCHEMA or set(value) - allowed_keys:
            continue
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if PRIVATE_PATTERN.search(serialized):
            continue
        if str(value.get("product") or "").casefold() != "loyalty-radar":
            continue
        if not SEMVER_PATTERN.fullmatch(str(value.get("version") or "")):
            continue
        if not PYTHON_PATTERN.fullmatch(str(value.get("python") or "")):
            continue
        if str(value.get("os") or "").casefold() not in supported_os:
            continue
        surfaces = value.get("surfaces")
        if not isinstance(surfaces, dict) or set(surfaces) != allowed_surfaces:
            continue
        if any(str(surfaces.get(name) or "").casefold() not in good_statuses for name in allowed_surfaces):
            continue
        return value
    return None


def version_core(value: str) -> tuple[int, int, int]:
    core = re.split(r"[-+]", value, maxsplit=1)[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)


def valid_install_confirmations(
    comments: Iterable[dict[str, Any]], owner: str, launch_at: dt.datetime | None
) -> list[dict[str, Any]]:
    """Count one post-launch valid receipt per external GitHub account."""

    accepted: dict[str, dict[str, Any]] = {}
    for comment in comments:
        author = comment.get("author") or comment.get("user")
        if not is_external_human(author, owner):
            continue
        created_at = parse_datetime(comment.get("createdAt") or comment.get("created_at"))
        if launch_at and (not created_at or created_at < launch_at):
            continue
        receipt = parse_doctor_receipt(str(comment.get("body") or ""))
        if receipt is None or version_core(str(receipt["version"])) < (0, 1, 2):
            continue
        login = actor_login(author)
        key = login.casefold()
        candidate = {
            "login": login,
            "created_at": created_at.isoformat() if created_at else None,
            "version": receipt["version"],
            "os": receipt["os"],
            "url": comment.get("url") or comment.get("html_url"),
        }
        existing = accepted.get(key)
        if existing is None or str(candidate["created_at"]) < str(existing["created_at"]):
            accepted[key] = candidate
    return sorted(accepted.values(), key=lambda row: row["login"].casefold())


def _labels(item: dict[str, Any]) -> set[str]:
    values = item.get("labels") or []
    return {
        str(value.get("name") if isinstance(value, dict) else value).strip().casefold()
        for value in values
        if value
    }


def _maintainer_replied(item: dict[str, Any], owner: str) -> bool:
    for comment in item.get("comments") or []:
        association = str(comment.get("authorAssociation") or comment.get("author_association") or "").upper()
        author = comment.get("author") or comment.get("user")
        if association in MAINTAINER_ASSOCIATIONS or actor_login(author).casefold() == owner.casefold():
            return True
    return False


def qualifies_external_feedback(
    item: dict[str, Any], owner: str, launch_at: dt.datetime | None
) -> bool:
    """Qualify an external issue/discussion only after a maintainer response."""

    if "pull_request" in item or str(item.get("kind") or "").casefold() == "pull_request":
        return False
    author = item.get("author") or item.get("user")
    if not is_external_human(author, owner):
        return False
    created_at = parse_datetime(item.get("createdAt") or item.get("created_at"))
    if launch_at and (not created_at or created_at < launch_at):
        return False
    if _labels(item) & INVALID_FEEDBACK_LABELS:
        return False
    return _maintainer_replied(item, owner)


def valid_external_feedback(
    items: Iterable[dict[str, Any]], owner: str, launch_at: dt.datetime | None
) -> list[dict[str, Any]]:
    accepted: dict[str, dict[str, Any]] = {}
    for item in items:
        if not qualifies_external_feedback(item, owner, launch_at):
            continue
        key = str(item.get("url") or item.get("html_url") or item.get("id") or item.get("number"))
        if not key:
            continue
        accepted[key] = {
            "kind": item.get("kind") or "issue",
            "number": item.get("number"),
            "title": item.get("title"),
            "author": actor_login(item.get("author") or item.get("user")),
            "url": item.get("url") or item.get("html_url"),
        }
    return sorted(accepted.values(), key=lambda row: (str(row["kind"]), int(row["number"] or 0)))


def qualifies_source_contribution(
    item: dict[str, Any], owner: str, launch_at: dt.datetime | None
) -> bool:
    """Qualify an accepted source request or a merged source-pack PR."""

    author = item.get("author") or item.get("user")
    if not is_external_human(author, owner):
        return False
    created_at = parse_datetime(
        item.get("mergedAt") or item.get("merged_at") or item.get("closedAt") or item.get("closed_at") or item.get("createdAt") or item.get("created_at")
    )
    if launch_at and (not created_at or created_at < launch_at):
        return False
    labels = _labels(item)
    kind = str(item.get("kind") or "").casefold()
    if kind == "pull_request" or item.get("pull_request"):
        if not (item.get("mergedAt") or item.get("merged_at") or item.get("merged")):
            return False
        files = [str(value.get("filename") if isinstance(value, dict) else value) for value in item.get("files") or []]
        return "source-accepted" in labels or any(path.startswith(SOURCE_PACK_PREFIX) and path.endswith((".yaml", ".yml")) for path in files)
    return "source-accepted" in labels


def valid_source_contributions(
    items: Iterable[dict[str, Any]], owner: str, launch_at: dt.datetime | None
) -> list[dict[str, Any]]:
    accepted: dict[str, dict[str, Any]] = {}
    for item in items:
        if not qualifies_source_contribution(item, owner, launch_at):
            continue
        key = str(item.get("url") or item.get("html_url") or item.get("id") or item.get("number"))
        if not key:
            continue
        accepted[key] = {
            "kind": item.get("kind") or "issue",
            "number": item.get("number"),
            "title": item.get("title"),
            "author": actor_login(item.get("author") or item.get("user")),
            "url": item.get("url") or item.get("html_url"),
        }
    return sorted(accepted.values(), key=lambda row: (str(row["kind"]), int(row["number"] or 0)))


class GitHubClient:
    def __init__(self, repository: str, token: str) -> None:
        owner, separator, name = repository.partition("/")
        if not separator or not owner or not name:
            raise ValueError("repository must use owner/name form")
        self.repository = repository
        self.owner = owner
        self.name = name
        self.token = token
        self.api = "https://api.github.com"

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> tuple[Any, dict[str, str]]:
        url = path if path.startswith("https://") else f"{self.api}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "loyalty-radar-growth/0.1.2",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                value = json.loads(raw) if raw else None
                return value, dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            detail = exc.read(512).decode("utf-8", errors="replace")
            raise GitHubAPIError(f"GitHub API {method} {urllib.parse.urlparse(url).path} returned {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise GitHubAPIError(f"GitHub API request failed: {type(exc.reason).__name__}") from exc

    def rest(self, method: str, path: str, payload: dict[str, Any] | None = None, *, accept: str = "application/vnd.github+json") -> Any:
        return self._request(method, path, payload=payload, accept=accept)[0]

    def paginate(self, path: str, *, accept: str = "application/vnd.github+json", maximum_pages: int = 20) -> list[Any]:
        separator = "&" if "?" in path else "?"
        url = f"{path}{separator}per_page=100"
        rows: list[Any] = []
        for _ in range(maximum_pages):
            payload, headers = self._request("GET", url, accept=accept)
            if isinstance(payload, list):
                rows.extend(payload)
            link = headers.get("Link") or headers.get("link") or ""
            match = re.search(r'<([^>]+)>;\s*rel="next"', link)
            if not match:
                break
            url = match.group(1)
        return rows

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = self.rest("POST", "/graphql", {"query": query, "variables": variables})
        if payload.get("errors"):
            messages = "; ".join(str(error.get("message") or "GraphQL error") for error in payload["errors"][:3])
            raise GitHubAPIError(messages)
        return payload.get("data") or {}


DISCUSSION_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    discussion(number:$number) {
      number title url createdAt
      author { login }
      comments(first:100) {
        nodes {
          body createdAt url authorAssociation author { login }
          replies(first:100) { nodes { body createdAt url authorAssociation author { login } } }
        }
      }
    }
  }
}
"""

DISCUSSIONS_QUERY = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    discussions(first:50, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes {
        number title url createdAt authorAssociation author { login }
        comments(first:50) {
          nodes {
            body createdAt url authorAssociation author { login }
            replies(first:20) { nodes { body createdAt url authorAssociation author { login } } }
          }
        }
      }
    }
  }
}
"""


def _flatten_discussion_comments(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in nodes:
        row = {key: value for key, value in node.items() if key != "replies"}
        rows.append(row)
        rows.extend((node.get("replies") or {}).get("nodes") or [])
    return rows


def collect_api_payload(client: GitHubClient, discussion_number: int | None) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    repository = client.rest("GET", f"/repos/{client.repository}")
    releases = client.paginate(f"/repos/{client.repository}/releases")
    stargazers = client.paginate(
        f"/repos/{client.repository}/stargazers",
        accept="application/vnd.github.star+json",
    )
    contributors = client.paginate(f"/repos/{client.repository}/contributors?anon=0", maximum_pages=10)
    milestones = client.paginate(f"/repos/{client.repository}/milestones?state=all", maximum_pages=3)

    traffic: dict[str, Any] = {
        "status": "available",
        "clones": {
            "status": "excluded",
            "reason": "CI clones cannot be separated reliably, so the clones endpoint is never requested.",
        },
    }
    for key, endpoint in (
        ("views", "views"),
        ("popular_paths", "popular/paths"),
        ("popular_referrers", "popular/referrers"),
    ):
        try:
            traffic[key] = client.rest("GET", f"/repos/{client.repository}/traffic/{endpoint}")
        except GitHubAPIError as exc:
            traffic[key] = {"status": "unavailable"}
            traffic["status"] = "partial"
            warnings.append(f"Traffic {key} unavailable: {exc}")

    issues = client.paginate(f"/repos/{client.repository}/issues?state=all&sort=created&direction=desc")
    normalized_issues: list[dict[str, Any]] = []
    for issue in issues:
        if issue.get("pull_request"):
            continue
        comments: list[dict[str, Any]] = []
        if issue.get("comments") and is_external_human(issue.get("user"), client.owner):
            comments = client.paginate(f"/repos/{client.repository}/issues/{issue['number']}/comments")
        normalized_issues.append(issue | {"kind": "issue", "comments": comments})

    pulls = client.paginate(f"/repos/{client.repository}/pulls?state=closed&sort=updated&direction=desc")
    normalized_pulls: list[dict[str, Any]] = []
    for pull in pulls:
        if not pull.get("merged_at") or not is_external_human(pull.get("user"), client.owner):
            continue
        files = client.paginate(f"/repos/{client.repository}/pulls/{pull['number']}/files", maximum_pages=5)
        normalized_pulls.append(pull | {"kind": "pull_request", "files": files})

    install_comments: list[dict[str, Any]] = []
    if discussion_number:
        try:
            data = client.graphql(
                DISCUSSION_QUERY,
                {"owner": client.owner, "name": client.name, "number": discussion_number},
            )
            discussion = (data.get("repository") or {}).get("discussion")
            if discussion:
                install_comments = _flatten_discussion_comments((discussion.get("comments") or {}).get("nodes") or [])
            else:
                warnings.append(f"Configured install Discussion #{discussion_number} was not found")
        except GitHubAPIError as exc:
            warnings.append(f"Install Discussion unavailable: {exc}")
    else:
        warnings.append("INSTALL_CONFIRMATION_DISCUSSION_NUMBER is not configured")

    discussions: list[dict[str, Any]] = []
    try:
        data = client.graphql(DISCUSSIONS_QUERY, {"owner": client.owner, "name": client.name})
        nodes = (((data.get("repository") or {}).get("discussions") or {}).get("nodes") or [])
        for node in nodes:
            if discussion_number and int(node.get("number") or 0) == discussion_number:
                continue
            discussions.append(
                node
                | {
                    "kind": "discussion",
                    "comments": _flatten_discussion_comments((node.get("comments") or {}).get("nodes") or []),
                }
            )
    except GitHubAPIError as exc:
        warnings.append(f"Discussions unavailable: {exc}")

    workflows: list[dict[str, Any]] = []
    try:
        workflow_payload = client.rest(
            "GET", f"/repos/{client.repository}/actions/workflows?per_page=100"
        )
        workflow_rows = workflow_payload.get("workflows") or []
        for workflow in workflow_rows:
            runs = client.rest(
                "GET",
                f"/repos/{client.repository}/actions/workflows/{workflow['id']}/runs?per_page=1&status=completed",
            )
            latest = (runs.get("workflow_runs") or [None])[0]
            workflows.append(
                {
                    "id": workflow.get("id"),
                    "name": workflow.get("name"),
                    "path": workflow.get("path"),
                    "state": workflow.get("state"),
                    "latest": {
                        "conclusion": latest.get("conclusion"),
                        "created_at": latest.get("created_at"),
                        "html_url": latest.get("html_url"),
                    }
                    if latest
                    else None,
                }
            )
    except GitHubAPIError as exc:
        warnings.append(f"Actions health unavailable: {exc}")

    pages: dict[str, Any]
    try:
        page = client.rest("GET", f"/repos/{client.repository}/pages")
        pages = {"status": page.get("status"), "html_url": page.get("html_url"), "build_type": page.get("build_type")}
    except GitHubAPIError as exc:
        pages = {"status": "unavailable"}
        warnings.append(f"Pages health unavailable: {exc}")

    return (
        {
            "repository": repository,
            "releases": releases,
            "stargazers": stargazers,
            "contributors": contributors,
            "milestones": milestones,
            "traffic": traffic,
            "install_comments": install_comments,
            "issues": normalized_issues,
            "discussions": discussions,
            "pull_requests": normalized_pulls,
            "workflows": workflows,
            "pages": pages,
        },
        warnings,
    )


def campaign_release(releases: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    return next((release for release in releases if str(release.get("tag_name")) == CAMPAIGN_TAG), None)


def _star_baseline(stargazers: Iterable[dict[str, Any]], launch_at: dt.datetime, fallback: int) -> int:
    timestamps = [parse_datetime(row.get("starred_at")) for row in stargazers]
    valid = [value for value in timestamps if value is not None]
    if not valid:
        return fallback
    return sum(1 for value in valid if value < launch_at)


def parse_state(body: str) -> dict[str, Any]:
    match = STATE_PATTERN.search(body or "")
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def build_snapshot(
    payload: dict[str, Any],
    *,
    repository_name: str,
    now: dt.datetime,
    prior_state: dict[str, Any] | None = None,
    warnings: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = repository_name.partition("/")[0]
    state = dict(prior_state or {})
    release = campaign_release(payload.get("releases") or [])
    launch_at = parse_datetime(release.get("published_at") or release.get("created_at")) if release else None
    current_stars = int((payload.get("repository") or {}).get("stargazers_count") or 0)
    if launch_at:
        stored_launch_at = parse_datetime(state.get("launch_at"))
        first_launch_observation = stored_launch_at is None
        if first_launch_observation:
            state["launch_at"] = launch_at.isoformat()
        launch_at = stored_launch_at or launch_at
        if first_launch_observation or "star_baseline" not in state:
            state["star_baseline"] = _star_baseline(payload.get("stargazers") or [], launch_at, current_stars)
    else:
        state.setdefault("star_baseline", current_stars)

    installs = valid_install_confirmations(payload.get("install_comments") or [], owner, launch_at)
    feedback = valid_external_feedback(
        [*(payload.get("issues") or []), *(payload.get("discussions") or [])], owner, launch_at
    )
    contributions = valid_source_contributions(
        [*(payload.get("issues") or []), *(payload.get("pull_requests") or [])], owner, launch_at
    )
    baseline = int(state.get("star_baseline") or 0)
    stars_gained = current_stars - baseline if launch_at else 0
    day = max(0, min(30, (now.date() - launch_at.date()).days)) if launch_at else None
    expected = round(50 * (day or 0) / 30, 1) if day is not None else 0.0

    release_rows = payload.get("releases") or []
    release_downloads = {
        str(row.get("tag_name") or "untagged"): sum(int(asset.get("download_count") or 0) for asset in row.get("assets") or [])
        for row in release_rows
    }
    workflow_health = {
        str(row.get("name") or row.get("path") or row.get("id")): {
            "state": row.get("state"),
            "latest": row.get("latest"),
        }
        for row in payload.get("workflows") or []
    }
    external_contributors = sorted(
        {
            actor_login(row)
            for row in payload.get("contributors") or []
            if is_external_human(row, owner)
        },
        key=str.casefold,
    )
    traffic = dict(payload.get("traffic") or {"status": "unavailable"})
    traffic["clones"] = {
        "status": "excluded",
        "reason": "CI clones cannot be separated reliably, so the clones endpoint is never requested.",
    }
    view_totals = traffic.get("views") if isinstance(traffic.get("views"), dict) else {}
    popular_paths = traffic.get("popular_paths") if isinstance(traffic.get("popular_paths"), list) else []
    report_paths = [
        row
        for row in popular_paths
        if any(
            marker in f"{row.get('path', '')} {row.get('title', '')}".casefold()
            for marker in ("/reports/", "public-brief", "weekly brief", "周报")
        )
    ]
    referrers = traffic.get("popular_referrers") if isinstance(traffic.get("popular_referrers"), list) else []
    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "generated_at": now.isoformat(),
        "repository": repository_name,
        "campaign": {
            "tag": CAMPAIGN_TAG,
            "status": "active" if launch_at else "prelaunch",
            "launch_at": launch_at.isoformat() if launch_at else None,
            "day": day,
            "target_days": 30,
        },
        "metrics": {
            "stars": {
                "current": current_stars,
                "baseline": baseline,
                "gained": stars_gained,
                "floor_target": 25,
                "target": 50,
                "stretch": 100,
                "linear_target_today": expected,
            },
            "confirmed_external_installs": {"count": len(installs), "target": 10, "records": installs},
            "valid_external_feedback": {"count": len(feedback), "target": 5, "records": feedback},
            "external_source_contributions": {"count": len(contributions), "target": 2, "records": contributions},
            "release_downloads": {"total": sum(release_downloads.values()), "by_tag": release_downloads},
            "auxiliary": {
                "forks": int((payload.get("repository") or {}).get("forks_count") or 0),
                "external_contributors": {
                    "count": len(external_contributors),
                    "logins": external_contributors,
                },
                "traffic_views": {
                    "status": traffic.get("status", "unavailable"),
                    "count": view_totals.get("count"),
                    "uniques": view_totals.get("uniques"),
                },
                "report_pages": {
                    "views": sum(int(row.get("count") or 0) for row in report_paths),
                    "uniques": sum(int(row.get("uniques") or 0) for row in report_paths),
                    "paths": report_paths[:10],
                },
                "popular_referrers": [
                    {
                        "referrer": row.get("referrer"),
                        "views": int(row.get("count") or 0),
                        "uniques": int(row.get("uniques") or 0),
                    }
                    for row in referrers[:10]
                ],
            },
        },
        "health": {
            "actions": workflow_health,
            "pages": payload.get("pages") or {"status": "unknown"},
            "traffic": traffic,
            "skills_sh": {
                "status": "best_effort_not_collected",
                "reason": "No external service or token is required by this workflow.",
            },
            "warnings": list(warnings),
        },
    }

    history = [row for row in state.get("history") or [] if isinstance(row, dict)]
    cutoff = now.date() - dt.timedelta(days=89)
    history = [row for row in history if (parse_datetime(row.get("generated_at")) or now).date() >= cutoff]
    daily = {
        "generated_at": now.isoformat(),
        "stars": stars_gained,
        "installs": len(installs),
        "feedback": len(feedback),
        "source_contributions": len(contributions),
    }
    history = [row for row in history if str(row.get("generated_at", ""))[:10] != now.date().isoformat()]
    history.append(daily)
    state.update(
        {
            "schema": "loyalty-radar-growth-state/v1",
            "launch_at": launch_at.isoformat() if launch_at else state.get("launch_at"),
            "star_baseline": baseline,
            "history": history,
            "weekly_comments": list(dict.fromkeys(state.get("weekly_comments") or [])),
        }
    )
    snapshot["history"] = history
    return snapshot, state


def _progress(value: int, target: int) -> str:
    return f"{value}/{target} ({min(100, round(value * 100 / target))}%)"


def render_tracking_section(snapshot: dict[str, Any], state: dict[str, Any]) -> str:
    metrics = snapshot["metrics"]
    campaign = snapshot["campaign"]
    stars = metrics["stars"]
    auxiliary = metrics["auxiliary"]
    report_uniques = auxiliary["report_pages"].get("uniques")
    traffic_uniques = auxiliary["traffic_views"].get("uniques")
    referrers = ", ".join(
        f"{row.get('referrer')} ({row.get('uniques')} unique)"
        for row in auxiliary.get("popular_referrers") or []
        if row.get("referrer")
    ) or "unavailable"
    warnings = snapshot["health"].get("warnings") or []
    status = (
        f"Day {campaign['day']} of 30"
        if campaign.get("day") is not None
        else f"Pre-launch: waiting for {CAMPAIGN_TAG}"
    )
    warning_lines = "\n".join(f"- {value}" for value in warnings) or "- None"
    machine_state = json.dumps(state, ensure_ascii=True, separators=(",", ":"))
    return "\n".join(
        [
            START_MARKER,
            "## Automated status",
            "",
            f"**{status}** · Last updated `{snapshot['generated_at']}`",
            "",
            "| Metric | Current | Goal |",
            "|---|---:|---:|",
            f"| Net new stars | {stars['gained']} | 25 floor / 50 target / 100 stretch |",
            f"| Confirmed external installs | {_progress(metrics['confirmed_external_installs']['count'], 10)} | 10 |",
            f"| Valid external Issue/Discussion threads | {_progress(metrics['valid_external_feedback']['count'], 5)} | 5 |",
            f"| Accepted external source contributions | {_progress(metrics['external_source_contributions']['count'], 2)} | 2 |",
            f"| Release asset downloads (secondary) | {metrics['release_downloads']['total']} | Observe only |",
            f"| Forks (secondary) | {auxiliary['forks']} | Observe only |",
            f"| External contributors (secondary) | {auxiliary['external_contributors']['count']} | Observe only |",
            f"| Repository unique views (best effort) | {traffic_uniques if traffic_uniques is not None else 'unavailable'} | Observe only |",
            f"| Public report page unique views (best effort) | {report_uniques if report_uniques is not None else 'unavailable'} | Observe only |",
            "",
            f"Linear 50-Star pace for today: **{stars['linear_target_today']}**. CI clones are excluded from all primary metrics.",
            f"Popular referrers (best effort): {referrers}.",
            "",
            "### Workflow health warnings",
            warning_lines,
            "",
            "Install confirmations count once per external GitHub account and require a valid `doctor --share` receipt in the configured Discussion.",
            "",
            f"<!-- loyalty-radar-growth-state:v1\n{machine_state}\n-->",
            END_MARKER,
        ]
    )


def replace_tracking_section(body: str, section: str) -> str:
    if START_MARKER in body and END_MARKER in body:
        pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
        return pattern.sub(section, body, count=1)
    prefix = body.rstrip()
    return f"{prefix}\n\n{section}\n" if prefix else f"{section}\n"


def render_weekly_comment(snapshot: dict[str, Any], week: str) -> str:
    metrics = snapshot["metrics"]
    stars = metrics["stars"]
    auxiliary = metrics["auxiliary"]
    return "\n".join(
        [
            f"{WEEK_MARKER_PREFIX}{week} -->",
            f"## Weekly growth snapshot · {week}",
            "",
            f"- Net new stars: **{stars['gained']}** (50 target, 100 stretch)",
            f"- Confirmed external installs: **{metrics['confirmed_external_installs']['count']} / 10**",
            f"- Valid external feedback: **{metrics['valid_external_feedback']['count']} / 5**",
            f"- Accepted external source contributions: **{metrics['external_source_contributions']['count']} / 2**",
            f"- Release downloads (secondary): **{metrics['release_downloads']['total']}**",
            f"- Forks / external contributors (secondary): **{auxiliary['forks']} / {auxiliary['external_contributors']['count']}**",
            f"- Public report page unique views (best effort): **{auxiliary['report_pages']['uniques']}**",
            "",
            f"Immutable snapshot generated at `{snapshot['generated_at']}`.",
        ]
    )


def find_tracking_issue(client: GitHubClient) -> dict[str, Any] | None:
    rows = client.paginate(f"/repos/{client.repository}/issues?state=all", maximum_pages=3)
    return next((row for row in rows if not row.get("pull_request") and row.get("title") == TRACKING_TITLE), None)


def resolve_milestone_number(
    milestones: Iterable[dict[str, Any]], explicit: int | None = None
) -> int | None:
    if explicit is not None:
        return explicit
    match = next(
        (row for row in milestones if str(row.get("title") or "") == "v0.1.2 Public Launch"),
        None,
    )
    return int(match["number"]) if match and match.get("number") is not None else None


def ensure_label(client: GitHubClient, name: str, color: str, description: str) -> None:
    try:
        client.rest(
            "POST",
            f"/repos/{client.repository}/labels",
            {"name": name, "color": color, "description": description},
        )
    except GitHubAPIError as exc:
        if "422" not in str(exc):
            raise


def apply_tracking_issue(
    client: GitHubClient,
    snapshot: dict[str, Any],
    state: dict[str, Any],
    existing: dict[str, Any] | None,
    milestone_number: int | None = None,
) -> dict[str, Any]:
    ensure_label(client, TRACKING_LABEL, "1d76db", "Automated public growth tracking")
    section = render_tracking_section(snapshot, state)
    milestone_payload = {"milestone": milestone_number} if milestone_number is not None else {}
    if existing:
        body = replace_tracking_section(str(existing.get("body") or ""), section)
        issue = client.rest(
            "PATCH",
            f"/repos/{client.repository}/issues/{existing['number']}",
            {"body": body, "state": "open"} | milestone_payload,
        )
    else:
        issue = client.rest(
            "POST",
            f"/repos/{client.repository}/issues",
            {
                "title": TRACKING_TITLE,
                "body": section,
                "labels": [TRACKING_LABEL],
            }
            | milestone_payload,
        )

    week = dt.datetime.fromisoformat(snapshot["generated_at"]).strftime("%G-W%V")
    comments = client.paginate(
        f"/repos/{client.repository}/issues/{issue['number']}/comments",
        maximum_pages=5,
    )
    marker = f"{WEEK_MARKER_PREFIX}{week} -->"
    if not any(marker in str(comment.get("body") or "") for comment in comments):
        client.rest(
            "POST",
            f"/repos/{client.repository}/issues/{issue['number']}/comments",
            {"body": render_weekly_comment(snapshot, week)},
        )
    return issue


def write_summary(path: Path, snapshot: dict[str, Any]) -> None:
    metrics = snapshot["metrics"]
    lines = [
        "## Loyalty Radar growth metrics",
        "",
        f"- Campaign: {snapshot['campaign']['status']} ({snapshot['campaign'].get('day')})",
        f"- Net new stars: {metrics['stars']['gained']}",
        f"- Confirmed external installs: {metrics['confirmed_external_installs']['count']}",
        f"- Valid external feedback: {metrics['valid_external_feedback']['count']}",
        f"- Accepted source contributions: {metrics['external_source_contributions']['count']}",
        f"- Forks / external contributors (secondary): {metrics['auxiliary']['forks']} / {metrics['auxiliary']['external_contributors']['count']}",
        f"- Public report page unique views (best effort): {metrics['auxiliary']['report_pages']['uniques']}",
        "- Clone traffic is excluded because CI clones cannot be separated reliably.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--discussion-number", type=int)
    parser.add_argument("--milestone-number", type=int)
    parser.add_argument("--api-input", type=Path, help="Normalized API payload for deterministic/offline runs")
    parser.add_argument("--prior-state", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--now", help="UTC ISO timestamp override")
    parser.add_argument("--apply", action="store_true", help="Create/update the one growth tracking Issue")
    args = parser.parse_args()
    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")
    now = parse_datetime(args.now) if args.now else dt.datetime.now(dt.UTC)
    if now is None:
        parser.error("--now must be an ISO timestamp")

    client: GitHubClient | None = None
    existing: dict[str, Any] | None = None
    warnings: list[str] = []
    if args.api_input:
        payload = json.loads(args.api_input.read_text(encoding="utf-8"))
    else:
        if not args.token:
            parser.error("--token or GITHUB_TOKEN is required for live collection")
        client = GitHubClient(args.repository, args.token)
        payload, warnings = collect_api_payload(client, args.discussion_number)
        existing = find_tracking_issue(client)

    prior_state: dict[str, Any] = {}
    if args.prior_state and args.prior_state.is_file():
        prior_state = json.loads(args.prior_state.read_text(encoding="utf-8"))
    elif existing:
        prior_state = parse_state(str(existing.get("body") or ""))
    snapshot, state = build_snapshot(
        payload,
        repository_name=args.repository,
        now=now,
        prior_state=prior_state,
        warnings=warnings,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        write_summary(args.summary, snapshot)
    if args.apply:
        if client is None:
            parser.error("--apply requires live GitHub collection")
        milestone_number = resolve_milestone_number(
            payload.get("milestones") or [], args.milestone_number
        )
        issue = apply_tracking_issue(
            client,
            snapshot,
            state,
            existing,
            milestone_number=milestone_number,
        )
        snapshot["tracking_issue"] = {"number": issue.get("number"), "url": issue.get("html_url")}
        snapshot["campaign"]["milestone_number"] = milestone_number
        args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(args.output),
                "campaign": snapshot["campaign"]["status"],
                "stars": snapshot["metrics"]["stars"]["gained"],
                "installs": snapshot["metrics"]["confirmed_external_installs"]["count"],
                "feedback": snapshot["metrics"]["valid_external_feedback"]["count"],
                "source_contributions": snapshot["metrics"]["external_source_contributions"]["count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GitHubAPIError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"growth-metrics: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
