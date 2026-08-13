#!/usr/bin/env bash
set -euo pipefail
umask 027

usage() {
  cat <<'EOF'
Usage: sudo ./scripts/install-native.sh --public-base-url https://link.example.com[:port] [options]

Installs Hermes Link Server and a dedicated Caddy HTTPS proxy on Debian/Ubuntu.
The default path creates a dedicated Hermes Link-to-Agent credential and injects
it into Hermes Agent automatically. It never asks for, prints, or reuses an
upstream Agent token.

Options:
  --port PORT         HTTPS listener port (default: inferred from URL or 443)
  --source-dir DIR    Reviewed Server release directory (default: repository root)
  --install-dir DIR   Installation directory (default: /opt/hermes-link-server)
  --server-env PATH   Optional existing Server settings file (advanced compatibility)
  --agent-service NAME Hermes Agent systemd unit (default: hermes-gateway.service)
  --agent-command PATH Hermes CLI command for first-time service installation
  --agent-run-as-user USER Agent owner for first-time service installation
  --hermes-home PATH  Agent metadata directory (default: <agent home>/.hermes)
  --profiles LIST     Pairing Profile scope (default: default)
  --ttl SECONDS       Pairing lifetime, 30..3600 (default: 600)
  --dry-run           Validate inputs and print the planned operations only
  --skip-pairing-qr   Do not render the initial pairing QR code
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$(cd -- "$script_dir/.." && pwd)"
install_dir='/opt/hermes-link-server'
server_env=''
agent_service='hermes-gateway.service'
agent_command="${HERMES_AGENT_COMMAND:-hermes}"
agent_user=''
hermes_home=''
public_base_url=''
listen_port=''
profiles='default'
ttl='600'
dry_run=false
render_qr=true
python_bin="${HERMES_LINK_PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-base-url) public_base_url="${2:-}"; shift 2 ;;
    --port) listen_port="${2:-}"; shift 2 ;;
    --source-dir) source_dir="${2:-}"; shift 2 ;;
    --install-dir) install_dir="${2:-}"; shift 2 ;;
    --server-env) server_env="${2:-}"; shift 2 ;;
    --agent-service) agent_service="${2:-}"; shift 2 ;;
    --agent-command) agent_command="${2:-}"; shift 2 ;;
    --agent-run-as-user) agent_user="${2:-}"; shift 2 ;;
    --hermes-home) hermes_home="${2:-}"; shift 2 ;;
    --profiles) profiles="${2:-}"; shift 2 ;;
    --ttl) ttl="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --skip-pairing-qr) render_qr=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$public_base_url" ]]; then
  usage >&2
  exit 2
fi

validation="$("$python_bin" - "$public_base_url" "$listen_port" <<'PY'
from __future__ import annotations
import ipaddress
import sys
from urllib.parse import urlparse

raw, requested_port = sys.argv[1], sys.argv[2]
parsed = urlparse(raw)
if parsed.scheme != "https" or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit("public base URL must be an HTTPS origin without credentials, path, query, or fragment")
if not parsed.hostname:
    raise SystemExit("public base URL must contain a DNS hostname")
try:
    ipaddress.ip_address(parsed.hostname)
except ValueError:
    pass
else:
    raise SystemExit("public base URL must use a DNS hostname, not an IP address")
try:
    url_port = parsed.port or 443
except ValueError as error:
    raise SystemExit("public base URL has an invalid port") from error
port = int(requested_port or url_port)
if not 1 <= port <= 65535:
    raise SystemExit("port must be in 1..65535")
if port != url_port:
    raise SystemExit("--port must match the port in --public-base-url (or 443 when omitted)")
print(f"{parsed.hostname}\t{port}")
PY
)"
IFS=$'\t' read -r public_host listen_port <<< "$validation"

if [[ ! -f "$source_dir/pyproject.toml" || ! -f "$source_dir/deploy/caddy/Caddyfile.service.template" ]]; then
  echo "Source directory is not a Hermes Link Server release: $source_dir" >&2
  exit 1
fi

if [[ "$dry_run" == true ]]; then
  bootstrap_args=(--agent-service "$agent_service" --agent-command "$agent_command")
  if [[ -n "$agent_user" ]]; then bootstrap_args+=(--agent-run-as-user "$agent_user"); fi
  if [[ -n "$hermes_home" ]]; then bootstrap_args+=(--hermes-home "$hermes_home"); fi
  bash "$script_dir/bootstrap-hermes-agent-access.sh" "${bootstrap_args[@]}" --dry-run
  printf '%s\n' \
    "DRY RUN: install reviewed release from $source_dir to $install_dir (refuse if destination exists)." \
    "DRY RUN: install Python 3, venv, and Caddy through apt on Debian/Ubuntu when absent." \
    "DRY RUN: install hermes-link-server.service and hermes-link-proxy.service." \
    "DRY RUN: configure Caddy for https://$public_host:$listen_port and only proxy /hermes-link/v1/ to 127.0.0.1:8765." \
    "DRY RUN: retain Agent loopback access and do not expose 8642 or 8765." \
    "DRY RUN: render a one-time pairing QR after services pass local health checks: $render_qr."
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root (for example with sudo)." >&2
  exit 1
fi
if [[ -n "$server_env" && ! -r "$server_env" ]]; then
  echo "Restricted Server environment file is not readable: $server_env" >&2
  exit 1
fi
if [[ -e "$install_dir" ]]; then
  echo "Installation directory already exists; this installer never overwrites an existing deployment: $install_dir" >&2
  exit 1
fi
if [[ ! -f /etc/debian_version ]]; then
  echo "This native installer supports Debian/Ubuntu only. Use Docker Compose on another Linux distribution." >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv caddy curl
if ! id -u hermes-link >/dev/null 2>&1; then
  useradd --system --home /var/lib/hermes-link-server --create-home --shell /usr/sbin/nologin hermes-link
fi
install -d -o hermes-link -g hermes-link -m 0700 /var/lib/hermes-link-server
install -d -o caddy -g caddy -m 0700 /var/lib/hermes-link-caddy
install -d -m 0750 /etc/hermes-link-server
installed_server_env='/etc/hermes-link-server/server.env'
if [[ -n "$server_env" && "$server_env" != "$installed_server_env" ]]; then
  if [[ -e "$installed_server_env" ]]; then
    echo "Refusing to overwrite the existing restricted Server environment file: $installed_server_env" >&2
    exit 1
  fi
  install -m 0640 -o root -g hermes-link "$server_env" "$installed_server_env"
fi
bootstrap_args=(--agent-service "$agent_service" --agent-command "$agent_command")
if [[ -n "$agent_user" ]]; then bootstrap_args+=(--agent-run-as-user "$agent_user"); fi
if [[ -n "$hermes_home" ]]; then bootstrap_args+=(--hermes-home "$hermes_home"); fi
bash "$source_dir/scripts/bootstrap-hermes-agent-access.sh" "${bootstrap_args[@]}"
internal_env='/etc/hermes-link-server/internal-agent.env'
cp -a "$source_dir/." "$install_dir"
"$python_bin" -m venv "$install_dir/.venv"
"$install_dir/.venv/bin/pip" install "$install_dir"
install -m 0644 "$install_dir/deploy/systemd/hermes-link-server.service" /etc/systemd/system/hermes-link-server.service
install -m 0644 "$install_dir/deploy/systemd/hermes-link-proxy.service" /etc/systemd/system/hermes-link-proxy.service
"$python_bin" - "$install_dir/deploy/caddy/Caddyfile.service.template" /etc/hermes-link-server/Caddyfile "$public_host" "$listen_port" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
host = sys.argv[3]
port = sys.argv[4]
content = template_path.read_text(encoding="utf-8")
content = content.replace("{$HERMES_LINK_PUBLIC_HOST}", host)
content = content.replace("{$HERMES_LINK_LISTEN_PORT}", port)
content = content.replace("{$HERMES_LINK_BRIDGE_PORT}", "8765")
output_path.write_text(content, encoding="utf-8")
PY
systemctl daemon-reload
systemctl enable --now hermes-link-server.service hermes-link-proxy.service
curl --fail --silent http://127.0.0.1:8765/health >/dev/null
systemctl is-active --quiet hermes-link-proxy.service

if [[ "$render_qr" == true ]]; then
  "$install_dir/scripts/generate-pairing-qr.sh" \
    --python "$install_dir/.venv/bin/python" \
    --base-url "$public_base_url" \
    --env-file "$internal_env" \
    --profiles "$profiles" \
    --ttl "$ttl"
fi

echo "Hermes Link Server is running at $public_base_url."
