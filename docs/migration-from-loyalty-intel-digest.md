# Migrating from `loyalty-intel-digest`

Loyalty Radar is a new public package derived from the workflow learned in the personal `loyalty-intel-digest` Skill. Migration is opt-in.

> **The existing `loyalty-intel-digest` Skill remains untouched.** Installing or testing Loyalty Radar does not delete, overwrite, rename, or modify the old Skill, its configuration, or its reports.

Keep both Skills until Loyalty Radar has generated and rendered a report that meets your needs.

## What changes

| Area | `loyalty-intel-digest` | Loyalty Radar `v0.1.0` |
| --- | --- | --- |
| Identity | Personal Skill name | `loyalty-radar` product, Plugin, Skill, and CLI |
| Entry point | `python scripts/run_digest.py` | `loyalty-radar` CLI; compatibility wrapper retained |
| Configuration | Files bundled in the personal Skill | User configuration outside the repository |
| Source registry | One source file | Five composable Source Packs |
| Visible language | Simplified Chinese workflow | Simplified Chinese and English per locale |
| JSON | Legacy fields including `title_zh`/`summary_zh` | `schema_version: "1.0"`, `original`, and `localized[locale]` |
| Distribution | Local Codex Skill | Codex Plugin, portable Agent Skill, and Python CLI |
| Public website | Real local reports may exist outside Git | Source catalog metadata only; reports remain local |

## Before migration

1. Record the path and version of the old Skill.
2. Keep a private backup of the old `profile.yaml`, `cards.yaml`, and any source customizations.
3. Do not copy old report directories, caches, cookies, or absolute paths into the new repository.
4. Review personal fields before moving configuration. Memberships and card holdings belong in the user configuration directory, not Git.

The old Skill's report output remains where it was originally generated.

## Install side by side

Install Loyalty Radar under its new identity. Do not rename the old directory.

For CLI testing from a Loyalty Radar checkout:

```bash
uv tool install .
loyalty-radar init
loyalty-radar sources list
```

For Agent testing, install the new Skill directory as `loyalty-radar` while leaving `loyalty-intel-digest` in place.

## Recreate the user profile

Run:

```bash
loyalty-radar init
```

Map old settings deliberately:

| Old setting | New destination |
| --- | --- |
| preferred language | `locale` / default report locale |
| home region | profile region |
| airline and alliance status | memberships |
| hotel status | memberships |
| Chase/Amex card coverage | card families or exact holdings |
| focus topics | watched topics |
| date window | evidence-window setting; default 14 days |
| future dates | watch horizon; default 60 days |
| source enable/disable flags | selected Source Packs plus per-source overrides |
| ranking weights | optional advanced ranking configuration |

Do not commit the generated user configuration. The exact directory is selected through `platformdirs` and therefore differs by operating system.

## Command mapping

```bash
# Old
python scripts/run_digest.py --mode daily --focus all --max-items 40 --include-p2

# New
loyalty-radar run --mode daily --focus all --locale zh-CN
```

```bash
# Old
python scripts/run_digest.py --mode weekly --focus credit-card

# New
loyalty-radar run --mode weekly --focus credit-card --locale zh-CN
```

```bash
# New bilingual rendering from one collection pass
loyalty-radar run --mode daily --locale zh-CN --locale en
```

The compatibility entry point remains available inside the new Skill:

```bash
python scripts/run_digest.py --mode daily --focus all
```

It accepts documented legacy arguments during the v0.1 series and emits a deprecation notice. New automation should use `loyalty-radar`.

## Existing JSON reports

The v0.1 reader accepts legacy event fields such as:

```json
{
  "title": "Original title",
  "summary": "Original summary",
  "title_zh": "中文标题",
  "summary_zh": "中文摘要"
}
```

It normalizes them conceptually to:

```json
{
  "original": {
    "title": "Original title",
    "summary": "Original summary"
  },
  "localized": {
    "zh-CN": {
      "title": "中文标题",
      "summary": "中文摘要"
    }
  }
}
```

Re-render an old audit file without fetching sources again:

```bash
loyalty-radar render --input-json /absolute/path/to/legacy-report.json --locale zh-CN
```

The common output JSON uses `schema_version: "1.0"`. Preserve the original legacy file until you have inspected the normalized output.

## Source customizations

Do not paste an entire personal `sources.yaml` into a public Source Pack.

1. Compare the old source ID with `loyalty-radar sources list`.
2. Use the packaged source when it already exists.
3. Put private enable/disable choices in the user configuration.
4. Convert a genuinely new public source into a Source Pack entry using [source-contribution.md](source-contribution.md).
5. Sanitize fixtures and remove real article bodies before proposing a pull request.

## Acceptance check

Keep using the old Skill until all applicable checks pass:

- The new profile ranks your memberships and card families correctly.
- The report uses only the selected visible locale.
- Original titles and summaries appear only in JSON when that is your chosen policy.
- HTML, PNG, Markdown, and JSON are generated in the expected output directory.
- Source and translation failures are visible.
- P0/P1 events and future dates are sensible.
- No personal path, profile, real report, or translation cache appears in `git status`.

## Rollback

There is no data migration that must be reversed. Stop invoking Loyalty Radar and continue using `loyalty-intel-digest`. Because the old Skill was not modified, its behavior and files remain independent.

Uninstalling Loyalty Radar does not automatically delete user-created configuration or reports. Remove those only after confirming their paths and contents.
