# Changelog

All notable changes to Loyalty Radar will be documented in this file.

The project follows [Semantic Versioning](https://semver.org/). The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

No user-visible changes have been assigned after `v0.1.2`.

## [0.1.2] - 2026-07-18

Public-report quality and review-first growth automation release.

### Added

- A neutral `public-weekly` preset, deterministic public-report audit policy, and privacy-preserving `doctor --share` installation receipt.
- Weekly real-report PR generation, daily growth metrics, source-health escalation, reviewed announcement drafts, and a public 30-day growth tracker.
- Bilingual Pages report archive and source explorer built only from sanitized, source-linked public report data.

### Changed

- Public scans now expose per-source progress and apply stricter event clustering, source-time, question, and evergreen-content rules.
- Release validation covers the Agent Skill installer, Plugin and Skill archives, clean-room CLI installation, and public-data hygiene.

### Fixed

- Elevated welcome offers are no longer misclassified as policy changes merely because they are ending soon.
- Duplicate Chase-to-IHG transfer bonuses, Marriott award-price reports, and JAL partnership coverage now cluster consistently.
- Blog comments no longer add incidental brands or ecosystem signals to the parent event, and Flyert board dates are retained when present.
- CJK font discovery now includes common macOS, Linux, and Windows families for readable PNG output.

## [0.1.1] - 2026-07-15

Public-beta packaging and source-health hardening release.

### Changed

- Weekly source-health checks now balance their bounded sample across Source Packs and rotate candidates by ISO week instead of repeatedly probing the same P0-heavy prefix.
- Runtime report footers and JSON product metadata now use the installed package version instead of a hardcoded release string.
- README installation examples now target the latest immutable patch tag.

### Fixed

- Source distributions no longer bundle deterministic test fixtures or repository-only CI, Pages, and tooling files.
- CI and release packaging now inspect every wheel, source archive, Plugin ZIP, and Skill ZIP for test paths, mock-report markers, private paths, and common secret formats.
- The first public release is now recorded with its actual publication date.

## [0.1.0] - 2026-07-11

First public-beta release.

### Added

- Public-beta repository packaging for a Codex Skill-only Plugin, portable Agent Skill, and Python CLI.
- Simplified Chinese and English report contracts with locale-specific HTML, PNG, and Markdown output.
- Schema-versioned JSON with original and localized event text, source health, and translation health.
- Five extensible source packs: `core`, `industry`, `forums-global`, `forums-cn`, and `experimental`.
- Translation-provider interface for `google-public`, `openai-compatible`, and `none`.
- Bilingual public Source Catalog Explorer generated only from committed source metadata.
- Open-source governance, privacy, security, source-contribution, architecture, and migration documentation.

### Changed

- Product and Skill identity standardized as **Loyalty Radar** / `loyalty-radar`.
- Personal profile and card holdings moved out of the repository into platform-specific user configuration.
- Visible reports localized from centralized dictionaries instead of renderer-owned hardcoded labels.
- Default evidence window standardized to 14 days with a 60-day future-event watch horizon.

### Compatibility

- `run_digest.py` remains a compatibility entry point for legacy arguments and emits a deprecation notice.
- Legacy report fields such as `title_zh` and `summary_zh` remain readable during the v0.1 series.
- The predecessor `loyalty-intel-digest` Skill remains separate and untouched.
