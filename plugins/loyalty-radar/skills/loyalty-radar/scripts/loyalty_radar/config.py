"""Cross-platform user configuration and first-run initialization."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .i18n import normalize_locale
from .paths import REFERENCES_DIR, config_dir

DEFAULT_SETTINGS = {
    "locale": "en",
    "timezone": "UTC",
    "region": "global",
    "source_packs": ["core", "industry", "forums-global"],
    "translation": {"provider": "google-public", "model": ""},
}

PUBLIC_WEEKLY_SOURCE_PACKS = ("core", "industry", "forums-global", "forums-cn")

AIRLINE_HINTS = {
    "air china",
    "united",
    "delta",
    "american airlines",
    "aeroplan",
    "ana",
    "krisflyer",
    "singapore airlines",
    "lufthansa",
    "flying blue",
    "avios",
    "star alliance",
    "oneworld",
    "skyteam",
}


@dataclass(frozen=True)
class ConfigPaths:
    directory: Path
    settings: Path
    profile: Path
    cards: Path


def paths(directory: Path | None = None) -> ConfigPaths:
    root = directory or config_dir()
    return ConfigPaths(root, root / "settings.yaml", root / "profile.yaml", root / "cards.yaml")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration must contain a mapping: {path}")
    return payload


def write_yaml(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load_settings(directory: Path | None = None) -> dict[str, Any]:
    current = copy.deepcopy(DEFAULT_SETTINGS)
    current.update(load_yaml(paths(directory).settings))
    current["locale"] = normalize_locale(str(current.get("locale", "en")))
    source_packs = current.get("source_packs", DEFAULT_SETTINGS["source_packs"])
    current["source_packs"] = list(dict.fromkeys(str(value) for value in source_packs))
    return current


def resolve_profile(directory: Path | None = None) -> Path:
    candidate = paths(directory).profile
    return candidate if candidate.exists() else REFERENCES_DIR / "profile.default.yaml"


def resolve_cards(directory: Path | None = None) -> Path:
    candidate = paths(directory).cards
    if candidate.exists() and load_yaml(candidate).get("issuers"):
        return candidate
    return REFERENCES_DIR / "cards.yaml"


def resolve_public_weekly_profile() -> Path:
    """Return the repository-owned profile used for public editorial runs."""

    return REFERENCES_DIR / "profile.public-weekly.yaml"


def resolve_public_weekly_cards() -> Path:
    """Return the empty card-preference file used for public editorial runs."""

    return REFERENCES_DIR / "cards.public-weekly.yaml"


def initialize(
    *,
    directory: Path | None = None,
    locale: str = "en",
    timezone: str = "UTC",
    region: str = "global",
    programs: list[str] | None = None,
    memberships: list[str] | None = None,
    issuers: list[str] | None = None,
    held_cards: list[str] | None = None,
    topics: list[str] | None = None,
    source_packs: list[str] | None = None,
    translation_provider: str = "google-public",
    force: bool = False,
) -> ConfigPaths:
    target = paths(directory)
    existing = [path for path in (target.settings, target.profile, target.cards) if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Configuration already exists: {joined}. Use --force to replace it.")

    normalized_locale = normalize_locale(locale)
    selected_programs = [value.strip() for value in programs or [] if value.strip()]
    parsed_memberships: list[tuple[str, str]] = []
    for value in memberships or []:
        program, separator, status = value.partition("=")
        program = program.strip()
        if not separator or not program or not status.strip():
            raise ValueError(f"Membership must use Program=Status format: {value!r}")
        parsed_memberships.append((program, status.strip()))
        if program not in selected_programs:
            selected_programs.append(program)
    selected_issuers = [value.strip() for value in issuers or [] if value.strip()]
    selected_cards = [value.strip() for value in held_cards or [] if value.strip()]
    selected_packs = source_packs or list(DEFAULT_SETTINGS["source_packs"])
    if normalized_locale == "zh-CN" and source_packs is None:
        selected_packs.append("forums-cn")
    settings = {
        "locale": normalized_locale,
        "timezone": timezone,
        "region": region,
        "source_packs": list(dict.fromkeys(selected_packs)),
        "translation": {"provider": translation_provider, "model": ""},
    }
    profile = load_yaml(REFERENCES_DIR / "profile.default.yaml")
    profile["language"] = normalized_locale
    profile["timezone"] = timezone
    profile["region"] = region
    status_by_program = dict(parsed_memberships)
    loyalty_profile: dict[str, list[dict[str, Any]]] = {"airline": [], "hotel": []}
    for value in selected_programs:
        normalized = value.casefold()
        group = "airline" if any(hint in normalized or normalized in hint for hint in AIRLINE_HINTS) else "hotel"
        loyalty_profile[group].append(
            {"program": value, "status": status_by_program.get(value, ""), "keywords": [value]}
        )
    profile["loyalty_profile"] = loyalty_profile
    profile["priority_topics"] = topics or profile.get("priority_topics", [])
    profile.setdefault("ranking", {})["direct_programs"] = selected_programs
    profile["ranking"]["direct_issuers"] = selected_issuers
    profile["ranking"]["direct_cards"] = selected_cards
    cards = {"held_cards": selected_cards, "preferred_issuers": selected_issuers}

    write_yaml(target.settings, settings)
    write_yaml(target.profile, profile)
    write_yaml(target.cards, cards)
    return target


def migrate_legacy_profile(legacy_profile: Path, *, directory: Path | None = None, force: bool = False) -> ConfigPaths:
    target = paths(directory)
    if target.profile.exists() and not force:
        raise FileExistsError(f"Configuration already exists: {target.profile}")
    profile = load_yaml(legacy_profile)
    locale = normalize_locale(str(profile.get("language", "zh-CN")))
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(
        {
            "locale": locale,
            "timezone": profile.get("timezone", "Asia/Shanghai"),
            "region": profile.get("region", "global"),
            "source_packs": ["core", "industry", "forums-global", "forums-cn"],
        }
    )
    write_yaml(target.settings, settings)
    write_yaml(target.profile, profile)
    if not target.cards.exists():
        write_yaml(target.cards, {"held_cards": [], "preferred_issuers": profile.get("ranking", {}).get("direct_issuers", [])})
    return target
