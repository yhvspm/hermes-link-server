# Hermes Link Server

Public, self-hostable compatibility boundary for Hermes Link clients and Hermes Agent.

Self-hosted is the baseline. Cloud is optional. Current Server version is `1.0.0`; Hermes Link Protocol is v1 and Cloud Protocol is v2.

## Responsibilities

- Stable capability, Chat, Session, Model, Job/Cron and notification contracts
- Pairing and device tokens
- Server-owned Ed25519 identity and signed Cloud event envelopes
- DIRECT notification stream that does not require Cloud
- Optional Cloud event sender through HTTPS only
- Hermes Agent compatibility isolated under `integrations/hermes_agent/`
- Versioned Agent support policy in [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md)

The repository never imports Cloud internal Python modules or accesses the Cloud database. Huawei provider credentials do not belong here.

## Tests

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -t . -p 'test_*.py'
python scripts/architecture_gate.py
python scripts/secret_scan.py
```

Deployment examples are templates only. On a fresh host the installer generates
the dedicated Hermes Link-to-Agent credential locally, stores it root-only, and
injects it into the Agent service. It never asks users to obtain, paste, or see
an upstream Agent token.

## One-command deployment

For a public DNS name with HTTPS, the Server now provides two deployment paths:

- Native Debian/Ubuntu + systemd + Caddy: [`scripts/install-native.sh`](scripts/install-native.sh)
- Linux Docker Engine + Docker Compose: [`scripts/docker-deploy.sh`](scripts/docker-deploy.sh)

中文 Docker 全新环境一键部署说明：
[`docs/docker-one-click-deployment-zh-CN.md`](docs/docker-one-click-deployment-zh-CN.md)。

Both take a full public HTTPS origin, so a non-default port is supported:

```bash
sudo bash ./scripts/install-native.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443
```

The installer validates the URL/port match, installs/configures the local Hermes
Agent service when needed, keeps Hermes Agent and Bridge loopback-only, and
prints a one-time pairing QR only to the invoking terminal after the local
health check. Use `--dry-run` first. No credential value is printed, copied to
Git, or placed in a QR code.

面向自托管用户的完整中文手册见
[`docs/user-deployment-guide-zh-CN.md`](docs/user-deployment-guide-zh-CN.md)。
