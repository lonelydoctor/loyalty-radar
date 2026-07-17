#!/usr/bin/env python3
"""Validate the public Plugin, Agent Skill, package, and source catalog contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "loyalty-radar"
SKILL = PLUGIN / "skills" / "loyalty-radar"
REFERENCES = SKILL / "references"


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def load_json(path: Path, validation: Validation) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(payload, dict):
        validation.errors.append(f"{path.relative_to(ROOT)}: root must be an object")
        return {}
    return payload


def load_yaml(path: Path, validation: Validation) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        validation.errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(payload, dict):
        validation.errors.append(f"{path.relative_to(ROOT)}: root must be a mapping")
        return {}
    return payload


def flatten_keys(value: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            keys.add(child_prefix)
            keys.update(flatten_keys(child, child_prefix))
    return keys


def flatten_leaves(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    leaves: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            leaves.extend(flatten_leaves(child, child_prefix))
    else:
        leaves.append((prefix, value))
    return leaves


def parse_skill_frontmatter(path: Path, validation: Validation) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        validation.errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return {}
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if not match:
        validation.errors.append(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
        return {}
    try:
        payload = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        validation.errors.append(f"{path.relative_to(ROOT)}: invalid frontmatter: {exc}")
        return {}
    return payload if isinstance(payload, dict) else {}


def validate_asset_path(raw: Any, label: str, validation: Validation) -> None:
    validation.require(isinstance(raw, str) and raw.startswith("./"), f"{label} must start with ./")
    if not isinstance(raw, str) or not raw.startswith("./"):
        return
    candidate = (PLUGIN / raw[2:]).resolve()
    validation.require(PLUGIN.resolve() in candidate.parents, f"{label} escapes the plugin directory")
    validation.require(candidate.is_file(), f"{label} does not exist: {raw}")


def validate_manifests(expected_version: str | None, validation: Validation) -> None:
    plugin_path = PLUGIN / ".codex-plugin" / "plugin.json"
    marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
    plugin = load_json(plugin_path, validation)
    marketplace = load_json(marketplace_path, validation)

    try:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    except (OSError, tomllib.TOMLDecodeError, KeyError) as exc:
        validation.errors.append(f"pyproject.toml: {exc}")
        project = {}

    version = str(plugin.get("version") or "")
    init_path = SKILL / "scripts" / "loyalty_radar" / "__init__.py"
    try:
        init_text = init_path.read_text(encoding="utf-8")
    except OSError as exc:
        validation.errors.append(f"{init_path.relative_to(ROOT)}: {exc}")
        init_text = ""
    init_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, flags=re.MULTILINE)
    validation.require(plugin.get("name") == "loyalty-radar", "plugin.json name must be loyalty-radar")
    validation.require(version == str(project.get("version") or ""), "Plugin and Python package versions must match")
    validation.require(bool(init_match) and init_match.group(1) == version, "Plugin, package, and runtime versions must match")
    if expected_version:
        validation.require(version == expected_version, f"tag version {expected_version} does not match {version}")
    validation.require(plugin.get("license") == "MIT", "plugin.json license must be MIT")
    validation.require(plugin.get("skills") == "./skills/", "plugin.json skills path must be ./skills/")

    interface = plugin.get("interface") if isinstance(plugin.get("interface"), dict) else {}
    validation.require(interface.get("category") == "Productivity", "Plugin category must be Productivity")
    capabilities = interface.get("capabilities")
    validation.require(
        isinstance(capabilities, list) and {"Interactive", "Write"}.issubset(set(capabilities)),
        "Plugin capabilities must include Interactive and Write",
    )
    prompts = interface.get("defaultPrompt")
    validation.require(isinstance(prompts, list) and 1 <= len(prompts) <= 3, "Plugin must have 1-3 starter prompts")
    if isinstance(prompts, list):
        validation.require(any(re.search(r"[\u4e00-\u9fff]", str(item)) for item in prompts), "Starter prompts must include Chinese")
        validation.require(any(re.search(r"[A-Za-z]", str(item)) for item in prompts), "Starter prompts must include English")
        validation.require(all(len(str(item)) <= 128 for item in prompts), "Starter prompts must be at most 128 characters")

    validate_asset_path(interface.get("composerIcon"), "interface.composerIcon", validation)
    for field in ("logo", "logoDark"):
        if interface.get(field) is not None:
            validate_asset_path(interface.get(field), f"interface.{field}", validation)
    screenshots = interface.get("screenshots")
    validation.require(isinstance(screenshots, list) and len(screenshots) == 3, "Plugin must declare exactly three screenshots")
    if isinstance(screenshots, list):
        for index, screenshot in enumerate(screenshots):
            validation.require(str(screenshot).lower().endswith(".png"), f"screenshot {index + 1} must be PNG")
            validate_asset_path(screenshot, f"interface.screenshots[{index}]", validation)

    plugins = marketplace.get("plugins")
    validation.require(isinstance(plugins, list) and len(plugins) == 1, "Marketplace must declare one plugin")
    if isinstance(plugins, list) and plugins:
        entry = plugins[0] if isinstance(plugins[0], dict) else {}
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        validation.require(entry.get("name") == "loyalty-radar", "Marketplace plugin name must be loyalty-radar")
        validation.require(source.get("source") == "local", "Marketplace source type must be local")
        validation.require(source.get("path") == "./plugins/loyalty-radar", "Marketplace plugin path is incorrect")


def validate_skill(validation: Validation) -> None:
    skill_md = SKILL / "SKILL.md"
    metadata = parse_skill_frontmatter(skill_md, validation)
    validation.require(metadata.get("name") == "loyalty-radar", "SKILL.md name must be loyalty-radar")
    description = metadata.get("description")
    validation.require(isinstance(description, str) and 20 <= len(description) <= 1024, "SKILL.md description must be 20-1024 characters")
    validation.require((SKILL / "agents" / "openai.yaml").is_file(), "agents/openai.yaml is required")
    validation.require((SKILL / "scripts" / "run_digest.py").is_file(), "legacy run_digest.py entry point is required")
    validation.require((SKILL / "scripts" / "loyalty_radar" / "cli.py").is_file(), "loyalty_radar/cli.py is required")


def validate_source_packs(validation: Validation) -> None:
    pack_dir = REFERENCES / "source-packs"
    paths = sorted(pack_dir.glob("*.yaml"))
    expected = {"core", "industry", "forums-global", "forums-cn", "experimental"}
    validation.require({path.stem for path in paths} == expected, "Source Pack set must be core, industry, forums-global, forums-cn, and experimental")
    source_ids: dict[str, Path] = {}
    source_urls: dict[str, Path] = {}
    source_count = 0
    allowed_methods = {"rss", "flyert_forum", "html_keyword", "browser_only"}
    for path in paths:
        payload = load_yaml(path, validation)
        pack = payload.get("pack") if isinstance(payload.get("pack"), dict) else {}
        validation.require(pack.get("id") == path.stem, f"{path.name}: pack.id must match filename")
        sources = payload.get("sources")
        validation.require(isinstance(sources, list), f"{path.name}: sources must be a list")
        if not isinstance(sources, list):
            continue
        for index, source in enumerate(sources):
            label = f"{path.name}: sources[{index}]"
            if not isinstance(source, dict):
                validation.errors.append(f"{label} must be a mapping")
                continue
            source_count += 1
            source_id = str(source.get("id") or "")
            validation.require(bool(source_id), f"{label}.id is required")
            if source_id in source_ids:
                validation.errors.append(f"{label}.id duplicates {source_ids[source_id].name}")
            source_ids[source_id] = path
            raw_url = str(source.get("url") or "")
            parsed_url = urlparse(raw_url)
            validation.require(parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc), f"{label}.url must be public HTTP(S)")
            if raw_url in source_urls:
                validation.errors.append(f"{label}.url duplicates {source_urls[raw_url].name}")
            source_urls[raw_url] = path
            validation.require(source.get("priority") in {"P0", "P1", "P2"}, f"{label}.priority is invalid")
            validation.require(source.get("fetch_method") in allowed_methods, f"{label}.fetch_method is invalid")
            validation.require(bool(str(source.get("region") or "").strip()), f"{label}.region is required")
            validation.require(bool(str(source.get("language") or "").strip()), f"{label}.language is required")
            try:
                validation.require(float(source.get("rate_limit_seconds")) >= 0, f"{label}.rate_limit_seconds must be nonnegative")
            except (TypeError, ValueError):
                validation.errors.append(f"{label}.rate_limit_seconds must be numeric")
            try:
                validation.require(int(source.get("default_limit")) > 0, f"{label}.default_limit must be positive")
            except (TypeError, ValueError):
                validation.errors.append(f"{label}.default_limit must be an integer")
    validation.require(source_count == 59, f"v0.1.2 public catalog must contain exactly 59 sources, found {source_count}")


def validate_locales_and_schemas(validation: Validation) -> None:
    en = load_yaml(REFERENCES / "locales" / "en.yaml", validation)
    zh = load_yaml(REFERENCES / "locales" / "zh-CN.yaml", validation)
    en_keys = flatten_keys(en)
    zh_keys = flatten_keys(zh)
    validation.require(en_keys == zh_keys, f"Locale key mismatch: en-only={sorted(en_keys - zh_keys)}, zh-only={sorted(zh_keys - en_keys)}")
    for locale, catalog in (("en", en), ("zh-CN", zh)):
        for key, value in flatten_leaves(catalog):
            validation.require(isinstance(value, str) and bool(value.strip()), f"{locale} locale value is empty or non-text: {key}")
    for name in (
        "config.schema.json",
        "report.schema.json",
        "source-pack.schema.json",
        "public-report.schema.json",
    ):
        load_json(REFERENCES / "schemas" / name, validation)


def validate_github_automation(validation: Validation) -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    expected = {
        "ci.yml",
        "ecosystem-smoke.yml",
        "growth-metrics.yml",
        "pages.yml",
        "public-brief-merged.yml",
        "release.yml",
        "source-health.yml",
        "source-pr-health.yml",
        "weekly-public-brief.yml",
    }
    paths = sorted(workflow_dir.glob("*.yml"))
    validation.require({path.name for path in paths} == expected, "GitHub workflow set is incomplete or contains an unreviewed workflow")

    payloads: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            payload = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        except (OSError, yaml.YAMLError) as exc:
            validation.errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        if not isinstance(payload, dict):
            validation.errors.append(f"{path.relative_to(ROOT)}: workflow root must be a mapping")
            continue
        payloads[path.name] = payload
        validation.require(bool(payload.get("name")), f"{path.name}: name is required")
        validation.require(isinstance(payload.get("on"), (dict, str, list)), f"{path.name}: on trigger is required")
        validation.require(isinstance(payload.get("jobs"), dict) and bool(payload.get("jobs")), f"{path.name}: jobs are required")
        triggers = payload.get("on") if isinstance(payload.get("on"), dict) else {}
        validation.require("pull_request_target" not in triggers, f"{path.name}: pull_request_target is forbidden")
        validation.require(payload.get("permissions") != "write-all", f"{path.name}: write-all permissions are forbidden")
        text = path.read_text(encoding="utf-8")
        if path.name == "weekly-public-brief.yml":
            validation.require("bot/brief-${WEEK}" in text, "weekly-public-brief.yml must use a deterministic bot branch")
            validation.require("public-briefs/${WEEK}/report.json" in text, "weekly-public-brief.yml must commit only the audited public-report contract")
            validation.require("gh pr merge" not in text and "--auto" not in text, "weekly-public-brief.yml must never merge automatically")
        else:
            validation.require(
                "git push" not in text and "git commit" not in text,
                f"{path.name}: only the audited weekly-brief workflow may commit content",
            )
        for token_name in ("TWITTER_TOKEN", "REDDIT_TOKEN", "FLYERTALK_TOKEN", "V2EX_TOKEN"):
            validation.require(token_name not in text, f"{path.name}: external community posting tokens are forbidden")

    health_on = payloads.get("source-health.yml", {}).get("on", {})
    if isinstance(health_on, dict):
        validation.require(set(health_on) == {"schedule", "workflow_dispatch"}, "source-health.yml must remain schedule/manual only")
    health_permissions = payloads.get("source-health.yml", {}).get("permissions", {})
    validation.require(
        health_permissions == {"contents": "read", "issues": "write"},
        "source-health.yml may write only deduplicated health Issues",
    )

    growth_text = (workflow_dir / "growth-metrics.yml").read_text(encoding="utf-8") if (workflow_dir / "growth-metrics.yml").is_file() else ""
    validation.require("actions/checkout" not in growth_text, "growth-metrics.yml must not checkout the repository")
    validation.require('cron: "13 2 * * *"' in growth_text, "growth-metrics.yml schedule must remain 02:13 UTC daily")

    weekly_text = (workflow_dir / "weekly-public-brief.yml").read_text(encoding="utf-8") if (workflow_dir / "weekly-public-brief.yml").is_file() else ""
    validation.require('cron: "27 1 * * 2"' in weekly_text, "weekly-public-brief.yml schedule must remain Tuesday 01:27 UTC")
    for required in ("--preset public-weekly", "--policy public", "retention-days: 14", "Required human review (Top 10)"):
        validation.require(required in weekly_text, f"weekly-public-brief.yml is missing {required}")

    source_pr = payloads.get("source-pr-health.yml", {})
    validation.require(
        source_pr.get("permissions") == {"contents": "read"},
        "source-pr-health.yml must remain read-only",
    )
    source_pr_text = (workflow_dir / "source-pr-health.yml").read_text(encoding="utf-8") if (workflow_dir / "source-pr-health.yml").is_file() else ""
    validation.require("continue-on-error: true" in source_pr_text, "source-pr-health.yml must remain non-blocking")
    validation.require("--source-id" in source_pr_text, "source-pr-health.yml must probe only changed sources")

    ci_text = (workflow_dir / "ci.yml").read_text(encoding="utf-8") if (workflow_dir / "ci.yml").is_file() else ""
    for required in ("ubuntu-latest", "macos-latest", "windows-latest", 'python: "3.11"', 'python: "3.12"', 'python: "3.13"'):
        validation.require(required in ci_text, f"ci.yml matrix is missing {required}")

    community_files = (
        ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml",
        ROOT / ".github" / "ISSUE_TEMPLATE" / "source.yml",
        ROOT / ".github" / "ISSUE_TEMPLATE" / "install.yml",
        ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml",
        ROOT / ".github" / "pull_request_template.md",
        ROOT / ".github" / "dependabot.yml",
    )
    for path in community_files:
        validation.require(path.is_file() and path.stat().st_size > 0, f"{path.relative_to(ROOT)} is required")


def validate_public_hygiene(validation: Validation) -> None:
    required = [
        "README.md",
        "README.zh-CN.md",
        "LICENSE",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "PRIVACY.md",
        "TRADEMARKS.md",
        "uv.lock",
    ]
    for relative in required:
        validation.require((ROOT / relative).is_file(), f"{relative} is required for the public release")

    forbidden_public_files = (
        ROOT / "examples" / "demo-report.json",
        ROOT / "tools" / "build_demo.py",
        REFERENCES / "profile.demo.yaml",
        ROOT / "docs" / "assets" / "demo-en.gif",
    )
    for path in forbidden_public_files:
        validation.require(not path.exists(), f"Mock report artifact must not be published: {path.relative_to(ROOT)}")
    validation.require((ROOT / "tools" / "build_public_site.py").is_file(), "Source Catalog builder is required")
    validation.require((ROOT / "docs" / "assets" / "catalog-en.gif").is_file(), "Source Catalog GIF is required")

    manifest_text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8") if (ROOT / "MANIFEST.in").is_file() else ""
    validation.require("prune tests" in manifest_text, "Source distributions must explicitly prune tests")
    validation.require("recursive-include tests" not in manifest_text, "Source distributions must not include test fixtures")

    profile = load_yaml(REFERENCES / "profile.yaml", validation)
    validation.require(profile.get("profile_name") == "blank-public-profile", "Compatibility profile must be blank")
    validation.require(not profile.get("ranking", {}).get("direct_programs"), "Compatibility profile must not prioritize programs")
    validation.require(not profile.get("ranking", {}).get("direct_cards"), "Compatibility profile must not include cards")

    public_text_paths = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "PRIVACY.md",
        ROOT / "CHANGELOG.md",
        PLUGIN / ".codex-plugin" / "plugin.json",
        *sorted((ROOT / "docs" / "site").rglob("*.html")),
    ]
    public_markers = ("example.invalid", "synthetic demo", "fictional report", "demo-report", "合成演示", "虚构报告")
    for path in public_text_paths:
        try:
            text = path.read_text(encoding="utf-8").lower()
        except OSError as exc:
            validation.errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        for marker in public_markers:
            validation.require(marker not in text, f"{path.relative_to(ROOT)} contains public mock-data marker {marker!r}")

    asset_pairs = (
        (ROOT / "docs/assets/icon-128.png", PLUGIN / "assets/icon-128.png"),
        (ROOT / "docs/assets/icon-512.png", PLUGIN / "assets/logo.png"),
        (ROOT / "docs/assets/overview-en.png", PLUGIN / "assets/screenshot-overview.png"),
        (ROOT / "docs/assets/report-desktop-zh-CN.png", PLUGIN / "assets/screenshot-desktop-zh-CN.png"),
        (ROOT / "docs/assets/report-mobile-en.png", PLUGIN / "assets/screenshot-mobile-en.png"),
    )
    for source, packaged in asset_pairs:
        validation.require(source.is_file() and packaged.is_file(), f"Missing synchronized public asset: {source.name}")
        if source.is_file() and packaged.is_file():
            validation.require(
                hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(packaged.read_bytes()).digest(),
                f"Plugin asset is not synchronized with Source Catalog output: {packaged.name}",
            )

    forbidden_dirs = (ROOT / "reports", ROOT / "output", ROOT / ".translation-cache")
    for path in forbidden_dirs:
        validation.require(not path.exists(), f"Private/generated directory must not be committed: {path.name}")

    profile_files = {path.name for path in REFERENCES.glob("profile*.yaml")}
    validation.require(
        profile_files == {"profile.yaml", "profile.default.yaml", "profile.public-weekly.yaml"},
        f"Unexpected profile file detected: {sorted(profile_files)}",
    )

    text_suffixes = {".md", ".py", ".toml", ".yaml", ".yml", ".json", ".txt", ".html", ".css", ".js"}
    patterns = {
        "absolute macOS home path": re.compile(r"/" r"Users/[^/\s]+/"),
        "absolute Windows home path": re.compile(r"[A-Za-z]:\\" r"Users\\[^\\\s]+\\"),
        "private key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
        "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    }
    ignored_parts = {".git", ".venv", "dist", "build", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes or any(part in ignored_parts for part in path.parts):
            continue
        validation.require(not re.search(r"\s+\d+\.[^.]+$", path.name), f"Conflict-copy filename is forbidden: {path.relative_to(ROOT)}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in patterns.items():
            if pattern.search(text):
                validation.errors.append(f"{path.relative_to(ROOT)} contains a possible {label}")

    image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in image_suffixes or any(part in ignored_parts for part in path.parts):
            continue
        try:
            with Image.open(path) as image:
                validation.require(not bool(image.getexif()), f"{path.relative_to(ROOT)} contains EXIF metadata")
        except (OSError, UnidentifiedImageError) as exc:
            validation.errors.append(f"{path.relative_to(ROOT)} is not a readable image: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", help="Require manifests to match this release version")
    args = parser.parse_args()

    validation = Validation()
    validate_manifests(args.expected_version, validation)
    validate_skill(validation)
    validate_source_packs(validation)
    validate_locales_and_schemas(validation)
    validate_github_automation(validation)
    validate_public_hygiene(validation)

    if validation.errors:
        print(f"Distribution validation failed with {len(validation.errors)} issue(s):", file=sys.stderr)
        for error in validation.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Distribution contract is valid: Plugin, Skill, package, source catalog, locales, and public hygiene.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
