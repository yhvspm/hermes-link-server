#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: generate-pairing-qr.sh --base-url http://IP-or-host:PORT --env-file /etc/hermes-link-server/server.env [options]

Options:
  --profiles LIST    Comma-separated Profile IDs (default: default)
  --ttl SECONDS      Pairing lifetime, 30..3600 (default: 600)
  --db PATH          Pairing database path (default: value in env file)
  --python PATH      Python executable (default: python3)
EOF
}

base_url=''
env_file=''
profiles='default'
ttl='600'
db=''
python_bin='python3'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) base_url="${2:-}"; shift 2 ;;
    --env-file) env_file="${2:-}"; shift 2 ;;
    --profiles) profiles="${2:-}"; shift 2 ;;
    --ttl) ttl="${2:-}"; shift 2 ;;
    --db) db="${2:-}"; shift 2 ;;
    --python) python_bin="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$base_url" || -z "$env_file" ]]; then
  usage >&2
  exit 2
fi
if [[ ! -r "$env_file" ]]; then
  echo "Restricted Server environment file is not readable: $env_file" >&2
  exit 1
fi

set -a
# This is a Server-owned restricted environment file. Never enable shell tracing here.
. "$env_file"
set +a

args=(-m hermes_link.pairing.store --base-url "$base_url" --profiles "$profiles" --ttl "$ttl" --qr)
if [[ -n "$db" ]]; then
  args+=(--db "$db")
fi
exec "$python_bin" "${args[@]}"
