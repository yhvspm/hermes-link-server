#!/usr/bin/env bash
set -euo pipefail
umask 077

# This is the supported entry point for the standard Docker runtime. It is
# intentionally independent from the older development/validation Compose
# assets under deploy/docker.
DEFAULT_VERSION='1.0.0'
DEFAULT_IMAGE_REPOSITORY='ghcr.io/yhvspm/hermes-link-server'
DEFAULT_RELEASE_BASE_URL='https://raw.githubusercontent.com/yhvspm/hermes-link-server'
DEFAULT_RELEASE_DOWNLOAD_BASE_URL='https://github.com/yhvspm/hermes-link-server/releases/download'
INSTALL_DIR='/opt/hermes-link'
INTERNAL_CREDENTIAL_FILE='/etc/hermes-link-server/internal-agent.env'
INTERNAL_BRIDGE_PORT='18765'

usage() {
  cat <<'EOF'
Usage: curl -fsSL https://raw.githubusercontent.com/yhvspm/hermes-link-server/v1.0.0/install.sh | sudo bash

Or from a reviewed release tree:
  sudo bash ./install.sh [options]

Options:
  --domain DOMAIN              Public DNS name for Hermes Link
  --public-port PORT           Public HTTPS port (default: 443)
  --proxy-mode MODE            caddy (default) or external
  --agent-service NAME         Hermes Agent systemd service (default: hermes-gateway.service)
  --agent-service-scope SCOPE  system (default) or user
  --agent-user USER            Hermes Agent operating-system user
  --hermes-home PATH           Hermes metadata directory
  --image IMAGE                Advanced local-source image override
  --version VERSION            Pinned release version (default: 1.0.0)
  --source-dir PATH            Use local release assets instead of downloading them
  --install-dir PATH           Installation directory (default: /opt/hermes-link)
  --reuse-agent-credential PATH
                               Advanced migration: reuse a root-only Agent credential
  --state-import-dir PATH      Advanced migration: import existing Server identity and pairing state
  --skip-image-pull            Advanced migration: use an already-built local Server image
  --non-interactive            Require all deployment choices as flags
  --dry-run                    Validate choices and print the planned operations only
  -h, --help                   Show this help

The normal flow asks only for a DNS name, a public HTTPS port, and HTTPS mode.
It never asks for, prints, or copies an upstream Hermes Agent token.
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*"
}

version="$DEFAULT_VERSION"
image=''
domain=''
public_port=''
proxy_mode=''
agent_service='hermes-gateway.service'
agent_service_scope='system'
agent_user=''
hermes_home=''
source_dir=''
install_dir="$INSTALL_DIR"
reuse_agent_credential=''
state_import_dir=''
state_identity_source=''
state_cloud_source=''
skip_image_pull=false
internal_bridge_port="$INTERNAL_BRIDGE_PORT"
dry_run=false
non_interactive=false
release_base_url="${HERMES_LINK_RELEASE_BASE_URL:-$DEFAULT_RELEASE_BASE_URL}"
release_download_base_url="${HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL:-$DEFAULT_RELEASE_DOWNLOAD_BASE_URL}"
python_bin="${HERMES_LINK_PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) domain="${2:-}"; shift 2 ;;
    --public-port) public_port="${2:-}"; shift 2 ;;
    --proxy-mode) proxy_mode="${2:-}"; shift 2 ;;
    --agent-service) agent_service="${2:-}"; shift 2 ;;
    --agent-service-scope) agent_service_scope="${2:-}"; shift 2 ;;
    --agent-user) agent_user="${2:-}"; shift 2 ;;
    --hermes-home) hermes_home="${2:-}"; shift 2 ;;
    --image) image="${2:-}"; shift 2 ;;
    --version) version="${2:-}"; shift 2 ;;
    --source-dir) source_dir="${2:-}"; shift 2 ;;
    --install-dir) install_dir="${2:-}"; shift 2 ;;
    --reuse-agent-credential) reuse_agent_credential="${2:-}"; shift 2 ;;
    --state-import-dir) state_import_dir="${2:-}"; shift 2 ;;
    --skip-image-pull) skip_image_pull=true; shift ;;
    --non-interactive) non_interactive=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

version="${version#v}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.]+)?$ ]]; then
  fail "--version must be a pinned semantic version"
fi
if [[ -n "$image" && ! "$image" =~ ^[A-Za-z0-9./:@_-]+$ ]]; then
  fail "--image contains unsupported characters"
fi
if [[ "$install_dir" != /* ]]; then fail "--install-dir must be an absolute path"; fi
if [[ -n "$reuse_agent_credential" && "$reuse_agent_credential" != /* ]]; then
  fail "--reuse-agent-credential must be an absolute path"
fi
if [[ -n "$state_import_dir" && "$state_import_dir" != /* ]]; then
  fail "--state-import-dir must be an absolute path"
fi
if [[ -n "$state_import_dir" && -z "$reuse_agent_credential" ]]; then
  fail "--state-import-dir requires --reuse-agent-credential so Agent access is left unchanged"
fi
if [[ ! "$agent_service" =~ ^[A-Za-z0-9_.@-]+\.service$ ]]; then
  fail "--agent-service must be a systemd service unit name"
fi
if [[ "$agent_service_scope" != 'system' && "$agent_service_scope" != 'user' ]]; then
  fail "--agent-service-scope must be system or user"
fi
if [[ "$release_base_url" != https://* ]]; then
  fail "HERMES_LINK_RELEASE_BASE_URL must use HTTPS"
fi
if [[ "$release_download_base_url" != https://* ]]; then
  fail "HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL must use HTTPS"
fi

is_interactive() {
  [[ "$non_interactive" == false && -r /dev/tty ]]
}

prompt_value() {
  local prompt="$1"
  local default_value="$2"
  local value=''
  is_interactive || return 1
  if [[ -n "$default_value" ]]; then
    printf '%s [%s]: ' "$prompt" "$default_value" >/dev/tty
  else
    printf '%s: ' "$prompt" >/dev/tty
  fi
  IFS= read -r value </dev/tty || return 1
  printf '%s' "${value:-$default_value}"
}

ubuntu_version_supported() {
  local version="$1"
  local major=''
  local minor=''
  [[ "$version" =~ ^([0-9]+)\.([0-9]+)$ ]] || return 1
  major="${BASH_REMATCH[1]}"
  minor="${BASH_REMATCH[2]}"
  (( 10#$major > 22 || (10#$major == 22 && 10#$minor >= 4) ))
}

ensure_ubuntu_prerequisites() {
  [[ -r /etc/os-release ]] || fail "Only Ubuntu 22.04 or newer is supported by this installer."
  # /etc/os-release is operating-system metadata maintained by the host.
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ "${ID:-}" != 'ubuntu' ]] || ! ubuntu_version_supported "${VERSION_ID:-}"; then
    fail "This installer supports Ubuntu 22.04 and newer only."
  fi
  note "Ubuntu $VERSION_ID is supported."
  [[ "$dry_run" == true ]] && return 0
  [[ "${EUID}" -eq 0 ]] || fail "Run the installer as root, for example with sudo."
  local missing=()
  local command_name
  for command_name in "$python_bin" curl openssl; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
  done
  if (( ${#missing[@]} > 0 )); then
    note "Installing required host tools: ${missing[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl openssl ca-certificates
  fi
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    fail "Docker Engine and the Docker Compose v2 plugin are required. Install Docker first, then rerun this command."
  fi
}

initial_install_exists() {
  [[ -f "$install_dir/.env" && -x "$install_dir/bin/hermes-link" ]]
}

if [[ "$dry_run" == false && $(id -u) -eq 0 ]] && initial_install_exists; then
  note "An existing Hermes Link installation was found at $install_dir."
  note "Its identity and configuration were left unchanged."
  "$install_dir/bin/hermes-link" status || true
  exit 0
fi

ensure_ubuntu_prerequisites
command -v "$python_bin" >/dev/null 2>&1 || fail "python3 is required to validate deployment metadata"

script_path="${BASH_SOURCE[0]}"
script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
if [[ -z "$source_dir" && -f "$script_path" && "$script_dir/install.sh" -ef "$script_path" ]]; then
  source_dir="$script_dir"
fi
if [[ -n "$source_dir" ]]; then
  source_dir="$(cd -- "$source_dir" && pwd)"
fi

stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/hermes-link-install.XXXXXX")"
cleanup() {
  rm -rf -- "$stage_dir"
}
trap cleanup EXIT

release_manifest=''

release_manifest_value() {
  local requested_path="${1:-}"
  "$python_bin" - "$release_manifest" "$version" "$DEFAULT_IMAGE_REPOSITORY" "$requested_path" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

manifest_path, expected_version, image_repository, requested_path = sys.argv[1:]
release_paths = {
    "install.sh",
    "deploy/standard/compose.yaml",
    "deploy/standard/Caddyfile",
    "deploy/standard/.env.example",
    "deploy/standard/bin/hermes-link",
    "scripts/deployment_helpers.py",
    "scripts/bootstrap-hermes-agent-access.sh",
    "scripts/manage-internal-credential.py",
    "scripts/release_manifest.py",
}
try:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"Cannot read release manifest: {error}")

if set(manifest) != {"schema_version", "version", "source_commit", "image", "files"}:
    raise SystemExit("Release manifest has unexpected or missing fields")
if manifest["schema_version"] != 1:
    raise SystemExit("Release manifest schema is unsupported")
if manifest["version"] != expected_version or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?", manifest["version"]) is None:
    raise SystemExit("Release manifest version does not match the requested version")
if not isinstance(manifest["source_commit"], str) or re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]) is None:
    raise SystemExit("Release manifest source commit is invalid")
if not isinstance(manifest["image"], str) or re.fullmatch(
    re.escape(image_repository) + r"@sha256:[0-9a-f]{64}", manifest["image"]
) is None:
    raise SystemExit("Release manifest image is not an immutable official GHCR digest")
files = manifest["files"]
if not isinstance(files, dict) or set(files) != release_paths:
    raise SystemExit("Release manifest assets are incomplete or unexpected")
if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in files.values()):
    raise SystemExit("Release manifest contains an invalid asset digest")
if requested_path:
    if requested_path not in release_paths:
        raise SystemExit("Release asset is not in the supported manifest")
    print(files[requested_path])
else:
    print(manifest["image"])
PY
}

verify_release_asset() {
  local relative_path="$1"
  local asset_path="$2"
  local expected=''
  local actual=''
  expected="$(release_manifest_value "$relative_path")" || fail "Release manifest validation failed"
  actual="$(sha256sum -- "$asset_path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || fail "Release asset integrity verification failed: $relative_path"
}

prepare_release_manifest() {
  local source_manifest=''
  if [[ -n "$source_dir" ]]; then
    source_manifest="$source_dir/release-manifest.json"
    if [[ ! -f "$source_manifest" ]]; then
      return
    fi
    install -m 0644 "$source_manifest" "$stage_dir/release-manifest.json"
  else
    command -v curl >/dev/null 2>&1 || fail "curl is required to download the release manifest"
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
      "$release_download_base_url/v$version/release-manifest.json" -o "$stage_dir/release-manifest.json"
  fi
  release_manifest="$stage_dir/release-manifest.json"
  local verified_image=''
  verified_image="$(release_manifest_value)" || fail "Release manifest validation failed"
  if [[ -n "$image" && "$image" != "$verified_image" ]]; then
    fail "--image must match the verified release image digest"
  fi
  image="$verified_image"
}

prepare_release_manifest
if [[ -z "$image" ]]; then
  if [[ -n "$source_dir" ]]; then
    image="$DEFAULT_IMAGE_REPOSITORY:$version"
    note 'Using a reviewed local source tree without a release manifest; image digest verification is not available.'
  else
    fail 'Published installation requires release-manifest.json and its verified image digest.'
  fi
fi
if [[ ! "$image" =~ ^[A-Za-z0-9./:@_-]+$ ]]; then
  fail "--image contains unsupported characters"
fi

copy_asset() {
  local relative_path="$1"
  local destination="$2"
  local mode="$3"
  local target="$stage_dir/$destination"
  install -d -m 0755 "$(dirname -- "$target")"
  if [[ -n "$source_dir" ]]; then
    [[ -f "$source_dir/$relative_path" ]] || fail "Release asset is missing: $relative_path"
    install -m "$mode" "$source_dir/$relative_path" "$target"
    if [[ -n "$release_manifest" ]]; then verify_release_asset "$relative_path" "$target"; fi
    return
  fi
  command -v curl >/dev/null 2>&1 || fail "curl is required to download the standard release assets"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$release_base_url/v$version/$relative_path" -o "$target"
  chmod "$mode" "$target"
  verify_release_asset "$relative_path" "$target"
}

copy_asset 'deploy/standard/compose.yaml' 'compose.yaml' '0644'
copy_asset 'deploy/standard/Caddyfile' 'Caddyfile' '0644'
copy_asset 'deploy/standard/.env.example' '.env.example' '0644'
copy_asset 'deploy/standard/bin/hermes-link' 'bin/hermes-link' '0755'
copy_asset 'scripts/deployment_helpers.py' 'bin/lib/deployment_helpers.py' '0755'
copy_asset 'scripts/bootstrap-hermes-agent-access.sh' 'bin/lib/bootstrap-hermes-agent-access.sh' '0755'
copy_asset 'scripts/manage-internal-credential.py' 'bin/lib/manage-internal-credential.py' '0755'
copy_asset 'scripts/release_manifest.py' 'bin/lib/release_manifest.py' '0755'

helper="$stage_dir/bin/lib/deployment_helpers.py"

resolve_endpoint() {
  local resolved=''
  while true; do
    if [[ -z "$domain" ]]; then
      domain="$(prompt_value '请输入 Hermes Link 域名' '')" || fail "Pass --domain when no terminal is available"
    fi
    if [[ -z "$public_port" ]]; then
      public_port="$(prompt_value '请输入公网 HTTPS 端口' '443')" || fail "Pass --public-port when no terminal is available"
    fi
    if resolved="$("$python_bin" "$helper" endpoint --host "$domain" --port "$public_port" 2>&1)"; then
      IFS=$'\t' read -r domain public_port public_url <<< "$resolved"
      return
    fi
    printf '%s\n' "$resolved" >&2
    domain=''
    public_port=''
  done
}

resolve_proxy_mode() {
  if [[ -z "$proxy_mode" ]]; then
    local choice=''
    if is_interactive; then
      note 'HTTPS 方式：'
      note '1. Hermes Link 自动配置 Caddy（推荐）'
      note '2. 使用现有反向代理'
      choice="$(prompt_value '请选择' '1')" || true
      case "$choice" in
        1) proxy_mode='caddy' ;;
        2) proxy_mode='external' ;;
        *) fail '请选择 1 或 2' ;;
      esac
    else
      proxy_mode='caddy'
    fi
  fi
  [[ "$proxy_mode" == 'caddy' || "$proxy_mode" == 'external' ]] || fail "--proxy-mode must be caddy or external"
}

port_is_free() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    if ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .; then return 1; fi
    return 0
  fi
  "$python_bin" - "$port" <<'PY'
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    try:
        sock.bind(("0.0.0.0", int(sys.argv[1])))
    except OSError:
        raise SystemExit(1)
PY
}

resolve_caddy_ports() {
  [[ "$dry_run" == true || "$proxy_mode" != 'caddy' ]] && return
  while ! port_is_free "$public_port"; do
    note "端口 $public_port 已被占用。"
    if ! is_interactive; then
      fail "Choose another --public-port or use --proxy-mode external."
    fi
    note '请选择：'
    note '1. 使用其他公网端口'
    note '2. 使用现有反向代理'
    note '3. 退出安装'
    case "$(prompt_value '请选择' '1')" in
      1)
        public_port="$(prompt_value '请输入新的公网 HTTPS 端口' '8443')" || fail '未提供端口'
        resolve_endpoint
        ;;
      2) proxy_mode='external'; return ;;
      *) fail '安装已取消' ;;
    esac
  done
  if ! port_is_free 80; then
    note '自动 Caddy TLS 需要本机 TCP 80 可用于 HTTP-01 证书验证。'
    note '请释放端口 80，或选择现有反向代理 / DNS challenge / 已有证书的高级部署方式。'
    if is_interactive && [[ "$(prompt_value '改用现有反向代理？(y/N)' 'N')" =~ ^[Yy]$ ]]; then
      proxy_mode='external'
      return
    fi
    fail '无法在当前端口状态下启用自动 Caddy TLS'
  fi
}

resolve_internal_bridge_port() {
  local candidate
  for ((candidate=INTERNAL_BRIDGE_PORT; candidate<=INTERNAL_BRIDGE_PORT + 10; candidate++)); do
    if port_is_free "$candidate"; then
      internal_bridge_port="$candidate"
      return
    fi
  done
  fail "No free loopback port was found in the Hermes Link internal range."
}

resolve_agent_context() {
  if [[ -z "$agent_user" ]]; then
    agent_user="$(systemctl show "$agent_service" --property User --value 2>/dev/null || true)"
  fi
  if [[ -z "$agent_user" ]]; then agent_user="${SUDO_USER:-}"; fi
  if [[ -z "$agent_user" ]]; then
    agent_user="$(prompt_value '请输入 Hermes Agent 的系统用户' '')" || fail 'Pass --agent-user when it cannot be detected'
  fi
  if [[ "$dry_run" == false ]] && ! getent passwd "$agent_user" >/dev/null; then
    fail "Hermes Agent user does not exist: $agent_user"
  fi
  if [[ -z "$hermes_home" ]]; then
    local agent_home=''
    agent_home="$(getent passwd "$agent_user" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -z "$agent_home" && "$dry_run" == true ]]; then agent_home="/home/$agent_user"; fi
    [[ -n "$agent_home" ]] || fail "Cannot determine the home directory for $agent_user; pass --hermes-home"
    hermes_home="$agent_home/.hermes"
  fi
  [[ "$hermes_home" == /* ]] || fail '--hermes-home must be an absolute path'
}

validate_reused_agent_credential() {
  [[ -n "$reuse_agent_credential" ]] || return
  [[ -f "$reuse_agent_credential" && ! -L "$reuse_agent_credential" ]] || fail "--reuse-agent-credential must be a regular file"
  local ownership=''
  ownership="$(stat -c '%u %a' -- "$reuse_agent_credential")" || fail "Cannot inspect --reuse-agent-credential"
  [[ "$ownership" == '0 600' ]] || fail "--reuse-agent-credential must be owned by root with mode 0600"
  grep -q '^HERMES_LINK_AGENT_TOKEN=.' -- "$reuse_agent_credential" || fail "--reuse-agent-credential does not contain a usable Agent credential"
}

select_state_source() {
  local result_name="$1"
  shift
  local state_name=''
  local candidate=''
  local selected=''
  for state_name in "$@"; do
    candidate="$state_import_dir/$state_name"
    if [[ -e "$candidate" || -L "$candidate" ]]; then
      [[ -f "$candidate" && ! -L "$candidate" ]] || fail "--state-import-dir contains an unsafe state entry: $state_name"
      [[ -z "$selected" ]] || fail "--state-import-dir contains multiple files for the same state"
      selected="$candidate"
    fi
  done
  printf -v "$result_name" '%s' "$selected"
}

validate_state_import_dir() {
  [[ -n "$state_import_dir" ]] || return
  [[ -d "$state_import_dir" && ! -L "$state_import_dir" ]] || fail "--state-import-dir must be a directory"
  state_import_dir="$(cd -P -- "$state_import_dir" && pwd)" || fail "Cannot resolve --state-import-dir"

  select_state_source state_identity_source server-identity.json hermes_link_server_identity.json
  [[ -n "$state_identity_source" ]] || fail "--state-import-dir is missing required Server identity state"
  local state_name=''
  for state_name in pairing.db; do
    [[ -f "$state_import_dir/$state_name" && ! -L "$state_import_dir/$state_name" ]] || fail "--state-import-dir is missing required state: $state_name"
  done
  select_state_source state_cloud_source cloud-config.json hermes_link_cloud_config.json
  for state_name in pairing.db-wal pairing.db-shm; do
    if [[ -e "$state_import_dir/$state_name" || -L "$state_import_dir/$state_name" ]]; then
      [[ -f "$state_import_dir/$state_name" && ! -L "$state_import_dir/$state_name" ]] || fail "--state-import-dir contains an unsafe state entry: $state_name"
    fi
  done
}

import_server_state() {
  [[ -n "$state_import_dir" ]] || return
  local state_name=''
  install -m 0600 -- "$state_identity_source" "$install_dir/data/server/server-identity.json"
  chown 10001:10001 "$install_dir/data/server/server-identity.json"
  for state_name in pairing.db pairing.db-wal pairing.db-shm; do
    if [[ -f "$state_import_dir/$state_name" && ! -L "$state_import_dir/$state_name" ]]; then
      install -m 0600 -- "$state_import_dir/$state_name" "$install_dir/data/server/$state_name"
      chown 10001:10001 "$install_dir/data/server/$state_name"
    fi
  done
  if [[ -n "$state_cloud_source" ]]; then
    install -m 0600 -- "$state_cloud_source" "$install_dir/data/server/cloud-config.json"
    chown 10001:10001 "$install_dir/data/server/cloud-config.json"
  fi
}

resolve_endpoint
resolve_proxy_mode
resolve_caddy_ports
resolve_internal_bridge_port
resolve_agent_context
validate_reused_agent_credential
validate_state_import_dir

agent_credential_file="$INTERNAL_CREDENTIAL_FILE"
if [[ -n "$reuse_agent_credential" ]]; then
  agent_credential_file="$reuse_agent_credential"
fi

bootstrap_args=(
  --agent-service "$agent_service"
  --agent-service-scope "$agent_service_scope"
  --agent-user "$agent_user"
  --hermes-home "$hermes_home"
  --credential-file "$agent_credential_file"
)

if [[ "$dry_run" == true ]]; then
  if [[ -n "$reuse_agent_credential" ]]; then
    note 'DRY RUN: reuse the existing root-only Agent credential and leave the Agent service unchanged.'
  else
    bash "$stage_dir/bin/lib/bootstrap-hermes-agent-access.sh" "${bootstrap_args[@]}" --dry-run
  fi
  note "DRY RUN: create $install_dir with a generated .env and persistent data/server state."
  if [[ -n "$state_import_dir" ]]; then
    note 'DRY RUN: import only Server identity, pairing, optional Cloud binding, and SQLite sidecar state.'
  fi
  if [[ "$skip_image_pull" == true ]]; then
    note "DRY RUN: use the already-built local image $image."
  else
    note "DRY RUN: pull $image."
  fi
  note "DRY RUN: start the Server on hidden loopback port $internal_bridge_port."
  if [[ "$proxy_mode" == 'caddy' ]]; then
    note "DRY RUN: Caddy will serve $public_url and use TCP 80 for HTTP-01 certificate validation."
  else
    note "DRY RUN: external reverse proxy target will be http://127.0.0.1:$internal_bridge_port."
  fi
  note "DRY RUN: detected Profile directory names will be enabled automatically after Hermes access is ready."
  exit 0
fi

[[ "${EUID}" -eq 0 ]] || fail "Run the installer as root, for example with sudo."
if [[ -e "$install_dir" ]]; then
  fail "Installation directory already exists and is not a managed Hermes Link installation: $install_dir"
fi
if [[ -e /usr/local/bin/hermes-link || -L /usr/local/bin/hermes-link ]]; then
  existing_cli="$(readlink -f /usr/local/bin/hermes-link 2>/dev/null || true)"
  [[ "$existing_cli" == "$install_dir/bin/hermes-link" ]] || fail '/usr/local/bin/hermes-link is already owned by another installation'
fi

install -d -m 0755 "$install_dir"
cp -a "$stage_dir/." "$install_dir/"
install -d -m 0700 "$install_dir/data/server"
chown 10001:10001 "$install_dir/data/server"
install -d -m 0700 "$install_dir/data/caddy-data" "$install_dir/data/caddy-config" "$install_dir/backups"

import_server_state
if [[ -n "$reuse_agent_credential" ]]; then
  note 'Reusing the existing root-only Agent credential; the Agent service was left unchanged.'
else
  bash "$install_dir/bin/lib/bootstrap-hermes-agent-access.sh" "${bootstrap_args[@]}"
fi
[[ -d "$hermes_home" ]] || fail "Hermes metadata directory is unavailable after Agent setup: $hermes_home"
mapfile -t profile_ids < <("$python_bin" "$install_dir/bin/lib/deployment_helpers.py" profiles --hermes-home "$hermes_home")
(( ${#profile_ids[@]} > 0 )) || fail 'No Hermes Profiles were discovered'
profile_list="$(IFS=,; printf '%s' "${profile_ids[*]}")"

note '检测到 Hermes Profiles：'
for profile_id in "${profile_ids[@]}"; do note "✓ $profile_id"; done

environment_tmp="$(mktemp "$install_dir/.env.XXXXXX")"
{
  printf 'HERMES_LINK_VERSION=%s\n' "$version"
  printf 'HERMES_LINK_IMAGE=%s\n' "$image"
  printf 'HERMES_LINK_RELEASE_BASE_URL=%s\n' "$release_base_url"
  printf 'HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL=%s\n' "$release_download_base_url"
  printf 'HERMES_LINK_RELEASE_API_URL=https://api.github.com/repos/yhvspm/hermes-link-server/releases/latest\n'
  printf 'HERMES_LINK_PUBLIC_HOST=%s\n' "$domain"
  printf 'HERMES_LINK_PUBLIC_PORT=%s\n' "$public_port"
  printf 'HERMES_LINK_PUBLIC_URL=%s\n' "$public_url"
  printf 'HERMES_LINK_PROXY_MODE=%s\n' "$proxy_mode"
  printf 'HERMES_LINK_AGENT_HOME_HOST=%s\n' "$hermes_home"
  printf 'HERMES_LINK_PROFILE_IDS=%s\n' "$profile_list"
  printf 'HERMES_LINK_INTERNAL_ENV_FILE=%s\n' "$agent_credential_file"
  printf 'HERMES_LINK_BRIDGE_PORT=%s\n' "$internal_bridge_port"
  printf 'HERMES_LINK_FIREWALL_MANAGED=0\n'
} > "$environment_tmp"
install -m 0600 "$environment_tmp" "$install_dir/.env"
rm -f -- "$environment_tmp"

compose=(docker compose --env-file "$install_dir/.env" --project-directory "$install_dir" -f "$install_dir/compose.yaml")
if [[ "$proxy_mode" == 'caddy' ]]; then compose+=(--profile caddy); fi
if [[ "$skip_image_pull" == true ]]; then
  docker image inspect "$image" >/dev/null || fail "Local Server image is unavailable: $image"
else
  "${compose[@]}" pull
fi
"${compose[@]}" up -d --remove-orphans

wait_for_local_health() {
  local attempt
  for attempt in {1..30}; do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$internal_bridge_port/health" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

if ! wait_for_local_health; then
  note 'Server container did not become healthy. Its persisted state was retained.'
  "$install_dir/bin/hermes-link" doctor || true
  exit 1
fi
server_info="$(curl --fail --silent --max-time 5 "http://127.0.0.1:$internal_bridge_port/hermes-link/v1/server-info")"
IFS=$'\t' read -r gateway_state active_agents server_id cloud_multi_binding <<< "$(printf '%s' "$server_info" | "$python_bin" "$install_dir/bin/lib/deployment_helpers.py" server-info)"
[[ -n "$server_id" ]] || fail 'Server identity was not created in persistent state'

https_state='External reverse proxy mode'
if [[ "$proxy_mode" == 'caddy' ]]; then
  https_state='Waiting for HTTPS'
  for _attempt in {1..45}; do
    if curl --fail --silent --max-time 5 "$public_url/hermes-link/v1/server-info" >/dev/null; then
      https_state='✓'
      break
    fi
    sleep 2
  done
  if [[ "$https_state" != '✓' ]]; then
    note 'Server is healthy, but HTTPS has not been verified. DNS, TCP 80/your public port, or certificate validation needs attention.'
    "$install_dir/bin/hermes-link" doctor || true
    exit 1
  fi
fi

ln -s "$install_dir/bin/hermes-link" /usr/local/bin/hermes-link
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  note "Firewall is active. If needed, allow public TCP $public_port yourself; the installer did not change firewall rules."
fi

note ''
note 'Hermes Link Server 部署成功'
note ''
note 'Server       ✓ Running'
if [[ "$gateway_state" == 'unavailable' ]]; then
  note 'Hermes       ! Server is running but Agent connectivity is unavailable'
else
  note 'Hermes       ✓ Connected'
fi
note "Agents       ✓ $active_agents"
note 'Server ID    ✓ Stable'
if [[ "$proxy_mode" == 'caddy' ]]; then note 'HTTPS        ✓'; else note 'HTTPS        ! External reverse proxy mode'; fi
if [[ "$cloud_multi_binding" == 'true' ]]; then note 'Cloud V3     ✓ Supported'; else note 'Cloud V3     ! Identity capability not reported'; fi
note ''
note 'App 地址：'
note "$public_url"
note ''
note '下一步：'
note '打开 Hermes Link App → 设置 → 服务器 → 添加 Hermes'
