# Advanced deployment

The supported default is [`install.sh`](../install.sh). It runs Hermes Link
Server directly over HTTP. It does not install or manage Caddy, Nginx, a TLS
certificate, DNS validation, or TCP `80`.

## Direct HTTP with an IP address

This is the lowest-friction mode for a trusted LAN, VPN, or other controlled
network. Choose an App-reachable IP address and an unprivileged TCP port:

```bash
sudo bash ./install.sh \
  --host 192.168.1.10 \
  --public-port 18766
```

The App URL is `http://192.168.1.10:18766`. The Server binds directly to
`0.0.0.0:18766`; allow that port in the host firewall if the phone is on a
different device or network namespace. There is no TCP `80` prerequisite.

HTTP carries API and pairing device tokens without transport encryption. Use
this mode only when the network is trusted. Do not expose it broadly to the
Internet.

## User-managed HTTPS proxy

For a public HTTPS endpoint, obtain the domain certificate and configure the
proxy yourself. Hermes Link Server remains an HTTP upstream and does not read
certificate files.

```bash
sudo bash ./install.sh \
  --public-url https://hermes.example.com:24443 \
  --listen-host 127.0.0.1 \
  --listen-port 18766
```

Configure the chosen proxy to forward only `/hermes-link/v1/*` to
`http://127.0.0.1:18766`, preserve `Authorization`, and disable response
buffering for long-lived chat and notification streams. For example:

```nginx
location /hermes-link/v1/ {
    proxy_pass http://127.0.0.1:18766;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

The proxy owns the certificate lifecycle, DNS configuration, public port,
firewall rule, and any TLS security headers. The Server's pairing QR will use
the `--public-url` origin.

## State and migration

`data/server/` holds Server identity, device pairing records, optional Cloud
binding, direct-notification state, and redacted diagnostics. Do not run
`docker compose down -v` inside `/opt/hermes-link/`.

`sudo hermes-link update` creates a timestamped snapshot and rolls back if
local health, identity, Profile exposure, or Cloud capability verification
fails. A prior installer-managed Caddy runtime is deliberately not upgraded
in place: configure the desired direct HTTP or external-proxy transport first,
then perform a reviewed migration so an existing public endpoint is not
silently broken.
