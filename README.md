# Hermes Link Server

Connect the Hermes Link app securely to a self-hosted Hermes Agent.

Hermes Link Server is the public, self-hostable compatibility boundary. It
keeps Hermes Agent loopback-only, stores its own pairing and Server identity
state locally, and treats Cloud notifications as optional.

## Install

On a supported Ubuntu host that already runs Hermes Agent and Docker Compose:

```bash
curl -fL https://github.com/yhvspm/hermes-link-server/releases/download/v1.0.1/hermes-link-server-install.sh -o hermes-link-server-install.sh
sudo bash hermes-link-server-install.sh
```

The installer asks for:

- A public DNS name
- A public HTTPS port (default: `443`)
- Automatic Caddy HTTPS, or an existing reverse proxy

To migrate an existing managed `v1.0.0` installation without changing its
identity or pairing state, run the same downloaded installer with
`--upgrade-existing`. It first stages the verified `v1.0.1` update command,
then uses the normal backup-and-rollback update flow.

When the selected port is `443`, the App URL is `https://hermes.example.com`.
For another port it is `https://hermes.example.com:18443`. The private internal
Bridge port is managed by Hermes Link and is not an App or firewall setting.

The current standard installer supports Ubuntu 22.04 and newer, including
25.10 and 26.04. It checks for Docker Engine with Compose v2 rather than
installing Docker silently.

## Operate

```bash
sudo hermes-link status
sudo hermes-link doctor
sudo hermes-link update
sudo hermes-link restart
sudo hermes-link logs server
```

`update` backs up configuration and persisted Server state, verifies local
health, identity stability, Profile preservation, Cloud V3 capability, and
the public HTTPS URL. If a managed-Caddy update fails, it restores the
previous image, configuration, and state automatically.

## Release integrity

Published installs download `release-manifest.json` and every standard
deployment asset from the GitHub Release, verifying each SHA-256 digest. The
generated runtime `.env` uses the manifest's immutable GHCR `@sha256` image
reference, not a mutable image tag. `sudo hermes-link doctor` checks that the
installed manifest still matches the configured image.

The installer and `update` command pull that digest normally. If the GHCR data
path fails on a Linux amd64 Docker host, they download the release's
manifest-bound OCI archive, verify its file hash and embedded image digest, and
import it into Docker's containerd store before starting the runtime. The
archive is a fallback only; it never replaces a successful registry pull.

Every release workflow also publishes a BuildKit provenance record and SBOM,
then verifies the downloaded manifest and image digest after publication.
Before publishing the first release, enable GitHub Release immutability as
described in the [public release gate](docs/public-release-gate.md).

## What the standard runtime manages

The installer creates `/opt/hermes-link/`:

```text
compose.yaml     Standard prebuilt-image runtime
.env             Generated deployment metadata, mode 0600
data/server/     Pairing, Server identity, Cloud binding, and redacted logs
data/caddy-*/    Caddy certificate and configuration state
backups/         Update snapshots
bin/             hermes-link CLI and local installer helpers
```

The Server container is read-only except for `data/server/`; its persisted
identity is explicitly mounted there, so replacing a container does not create
a new `serverId`. Hermes Profile discovery reads only valid Profile directory
names and enables them through the generated allowlist.

## HTTPS and custom ports

The recommended mode is Caddy. It proxies streaming responses without buffering
and obtains/renews certificates automatically. Caddy's HTTP-01 certificate
flow still needs inbound TCP 80 even when the App uses a custom HTTPS port.

If another proxy already owns the public port or certificate, choose external
proxy mode. Hermes Link selects an unused loopback Bridge port and records it
in the root-only generated `.env`; `sudo hermes-link doctor` reports the exact
proxy target. Configure the existing proxy for `/hermes-link/v1/*` with
SSE/streaming support. See [advanced deployment](docs/advanced-deployment.md).

## Security and repository boundaries

- Hermes Agent credentials, Server private keys, Cloud secrets, and provider
  credentials stay server-side and are never printed by the installer or CLI.
- The Server never imports Cloud implementation modules or accesses its
  database. Cloud Protocol is a network contract only.
- Cloud events remain allowlisted to `chat.completed`, `job.completed`, and
  `job.failed`, without prompts, replies, tokens, raw tool output, or arbitrary
  click targets.
- See [SECURITY.md](SECURITY.md) and the
  [public release gate](docs/public-release-gate.md) before publishing.

## Security

Do not report vulnerabilities through public GitHub Issues, Discussions, or
pull requests. See [SECURITY.md](SECURITY.md) for the GitHub private reporting
process.

## Development and validation

```bash
python -m unittest discover -s tests -t . -p 'test_*.py'
python scripts/architecture_gate.py
python scripts/secret_scan.py
python scripts/public_release_gate.py --current-only
```

The former native/systemd and build-from-source Docker instructions are kept as
advanced compatibility material only. They are not the standard end-user
deployment path.
