# Contributing to Loyalty Radar

Thank you for helping improve source coverage, report quality, portability, or documentation. Loyalty Radar is a public beta, so small, well-tested changes are preferred over broad rewrites.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Good contribution areas

- Add a public regional source through a Source Pack.
- Add a fixed parser fixture for a source layout change.
- Improve event classification, clustering, or prioritization with a failing test first.
- Add or correct English and Simplified Chinese locale keys together.
- Improve accessibility, responsive layout, or long-title handling.
- Reproduce and document an installation or migration failure.
- Improve deterministic fixture coverage without including fetched article text or personal data.

Security vulnerabilities must not be filed as public issues. Follow [SECURITY.md](SECURITY.md).

## Development setup

Requirements:

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Git
- Playwright only when working on browser rendering or screenshot checks

From a checkout:

```bash
uv sync --no-editable --extra dev
uv run pytest
```

For visual work:

```bash
uv sync --no-editable --extra dev --extra render
uv run playwright install chromium
```

Useful local checks:

```bash
uv run ruff check .
uv run pytest
uv build
loyalty-radar sources validate path/to/source-pack.yaml
```

These are contributor commands, not a statement that the current checkout has already passed every release check.

## Branch and pull-request workflow

1. Open an issue first for broad architecture changes, new network behavior, schema changes, or breaking CLI changes.
2. Create a focused branch from the current default branch.
3. Keep implementation, tests, locale changes, and user-facing documentation in the same pull request.
4. Avoid formatting or refactoring unrelated files.
5. Explain the user impact, evidence, risk, and verification performed in the pull-request description.

Pull requests should remain reviewable. Separate source-catalog additions from classifier or renderer rewrites unless one requires the other.

## Test policy

Normal pull-request tests must not depend on live websites.

- Use deterministic fixtures for RSS, HTML, JSON, dates, translation responses, and browser states.
- Remove or replace real article bodies, user handles, account details, and tracking parameters.
- Use reserved domains such as `example.com` and clearly non-production values in test fixtures.
- Freeze or inject time when testing the 14-day evidence window and 60-day future horizon.
- Test failure states including `403`, timeout, parse error, browser-assisted, disabled, and rate-limited.
- Do not make a flaky live request pass by adding aggressive retries or anti-bot workarounds.

The weekly live-source health workflow is an operational audit. It is separate from deterministic PR tests and must not commit fetched content.

## Source contributions

Read [docs/source-contribution.md](docs/source-contribution.md) before submitting a Source Pack change. A source contribution must include:

- a stable, public URL;
- ownership, region, language, and fetch-method metadata;
- a conservative rate limit;
- at least one sanitized fixture and parser or schema test;
- expected failure behavior;
- a short explanation of loyalty-specific value and likely noise.

Sources that require authentication, private cookies, CAPTCHA bypass, access-control evasion, or prohibited scraping are not accepted.

## Internationalization

English and Simplified Chinese are both release languages.

- Add every renderer-owned string to `en` and `zh-CN` locale catalogs.
- Keep locale keys identical across catalogs.
- Do not hardcode visible UI strings in renderers.
- Test long unbroken words, Chinese wrapping, missing translations, and language switching.
- Keep program names, source brands, account handles, metrics, and URLs canonical unless an established localized name improves clarity.
- A translation failure must use the target-locale placeholder, never source-language leakage.

Changes written in one README should be mirrored in the other when they affect user behavior.

## Privacy and repository hygiene

Do not commit:

- real reports or fetched article bodies;
- personal membership levels, card holdings, names, email addresses, or account identifiers;
- API keys, cookies, authorization headers, local endpoints with credentials, or translation caches;
- absolute home-directory paths;
- browser profiles, screenshots with personal tabs, or image EXIF metadata;
- site content whose license does not allow redistribution.

Before submitting, inspect the staged diff and run the repository's PII, secret, and license checks when available.

## Code expectations

- Support Python 3.11 and newer.
- Prefer typed, testable modules and structured parsers over ad hoc string processing.
- Preserve the event/evidence distinction and source-health audit trail.
- Keep collectors explicit about fetch method, timeout, limits, and failure reasons.
- Keep clustering conservative; false merges are harder to audit than duplicate events.
- Treat source text as untrusted input in HTML, Markdown, logs, and filenames.
- Maintain compatibility readers for schema `1.0` and documented legacy fields throughout the v0.1 series.

## Review checklist

- [ ] The change is scoped and explained.
- [ ] Tests use fixed, sanitized fixtures and make no live network calls.
- [ ] Both locale catalogs and READMEs are updated where needed.
- [ ] Visible reports do not leak source-language text on translation failure.
- [ ] No personal data, secrets, caches, real reports, or restricted content are committed.
- [ ] Source collection remains within the documented public-access boundaries.
- [ ] User-facing behavior and migration impact are documented.

Contributions are licensed under the repository's [MIT License](LICENSE).
