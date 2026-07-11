## Summary

Describe the user-visible change and why it belongs in Loyalty Radar.

## Change type

- [ ] Core collection, clustering, ranking, or schema
- [ ] Source Pack
- [ ] Translation or locale
- [ ] Rendering or public Source Catalog
- [ ] Plugin, Skill, CLI, packaging, or CI
- [ ] Documentation only

## Verification

List the exact commands run and their results. Use fixture-only tests for pull requests; do not attach real scraped reports.

```text
uv run pytest -m "not live and not screenshot"
```

- [ ] Relevant tests were added or updated.
- [ ] `uv build` succeeds when packaging changed.
- [ ] Plugin/Skill distribution validation succeeds when manifests or assets changed.
- [ ] English and Simplified Chinese layouts were checked when visible text changed.

## Source changes

Complete this section for a Source Pack change.

- Public source URL:
- Region and language:
- Fetch method:
- Proposed rate limit:
- [ ] No login, private cookie, CAPTCHA bypass, or anti-bot circumvention is required.
- [ ] Fixtures contain only the minimum sanitized or transformed material needed for testing.
- [ ] The Source Pack validator reports no duplicate IDs or URLs.

## Privacy and security

- [ ] No personal profile, membership/card data, real report, cache, API key, cookie, or absolute local path is included.
- [ ] New network behavior is bounded, transparent, and documented.
- [ ] Public Pages and release visuals contain source metadata only, with no report events or mock data.

## Compatibility

Describe CLI, configuration, JSON schema, and legacy `run_digest.py` compatibility impact, or write `None`.

## Visual evidence

For UI changes, attach source-catalog or empty-state desktop and mobile screenshots. Do not attach locally generated real reports.
