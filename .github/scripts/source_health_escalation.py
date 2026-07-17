#!/usr/bin/env python3
"""Persist source-health streaks and deduplicate P0 GitHub Issue escalation."""

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
from pathlib import Path
from typing import Any

STATE_SCHEMA = "loyalty-radar-source-health-state/v1"
DASHBOARD_TITLE = "Loyalty Radar source-health dashboard"
LABEL = "source-health"
STATE_PATTERN = re.compile(
    r"<!-- loyalty-radar-source-health-state:v1\s*(\{.*?\})\s*-->", re.DOTALL
)
FAILURE_STATUSES = {"failed", "http_error", "network_error"}
SUCCESS_STATUSES = {"ok"}


class GitHubAPIError(RuntimeError):
    pass


def parse_state(body: str) -> dict[str, Any]:
    match = STATE_PATTERN.search(body or "")
    if not match:
        return {"schema": STATE_SCHEMA, "sources": {}}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"schema": STATE_SCHEMA, "sources": {}}
    if not isinstance(value, dict) or value.get("schema") != STATE_SCHEMA:
        return {"schema": STATE_SCHEMA, "sources": {}}
    value.setdefault("sources", {})
    return value


def _status_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(row.get("source_id") or ""),
        "source_name": str(row.get("source_name") or row.get("source") or ""),
        "pack_id": str(row.get("pack_id") or ""),
        "priority": str(row.get("priority") or "P2").upper(),
        "fetch_method": str(row.get("fetch_method") or ""),
        "url": str(row.get("url") or ""),
        "status": str(row.get("status") or "unknown").casefold(),
        "status_code": row.get("status_code"),
        "error_type": str(row.get("error_type") or ""),
    }


def update_streaks(
    current: dict[str, Any], prior: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Update observed streaks and return idempotent open/close actions."""

    generated_at = str(current.get("generated_at") or dt.datetime.now(dt.UTC).isoformat())
    sources = {
        str(key): dict(value)
        for key, value in (prior.get("sources") or {}).items()
        if isinstance(value, dict)
    }
    actions: list[dict[str, Any]] = []
    for raw in current.get("results") or []:
        row = _status_metadata(raw)
        source_id = row["source_id"]
        if not source_id:
            continue
        previous = sources.get(source_id, {})
        status = row["status"]
        streak = int(previous.get("failure_streak") or 0)
        alerted = bool(previous.get("alerted"))
        if status in SUCCESS_STATUSES:
            if alerted:
                actions.append({"action": "close", "source": row, "previous_streak": streak})
            streak = 0
            alerted = False
        elif status in FAILURE_STATUSES:
            streak += 1
            if row["priority"] == "P0" and streak >= 2 and not alerted:
                actions.append({"action": "open", "source": row, "failure_streak": streak})
                alerted = True
        entry = previous | row
        entry.update(
            {
                "failure_streak": streak,
                "alerted": alerted,
                "last_checked_at": generated_at,
            }
        )
        sources[source_id] = entry

    for raw in current.get("browser_assisted_sources") or []:
        source_id = str(raw.get("source_id") or "")
        if not source_id:
            continue
        previous = sources.get(source_id, {})
        sources[source_id] = previous | {
            "source_id": source_id,
            "pack_id": str(raw.get("pack_id") or ""),
            "priority": str(raw.get("priority") or previous.get("priority") or "P2").upper(),
            "status": "skipped",
            "skip_reason": "browser_assisted",
            "failure_streak": 0,
            "alerted": False,
            "last_checked_at": generated_at,
        }

    for raw in current.get("disabled_sources") or []:
        source_id = str(raw.get("source_id") or "")
        if not source_id:
            continue
        previous = sources.get(source_id, {})
        sources[source_id] = previous | {
            "source_id": source_id,
            "pack_id": str(raw.get("pack_id") or ""),
            "priority": str(raw.get("priority") or previous.get("priority") or "P2").upper(),
            "status": "skipped",
            "skip_reason": "disabled_in_catalog",
            "failure_streak": 0,
            "alerted": False,
            "last_checked_at": generated_at,
        }

    state = {
        "schema": STATE_SCHEMA,
        "generated_at": generated_at,
        "sources": dict(sorted(sources.items())),
    }
    return state, actions


def render_dashboard(state: dict[str, Any], current: dict[str, Any]) -> str:
    rows = list((state.get("sources") or {}).values())
    rows.sort(key=lambda row: ({"P0": 0, "P1": 1, "P2": 2}.get(str(row.get("priority")), 9), str(row.get("source_id"))))
    table = ["| Source | Priority | Last status | Failure streak | Issue |", "|---|---:|---|---:|---|"]
    for row in rows:
        issue = f"#{row['issue_number']}" if row.get("issue_number") else "—"
        table.append(
            f"| `{row.get('source_id','')}` | {row.get('priority','')} | {row.get('status','unknown')} | {int(row.get('failure_streak') or 0)} | {issue} |"
        )
    machine = json.dumps(state, ensure_ascii=True, separators=(",", ":"))
    return "\n".join(
        [
            "# Loyalty Radar source-health dashboard",
            "",
            "This Issue stores the machine-readable source failure streak. Browser-assisted sources remain skipped; a P0 alert opens only after two consecutive observed failures.",
            "",
            f"Last probe: `{current.get('generated_at','')}` · Checked: **{current.get('checked',0)}**",
            "",
            *table,
            "",
            "Repeated failures update this dashboard without posting repeated Issue comments. Recovery closes the existing source Issue once.",
            "",
            f"<!-- loyalty-radar-source-health-state:v1\n{machine}\n-->",
            "",
        ]
    )


def render_alert_body(source: dict[str, Any], streak: int) -> str:
    status_bits = [str(source.get("status") or "unknown")]
    if source.get("status_code") is not None:
        status_bits.append(f"HTTP {source['status_code']}")
    if source.get("error_type"):
        status_bits.append(str(source["error_type"]))
    return "\n".join(
        [
            f"# P0 source health: {source.get('source_id')}",
            "",
            f"The bounded public probe observed **{streak} consecutive failures** for this P0 source.",
            "",
            f"- Source: {source.get('source_name') or source.get('source_id')}",
            f"- Pack: `{source.get('pack_id')}`",
            f"- Status: `{' / '.join(status_bits)}`",
            f"- Public endpoint: {source.get('url')}",
            "",
            "No response body, cookie, credential, or private account data was retained. The next successful observed probe will close this Issue automatically.",
            "",
            f"<!-- loyalty-radar-source-health-alert:{source.get('source_id')} -->",
            "",
        ]
    )


class GitHubClient:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "loyalty-radar-source-health/0.1.2",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read(256).decode("utf-8", errors="replace")
            raise GitHubAPIError(f"GitHub API {method} {urllib.parse.urlparse(url).path} returned {exc.code}: {detail}") from exc

    def paginate(self, path: str, maximum_pages: int = 10) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        rows: list[dict[str, Any]] = []
        for page in range(1, maximum_pages + 1):
            payload = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(payload, list):
                break
            rows.extend(payload)
            if len(payload) < 100:
                break
        return rows


def ensure_label(client: GitHubClient) -> None:
    try:
        client.request(
            "POST",
            f"/repos/{client.repository}/labels",
            {"name": LABEL, "color": "b60205", "description": "Automated public source-health escalation"},
        )
    except GitHubAPIError as exc:
        if "422" not in str(exc):
            raise


def find_issue(client: GitHubClient, title: str, state: str = "all") -> dict[str, Any] | None:
    rows = client.paginate(f"/repos/{client.repository}/issues?state={state}")
    return next((row for row in rows if not row.get("pull_request") and row.get("title") == title), None)


def apply_actions(
    client: GitHubClient,
    state: dict[str, Any],
    actions: list[dict[str, Any]],
) -> None:
    ensure_label(client)
    for action in actions:
        source = action["source"]
        source_id = source["source_id"]
        title = f"Source health: {source_id}"
        existing = find_issue(client, title)
        entry = state["sources"][source_id]
        if action["action"] == "open":
            body = render_alert_body(source, int(action["failure_streak"]))
            if existing:
                issue = client.request(
                    "PATCH",
                    f"/repos/{client.repository}/issues/{existing['number']}",
                    {"body": body, "state": "open", "labels": [LABEL]},
                )
            else:
                issue = client.request(
                    "POST",
                    f"/repos/{client.repository}/issues",
                    {"title": title, "body": body, "labels": [LABEL]},
                )
            entry["issue_number"] = issue.get("number")
            entry["issue_url"] = issue.get("html_url")
            entry["alerted"] = True
        elif action["action"] == "close" and existing and existing.get("state") == "open":
            client.request(
                "POST",
                f"/repos/{client.repository}/issues/{existing['number']}/comments",
                {"body": "The next observed probe succeeded. Closing this deduplicated source-health alert."},
            )
            client.request(
                "PATCH",
                f"/repos/{client.repository}/issues/{existing['number']}",
                {"state": "closed", "state_reason": "completed"},
            )
            entry["issue_number"] = existing.get("number")
            entry["issue_url"] = existing.get("html_url")
            entry["alerted"] = False


def apply_dashboard(client: GitHubClient, body: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    ensure_label(client)
    if existing:
        return client.request(
            "PATCH",
            f"/repos/{client.repository}/issues/{existing['number']}",
            {"body": body, "state": "open", "labels": [LABEL]},
        )
    return client.request(
        "POST",
        f"/repos/{client.repository}/issues",
        {"title": DASHBOARD_TITLE, "body": body, "labels": [LABEL]},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--prior-body", type=Path)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--actions-output", type=Path, required=True)
    parser.add_argument("--dashboard-output", type=Path, required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))

    client: GitHubClient | None = None
    dashboard_issue: dict[str, Any] | None = None
    prior_body = ""
    if args.apply:
        if not args.repository or not args.token:
            parser.error("--apply requires GITHUB_REPOSITORY and GITHUB_TOKEN")
        client = GitHubClient(args.repository, args.token)
        dashboard_issue = find_issue(client, DASHBOARD_TITLE)
        prior_body = str((dashboard_issue or {}).get("body") or "")
    elif args.prior_body and args.prior_body.is_file():
        prior_body = args.prior_body.read_text(encoding="utf-8")

    state, actions = update_streaks(current, parse_state(prior_body))
    if client:
        apply_actions(client, state, actions)
    dashboard = render_dashboard(state, current)
    if client:
        dashboard_issue = apply_dashboard(client, dashboard, dashboard_issue)

    for path in (args.state_output, args.actions_output, args.dashboard_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.state_output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.actions_output.write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.dashboard_output.write_text(dashboard, encoding="utf-8")
    print(
        json.dumps(
            {
                "actions": len(actions),
                "alerts": sum(action["action"] == "open" for action in actions),
                "recoveries": sum(action["action"] == "close" for action in actions),
                "dashboard_issue": (dashboard_issue or {}).get("html_url"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, GitHubAPIError) as exc:
        print(f"source-health-escalation: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
