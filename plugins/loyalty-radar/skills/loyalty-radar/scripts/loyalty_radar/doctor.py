"""Privacy-safe local installation receipt for voluntary sharing."""

from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .paths import PLUGIN_DIR, SKILL_DIR
from .sources import list_packs, validate_all_packs

DOCTOR_RECEIPT_SCHEMA = "loyalty-radar-doctor-receipt/v1"


def _skill_surface() -> str:
    candidates = (
        SKILL_DIR / "SKILL.md",
        Path(sys.prefix) / "share" / "loyalty-radar" / "SKILL.md",
    )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        try:
            _opening, frontmatter, _body = text.split("---", 2)
            metadata = yaml.safe_load(frontmatter) or {}
        except (ValueError, yaml.YAMLError):
            continue
        if metadata.get("name") == "loyalty-radar" and metadata.get("description"):
            return "ok"
    return "degraded"


def _plugin_surface() -> str:
    try:
        payload = json.loads((PLUGIN_DIR / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "degraded"
    return "ok" if payload.get("name") == "loyalty-radar" else "degraded"


def _source_catalog_surface() -> str:
    try:
        packs = list_packs()
        source_ids = {str(source.get("id")) for pack in packs for source in pack.sources}
        return "ok" if source_ids and not validate_all_packs() else "degraded"
    except (OSError, ValueError, yaml.YAMLError):
        return "degraded"


def _render_surface() -> str:
    playwright = importlib.util.find_spec("playwright") is not None
    pillow = importlib.util.find_spec("PIL") is not None
    if playwright:
        return "ok"
    if pillow:
        return "available"
    return "degraded"


def build_share_receipt() -> dict[str, Any]:
    """Return stable environment capabilities without paths or user identifiers."""

    os_family = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(
        platform.system(), "linux"
    )
    return {
        "schema": DOCTOR_RECEIPT_SCHEMA,
        "product": "loyalty-radar",
        "version": __version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "os": os_family,
        "surfaces": {
            "skill": _skill_surface(),
            "plugin": _plugin_surface(),
            "source_catalog": _source_catalog_surface(),
            "render": _render_surface(),
        },
    }


def share_receipt_json() -> str:
    return json.dumps(build_share_receipt(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
