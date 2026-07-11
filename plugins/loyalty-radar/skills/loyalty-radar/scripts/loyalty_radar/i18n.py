"""Locale catalog loading and validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .paths import LOCALES_DIR

SUPPORTED_LOCALES = ("en", "zh-CN")


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            result.update(_flatten(child, path))
        else:
            result[path] = str(child)
    return result


@dataclass(frozen=True)
class Catalog:
    locale: str
    values: dict[str, str]

    def text(self, key: str, **values: Any) -> str:
        if key not in self.values:
            raise KeyError(f"Missing locale key {key!r} for {self.locale}")
        template = self.values[key]
        return template.format(**values) if values else template

    def get(self, key: str, default: str | None = None, **values: Any) -> str:
        template = self.values.get(key, default if default is not None else key)
        return template.format(**values) if values else template


def normalize_locale(locale: str) -> str:
    normalized = locale.strip().replace("_", "-")
    aliases = {"zh": "zh-CN", "zh-cn": "zh-CN", "en-us": "en", "en-gb": "en"}
    value = aliases.get(normalized.lower(), normalized)
    if value not in SUPPORTED_LOCALES:
        raise ValueError(f"Unsupported locale {locale!r}; choose from {', '.join(SUPPORTED_LOCALES)}")
    return value


def load_catalog(locale: str, locales_dir: Path = LOCALES_DIR) -> Catalog:
    normalized = normalize_locale(locale)
    path = locales_dir / f"{normalized}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Locale catalog not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Locale catalog must contain a mapping: {path}")
    return Catalog(normalized, _flatten(data))


def validate_catalogs(locales: Iterable[str] = SUPPORTED_LOCALES, locales_dir: Path = LOCALES_DIR) -> list[str]:
    catalogs = [load_catalog(locale, locales_dir) for locale in locales]
    if not catalogs:
        return []
    reference = set(catalogs[0].values)
    errors: list[str] = []
    for catalog in catalogs[1:]:
        missing = sorted(reference - set(catalog.values))
        extra = sorted(set(catalog.values) - reference)
        if missing:
            errors.append(f"{catalog.locale}: missing keys: {', '.join(missing)}")
        if extra:
            errors.append(f"{catalog.locale}: extra keys: {', '.join(extra)}")
    return errors
