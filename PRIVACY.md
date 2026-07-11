# Privacy and Data Handling

Loyalty Radar is a local-first open-source Skill and command-line tool. It has no hosted account system, product telemetry, advertising identifier, or background scheduler in `v0.1.0`.

This document describes the project's intended data flows. It does not govern third-party websites, translation services, agent hosts, or tools used to install the project.

## Data Loyalty Radar may process

### User configuration

The optional profile can include:

- preferred locale and region;
- airline, hotel, and rental-car memberships;
- travel-card families and transferable-points programs;
- topics, programs, and source packs to prioritize;
- translation-provider settings.

The repository contains only blank configuration templates. `loyalty-radar init` stores real configuration in the platform-standard user configuration directory provided by `platformdirs`, outside the repository.

### Public source data

Collectors may process public article or post titles, summaries, timestamps, URLs, source names, and public author or account handles when available. The common audit JSON may retain original text and the evidence needed to explain an event.

Public availability does not make content free of privacy or copyright concerns. Do not publish real report JSON, bulk source text, or user handles without reviewing the source's terms and the rights of the people involved.

### Generated data

Loyalty Radar may create:

- localized HTML, PNG, and Markdown reports;
- schema-versioned JSON audit data;
- source-health and translation-health records;
- translation caches;
- diagnostic logs that exclude secrets and article bodies by default.

Users choose the output directory and control retention.

## Network destinations

### Configured sources

Running collection sends normal HTTP requests to the public URLs enabled in the selected Source Packs. A request may expose ordinary network metadata such as IP address, User-Agent, request time, and requested path to the source and its infrastructure providers.

Collectors must not send account cookies, login credentials, private profile data, or authorization headers to content sources.

### Translation providers

Translation runs only after ranking and should send only the selected title and summary text needed for a target locale.

| Provider | Data destination | Key point |
| --- | --- | --- |
| `google-public` | An unofficial third-party public translation endpoint | No key required; availability and privacy terms are not controlled by this project |
| `openai-compatible` | The endpoint configured by the user | May be a hosted provider or a compatible local service such as Ollama |
| `none` | No translation network request | Reports use already localized content or a target-language missing-translation placeholder |

Provider, model, source locale, target locale, and a hash of the original text form part of the translation-cache key. Translation failures must not expose the original in a visible target-language report.

Do not place API keys directly in repository configuration or command history. Follow the selected provider's credential guidance.

### Agent hosts and installers

Codex, another Agent host, Git, uv, package indexes, GitHub, and browser-rendering dependencies may process data under their own terms. Loyalty Radar does not control those tools.

## Local storage and retention

Real configuration, caches, and reports stay on the user's machine unless the user explicitly uploads, shares, or places them in a synchronized directory.

Loyalty Radar does not automatically delete reports because audit retention needs vary. Users can remove configuration, output directories, and translation caches with normal filesystem tools. Uninstalling the CLI or Skill may not remove those user-created files.

The project does not intentionally collect usage metrics. GitHub may provide aggregate repository traffic and release-download statistics under GitHub's policies; those are not embedded product telemetry.

## Public website and visuals

The public website and release visuals contain source-catalog metadata read from committed Source Packs. They do not contain report events, offers, user datapoints, fetched article bodies, personal membership/card data, browser tabs, absolute user paths, or identifying image metadata. Real reports stay local and are not used as public screenshots.

## Collection boundaries

Loyalty Radar is designed for publicly accessible material only. It must not:

- authenticate to content sources;
- reuse user cookies or browser profiles;
- bypass CAPTCHAs, paywalls, access controls, or anti-bot systems;
- collect private messages or private account pages;
- silently continue when a source denies access.

Unavailable sources are recorded as failed, skipped, disabled, or browser-assisted in source health.

## User responsibilities

Before enabling, sharing, or contributing a source, review applicable laws, source terms, robots guidance, and content licenses. Before sharing a report, inspect its JSON and visible artifacts for public handles, quoted text, personal configuration, and sensitive business or travel information.

To report a privacy or security issue, follow [SECURITY.md](SECURITY.md).
