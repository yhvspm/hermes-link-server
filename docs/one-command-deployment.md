# One-command Server deployment

This guide deploys Hermes Link Server on an Ubuntu host where Hermes Agent is
already working. It does not deploy Hermes Link Cloud and it does not manage a
domain, Caddy, Nginx, certificate, or port `80`.

## Direct HTTP/IP mode

The normal path needs only an App-reachable IP address (or hostname) and an
unprivileged public port. The installer creates its own Server-to-Agent
credential, discovers Profiles, starts the runtime, and renders a short-lived
pairing QR. It never asks for or prints an upstream Hermes Agent token.

```bash
curl -fL https://github.com/yhvspm/hermes-link-server/releases/download/v1.0.3/hermes-link-server-install.sh \
  -o hermes-link-server-install.sh
sudo bash hermes-link-server-install.sh \
  --host 192.168.1.10 \
  --public-port 18766
```

The App scans the displayed QR under **设置 → 服务器 → 扫码配置**. Manual setup
also accepts `http://192.168.1.10:18766`.

The Server is intentionally an unprivileged process, so direct listener ports
must be in `1024..65535`. Allow the chosen TCP port through the host firewall
when the phone is not on the same host. Hermes Agent stays loopback-only.

## Security boundary

Direct HTTP has no transport encryption: a network observer can intercept API
and pairing device tokens. Use it only on a trusted LAN/VPN. Do not publish an
HTTP endpoint to the general Internet.

## External HTTPS is optional and user-managed

If an Internet-facing HTTPS URL is required, arrange the certificate, DNS, and
reverse proxy yourself, then install the Server as a loopback HTTP upstream:

```bash
sudo bash hermes-link-server-install.sh \
  --public-url https://hermes.example.com:24443 \
  --listen-host 127.0.0.1 \
  --listen-port 18766
```

Point the proxy at `http://127.0.0.1:18766` for `/hermes-link/v1/*`, preserve
`Authorization`, and disable buffering for streams. See
[advanced deployment](advanced-deployment.md). The installer does not validate
or renew the external certificate.

## Operate

```bash
sudo hermes-link status
sudo hermes-link doctor
sudo hermes-link pair
sudo hermes-link update
```

`pair` prints a fresh one-time QR without displaying the device token. Cloud
remains optional: local chat, Sessions, Jobs, history, and DIRECT notifications
work without it.
