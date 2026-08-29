#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: sudo ./scripts/docker-deploy.sh --public-base-url http://IP-or-host[:port] [options]

Runs the Server directly over HTTP with host networking while Hermes Agent stays
on 127.0.0.1. The default path creates and injects a dedicated
private Hermes Link credential; it never asks for or prints an Agent token.
For a user-scoped Agent service, the credential is stored under that user's
private configuration directory.
Docker host networking requires Linux.

Options:
  --port PORT         Direct HTTP listener port (must match the URL; 1024..65535)
  --server-env PATH   Optional existing Server settings file (advanced compatibility)
  --hermes-home PATH  Host Hermes metadata directory (default: <agent home>/.hermes)
  --agent-service NAME Hermes Agent systemd unit (default: hermes-gateway.service)
  --agent-service-scope SCOPE
                       Agent unit scope: system or user (default: system)
  --agent-user USER   Agent owner; required for user-scoped units
  --parallel-agent-credential
                       Keep an existing mobile credential during a parallel migration
  --agent-command PATH Hermes CLI command for first-time service installation
  --agent-run-as-user USER Agent owner for first-time service installation
  --rotate             Rotate the dedicated credential and recreate the Server container
  --profiles LIST     Pairing Profile scope (default: default)
  --ttl SECONDS       Pairing lifetime, 30..3600 (default: 600)
  --dry-run           Validate inputs and render the resolved Compose plan only
  --skip-pairing-qr   Do not render the initial pairing QR code
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
public_base_url=''
server_env=''
hermes_home=''
agent_service='hermes-gateway.service'
agent_service_scope='system'
agent_command="${HERMES_AGENT_COMMAND:-hermes}"
agent_user=''
listen_port=''
profiles='default'
profiles_explicit=false
ttl='600'
dry_run=false
render_qr=true
python_bin="${HERMES_LINK_PYTHON:-python3}"
rotate=false
parallel_agent_credential=false
agent_home=''

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-base-url) public_base_url="${2:-}"; shift 2 ;;
    --port) listen_port="${2:-}"; shift 2 ;;
    --server-env) server_env="${2:-}"; shift 2 ;;
    --hermes-home) hermes_home="${2:-}"; shift 2 ;;
    --agent-service) agent_service="${2:-}"; shift 2 ;;
    --agent-service-scope) agent_service_scope="${2:-}"; shift 2 ;;
    --agent-user) agent_user="${2:-}"; shift 2 ;;
    --parallel-agent-credential) parallel_agent_credential=true; shift ;;
    --agent-command) agent_command="${2:-}"; shift 2 ;;
    --agent-run-as-user) agent_user="${2:-}"; shift 2 ;;
    --rotate) rotate=true; shift ;;
    --profiles) profiles="${2:-}"; profiles_explicit=true; shift 2 ;;
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
import sys
from urllib.parse import urlparse

raw, requested_port = sys.argv[1], sys.argv[2]
parsed = urlparse(raw)
if parsed.scheme != "http" or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit("public base URL must be an HTTP origin without credentials, path, query, or fragment")
if not parsed.hostname:
    raise SystemExit("public base URL must contain an IP address or hostname")
try:
    url_port = parsed.port
except ValueError as error:
    raise SystemExit("public base URL has an invalid port") from error
if url_port is None:
    raise SystemExit("public base URL must include an unprivileged TCP port")
port = int(requested_port or url_port)
if not 1024 <= port <= 65535:
    raise SystemExit("port must be in 1024..65535 because the Server runs unprivileged")
if port != url_port:
    raise SystemExit("--port must match the port in --public-base-url")
print(port)
PY
)"
listen_port="$validation"

if [[ ! -f "$repo_dir/deploy/docker/compose.yaml" ]]; then
  echo "Docker deployment assets are missing from $repo_dir" >&2
  exit 1
fi
if [[ "$dry_run" == false ]]; then
  if [[ -n "$server_env" && ! -r "$server_env" ]]; then
    echo "Optional Server environment file is not accessible." >&2
    exit 1
  fi
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run Docker deployment as root so Docker can manage the host-network deployment." >&2
    exit 1
  fi
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Docker Engine with the Compose plugin is required." >&2
    exit 1
  fi
fi

bootstrap_args=(--agent-service "$agent_service" --agent-service-scope "$agent_service_scope" --agent-command "$agent_command")
if [[ -n "$agent_user" ]]; then bootstrap_args+=(--agent-user "$agent_user"); fi
if [[ "$parallel_agent_credential" == true ]]; then bootstrap_args+=(--parallel-agent-credential); fi
if [[ -n "$hermes_home" ]]; then bootstrap_args+=(--hermes-home "$hermes_home"); fi
if [[ "$rotate" == true ]]; then bootstrap_args+=(--rotate); fi
if [[ "$dry_run" == true ]]; then
  bash "$script_dir/bootstrap-hermes-agent-access.sh" "${bootstrap_args[@]}" --dry-run
fi
if [[ "$dry_run" == false ]]; then
  bash "$script_dir/bootstrap-hermes-agent-access.sh" "${bootstrap_args[@]}"
fi
internal_env='/etc/hermes-link-server/internal-agent.env'
if [[ "$agent_service_scope" == 'user' ]]; then
  if [[ -z "$agent_user" ]]; then agent_user="${SUDO_USER:-}"; fi
  if [[ "$dry_run" == true && -z "$agent_user" ]]; then agent_user='<sudo-caller>'; fi
  if [[ "$dry_run" == false ]]; then
    agent_home="$(getent passwd "$agent_user" | cut -d: -f6)"
    [[ -n "$agent_home" ]] || { echo "Cannot determine home directory for $agent_user" >&2; exit 1; }
  else
    agent_home="/home/$agent_user"
    if [[ "$agent_user" == 'root' ]]; then agent_home='/root'; fi
  fi
  internal_env="$agent_home/.config/hermes-link-server/internal-agent.env"
fi
if [[ -z "$hermes_home" && "$dry_run" == false ]]; then
  hermes_home="$(sed -n 's/^HERMES_HOME=//p' "$internal_env")"
fi
if [[ -z "$hermes_home" ]]; then hermes_home='/home/agent/.hermes'; fi
if [[ "$dry_run" == false && ! -d "$hermes_home" ]]; then
  echo "Hermes metadata directory is not accessible: $hermes_home" >&2
  exit 1
fi
discovered_profile_ids=(default)
if [[ "$dry_run" == false && -d "$hermes_home/profiles" ]]; then
  while IFS= read -r profile_id; do
    if [[ "$profile_id" =~ ^[A-Za-z0-9._-]{1,64}$ && "$profile_id" != 'default' ]]; then
      discovered_profile_ids+=("$profile_id")
    fi
  done < <(find "$hermes_home/profiles" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort)
fi
HERMES_LINK_PROFILE_IDS="$(IFS=,; printf '%s' "${discovered_profile_ids[*]}")"
export HERMES_LINK_PROFILE_IDS
if [[ "$profiles_explicit" == false ]]; then
  profiles="$HERMES_LINK_PROFILE_IDS"
fi
export HERMES_LINK_SERVER_ENV_FILE="${server_env:-/dev/null}"
export HERMES_LINK_INTERNAL_ENV_FILE="$internal_env"
if [[ "$dry_run" == true ]]; then
  # Dry-run validates the deployment plan only. Do not require an advanced
  # compatibility env file that the command intentionally does not read.
  export HERMES_LINK_SERVER_ENV_FILE='/dev/null'
  export HERMES_LINK_INTERNAL_ENV_FILE='/dev/null'
fi
export HERMES_HOME_HOST_PATH="$hermes_home"
export HERMES_LINK_BIND_HOST='0.0.0.0'
export HERMES_LINK_BRIDGE_PORT="$listen_port"

if [[ "$dry_run" == true ]]; then
  printf '%s\n' \
    "DRY RUN: Docker host networking keeps Hermes Agent at 127.0.0.1 and binds the Server HTTP listener to 0.0.0.0:$listen_port." \
    "DRY RUN: App connects directly to $public_base_url without TLS; use only a trusted network." \
    "DRY RUN: Server state uses a named volume; Hermes metadata is mounted read-only." \
    "DRY RUN: pairing QR after healthy startup: $render_qr."
  if [[ "$agent_service_scope" == 'user' ]]; then
    echo "DRY RUN: Docker will read the user-scoped private Agent credential at $internal_env."
  fi
  if [[ "$rotate" == true ]]; then echo "DRY RUN: recreate the Server container after Agent credential rotation."; fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose --project-directory "$repo_dir" -f "$repo_dir/deploy/docker/compose.yaml" config >/dev/null
    echo "DRY RUN: Docker Compose configuration is valid."
  else
    echo "DRY RUN: Docker is unavailable on this host; Compose runtime validation was skipped."
  fi
  exit 0
fi

compose_up=(docker compose --project-directory "$repo_dir" -f "$repo_dir/deploy/docker/compose.yaml" up -d --build)
if [[ "$rotate" == true ]]; then compose_up+=(--force-recreate); fi
"${compose_up[@]}"
docker compose --project-directory "$repo_dir" -f "$repo_dir/deploy/docker/compose.yaml" exec -T server \
  python -c "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:${listen_port}/health', timeout=5).status == 200"

if [[ "$render_qr" == true ]]; then
  pairing_token_env='HERMES_LINK_MOBILE_API_TOKEN'
  if [[ "$parallel_agent_credential" == true ]]; then
    pairing_token_env='HERMES_LINK_AGENT_TOKEN'
  fi
  docker compose --project-directory "$repo_dir" -f "$repo_dir/deploy/docker/compose.yaml" exec -T server \
    python -m hermes_link.pairing.store \
      --base-url "$public_base_url" \
      --profiles "$profiles" \
      --ttl "$ttl" \
      --token-env "$pairing_token_env" \
      --qr
fi

echo "Hermes Link Server is running at $public_base_url."
