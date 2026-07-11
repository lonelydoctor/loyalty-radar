"""Loyalty Radar command-line interface."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import __version__, engine
from .config import (
    initialize,
    load_settings,
    load_yaml,
    migrate_legacy_profile,
    resolve_cards,
    resolve_profile,
)
from .health import check_sources, localized_health_detail
from .i18n import load_catalog, normalize_locale
from .paths import SOURCE_PACKS_DIR, output_dir, translation_cache_path
from .rendering import RenderedArtifacts, render_locale
from .schema import build_report, read_report, write_report
from .sources import (
    combine_packs,
    list_packs,
    validate_all_packs,
    validate_pack,
    write_combined_registry,
)
from .translation import create_provider, localize_report

FOCUS_CHOICES = ("all", "credit-card", "air-china", "hotel", "bug")


def _csv(value: str) -> list[str]:
    return [row.strip() for row in value.split(",") if row.strip()]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _locales(values: list[str] | None, settings: dict[str, Any]) -> list[str]:
    requested = values or [str(settings.get("locale", "en"))]
    return _unique([normalize_locale(value) for value in requested])


def _provider(args: argparse.Namespace, settings: dict[str, Any]):
    translation_settings = settings.get("translation", {})
    name = args.translation_provider or translation_settings.get("provider") or "google-public"
    model = args.translation_model or translation_settings.get("model") or None
    return create_provider(
        name,
        model=model,
        base_url=args.openai_base_url,
        api_key=args.openai_api_key,
        timeout=args.translation_timeout,
    )


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def command_init(args: argparse.Namespace) -> int:
    locale = args.locale or "en"
    timezone = args.timezone or "UTC"
    region = args.region or "global"
    programs = list(args.program or [])
    memberships = list(args.membership or [])
    issuers = list(args.issuer or [])
    cards = list(args.card or [])
    topics = list(args.topic or [])
    packs = list(args.source_pack or [])
    if not args.non_interactive and sys.stdin.isatty():
        locale = _prompt("Report locale / 报告语言 (en or zh-CN)", locale)
        prompt_catalog = load_catalog(normalize_locale(locale))
        timezone = _prompt(prompt_catalog.text("cli.prompt_timezone"), timezone)
        region = _prompt(prompt_catalog.text("cli.prompt_region"), region)
        programs = programs or _csv(_prompt(prompt_catalog.text("cli.prompt_programs"), ""))
        memberships = memberships or _csv(_prompt(prompt_catalog.text("cli.prompt_memberships"), ""))
        issuers = issuers or _csv(_prompt(prompt_catalog.text("cli.prompt_issuers"), ""))
        cards = cards or _csv(_prompt(prompt_catalog.text("cli.prompt_cards"), ""))
        packs = packs or _csv(_prompt(prompt_catalog.text("cli.prompt_packs"), "core,industry,forums-global"))
    target = initialize(
        directory=Path(args.config_dir).expanduser() if args.config_dir else None,
        locale=locale,
        timezone=timezone,
        region=region,
        programs=programs,
        memberships=memberships,
        issuers=issuers,
        held_cards=cards,
        topics=topics,
        source_packs=packs or None,
        translation_provider=args.translation_provider or "google-public",
        force=args.force,
    )
    catalog = load_catalog(normalize_locale(locale))
    print(catalog.text("cli.config_written", path=target.directory))
    return 0


def _run_namespace(
    args: argparse.Namespace,
    profile: Path,
    cards: Path,
    sources_registry: Path,
    generated_at: dt.datetime,
    hours: int,
) -> argparse.Namespace:
    return argparse.Namespace(
        mode=args.mode,
        focus=args.focus,
        hours=hours,
        max_items=args.max_items,
        per_source_limit=args.per_source_limit,
        max_sources=args.max_sources,
        source_id=args.source_id,
        include_p2=args.include_p2,
        fetch_details=args.fetch_details,
        source_delay=args.source_delay,
        detail_delay=args.detail_delay,
        profile=str(profile),
        cards=str(cards),
        sources=str(sources_registry),
        reference_date=generated_at,
    )


def _stem(mode: str, focus: str, generated_at: dt.datetime) -> str:
    safe_focus = re.sub(r"[^a-z0-9_-]+", "-", focus.lower())
    return f"loyalty-radar-{mode}-{safe_focus}-{generated_at:%Y%m%d-%H%M}"


def _render_and_print(
    payload: dict[str, Any],
    locales: list[str],
    target_dir: Path,
    stem: str,
    *,
    image: bool,
    provider: Any,
    cache: Path,
    translation_delay: float,
    translation_batch_size: int,
) -> tuple[Path, list[RenderedArtifacts]]:
    for locale in locales:
        localize_report(
            payload,
            locale,
            provider,
            cache_path=cache,
            batch_size=translation_batch_size,
            delay=translation_delay,
        )
    json_path = write_report(payload, target_dir / f"{stem}.json")
    artifacts = [render_locale(payload, locale, target_dir, stem, locales, image=image) for locale in locales]
    catalog = load_catalog(locales[0])
    print(catalog.text("cli.report_written", path=target_dir))
    for artifact in artifacts:
        print(f"[{artifact.locale}] HTML: {artifact.html}")
        if artifact.png:
            print(f"[{artifact.locale}] PNG: {artifact.png}")
        print(f"[{artifact.locale}] Markdown: {artifact.markdown}")
    print(f"JSON: {json_path}")
    return json_path, artifacts


def command_run(args: argparse.Namespace) -> int:
    config_directory = Path(args.config_dir).expanduser() if args.config_dir else None
    settings = load_settings(config_directory)
    locales = _locales(args.locale, settings)
    pack_ids = args.source_pack or settings.get("source_packs") or ["core", "industry", "forums-global"]
    sources, packs = combine_packs(pack_ids)
    target_dir = Path(args.output_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    registry = write_combined_registry(sources, target_dir)
    profile_path = Path(args.profile).expanduser() if args.profile else resolve_profile(config_directory)
    cards_path = Path(args.cards).expanduser() if args.cards else resolve_cards(config_directory)
    profile = load_yaml(profile_path)
    timezone = args.timezone or settings.get("timezone") or profile.get("timezone") or "UTC"
    generated_at = engine.now_in_timezone(str(timezone))
    defaults = profile.get("default_modes", {})
    hours = args.hours if args.hours is not None else int(defaults.get("weekly_hours" if args.mode == "weekly" else "daily_hours", 336))
    run_args = _run_namespace(args, profile_path, cards_path, registry, generated_at, hours)
    try:
        events, health = engine.collect_all(run_args)
    finally:
        registry.unlink(missing_ok=True)
    payload = build_report(
        events,
        health,
        generated_at=generated_at.isoformat(),
        mode=args.mode,
        focus=args.focus,
        hours=hours,
        timezone=str(timezone),
        source_packs=[pack.pack_id for pack in packs],
    )
    provider = _provider(args, settings)
    cache = Path(args.translation_cache).expanduser() if args.translation_cache else translation_cache_path()
    _render_and_print(
        payload,
        locales,
        target_dir,
        _stem(args.mode, args.focus, generated_at),
        image=not args.no_image,
        provider=provider,
        cache=cache,
        translation_delay=args.translation_delay,
        translation_batch_size=args.translation_batch_size,
    )
    return 0


def command_render(args: argparse.Namespace) -> int:
    settings = load_settings(Path(args.config_dir).expanduser() if args.config_dir else None)
    locales = _locales(args.locale, settings)
    payload = read_report(Path(args.input_json).expanduser())
    target_dir = Path(args.output_dir).expanduser() if args.output_dir else Path(args.input_json).expanduser().parent
    raw_stem = Path(args.input_json).stem
    stem = re.sub(r"-(?:en|zh-CN)$", "", raw_stem)
    provider = _provider(args, settings)
    cache = Path(args.translation_cache).expanduser() if args.translation_cache else translation_cache_path()
    _render_and_print(
        payload,
        locales,
        target_dir,
        stem,
        image=not args.no_image,
        provider=provider,
        cache=cache,
        translation_delay=args.translation_delay,
        translation_batch_size=args.translation_batch_size,
    )
    return 0


def command_sources_list(args: argparse.Namespace) -> int:
    packs = list_packs(Path(args.source_pack_dir) if args.source_pack_dir else SOURCE_PACKS_DIR)
    if args.json:
        print(json.dumps([dataclasses.asdict(pack) | {"path": str(pack.path)} for pack in packs], ensure_ascii=False, indent=2, default=str))
        return 0
    catalog = load_catalog(args.locale)
    print(catalog.text("cli.source_list_header"))
    for pack in packs:
        enabled = catalog.text("cli.yes") if pack.default_enabled else catalog.text("cli.no")
        description = catalog.get(f"source_pack_description.{pack.pack_id}", pack.description)
        print(f"{pack.pack_id}\t{enabled}\t{len(pack.sources)}\t{description}")
    print(catalog.text("cli.source_list_total", sources=sum(len(pack.sources) for pack in packs), packs=len(packs)))
    return 0


def command_sources_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.locale)
    errors = validate_pack(Path(args.path)) if args.path else validate_all_packs(Path(args.source_pack_dir) if args.source_pack_dir else SOURCE_PACKS_DIR)
    if errors:
        print(catalog.text("cli.source_pack_invalid"), file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(catalog.text("cli.source_pack_valid"))
    return 0


def command_sources_check(args: argparse.Namespace) -> int:
    settings = load_settings(Path(args.config_dir).expanduser() if args.config_dir else None)
    pack_ids = args.source_pack or settings.get("source_packs") or ["core", "industry", "forums-global"]
    sources, packs = combine_packs(pack_ids)
    rows = check_sources(
        sources,
        profile=Path(args.profile).expanduser() if args.profile else None,
        cards=Path(args.cards).expanduser() if args.cards else None,
        source_ids=set(args.source_id or []),
        max_sources=args.max_sources,
        per_source_limit=args.per_source_limit,
    )
    payload = {
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
        "source_packs": [pack.pack_id for pack in packs],
        "health": rows,
    }
    if args.json_output:
        path = Path(args.json_output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    catalog = load_catalog(args.locale)
    print(catalog.text("cli.health_header"))
    for row in rows:
        status = catalog.get(f"health.{row.get('status')}", str(row.get("status")))
        print(f"{row.get('source_id')}\t{status}\t{row.get('fetched', 0)}\t{localized_health_detail(row, catalog)}")
    failed = sum(1 for row in rows if row.get("status") == "failed")
    return 2 if failed and args.fail_on_error else 0


def add_translation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--translation-provider", choices=["google-public", "openai-compatible", "none"])
    parser.add_argument("--translation-model")
    parser.add_argument("--translation-cache")
    parser.add_argument("--translation-timeout", type=int, default=60)
    parser.add_argument("--translation-delay", type=float, default=0.0)
    parser.add_argument("--translation-batch-size", type=int, default=20)
    parser.add_argument("--openai-base-url", default=os.environ.get("LOYALTY_RADAR_OPENAI_BASE_URL"))
    parser.add_argument("--openai-api-key", default=os.environ.get("LOYALTY_RADAR_OPENAI_API_KEY"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loyalty-radar", description="Source-backed loyalty intelligence.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create user-owned configuration.")
    init_parser.add_argument("--config-dir")
    init_parser.add_argument("--locale", choices=["en", "zh-CN"])
    init_parser.add_argument("--timezone")
    init_parser.add_argument("--region")
    init_parser.add_argument("--program", action="append")
    init_parser.add_argument("--membership", action="append", help="Membership in Program=Status form. Can be repeated.")
    init_parser.add_argument("--issuer", action="append")
    init_parser.add_argument("--card", action="append")
    init_parser.add_argument("--topic", action="append")
    init_parser.add_argument("--source-pack", action="append")
    init_parser.add_argument("--translation-provider", choices=["google-public", "openai-compatible", "none"])
    init_parser.add_argument("--non-interactive", action="store_true")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=command_init)

    run_parser = subparsers.add_parser("run", help="Collect once and render one or more locales.")
    run_parser.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    run_parser.add_argument("--focus", choices=FOCUS_CHOICES, default="all")
    run_parser.add_argument("--locale", action="append", choices=["en", "zh-CN"])
    run_parser.add_argument("--hours", type=int)
    run_parser.add_argument("--max-items", type=int, default=40)
    run_parser.add_argument("--per-source-limit", type=int)
    run_parser.add_argument("--max-sources", type=int)
    run_parser.add_argument("--source-id", action="append")
    run_parser.add_argument("--source-pack", action="append")
    run_parser.add_argument("--include-p2", action="store_true")
    run_parser.add_argument("--fetch-details", action="store_true")
    run_parser.add_argument("--source-delay", type=float, default=0.8)
    run_parser.add_argument("--detail-delay", type=float, default=1.5)
    run_parser.add_argument("--profile")
    run_parser.add_argument("--cards")
    run_parser.add_argument("--config-dir")
    run_parser.add_argument("--timezone")
    run_parser.add_argument("--output-dir", default=str(output_dir()))
    run_parser.add_argument("--no-image", action="store_true")
    add_translation_options(run_parser)
    run_parser.set_defaults(func=command_run)

    render_parser = subparsers.add_parser("render", help="Localize and render an existing report JSON.")
    render_parser.add_argument("--input-json", required=True)
    render_parser.add_argument("--locale", action="append", choices=["en", "zh-CN"])
    render_parser.add_argument("--output-dir")
    render_parser.add_argument("--config-dir")
    render_parser.add_argument("--no-image", action="store_true")
    add_translation_options(render_parser)
    render_parser.set_defaults(func=command_render)

    sources_parser = subparsers.add_parser("sources", help="Inspect, validate, and check source packs.")
    source_commands = sources_parser.add_subparsers(dest="sources_command", required=True)
    list_parser = source_commands.add_parser("list")
    list_parser.add_argument("--source-pack-dir")
    list_parser.add_argument("--locale", choices=["en", "zh-CN"], default="en")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=command_sources_list)
    validate_parser = source_commands.add_parser("validate")
    validate_parser.add_argument("path", nargs="?")
    validate_parser.add_argument("--source-pack-dir")
    validate_parser.add_argument("--locale", choices=["en", "zh-CN"], default="en")
    validate_parser.set_defaults(func=command_sources_validate)
    check_parser = source_commands.add_parser("check")
    check_parser.add_argument("--source-pack", action="append")
    check_parser.add_argument("--source-id", action="append")
    check_parser.add_argument("--max-sources", type=int)
    check_parser.add_argument("--per-source-limit", type=int, default=2)
    check_parser.add_argument("--profile")
    check_parser.add_argument("--cards")
    check_parser.add_argument("--config-dir")
    check_parser.add_argument("--locale", choices=["en", "zh-CN"], default="en")
    check_parser.add_argument("--json-output")
    check_parser.add_argument("--fail-on-error", action="store_true")
    check_parser.set_defaults(func=command_sources_check)

    migrate_parser = subparsers.add_parser("migrate", help="Migrate a legacy local profile without changing the old Skill.")
    migrate_parser.add_argument("--legacy-profile", required=True)
    migrate_parser.add_argument("--config-dir")
    migrate_parser.add_argument("--force", action="store_true")
    migrate_parser.set_defaults(
        func=lambda args: (
            print(
                migrate_legacy_profile(
                    Path(args.legacy_profile),
                    directory=Path(args.config_dir).expanduser() if args.config_dir else None,
                    force=args.force,
                ).directory
            )
            or 0
        )
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"loyalty-radar: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
