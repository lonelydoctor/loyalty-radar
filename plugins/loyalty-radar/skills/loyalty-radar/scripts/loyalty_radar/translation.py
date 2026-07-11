"""Batch translation providers with locale-safe caching."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import requests

from .i18n import load_catalog, normalize_locale
from .paths import translation_cache_path

GOOGLE_PUBLIC_URL = "https://translate.googleapis.com/translate_a/single"


@dataclass
class TranslationHealth:
    provider: str
    model: str
    target_locale: str
    requested: int = 0
    cache_hits: int = 0
    translated: int = 0
    passthrough: int = 0
    failed: int = 0
    request_attempts: int = 0
    cache_path: str = ""
    errors: list[str] = field(default_factory=list)


class TranslationProvider(Protocol):
    name: str
    model: str

    def translate_batch(self, texts: list[str], source_locale: str, target_locale: str) -> list[str]: ...


class GooglePublicProvider:
    name = "google-public"
    model = "translate.googleapis.com"

    def __init__(self, timeout: int = 25) -> None:
        self.timeout = timeout

    def translate_batch(self, texts: list[str], source_locale: str, target_locale: str) -> list[str]:
        results: list[str] = []
        target = "zh-CN" if target_locale == "zh-CN" else "en"
        for value in texts:
            response = requests.get(
                GOOGLE_PUBLIC_URL,
                params={"client": "gtx", "sl": source_locale, "tl": target, "dt": "t", "q": value},
                headers={"User-Agent": "Loyalty-Radar/0.1 (+https://github.com/lonelydoctor/loyalty-radar)"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            segments = payload[0] if isinstance(payload, list) and payload else []
            results.append("".join(str(row[0]) for row in segments if isinstance(row, list) and row))
        return results


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, timeout: int = 60) -> None:
        self.base_url = (base_url or os.environ.get("LOYALTY_RADAR_OPENAI_BASE_URL") or "http://localhost:11434/v1").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("LOYALTY_RADAR_OPENAI_API_KEY", "")
        self.model = model or os.environ.get("LOYALTY_RADAR_TRANSLATION_MODEL", "qwen2.5:7b")
        self.timeout = timeout

    def translate_batch(self, texts: list[str], source_locale: str, target_locale: str) -> list[str]:
        instruction = (
            "Translate each JSON array element faithfully for a loyalty-program intelligence report. "
            f"Target locale: {target_locale}. Preserve brands, handles, dates, numbers, URLs, and card names. "
            "Return only a JSON array of strings with the same length and order."
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S)
        values = json.loads(content)
        if not isinstance(values, list) or len(values) != len(texts):
            raise ValueError("OpenAI-compatible provider returned an invalid translation array")
        return [str(value) for value in values]


class NoneProvider:
    name = "none"
    model = "none"

    def translate_batch(self, texts: list[str], source_locale: str, target_locale: str) -> list[str]:
        raise RuntimeError("Translation is disabled")


def create_provider(name: str, **kwargs: Any) -> TranslationProvider:
    if name == "google-public":
        return GooglePublicProvider(timeout=int(kwargs.get("timeout", 25)))
    if name == "openai-compatible":
        return OpenAICompatibleProvider(
            base_url=kwargs.get("base_url"),
            api_key=kwargs.get("api_key"),
            model=kwargs.get("model"),
            timeout=int(kwargs.get("timeout", 60)),
        )
    if name == "none":
        return NoneProvider()
    raise ValueError(f"Unknown translation provider: {name}")


def _is_target_language(text: str, locale: str) -> bool:
    if not text.strip():
        return True
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if locale == "zh-CN":
        return cjk > 0 and cjk >= latin
    return latin > 0 and latin >= cjk


def _load_cache(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _cache_key(provider: TranslationProvider, source_locale: str, target_locale: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{provider.name}|{provider.model}|{source_locale}|{target_locale}|{digest}"


def _text_slots(payload: dict[str, Any]) -> list[tuple[dict[str, Any], str, str]]:
    slots: list[tuple[dict[str, Any], str, str]] = []
    for event in payload.get("items", []):
        original = event.get("original", {})
        for field_name in ("title", "summary", "why_it_matters"):
            slots.append((event, field_name, str(original.get(field_name) or "")))
        for evidence in event.get("evidence", []):
            evidence_original = evidence.get("original", {})
            for field_name in ("title", "summary"):
                slots.append((evidence, field_name, str(evidence_original.get(field_name) or "")))
    return slots


def localize_report(
    payload: dict[str, Any],
    locale: str,
    provider: TranslationProvider,
    *,
    cache_path: Path | None = None,
    batch_size: int = 20,
    delay: float = 0.0,
) -> TranslationHealth:
    target = normalize_locale(locale)
    cache_file = cache_path or translation_cache_path()
    cache = _load_cache(cache_file)
    catalog = load_catalog(target)
    health = TranslationHealth(provider.name, provider.model, target, cache_path=cache_file.name)
    pending: list[tuple[dict[str, Any], str, str, str]] = []

    for owner, field_name, original in _text_slots(payload):
        localized = owner.setdefault("localized", {}).setdefault(target, {})
        if localized.get(field_name):
            continue
        if not original:
            localized[field_name] = catalog.get("fallback.empty", "")
            health.passthrough += 1
            continue
        if _is_target_language(original, target):
            localized[field_name] = original
            health.passthrough += 1
            continue
        health.requested += 1
        key = _cache_key(provider, "auto", target, original)
        if key in cache:
            localized[field_name] = cache[key]
            health.cache_hits += 1
            continue
        pending.append((owner, field_name, original, key))

    for start in range(0, len(pending), max(1, batch_size)):
        batch = pending[start : start + max(1, batch_size)]
        health.request_attempts += 1
        try:
            translated = provider.translate_batch([row[2] for row in batch], "auto", target)
            if len(translated) != len(batch):
                raise ValueError("Translation provider returned a different number of rows")
            for (owner, field_name, _original, key), value in zip(batch, translated, strict=True):
                value = str(value).strip()
                if not value:
                    raise ValueError("Translation provider returned an empty string")
                owner.setdefault("localized", {}).setdefault(target, {})[field_name] = value
                cache[key] = value
                health.translated += 1
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            if message not in health.errors:
                health.errors.append(message[:300])
            placeholder = catalog.text("fallback.translation_failed")
            for owner, field_name, _original, _key in batch:
                owner.setdefault("localized", {}).setdefault(target, {})[field_name] = placeholder
                health.failed += 1
        if delay and start + batch_size < len(pending):
            time.sleep(delay)

    _save_cache(cache_file, cache)
    payload.setdefault("translation_health", {})[target] = asdict(health)
    return health
