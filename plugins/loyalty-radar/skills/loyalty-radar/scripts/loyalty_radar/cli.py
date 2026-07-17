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
    PUBLIC_WEEKLY_SOURCE_PACKS,
    initialize,
    load_settings,
    load_yaml,
    migrate_legacy_profile,
    resolve_cards,
    resolve_profile,
    resolve_public_weekly_cards,
    resolve_public_weekly_profile,
)
from .doctor import share_receipt_json
from .health import check_sources, localized_health_detail
from .i18n import load_catalog, normalize_locale
from .paths import SOURCE_PACKS_DIR, output_dir, translation_cache_path
from .public_audit import PublicAuditError, audit_public_report, write_public_report
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
PUBLIC_WEEKLY_PRESET = "public-weekly"


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
        quiet=args.quiet,
        profile=str(profile),
        cards=str(cards),
        sources=str(sources_registry),
        reference_date=generated_at,
    )


def _effective_run_args(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve defaults and enforce the non-personal public-weekly preset."""

    effective = argparse.Namespace(**vars(args))
    if args.preset != PUBLIC_WEEKLY_PRESET:
        effective.mode = args.mode or "daily"
        effective.focus = args.focus or "all"
        return effective

    conflicts: list[str] = []
    if args.mode not in {None, "weekly"}:
        conflicts.append("--mode must be weekly")
    if args.focus not in {None, "all"}:
        conflicts.append("--focus must be all")
    if args.hours not in {None, 336}:
        conflicts.append("--hours must be 336")
    if args.source_pack:
        conflicts.append("--source-pack cannot replace the four preset packs")
    if args.profile:
        conflicts.append("--profile cannot replace the neutral public profile")
    if args.cards:
        conflicts.append("--cards cannot replace the empty public card profile")
    if args.timezone:
        conflicts.append("--timezone cannot replace UTC")
    if args.include_p2:
        conflicts.append("--include-p2 broadens the preset")
    if args.fetch_details:
        conflicts.append("--fetch-details can copy forum body text into the private audit report")
    if args.max_items < 0 or args.max_items > 40:
        conflicts.append("--max-items must be between 0 and 40")
    if args.max_sources is not None and args.max_sources <= 0:
        conflicts.append("--max-sources must be positive")
    if args.per_source_limit is not None and args.per_source_limit <= 0:
        conflicts.append("--per-source-limit must be positive")
    if conflicts:
        raise ValueError(
            "public-weekly accepts only safe narrowing and output options: " + "; ".join(conflicts)
        )

    effective.mode = "weekly"
    effective.focus = "all"
    effective.hours = 336
    effective.locale = args.locale or ["en", "zh-CN"]
    effective.source_pack = list(PUBLIC_WEEKLY_SOURCE_PACKS)
    effective.profile = str(resolve_public_weekly_profile())
    effective.cards = str(resolve_public_weekly_cards())
    effective.timezone = "UTC"
    effective.include_p2 = False
    effective.fetch_details = False
    return effective


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
    for locale_index, locale in enumerate(locales, start=1):
        print(f"[translate {locale_index}/{len(locales)}] {locale}: preparing", file=sys.stderr)
        health = localize_report(
            payload,
            locale,
            provider,
            cache_path=cache,
            batch_size=translation_batch_size,
            delay=translation_delay,
            progress=lambda current, total, target=locale: print(
                f"[translate {target}] batch {current}/{total}",
                file=sys.stderr,
            ),
        )
        print(
            f"[translate {locale_index}/{len(locales)}] {locale}: "
            f"{health.translated} translated, {health.cache_hits} cached, {health.failed} failed",
            file=sys.stderr,
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
    args = _effective_run_args(args)
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
    if args.preset == PUBLIC_WEEKLY_PRESET:
        payload["preset"] = PUBLIC_WEEKLY_PRESET
        if args.source_id:
            payload["source_filter"] = list(dict.fromkeys(args.source_id))
        if args.max_sources is not None:
            payload["source_limit"] = args.max_sources
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


def command_audit(args: argparse.Namespace) -> int:
    input_path = Path(args.input_json).expanduser()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    try:
        public_report = audit_public_report(payload)
    except PublicAuditError as exc:
        print("Public audit failed:", file=sys.stderr)
        for issue in exc.issues:
            print(f"- {issue}", file=sys.stderr)
        return 2
    output_path = (
        Path(args.output).expanduser()
        if args.output
        else input_path.with_name(f"{input_path.stem}-public.json")
    )
    write_public_report(public_report, output_path)
    health = public_report["health"]
    print(f"Public report: {output_path}")
    print(
        "Quality gate: "
        f"sources {health['script_ok_rate']:.1%}, "
        f"P0 {health['p0_ok_rate']:.1%}, "
        f"fallbacks {health.get('fallback_sources', 0)}, "
        f"duplicates {health['duplicate_rate']:.1%}"
    )
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    print(share_receipt_json())
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

    run_parser = subparsers.add_parser(
        "run",
        help="Collect once and render one or more locales.",
        epilog=(
            "public-weekly precedence: weekly/all, 336 hours, UTC, the repository neutral "
            "profile, and core/industry/forums-global/forums-cn are fixed. --locale, "
            "--source-id, --max-sources, --per-source-limit, --max-items, --output-dir, "
            "and --no-image may narrow or redirect artifacts. A one-locale run is not "
            "eligible for the bilingual public audit. Conflicting broadening or personal "
            "profile options are rejected."
        ),
    )
    run_parser.add_argument(
        "--preset",
        choices=[PUBLIC_WEEKLY_PRESET],
        help="Use the non-personal bilingual weekly editorial collection policy.",
    )
    run_parser.add_argument("--mode", choices=["daily", "weekly"])
    run_parser.add_argument("--focus", choices=FOCUS_CHOICES)
    run_parser.add_argument(
        "--locale",
        action="append",
        choices=["en", "zh-CN"],
        help="Repeat for multiple locales; public-weekly defaults to en and zh-CN.",
    )
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
    run_parser.add_argument("--quiet", action="store_true", help="Suppress per-source collection progress.")
    run_parser.add_argument("--profile")
    run_parser.add_argument("--cards")
    run_parser.add_argument("--config-dir")
    run_parser.add_argument("--timezone")
    run_parser.add_argument("--output-dir", default=str(output_dir()))
    run_parser.add_argument("--no-image", action="store_true")
    add_translation_options(run_parser)
    run_parser.set_defaults(func=command_run)

    audit_parser = subparsers.add_parser(
        "audit", help="Gate a full local report and export a publication-safe JSON report."
    )
    audit_parser.add_argument("--input-json", required=True)
    audit_parser.add_argument("--policy", choices=["public"], required=True)
    audit_parser.add_argument("--output", help="Output path; defaults beside the input with -public.json.")
    audit_parser.set_defaults(func=command_audit)

    doctor_parser = subparsers.add_parser(
        "doctor", help="Create a privacy-safe local capability receipt."
    )
    doctor_parser.add_argument(
        "--share",
        action="store_true",
        required=True,
        help="Print stable JSON without paths, profile data, identifiers, or network access.",
    )
    doctor_parser.set_defaults(func=command_doctor)

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
