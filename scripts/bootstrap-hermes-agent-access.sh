#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: sudo ./scripts/bootstrap-hermes-agent-access.sh [options]

Creates or rotates the dedicated Hermes Link-to-Agent credential, injects it
into the Hermes Agent systemd service, and starts that service. No Agent API
token is requested, printed, or taken from the command line.

Options:
  --agent-service NAME     Hermes Agent systemd unit (default: hermes-gateway.service)
  --agent-service-scope SCOPE
                            Agent unit scope: system or user (default: system)
  --agent-user USER        Agent owner; required for user-scoped units
  --agent-command PATH     Hermes CLI command used only when the service is absent (default: hermes)
  --agent-run-as-user USER Agent owner for first-time service installation
  --hermes-home PATH       Agent metadata directory (default: <agent home>/.hermes)
  --credential-file PATH   Dedicated root-only credential file
  --parallel-agent-credential
                            Keep an existing mobile credential while adding this Server credential
  --rotate                 Replace the existing dedicated credential
  --dry-run                Print the plan without creating files or restarting services
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
agent_service='hermes-gateway.service'
agent_service_scope='system'
agent_command="${HERMES_AGENT_COMMAND:-hermes}"
agent_user=''
hermes_home=''
credential_file='/etc/hermes-link-server/internal-agent.env'
rotate=false
parallel_agent_credential=false
dry_run=false
python_bin="${HERMES_LINK_PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-service) agent_service="${2:-}"; shift 2 ;;
    --agent-service-scope) agent_service_scope="${2:-}"; shift 2 ;;
    --agent-user) agent_user="${2:-}"; shift 2 ;;
    --agent-command) agent_command="${2:-}"; shift 2 ;;
    --agent-run-as-user) agent_user="${2:-}"; shift 2 ;;
    --hermes-home) hermes_home="${2:-}"; shift 2 ;;
    --credential-file) credential_file="${2:-}"; shift 2 ;;
    --parallel-agent-credential) parallel_agent_credential=true; shift ;;
    --rotate) rotate=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "$agent_service" =~ ^[A-Za-z0-9_.@-]+\.service$ ]]; then
  echo "--agent-service must be a systemd service unit name." >&2
  exit 2
fi
if [[ "$agent_service_scope" != 'system' && "$agent_service_scope" != 'user' ]]; then
  echo "--agent-service-scope must be system or user." >&2
  exit 2
fi
if [[ -z "$agent_user" ]]; then
  agent_user="${SUDO_USER:-}"
fi
if [[ "$dry_run" == true && -z "$agent_user" ]]; then agent_user='<sudo-caller>'; fi
if [[ "$dry_run" == false ]]; then
  if [[ -z "$agent_user" ]]; then
    echo "Specify --agent-user (or --agent-run-as-user for compatibility)." >&2
    exit 2
  fi
  if ! getent passwd "$agent_user" >/dev/null; then
    echo "Agent user does not exist: $agent_user" >&2
    exit 2
  fi
fi

run_agent_systemctl() {
  if [[ "$agent_service_scope" == 'user' ]]; then
    runuser -u "$agent_user" -- env "XDG_RUNTIME_DIR=/run/user/$agent_uid" systemctl --user "$@"
  else
    systemctl "$@"
  fi
}
if [[ -z "$hermes_home" ]]; then
  if [[ "$dry_run" == true ]]; then
    hermes_home="/home/$agent_user/.hermes"
  else
    agent_home="$(getent passwd "$agent_user" | cut -d: -f6)"
    hermes_home="$agent_home/.hermes"
  fi
fi
if [[ "$hermes_home" != /* ]]; then
  echo "--hermes-home must be an absolute path." >&2
  exit 2
fi

drop_in_dir="/etc/systemd/system/$agent_service.d"
drop_in_file="$drop_in_dir/hermes-link.conf"
agent_uid=''
if [[ "$agent_service_scope" == 'user' && "$dry_run" == false ]]; then
  agent_uid="$(id -u "$agent_user")"
  agent_home="$(getent passwd "$agent_user" | cut -d: -f6)"
  drop_in_dir="$agent_home/.config/systemd/user/$agent_service.d"
  drop_in_file="$drop_in_dir/hermes-link.conf"
elif [[ "$agent_service_scope" == 'user' ]]; then
  agent_home="/home/$agent_user"
  if [[ "$agent_user" == 'root' ]]; then agent_home='/root'; fi
  drop_in_dir="$agent_home/.config/systemd/user/$agent_service.d"
  drop_in_file="$drop_in_dir/hermes-link.conf"
fi
credential_args=(--credential-file "$credential_file" --hermes-home "$hermes_home")
if [[ "$rotate" == true ]]; then
  credential_args+=(--rotate)
fi
if [[ "$parallel_agent_credential" == true ]]; then
  credential_args+=(--parallel-agent-credential)
fi

if [[ "$dry_run" == true ]]; then
  printf '%s\n' \
    "DRY RUN: ensure $agent_service ($agent_service_scope scope) exists; if absent install it through the Hermes CLI for user $agent_user." \
    "DRY RUN: create or rotate a root-only dedicated Hermes Link credential at $credential_file without printing its value." \
    "DRY RUN: write $drop_in_file with EnvironmentFile=$credential_file." \
    "DRY RUN: reload systemd and restart $agent_service."
  if [[ "$parallel_agent_credential" == true ]]; then
    echo "DRY RUN: preserve the existing mobile credential and add a parallel Server credential."
  fi
  "$python_bin" "$script_dir/manage-internal-credential.py" "${credential_args[@]}" --dry-run
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this bootstrapper as root (for example with sudo)." >&2
  exit 1
fi

if ! run_agent_systemctl cat "$agent_service" >/dev/null 2>&1; then
  if ! command -v "$agent_command" >/dev/null 2>&1; then
    echo "Hermes Agent service is absent and Hermes CLI was not found: $agent_command" >&2
    exit 1
  fi
  if [[ "$agent_service_scope" == 'user' ]]; then
    runuser -u "$agent_user" -- "$agent_command" gateway install --no-start-now
  else
    "$agent_command" gateway install --system --run-as-user "$agent_user" --no-start-now
  fi
fi

"$python_bin" "$script_dir/manage-internal-credential.py" "${credential_args[@]}"
install -d -m 0755 "$drop_in_dir"
temporary_drop_in="$(mktemp "$drop_in_dir/.hermes-link.XXXXXX")"
trap 'rm -f "$temporary_drop_in"' EXIT
cat > "$temporary_drop_in" <<EOF
[Service]
EnvironmentFile=$credential_file
EOF
install -m 0644 "$temporary_drop_in" "$drop_in_file"
rm -f "$temporary_drop_in"
trap - EXIT
run_agent_systemctl daemon-reload
run_agent_systemctl enable --now "$agent_service"
run_agent_systemctl is-active --quiet "$agent_service"

if systemctl cat hermes-link-server.service >/dev/null 2>&1; then
  systemctl restart hermes-link-server.service
  systemctl is-active --quiet hermes-link-server.service
fi
echo "Hermes Agent access is ready. The internal credential was not printed."
