# Changelog

All notable changes to Loyalty Radar will be documented in this file.

The project follows [Semantic Versioning](https://semver.org/). The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

No user-visible changes have been assigned beyond the first public-beta release.

## [0.1.0] - Unreleased

First public-beta release. The release date and artifact links will be added only after the release workflow completes.

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
