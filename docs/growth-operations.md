# v0.1.2 Growth Operations

This runbook defines the review-first 30-day launch process for Loyalty Radar. It is an operating contract, not a promise of GitHub stars or coverage completeness.

## Goals

Day 0 is the publication time of the `v0.1.2` GitHub Release. The 30-day targets are:

| Metric | Floor | Target | Stretch |
| --- | ---: | ---: | ---: |
| Net new stars from the Day 0 baseline | 25 | 50 | 100 |
| Confirmed external installations | 10 | 10 | - |
| Valid external Issues or Discussions | 5 | 5 | - |
| Accepted external source contributions | 2 | 2 | - |

Stars are an outcome metric. Product accuracy, installation success, privacy, source attribution, and maintainer response time take precedence over promotion volume.

## Counting Rules

- **Star:** current GitHub API stargazer count minus the immutable Day 0 baseline. A negative delta is retained rather than clamped.
- **Confirmed installation:** one distinct external GitHub account posts a valid `loyalty-radar doctor --share` receipt in the pinned installation Discussion. The owner, bots, deleted accounts, and duplicate accounts are excluded.
- **External feedback:** an Issue or Discussion opened by an external account, acknowledged by a maintainer, and not classified as invalid or duplicate.
- **Source contribution:** an external source Pull Request merged into the repository, or a valid external source request labeled `source-accepted`.
- **Supporting metrics:** release-asset downloads, forks, contributors, repository traffic, and third-party directory counts are reported separately and never substituted for a primary metric.

The metrics workflow reads repository-level GitHub data only. Loyalty Radar contains no installation callback, tracking identifier, hosted analytics, or background telemetry.

## Public Weekly Report

The Tuesday workflow runs `loyalty-radar run --preset public-weekly` against the public editorial profile:

- no personal card or membership configuration;
- `core`, `industry`, `forums-global`, and `forums-cn` Source Packs;
- a 336-hour evidence window;
- explicit future dates through the next 60 days;
- both English and Simplified Chinese visible output.

The workflow creates a report Pull Request only when the public audit policy passes. It never merges the Pull Request.

Repository maintainers must enable **Settings > Actions > General > Workflow permissions > Allow GitHub Actions to create and approve pull requests**. This permits the workflow to open a review Pull Request; it does not approve or merge that Pull Request. If the setting is disabled, the workflow keeps the audited branch, opens one deduplicated `launch-blocker` Issue with a manual compare link, and exits unsuccessfully instead of silently losing the review candidate.

Automated gates:

1. Script-fetch source success is at least 70%.
2. P0 script-fetch source success is at least 80%.
3. Every Top 20 event has an HTTP(S) source and a valid publication time.
4. Target-language completeness is 100%.
5. Post-clustering duplicate rate is at most 10%.
6. Public files contain no private original payload, article/forum body, personal configuration, absolute path, or mock marker.

No minimum event count is required. Insufficient evidence produces a truthful empty report instead of filler.

## Human Review

Before merging a public-report Pull Request, a maintainer checks the Top 10 events and records all of the following in the Pull Request:

- source link resolves to the represented item;
- publication time is inside the stated evidence window;
- title and rule-generated summary do not overstate the source;
- event classification and lane are correct;
- no duplicate event remains;
- both visible locales are complete;
- action and risk labels are conservative;
- no source body, personal data, absolute path, or private audit field is public.

The merge deploys Pages and may create a GitHub Announcement from the reviewed public payload. Community posts remain manual.

## Source Health Escalation

- First consecutive P0 failure: warning in the weekly audit only.
- Second consecutive P0 failure: create or update one `source-health` Issue for that source.
- Recovery: update and close the matching Issue after a successful probe.
- Browser-assisted sources: always report `skipped`; never classify them as failed or silently report zero items.
- Health probes are bounded, rate-limited, and never attempt authentication, CAPTCHA solving, or access-control bypass.

## Operating Cadence

| Period | Cumulative target | Primary work |
| --- | --- | --- |
| Day 0-7 | 10 stars, 3 installs, 1 feedback | Release, Pages, directory submission, one Show HN, bilingual technical launch, forum-permission requests |
| Day 8-14 | 20 stars, 5 installs, 2 feedback, 1 source | Real clustering case study, selective awesome-list Pull Requests, installation fixes |
| Day 15-21 | 35 stars, 8 installs, 4 feedback | Local-source contribution campaign and five region-specific good-first Issues |
| Day 22-30 | 50 stars, 10 installs, 5 feedback, 2 sources | Fourth weekly report, contributor credit, retrospective, and a corrective `v0.1.3` only if needed |

Decision thresholds:

- Day 7 below 5 stars or 2 installations: pause channel expansion and repair the first screen and installation path.
- Day 14 below 10 stars: prioritize a verifiable real-report case study and directory discoverability.
- Day 21 with no accepted source contribution: invite regional users to review prepared source Issues rather than increasing generic promotion.

## Community Policy

Automation may collect metrics, validate reports, open reviewed-report Pull Requests, create repository-native announcements after merge, and generate channel-specific draft artifacts. It must not post automatically to Hacker News, FlyerTalk, V2EX, Flyert, Reddit, or social networks.

Every external post must be manually reviewed for the target community, self-contained, transparent about maintainer affiliation, and materially different from posts sent elsewhere. Do not buy stars, trade votes, ask for reciprocal stars, or reuse identical promotional copy across communities.

## Weekly Review

The growth Issue receives a replaceable current-state block plus an append-only weekly snapshot containing:

- current value, target, linear expected value, and gap for each primary metric;
- Day 0 baseline and elapsed launch days;
- supporting metrics;
- last successful public-report, Pages, metrics, source-health, and release workflow runs;
- the next operating decision implied by the thresholds above.

Raw daily metrics are retained as a 90-day Actions artifact. The snapshot contains aggregate repository measurements only.

GitHub does not expose a supported repository Social Preview upload API. After regenerating `docs/site/assets/social-preview.png`, a maintainer uploads that factual image through **Settings > General > Social preview**. The image is generated from product metadata and source-health labels, not report events or test fixtures.
