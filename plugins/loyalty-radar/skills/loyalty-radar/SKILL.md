---
name: loyalty-radar
description: Collect, cluster, prioritize, translate, and render public loyalty-program intelligence across airlines, hotels, travel credit cards, rental cars, and loyalty ecosystems. Use for 每日情报, 每周情报, 信用卡玩法, 酒店促销, 国航/星盟动态, transfer bonuses, lounges, status matches, bugs, clawbacks, risk datapoints, devaluations, partner-contract shifts, regulation, or source-health checks over the past two weeks and future 60-day dates mentioned by those sources.
---

# Loyalty Radar

## Purpose

Turn public loyalty information into source-backed events rather than a flat article list.

Produce two linked lanes:

- Member radar: promotions, credits, transfer bonuses, award availability, status matches, lounges, bugs, clawbacks, and conservative risk warnings.
- Ecosystem radar: revenue shifts, reimbursement conflicts, benefit-capacity pressure, devaluation, qualification gatekeeping, partner contracts, regulation, operational failures, supply stress, and consumer backlash.

The evidence window defaults to the past 14 days (`336` hours). Extract explicit dates in those items when they fall within the next 60 days.

## Safety And Scope

- Collect only public RSS, public HTML, public comments, and public news-index results.
- Never sign in, use account cookies, solve CAPTCHAs, or bypass anti-bot or access controls.
- Keep every failed, skipped, disabled, or browser-assisted source in health output.
- Do not confirm against official pages unless the user separately requests it.
- Do not provide steps for evading bank, airline, hotel, rental-car, merchant, or forum controls.
- Treat bugs, clawbacks, and risky plays as evidence and warnings, not exploitation instructions.
- Do not claim completeness beyond configured, publicly crawlable sources.
- Never publish the private audit JSON, fetched body text, personal profile, or test fixture as a public report.
- Public Pages may contain only real source-linked events that pass `audit --policy public`; an honest empty state is preferable to filler.

## Locale Rules

- Fresh installs default to English.
- For a Chinese conversation or a migrated Chinese profile, use `--locale zh-CN` unless the user requests another locale.
- Use repeated `--locale` arguments to generate both English and Simplified Chinese from one collection pass.
- HTML, PNG, and Markdown may read only `localized[locale]` fields. Original article text belongs only in the shared audit JSON.
- Source brands, account handles, metrics, card names, and URLs may remain canonical.
- Translation failure must show the target-language placeholder. Never fall back to the wrong visible language.

## First Run

The implementation is self-contained under `scripts/`. From this Skill directory, invoke it as:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar --help
```

If the user has not initialized a profile, gather locale, timezone, region, loyalty programs, card issuers, held travel cards, topics, and desired source packs through conversation. Then write the same cross-platform configuration used by the CLI:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar init \
  --non-interactive \
  --locale zh-CN \
  --timezone Asia/Shanghai \
  --region global \
  --membership "Marriott Bonvoy=Titanium Elite" \
  --issuer Chase \
  --issuer "American Express" \
  --source-pack core \
  --source-pack industry \
  --source-pack forums-global \
  --source-pack forums-cn
```

Never write personal profile or card data into the Skill or repository directory.

## Intent Mapping

- `每日情报`, `daily intelligence`: `run --mode daily`
- `每周情报`, `weekly intelligence`: `run --mode weekly`
- `只看信用卡`: add `--focus credit-card`
- `只看国航`, `只看星盟`: add `--focus air-china`
- `只看酒店`: add `--focus hotel`
- `只看 bug`, `只看异常`, `clawback`: add `--focus bug`
- `更新源库`, `检查来源`: use `sources list`, `sources check`, and `sources validate`
- `重新渲染`: use `render --input-json ...` and do not recollect
- `公开周报`, `public weekly brief`: use `run --preset public-weekly`, then `audit --policy public`
- `安装回执`, `installation receipt`: use `doctor --share`; sharing remains voluntary

## Normal Run

Run one collection pass and render the requested locale or locales:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar run \
  --mode daily \
  --focus all \
  --locale zh-CN \
  --max-items 40
```

For bilingual output:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar run \
  --mode daily \
  --locale zh-CN \
  --locale en
```

`daily` and `weekly` both use a rolling 14-day evidence window by default; the mode changes presentation and user intent, not the evidence cutoff. Use `--hours` only when the user explicitly asks for another range.

For a repository-owned public weekly candidate, use the fixed neutral preset:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar run \
  --preset public-weekly \
  --translation-provider google-public \
  --output-dir /absolute/private/candidate-directory
```

The preset fixes weekly/all, 336 hours, UTC, an empty membership/card profile, and the `core`, `industry`, `forums-global`, and `forums-cn` packs. It disables undated fallback and defaults to English plus Simplified Chinese. Personal profile, card, broadening, and forum-body options are rejected.

Gate and sanitize the resulting private JSON before any public use:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar audit \
  --input-json /absolute/private/candidate-directory/report.json \
  --policy public \
  --output /absolute/private/candidate-directory/public-report.json
```

The public audit requires at least 70% script-source success, 80% P0 success, valid time and HTTP(S) links for the Top 20, complete bilingual titles, no more than 10% remaining duplicates, and no private-original, path, profile, or mock markers. It has no minimum event count.

## Required Workflow

1. Resolve user configuration outside the Skill directory. With no user config, use the blank public profile and default English locale.
2. Load selected Source Packs from `references/source-packs/` and reject duplicate source IDs or invalid packs.
3. Collect configured public sources once. Do not silently omit browser-only or failed sources.
4. Apply the hard quality gate before ranking: remove ads, contests, irrelevant travel news, stale rows, invalid future-dated rows, and low-signal forum noise.
5. Classify program, card family, vertical, topic, action, risk, ecosystem signal, stakeholder, metric snippets, and future dates.
6. Cluster only evidence describing the same narrow event. Shared program names alone are not sufficient.
7. Rank against direct profile/card relevance, urgency, value, risk, confidence, future dates, and ecosystem impact. Preserve C-end, risk, ecosystem, hotel, airline, card, and rental diversity when candidates exist.
8. Translate only selected events and evidence through the configured `TranslationProvider`.
9. Write one schema `1.0` JSON containing `original`, `localized`, source health, and translation health.
10. Render locale-specific HTML, 2400 x 1800 PNG, and Markdown. Inspect P0/P1 ordering, locale leakage, source health, and image layout before reporting completion.

## Event And Priority Model

An event contains:

- identity: event ID, canonical URL, publication time
- content: original text in JSON and localized visible text
- relevance: program, card family, vertical, topic, consumer impact
- action: action label, risk label, future dates, metric snippets
- ecosystem: signal types and stakeholders
- evidence: source, source type, author, URL, time, localized summary
- ranking: score, score breakdown, confidence, and priority tier

Priority tiers:

- `P0`: directly relevant and urgent, materially risky, or unusually valuable
- `P1`: likely to affect redemption, benefits, status, or card-holding decisions
- `P2`: relevant evidence with lower urgency
- `P3`: supporting context
- `P4`: weak, undated, or uncorroborated lead

Use multi-source confidence only when at least two independent source IDs corroborate the same event. Multiple comments from one source are multiple user datapoints, not independent-source corroboration.

## Output Contract

Each normal run produces:

- `*-<locale>.html`: responsive interactive report, one event card per event
- `*-<locale>-overview.html`: bounded overview used for image rendering
- `*-<locale>.png`: 2400 x 1800 two-lane infographic; event count adapts to text volume
- `*-<locale>.md`: locale-specific text report
- `*.json`: shared schema `1.0` audit data with original and localized content

`audit --policy public` creates a separate `loyalty-radar-public-report/v1` JSON. It contains allowlisted real titles, links, times, taxonomy, metrics, deterministic rule-generated summaries, and aggregate health only. It never copies private `original` text, fetched summaries, authors, cards/profile configuration, or local paths.

The full HTML must include search, C-end/industry lane filter, vertical filter, priority filter, sorting, future-60-day timeline, expandable evidence, original links, and source-health funnel.

Never truncate or line-clamp event titles. The overview may show fewer than 12 events when full localized text needs more room. The complete HTML remains the authoritative human-readable report.

After a successful run, return the PNG as the primary preview and provide local links to HTML, Markdown, and JSON. State the exact evidence window, generated time, and any failed or browser-assisted sources.

## Source Management

List all five Source Packs and their entry counts:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar sources list
```

Validate the built-in catalog or a contributed pack:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar sources validate
PYTHONPATH=scripts python3 -m loyalty_radar sources validate /absolute/path/to/source-pack.yaml
```

Run a direct public-source health check only when requested; this command uses the network:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar sources check --max-sources 10 --json-output /absolute/path/to/health.json
```

Do not reinterpret `403`, Cloudflare, or browser-only status as zero news. Report it as an unavailable evidence lane.

## Shareable Installation Receipt

Generate the opt-in receipt with:

```bash
PYTHONPATH=scripts python3 -m loyalty_radar doctor --share
```

The JSON contains only product version, Python major/minor, OS family, and coarse Skill/Plugin/source-catalog/render capability states. It contains no username, hostname, absolute path, card or membership profile, cookie, IP address, report content, or tracking identifier. Do not post it unless the user explicitly chooses to confirm an external installation.

## Translation Providers

- `google-public`: default no-key, unofficial public endpoint; selected text is sent to a third party and availability is not guaranteed.
- `openai-compatible`: uses `LOYALTY_RADAR_OPENAI_BASE_URL`, optional `LOYALTY_RADAR_OPENAI_API_KEY`, and `LOYALTY_RADAR_TRANSLATION_MODEL`; compatible local services such as Ollama can be used.
- `none`: disables remote translation. Wrong-language source text receives a locale-specific visible placeholder.

Cache keys include provider, model, source locale, target locale, and source-text hash.

## Compatibility

`scripts/run_digest.py` retains the previous command surface and prints a deprecation warning. Prefer `loyalty-radar` or `python -m loyalty_radar` for all new work.

Legacy JSON with `title_zh` and `summary_zh` is accepted and upgraded in memory to schema `1.0`. The predecessor `loyalty-intel-digest` Skill is not modified or removed by this Skill.

## Resources

- `scripts/loyalty_radar/cli.py`: CLI orchestration
- `scripts/loyalty_radar/collectors.py`: public-source collection API
- `scripts/loyalty_radar/classification.py`: program, topic, risk, and ecosystem classification
- `scripts/loyalty_radar/clustering.py`: evidence-to-event clustering
- `scripts/loyalty_radar/ranking.py`: profile-aware scoring and diversity
- `scripts/loyalty_radar/translation.py`: batch providers and cache
- `scripts/loyalty_radar/rendering.py`: locale-safe HTML, Markdown, and PNG output
- `scripts/loyalty_radar/schema.py`: schema `1.0` and legacy readers
- `references/source-packs/`: 59-source catalog split into five packs
- `references/locales/`: English and Simplified Chinese dictionaries
- `references/schemas/`: report and Source Pack schemas
