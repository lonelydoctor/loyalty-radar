"""Load, combine, and validate source packs."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .paths import SOURCE_PACKS_DIR

ALLOWED_METHODS = {"rss", "flyert_forum", "html_keyword", "browser_only"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}


@dataclass(frozen=True)
class SourcePack:
    pack_id: str
    name: str
    description: str
    default_enabled: bool
    sources: list[dict[str, Any]]
    path: Path


def available_pack_paths(directory: Path = SOURCE_PACKS_DIR) -> list[Path]:
    return sorted(directory.glob("*.yaml"))


def load_pack(path_or_id: str | Path, directory: Path = SOURCE_PACKS_DIR) -> SourcePack:
    path = Path(path_or_id)
    if not path.exists():
        path = directory / f"{path_or_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Source pack not found: {path_or_id}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors = validate_pack_data(payload, path)
    if errors:
        raise ValueError("; ".join(errors))
    metadata = payload["pack"]
    return SourcePack(
        pack_id=str(metadata["id"]),
        name=str(metadata.get("name") or metadata["id"]),
        description=str(metadata.get("description") or ""),
        default_enabled=bool(metadata.get("default_enabled", False)),
        sources=list(payload["sources"]),
        path=path,
    )


def list_packs(directory: Path = SOURCE_PACKS_DIR) -> list[SourcePack]:
    return [load_pack(path, directory) for path in available_pack_paths(directory)]


def combine_packs(pack_ids: Iterable[str], directory: Path = SOURCE_PACKS_DIR) -> tuple[list[dict[str, Any]], list[SourcePack]]:
    packs = [load_pack(pack_id, directory) for pack_id in dict.fromkeys(pack_ids)]
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pack in packs:
        for source in pack.sources:
            source_id = str(source["id"])
            if source_id in seen:
                raise ValueError(f"Duplicate source id across packs: {source_id}")
            seen.add(source_id)
            sources.append(dict(source))
    return sources, packs


def write_combined_registry(sources: list[dict[str, Any]], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix="-sources.yaml",
        prefix="loyalty-radar-",
        dir=directory,
        encoding="utf-8",
        delete=False,
    )
    with handle:
        yaml.safe_dump({"sources": sources}, handle, allow_unicode=True, sort_keys=False)
    return Path(handle.name)


def validate_pack(path: Path) -> list[str]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path}: {exc}"]
    return validate_pack_data(payload, path)


def validate_pack_data(payload: Any, path: Path | None = None) -> list[str]:
    label = str(path or "source pack")
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{label}: root must be a mapping"]
    metadata = payload.get("pack")
    if not isinstance(metadata, dict) or not str(metadata.get("id") or "").strip():
        errors.append(f"{label}: pack.id is required")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        errors.append(f"{label}: sources must be a list")
        return errors
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, source in enumerate(sources):
        prefix = f"{label}: sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            errors.append(f"{prefix}.id is required")
        elif source_id in seen_ids:
            errors.append(f"{prefix}.id duplicates {source_id}")
        seen_ids.add(source_id)
        url = str(source.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{prefix}.url must be an http(s) URL")
        elif url in seen_urls:
            errors.append(f"{prefix}.url duplicates another source")
        seen_urls.add(url)
        if source.get("fetch_method") not in ALLOWED_METHODS:
            errors.append(f"{prefix}.fetch_method is unsupported")
        if source.get("priority") not in ALLOWED_PRIORITIES:
            errors.append(f"{prefix}.priority must be P0, P1, or P2")
        try:
            if float(source.get("rate_limit_seconds", 0)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix}.rate_limit_seconds must be zero or positive")
        try:
            if int(source.get("default_limit", 0)) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix}.default_limit must be positive")
    return errors


def validate_all_packs(directory: Path = SOURCE_PACKS_DIR) -> list[str]:
    errors: list[str] = []
    all_ids: dict[str, Path] = {}
    for path in available_pack_paths(directory):
        errors.extend(validate_pack(path))
        if errors:
            continue
        pack = load_pack(path, directory)
        for source in pack.sources:
            source_id = str(source["id"])
            if source_id in all_ids:
                errors.append(f"{path}: source id {source_id} already exists in {all_ids[source_id]}")
            all_ids[source_id] = path
    return errors
