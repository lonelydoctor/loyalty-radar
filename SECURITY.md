# Security Policy

## Supported versions

Loyalty Radar is in public beta. Security fixes target the latest `0.1.x` release and the default branch.

| Version | Supported |
| --- | --- |
| Latest `0.1.x` | Yes, after publication |
| Older beta builds | Best effort |
| Personal predecessor Skill | No; migrate or report against this repository |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting for this repository:

1. Open the repository's **Security** tab.
2. Select **Report a vulnerability**.
3. Include the affected version or commit, entry point, operating system, impact, and minimal reproduction.
4. Redact tokens, cookies, personal profiles, fetched content, and account details.

If private vulnerability reporting is not yet enabled, open a public issue that contains no exploit or sensitive detail and ask the maintainer to establish a private channel.

No bug bounty is offered. Reports are reviewed on a best-effort basis; no response or remediation deadline is guaranteed during the public beta.

## In scope

- command injection or unsafe subprocess invocation;
- path traversal or writes outside the selected configuration/output directory;
- server-side request forgery or unsafe redirect handling in collectors;
- credential, cookie, API-key, or personal-profile disclosure;
- cross-site scripting or script injection in generated HTML reports;
- unsafe deserialization or schema-validation bypass;
- translation-provider requests that transmit more data than documented;
- dependency vulnerabilities with a practical Loyalty Radar impact;
- release artifacts that contain secrets, personal paths, real reports, or unexpected fetched content.

## Usually not security issues

- a public source becoming unavailable, rate-limited, or blocked;
- an incorrect classification, summary, ranking, or translation without a security impact;
- a source's terms changing;
- incomplete news coverage;
- a loyalty-program policy dispute or incorrect public datapoint;
- reports produced after a user intentionally enables a third-party translation provider.

Those issues can be filed through the normal issue tracker after removing personal or copyrighted content.

## Security design expectations

Loyalty Radar treats all fetched text, URLs, filenames, configuration, and translation output as untrusted input. Implementations should:

- escape visible HTML and Markdown content;
- allow only declared HTTP and HTTPS source URLs;
- apply timeouts, response-size limits, redirect limits, and conservative rate limits;
- never read browser cookies or credential stores;
- avoid shell execution for network retrieval and rendering;
- keep user configuration and reports local unless the user explicitly selects a network provider;
- show failed and skipped sources instead of attempting access-control bypasses.

See [PRIVACY.md](PRIVACY.md) for the data-flow model.
