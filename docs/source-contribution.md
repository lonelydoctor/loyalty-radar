# Contributing a Source

Loyalty Radar grows through Source Packs rather than one global hardcoded list. A good source adds loyalty-specific evidence from a region, language, program, or stakeholder that the existing catalog misses.

This guide defines the v0.1.0 contribution contract. Run the repository validator against the checkout you are changing because the machine-readable schema is authoritative.

## Acceptance criteria

A source is eligible when all of the following are true:

- Its content is publicly accessible without an account, private cookie, or paid credential.
- It regularly contains program changes, offers, user datapoints, operational failures, loyalty economics, regulation, or benefit-delivery evidence.
- Its URL and retrieval method are specific enough to avoid broad unrelated crawling.
- The proposed request rate is conservative.
- Failure can be represented honestly as failed, skipped, disabled, or browser-assisted.
- The contribution includes a sanitized fixture and deterministic test.
- The source's likely noise and geographic or program bias are documented.

The following are not accepted:

- login-only pages, private groups, account portals, private messages, or leaked data;
- CAPTCHA solving, rotating-proxy instructions, browser-fingerprint evasion, or access-control bypass;
- collectors that import a user's browser profile or cookies;
- broad search queries with no loyalty-specific terms;
- affiliate-heavy evergreen content with no recurring event value;
- copied article bodies or forum threads committed as fixtures;
- a source whose terms clearly prohibit the proposed use.

## Choose a Source Pack

| Pack | Use it for | Default posture |
| --- | --- | --- |
| `core` | Stable, high-signal public feeds useful to most users | Enabled |
| `industry` | Loyalty economics, regulation, contracts, reimbursement, devaluation, and benefit delivery | Enabled |
| `forums-global` | Public international frequent-traveler, hotel, card, and rental-car communities | Enabled |
| `forums-cn` | Public Chinese-language loyalty and travel-card communities | Selected by locale/profile |
| `experimental` | Unstable, noisy, rate-limited, or browser-assisted sources | Disabled |

A regional source can remain in `forums-global` or `forums-cn`; v0.1.0 does not require a new pack for every country. Propose a new pack only when several sources share distinct defaults, language, region, and maintenance ownership.

Source Pack files live with the portable Skill under:

```text
plugins/loyalty-radar/skills/loyalty-radar/references/source-packs/
```

## Source Pack shape

Use YAML. The following schema illustration is non-production configuration, not report data:

```yaml
schema_version: "1.0"
pack:
  id: forums-example
  name: Example regional forums
  description: Public loyalty discussions from the Example region.
  default_enabled: false
  regions: [EX]
  languages: [en]

sources:
  - id: example-airline-forum
    name: Example Forum - Airline Loyalty
    site: Example Forum
    priority: P1
    source_type: forum
    fetch_method: rss
    url: https://example.com/loyalty/feed.xml
    region: EX
    language: en
    verticals: [airline]
    programs: [Example Airways]
    enabled: true
    default_limit: 20
    rate_limit_seconds: 10
    note: Public feed; titles and excerpts only.
```

Use ISO 3166-1 alpha-2 region codes where a source has a regional scope. Use BCP 47 language tags such as `en`, `zh-CN`, or `ja`.

### Required source fields

| Field | Meaning |
| --- | --- |
| `id` | Stable, lower-case, hyphenated identifier; never recycle an ID for a different source |
| `name` | Human-readable source/feed/board name |
| `site` | Publisher or community brand used for grouping |
| `priority` | Collection priority: `P0`, `P1`, or `P2`; this is not an event priority |
| `source_type` | Evidence category such as `rss`, `forum`, `blog_comment`, or `news_index` |
| `fetch_method` | A registered collector method |
| `fallback_provider` | Optional reviewed fallback; v0.1.x permits only `feedly-public` on RSS sources |
| `url` | Public HTTP or HTTPS endpoint |
| `region` | Intended geographic coverage |
| `language` | Expected source language |
| `enabled` | Whether the entry participates when its pack is selected |
| `default_limit` | Maximum rows requested or parsed per run before quality filtering |
| `rate_limit_seconds` | Minimum delay after a successful request |

`programs`, `verticals`, encoding, query metadata, browser-assisted state, and parser-specific fields are optional when they can be inferred safely. Prefer explicit metadata when inference could misclassify a source.

## Fetch methods

The initial catalog includes these collector classes:

| Method | Intended use | Contribution rule |
| --- | --- | --- |
| `rss` | RSS or Atom feeds, including focused public news queries | Preferred when available |
| `flyert_forum` | Public Flyert board HTML with declared encoding | Keep board-specific and rate-limited |
| `html_keyword` | Narrow public listing pages with stable selectors and loyalty filters | Requires parser fixture and noise test |
| `browser_only` | Valuable public source not reliably retrievable by the normal client | Report status only; do not add bypass logic |

Adding a new `fetch_method` requires a separate implementation review covering redirects, response limits, timeouts, encoding, HTML escaping, failure states, and deterministic fixtures.

`feedly-public` is a direct-failure fallback, not a replacement source. A contribution must prove that the returned stream ID matches the configured RSS URL, at least one usable cached item is present, items keep original HTTP(S) links and publication times, fallback use is visible in health output, and no account credential or private text is sent.

## Query design for industry signals

Industry queries should combine three dimensions:

1. A vertical or program, such as hotel, airline, credit card, rental car, Marriott, Flying Blue, or Hertz.
2. A structural signal, such as reimbursement, devaluation, loyalty revenue, capacity, regulation, partner contract, operational failure, or consumer complaints.
3. A loyalty term, such as points, miles, status, rewards, co-brand, redemption, lounge, upgrade, or loyalty program.

Good query intent:

```text
hotel owner reimbursement loyalty points redemption dispute
airline co-brand card loyalty revenue qualification change
rental car elite upgrade capacity loyalty program complaints
```

Too broad:

```text
hotel news
airline credit card
car rental deals
```

Queries must exclude generic openings, route launches, fleet news, reviews, and company earnings unless the event changes points, status, redemption, co-brand economics, or benefit delivery.

## Fixtures

Fixtures must be minimal and redistributable.

- Keep only the elements required to exercise the parser.
- Replace names, handles, URLs, article text, IDs, tracking parameters, and metrics with clearly non-production fixture values.
- Use `example.com` or another reserved domain.
- Preserve structural characteristics such as encoding, nesting, missing timestamps, or pagination.
- Add a short fixture header describing what behavior it tests, not where it was copied from.
- Do not include screenshots unless visual parsing is essential and reuse is permitted.
- Strip EXIF and other image metadata.

Normal PR tests must never call the live source. The separate scheduled health workflow is the only place for bounded live checks.

## Validation workflow

```bash
loyalty-radar sources validate plugins/loyalty-radar/skills/loyalty-radar/references/source-packs/forums-example.yaml
uv run pytest
```

The validator should reject:

- duplicate source or pack IDs;
- invalid URL schemes;
- missing language/region metadata;
- unknown priorities, source types, or fetch methods;
- missing or unsafe rate limits;
- browser-assisted sources presented as normal collectors;
- source IDs duplicated across packs.

Before opening a pull request, also inspect the source list:

```bash
loyalty-radar sources list
```

`sources check` performs network access and is not required for normal pull-request tests:

```bash
loyalty-radar sources check
```

Do not paste fetched response bodies into an issue or pull request. Report status, timing, HTTP class, parsed-row count, and a redacted error.

## Pull-request description

Include this table:

| Question | Answer |
| --- | --- |
| Source and region | |
| Loyalty-specific value | |
| Expected cadence | |
| Likely noise or bias | |
| Public-access evidence | |
| Fetch method and rate | |
| Expected blocked/failure behavior | |
| Fixture and tests added | |

Maintainers may place a source in `experimental`, lower its default priority, or decline it when legal, privacy, maintenance, or signal-quality risk exceeds its expected coverage value.

## Ongoing maintenance

A source is not permanent. It may be disabled or moved to `experimental` when it repeatedly fails, changes terms, becomes login-only, produces mostly irrelevant content, or requires brittle anti-bot behavior.

Health data should make that decision auditable. Never hide a failing source by silently returning an empty successful result.
