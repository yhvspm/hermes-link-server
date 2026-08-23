# Advanced deployment

The supported default is [`install.sh`](../install.sh), which owns the Caddy
configuration, public port, certificate lifecycle, and `/opt/hermes-link/`
runtime. This page is for hosts that already have a reverse proxy or a
certificate-management policy.

## Existing reverse proxy

Choose **existing reverse proxy** during installation. Hermes Link starts only
the Server and redacted-log exporter. It selects the first unused loopback port
in its private range and records it only in the root-only generated `.env`.
After installation, use the target reported by `sudo hermes-link doctor`; do
not expose that loopback port directly.

```text
http://127.0.0.1:<reported-in-hermes-link-doctor>
```

The generated `.env` still records the App-facing HTTPS URL and public port,
so `hermes-link status`, `doctor`, and future pairing flows report the correct
origin. Do not expose the loopback port directly.

Your proxy must route only `/hermes-link/v1/*`, preserve `Authorization` and
standard forwarding headers, support long-lived streaming responses, and avoid
response buffering. For example, an existing Caddy site can contain:

```caddyfile
@hermes_link path /hermes-link/v1/*
reverse_proxy @hermes_link 127.0.0.1:<reported-in-hermes-link-doctor> {
    flush_interval -1
}
```

An Nginx location needs equivalent SSE handling:

```nginx
location /hermes-link/v1/ {
    proxy_pass http://127.0.0.1:<reported-in-hermes-link-doctor>;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

The existing proxy, not Hermes Link, owns certificate issuance, public-port
conflicts, DNS challenge configuration, and firewall rules in this mode.

## Automatic Caddy certificate requirements

The standard Caddy mode accepts a custom public HTTPS port. Its certificate is
still validated separately: the first version uses Caddy's HTTP-01 flow, which
requires public TCP 80 to reach the host. If TCP 80 is unavailable because of
another proxy, network policy, or certificate-management policy, use external
proxy mode with an existing certificate or DNS challenge setup.

`hermes-link doctor` reports the Caddy container, Caddyfile validation, local
listener, and the configured public URL separately. A running container alone
does not prove that DNS, TLS, or the public firewall is correct.

## State and recovery

Do not run `docker compose down -v` in `/opt/hermes-link/`. The Server identity,
pairing records, Cloud binding, and redacted diagnostics live below
`data/server/`; Caddy's certificate state lives below `data/caddy-*`.

`sudo hermes-link update` creates a timestamped snapshot in `backups/`, keeps
the old image, and restores the prior state if its post-update checks fail.
`sudo hermes-link uninstall` stops the runtime but preserves data by default.
Only `sudo hermes-link uninstall --purge`, followed by typing `DELETE`, removes
the persisted identity and bindings.

## Migrating an existing runtime

The normal installer is intentionally a fresh-install path. For a reviewed
local migration, stop the old Server container first so SQLite state is
consistent, back up its Server state, then use the advanced
`--reuse-agent-credential` and `--state-import-dir` flags. The credential must
already be a regular root-owned `0600` file; in this mode the installer does
not create, rotate, restart, or otherwise alter the Agent service.

Only the stable Server identity, pairing database and its SQLite sidecars, and
an optional Cloud binding file are imported. Logs, arbitrary files, and Agent
credentials are never copied into the standard runtime. Build or preload a
reviewed local image and add `--skip-image-pull` when the cutover must avoid an
image download. A reviewed local source tree without `release-manifest.json`
is intentionally treated as an advanced migration path: it cannot provide the
published SHA-256 asset and image-digest verification. Normal published
installs and updates always require that manifest.

## Compatibility deployment assets

The repository retains the prior native/systemd and source-build Docker assets
for reviewed migrations and isolated validation. They use their own documented
settings and are not a substitute for the standard runtime. Do not copy a
historical deployment's domain, public port, host path, or credential file into
the generated standard `.env`.
