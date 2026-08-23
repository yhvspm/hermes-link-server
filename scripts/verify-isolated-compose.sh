#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: verify-isolated-compose.sh --server-env /secure/server.env --hermes-home /path/to/hermes-home [options]

Starts only a temporary Server container on an isolated loopback port, verifies
health, Server-info, and one-time pairing exchange, then removes its dedicated
Compose project and volumes. It never starts the Caddy proxy or prints tokens.

Options:
  --bridge-port PORT  Isolated Bridge port (default: 18765)
  --project-name NAME Compose project name (default: hermes-link-isolated-verify)
  --server-env PATH   Restricted Server environment file (required)
  --hermes-home PATH  Host Hermes metadata directory mounted read-only (required)
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
bridge_port='18765'
project_name='hermes-link-isolated-verify'
server_env=''
hermes_home=''

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bridge-port) bridge_port="${2:-}"; shift 2 ;;
    --project-name) project_name="${2:-}"; shift 2 ;;
    --server-env) server_env="${2:-}"; shift 2 ;;
    --hermes-home) hermes_home="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$server_env" || -z "$hermes_home" ]]; then
  usage >&2
  exit 2
fi
if [[ ! "$bridge_port" =~ ^[0-9]+$ ]] || (( bridge_port < 1 || bridge_port > 65535 )); then
  echo "--bridge-port must be in 1..65535" >&2
  exit 2
fi
if [[ ! -r "$server_env" || ! -d "$hermes_home" ]]; then
  echo "Server environment file or Hermes metadata directory is not accessible." >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker Engine with the Compose plugin is required." >&2
  exit 1
fi

export HERMES_LINK_SERVER_ENV_FILE="$server_env"
export HERMES_LINK_INTERNAL_ENV_FILE="${HERMES_LINK_INTERNAL_ENV_FILE:-$server_env}"
export HERMES_HOME_HOST_PATH="$hermes_home"
export HERMES_LINK_PUBLIC_HOST='compose-validation.example.invalid'
export HERMES_LINK_LISTEN_PORT='18443'
export HERMES_LINK_BRIDGE_PORT="$bridge_port"

compose=(docker compose --project-name "$project_name" --project-directory "$repo_dir" -f "$repo_dir/deploy/docker/compose.yaml")
cleanup() {
  "${compose[@]}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${compose[@]}" up -d --build server
for _attempt in {1..20}; do
  if curl --fail --silent "http://127.0.0.1:${bridge_port}/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent "http://127.0.0.1:${bridge_port}/health" >/dev/null

curl --fail --silent "http://127.0.0.1:${bridge_port}/hermes-link/v1/server-info" |
  python3 -c "import json,sys; value=json.load(sys.stdin); assert value['protocolVersion'] == 1; print('server-info: protocol-v1')"

pairing_code=$("${compose[@]}" exec -T server python -c "from hermes_link.pairing.store import create_pairing_ticket; import os; token=(os.environ.get('HERMES_LINK_MOBILE_API_TOKEN') or os.environ.get('HERMES_LINK_AGENT_TOKEN') or '').strip(); assert token, 'Missing Server-to-Agent credential'; url=create_pairing_ticket('https://compose-validation.example.invalid:18443', token, path=os.environ['HERMES_LINK_PAIRING_DB'])['pairing_url']; print(url.split('code=', 1)[1].split('&', 1)[0])")
pairing_response=$(curl --fail --silent -X POST "http://127.0.0.1:${bridge_port}/hermes-link/v1/pairing" \
  -H 'Content-Type: application/json' \
  --data "{\"schema_version\":1,\"code\":\"${pairing_code}\"}")
device_token=$(printf '%s' "$pairing_response" | python3 -c "import json,sys; value=json.load(sys.stdin); assert value['schema_version'] == 2; token=value['device_token']; assert token.startswith('hmd_'); print(token)")
test -n "$device_token"
echo "pairing-exchange: passed"

model_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H "Authorization: Bearer ${device_token}" \
  "http://127.0.0.1:${bridge_port}/hermes-link/v1/models" || true)
if [[ "$model_status" == '000' ]]; then
  echo "Server-to-Agent request did not receive an HTTP response." >&2
  exit 1
fi
echo "server-to-agent model request: HTTP ${model_status}"
echo "isolated-compose-verification: passed"
