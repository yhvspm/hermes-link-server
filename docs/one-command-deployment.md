# One-command Server deployment

This guide is for the public HTTPS deployment mode. It does not deploy Hermes Agent
or Hermes Link Cloud. Self-hosted Server functionality remains usable when Cloud is off.

## Before running either path

1. Use a public DNS name that resolves to the Server host. A raw IP address and HTTP URL are rejected.
2. Select the HTTPS port. `443` is the default; `8443` or another TCP port is supported when it is also present in the public URL.
3. Allow inbound TCP on the selected HTTPS port. Caddy certificate issuance also needs inbound TCP `80` for HTTP-01 validation.
4. Install Hermes Agent for the Linux account that will own its model/provider configuration. The Hermes Link installer creates its service automatically if the `hermes` CLI is available.
5. Keep Hermes Agent at loopback. Do not expose `8642` or the Bridge `8765` publicly.

The deployment command generates a dedicated random `HERMES_LINK_MOBILE_API_TOKEN` locally, stores it in `/etc/hermes-link-server/internal-agent.env` with mode `0600`, and installs a systemd drop-in for Hermes Agent. The value is never printed, copied into Git, accepted as a command-line argument, or shared with the App. This is a machine-internal Server → Agent credential; App devices use scoped pairing tokens instead.

## Native Debian/Ubuntu

Run from a reviewed release directory. The script refuses an existing installation directory and never deletes or overwrites it.

```bash
sudo bash ./scripts/install-native.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443 \
  --profiles default,mobiletest \
  --dry-run
```

Remove `--dry-run` only after reviewing the plan. The real run installs Python/Caddy on Debian/Ubuntu if required, creates a `hermes-link` service account, creates or configures the Hermes Agent systemd service, injects the dedicated credential through a drop-in, installs two Link systemd services, checks `127.0.0.1:8765/health`, then prints a terminal-only, one-time pairing QR. The installer refuses to overwrite an existing Link installation. `--server-env` remains available only for extra, pre-existing Server settings; it is not required for Agent access.

The initial QR expires after 600 seconds by default. The QR contains a short-lived pairing code, never an Agent API token, device token, private key, or Cloud credential.

## Docker Compose on Linux

Docker runs with `network_mode: host`. This is intentional: Hermes Agent remains at host-loopback `127.0.0.1`, and neither Agent nor Bridge needs a public Docker port mapping. The Caddy container binds only the selected public HTTPS port.

```bash
sudo bash ./scripts/docker-deploy.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443 \
  --profiles default,mobiletest \
  --dry-run
```

The Docker dry-run validates the origin and port, plans credential injection without generating any value, and, when Docker is installed, renders the resolved Compose model without starting containers. Remove `--dry-run` to create the root-only credential, build and start the containers; after their loopback health check, the command renders the initial pairing QR in the invoking terminal.

## Rotate the internal credential

Do not edit the generated file. The native path atomically replaces it and restarts Hermes Agent followed by Hermes Link Server:

```bash
sudo bash /opt/hermes-link-server/scripts/bootstrap-hermes-agent-access.sh --agent-run-as-user hermes --rotate
```

For Docker, rerun the deployment command with the same public URL and `--rotate`; it rotates the Agent credential and recreates the Server container so both sides load the same value. Neither command prints the credential.

### Isolated Docker validation

When an existing Bridge already owns `127.0.0.1:8765` or an existing reverse proxy owns the public HTTPS port, validate the container without touching either service:

```bash
sudo bash ./scripts/docker-deploy.sh \
  --public-base-url https://link.example.com:8443 \
  --port 8443 \
  --bridge-port 18765 \
  --server-only \
  --agent-run-as-user hermes
```

`--server-only` intentionally does not start Caddy or print a usable pairing QR, because no public HTTPS endpoint exists in this verification profile. It is suitable for local health, Server-info, pairing exchange, and Server-to-Agent adapter checks. Stop it with the same Compose project name after validation.

For an ephemeral verification that automatically removes its own container and volumes, use:

```bash
sudo ./scripts/verify-isolated-compose.sh \
  --server-env /secure/hermes-link-server.env \
  --hermes-home /var/lib/hermes-agent \
  --bridge-port 18765
```

Do not use Docker Desktop host networking as a substitute for the Linux Server path. This Compose profile is intentionally Linux-only.

## Pair another device later

Use the same full HTTPS origin and the generated root-only internal environment file. This prints a fresh one-time QR; it does not revoke existing devices.

```bash
sudo /opt/hermes-link-server/scripts/generate-pairing-qr.sh \
  --python /opt/hermes-link-server/.venv/bin/python \
  --base-url https://link.example.com:8443 \
  --env-file /etc/hermes-link-server/internal-agent.env \
  --profiles default,mobiletest
```

Pairing codes are single-use. If a code expires or has been scanned, generate a new code instead of weakening TLS or reusing a device token.
