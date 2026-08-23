# Security Policy

## Supported versions

Security fixes are provided for the latest stable release only.

| Version | Supported |
| --- | --- |
| Latest stable release | Yes |
| Earlier releases | No |
| Unreleased development builds | No |

## Reporting a vulnerability

Do not report security vulnerabilities through public GitHub Issues,
Discussions, or pull requests.

For the public repository, use GitHub Private Vulnerability Reporting:

1. Open the repository's **Security** tab.
2. Open **Advisories**.
3. Select **Report a vulnerability**.

If that button is unavailable, do not disclose the issue publicly. A maintainer
must enable GitHub Private Vulnerability Reporting before the repository is
announced as public.

Please include, where possible:

- affected version or commit;
- a clear vulnerability description and impact;
- minimal reproduction steps or proof of concept with secrets removed;
- relevant redacted logs; and
- a suggested remediation, if known.

Never include credentials, private keys, access tokens, pairing codes, personal
data, private deployment URLs, or raw Hermes logs in a public report.

## Response process

The maintainers will make a reasonable effort to:

- acknowledge a report within three business days;
- perform initial triage within seven business days;
- coordinate remediation and disclosure with the reporter; and
- publish a GitHub Security Advisory when appropriate.

Timelines can vary with severity, complexity, and maintainer availability.
Please give maintainers reasonable time to investigate and remediate an issue
before public disclosure.

## In scope

Examples of in-scope reports include:

- authentication, pairing, or authorization bypass;
- unauthorized Hermes Agent, Profile, session, or message access;
- token, credential, private-key, or sensitive-information disclosure;
- privilege escalation, remote code execution, or container escape; and
- violations of the documented Cloud event or notification isolation boundary.

## Deployment security boundaries

- The installer creates a dedicated Server-to-Agent credential locally and
  keeps it in a root-only file; it never prints the value.
- Server identity, pairing data, and Cloud binding are persisted in a local
  restricted state directory. Container recreation must not regenerate them.
- Hermes Agent and the internal Bridge remain loopback-only. Public access goes
  through a TLS reverse proxy to the versioned `/hermes-link/v1/*` contract.
- Notification payloads and Cloud events are allowlisted and do not carry
  prompts, replies, raw logs, private keys, or provider credentials.

## Release prerequisite

Follow [the public release gate](docs/public-release-gate.md). A secret scan of
only the current worktree is insufficient when an older private Git history may
become public.
