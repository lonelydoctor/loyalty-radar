"""Filesystem locations shared by the CLI and Agent Skill."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from platformdirs import user_cache_path, user_config_path, user_documents_path
except ImportError:  # Direct Agent Skill downloads may run before package installation.
    def user_config_path(appname: str) -> Path:
        if sys.platform == "win32":
            return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / appname
        if sys.platform == "darwin":
            return Path.home() / "Library/Application Support" / appname
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / appname

    def user_cache_path(appname: str) -> Path:
        if sys.platform == "win32":
            return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / appname / "Cache"
        if sys.platform == "darwin":
            return Path.home() / "Library/Caches" / appname
        return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / appname

    def user_documents_path() -> Path:
        return Path.home() / "Documents"


PACKAGE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PACKAGE_DIR.parent
SKILL_DIR = SCRIPTS_DIR.parent
PLUGIN_DIR = SKILL_DIR.parents[1]
_SOURCE_REFERENCES = SKILL_DIR / "references"
_SOURCE_ASSETS = PLUGIN_DIR / "assets"
_INSTALLED_SHARE = Path(sys.prefix) / "share" / "loyalty-radar"
REFERENCES_DIR = _SOURCE_REFERENCES if _SOURCE_REFERENCES.exists() else _INSTALLED_SHARE / "references"
ASSETS_DIR = _SOURCE_ASSETS if _SOURCE_ASSETS.exists() else _INSTALLED_SHARE / "assets"
SOURCE_PACKS_DIR = REFERENCES_DIR / "source-packs"
LOCALES_DIR = REFERENCES_DIR / "locales"
SCHEMAS_DIR = REFERENCES_DIR / "schemas"


def config_dir() -> Path:
    override = os.environ.get("LOYALTY_RADAR_CONFIG_DIR")
    return Path(override).expanduser() if override else Path(user_config_path("loyalty-radar"))


def cache_dir() -> Path:
    override = os.environ.get("LOYALTY_RADAR_CACHE_DIR")
    return Path(override).expanduser() if override else Path(user_cache_path("loyalty-radar"))


def output_dir() -> Path:
    override = os.environ.get("LOYALTY_RADAR_OUTPUT_DIR")
    if override:
        return Path(override).expanduser()
    return Path(user_documents_path()) / "Loyalty Radar"


def translation_cache_path() -> Path:
    return cache_dir() / "translations-v1.json"
