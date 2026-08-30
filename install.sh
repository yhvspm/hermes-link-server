#!/usr/bin/env bash
set -euo pipefail
umask 077

# This is the supported entry point for the standard Docker runtime. It is
# intentionally independent from the older development/validation Compose
# assets under deploy/docker.
DEFAULT_VERSION='1.0.3'
DEFAULT_IMAGE_REPOSITORY='ghcr.io/yhvspm/hermes-link-server'
DEFAULT_RELEASE_DOWNLOAD_BASE_URL='https://github.com/yhvspm/hermes-link-server/releases/download'
INSTALL_DIR='/opt/hermes-link'
INTERNAL_CREDENTIAL_FILE='/etc/hermes-link-server/internal-agent.env'
MOBILE_CREDENTIAL_FILE='/etc/hermes-link-server/mobile-api.env'

usage() {
  cat <<'EOF'
Usage: curl -fL https://github.com/yhvspm/hermes-link-server/releases/download/v1.0.3/hermes-link-server-install.sh -o hermes-link-server-install.sh
       sudo bash hermes-link-server-install.sh

Or from a reviewed release tree:
  sudo bash ./install.sh [options]

Options:
  --host HOST                  App-facing IP address or DNS name for direct HTTP
  --public-port PORT           App-facing HTTP port (default: 18766)
  --public-url URL             Advanced App URL for direct HTTP or an external HTTPS proxy
  --listen-host HOST           0.0.0.0 (default for HTTP) or 127.0.0.1 (external proxy)
  --listen-port PORT           Server HTTP listener (default: public port for HTTP)
  --agent-service NAME         Hermes Agent systemd service (default: hermes-gateway.service)
  --agent-service-scope SCOPE  system (default) or user
  --agent-user USER            Hermes Agent operating-system user
  --hermes-home PATH           Hermes metadata directory
  --image IMAGE                Advanced local-source image override
  --version VERSION            Pinned release version (default: 1.0.3)
  --source-dir PATH            Use local release assets instead of downloading them
  --install-dir PATH           Installation directory (default: /opt/hermes-link)
  --upgrade-existing           Bootstrap a managed installation into this pinned release
  --reuse-agent-credential PATH
                               Advanced migration: reuse a root-only Agent credential
  --state-import-dir PATH      Advanced migration: import existing Server identity and pairing state
  --skip-image-pull            Advanced migration: use an already-built local Server image
  --non-interactive            Require all deployment choices as flags
  --dry-run                    Validate choices and print the planned operations only
  -h, --help                   Show this help

The normal flow asks only for an App-facing IP/DNS address and a public HTTP port.
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
public_host=''
public_url_input=''
public_port=''
listen_port=''
listen_host=''
agent_service='hermes-gateway.service'
agent_service_scope='system'
agent_user=''
agent_home=''
hermes_home=''
source_dir=''
install_dir="$INSTALL_DIR"
reuse_agent_credential=''
state_import_dir=''
state_identity_source=''
state_cloud_source=''
skip_image_pull=false
image_loaded_from_archive=false
upgrade_existing=false
dry_run=false
non_interactive=false
release_download_base_url="${HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL:-$DEFAULT_RELEASE_DOWNLOAD_BASE_URL}"
python_bin="${HERMES_LINK_PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) public_host="${2:-}"; shift 2 ;;
    --public-port) public_port="${2:-}"; shift 2 ;;
    --public-url) public_url_input="${2:-}"; shift 2 ;;
    --listen-host) listen_host="${2:-}"; shift 2 ;;
    --listen-port) listen_port="${2:-}"; shift 2 ;;
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
    --upgrade-existing) upgrade_existing=true; shift ;;
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
if [[ "$agent_service_scope" == 'user' && -n "$reuse_agent_credential" ]]; then
  fail "--reuse-agent-credential is not supported with a user-scoped Agent service"
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
  for command_name in "$python_bin" curl; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
  done
  if (( ${#missing[@]} > 0 )); then
    note "Installing required host tools: ${missing[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl ca-certificates
  fi
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    fail "Docker Engine and the Docker Compose v2 plugin are required. Install Docker first, then rerun this command."
  fi
}

initial_install_exists() {
  [[ -f "$install_dir/.env" && -x "$install_dir/bin/hermes-link" ]]
}

existing_install=false
if initial_install_exists; then
  existing_install=true
  if [[ "$upgrade_existing" == false && "$dry_run" == false && $(id -u) -eq 0 ]]; then
    note "An existing Hermes Link installation was found at $install_dir."
    note "Its identity and configuration were left unchanged. Use --upgrade-existing to migrate it."
    "$install_dir/bin/hermes-link" status || true
    exit 0
  fi
elif [[ "$upgrade_existing" == true ]]; then
  fail "--upgrade-existing requires a managed Hermes Link installation at $install_dir"
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
  local requested_value="${2:-image}"
  "$python_bin" - "$release_manifest" "$version" "$DEFAULT_IMAGE_REPOSITORY" "$requested_path" "$requested_value" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path, expected_version, image_repository, requested_path, requested_value = sys.argv[1:]
release_paths = {
    "install.sh",
    "deploy/standard/compose.yaml",
    "deploy/standard/.env.example",
    "deploy/standard/bin/hermes-link",
    "scripts/deployment_helpers.py",
    "scripts/bootstrap-hermes-agent-access.sh",
    "scripts/manage-internal-credential.py",
    "scripts/release_manifest.py",
}
archive_name = f"hermes-link-server-{expected_version}-linux-amd64.oci.tar"
try:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"Cannot read release manifest: {error}")

schema_version = manifest.get("schema_version")
if type(schema_version) is not int:
    raise SystemExit("Release manifest schema is unsupported")
if schema_version == 1:
    expected_keys = {"schema_version", "version", "source_commit", "image", "files"}
elif schema_version == 2:
    expected_keys = {"schema_version", "version", "source_commit", "image", "image_archive", "files"}
else:
    raise SystemExit("Release manifest schema is unsupported")
if set(manifest) != expected_keys:
    raise SystemExit("Release manifest has unexpected or missing fields")
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
if schema_version == 2:
    image_archive = manifest["image_archive"]
    if not isinstance(image_archive, dict) or set(image_archive) != {"name", "sha256", "platform"}:
        raise SystemExit("Release manifest image archive is invalid")
    if image_archive.get("name") != archive_name or image_archive.get("platform") != "linux/amd64":
        raise SystemExit("Release manifest image archive is unsupported")
    if not isinstance(image_archive.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", image_archive["sha256"]) is None:
        raise SystemExit("Release manifest image archive digest is invalid")
if requested_path:
    if requested_path not in release_paths:
        raise SystemExit("Release asset is not in the supported manifest")
    print(files[requested_path])
elif requested_value == "image-archive-name":
    if schema_version != 2:
        raise SystemExit("Release manifest does not contain an OCI image archive")
    print(manifest["image_archive"]["name"])
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

release_asset_name() {
  case "$1" in
    install.sh) printf '%s' 'hermes-link-server-install.sh' ;;
    deploy/standard/compose.yaml) printf '%s' 'hermes-link-server-compose.yaml' ;;
    deploy/standard/.env.example) printf '%s' 'hermes-link-server-env.example' ;;
    deploy/standard/bin/hermes-link) printf '%s' 'hermes-link-server-cli' ;;
    scripts/deployment_helpers.py) printf '%s' 'hermes-link-server-deployment-helpers.py' ;;
    scripts/bootstrap-hermes-agent-access.sh) printf '%s' 'hermes-link-server-bootstrap-agent-access.sh' ;;
    scripts/manage-internal-credential.py) printf '%s' 'hermes-link-server-manage-internal-credential.py' ;;
    scripts/release_manifest.py) printf '%s' 'hermes-link-server-release-manifest.py' ;;
    *) fail "Unknown release asset path: $1" ;;
  esac
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
  local release_asset=''
  release_asset="$(release_asset_name "$relative_path")"
  command -v curl >/dev/null 2>&1 || fail "curl is required to download the standard release assets"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$release_download_base_url/v$version/$release_asset" -o "$target"
  chmod "$mode" "$target"
  verify_release_asset "$relative_path" "$target"
}

copy_asset 'deploy/standard/compose.yaml' 'compose.yaml' '0644'
copy_asset 'deploy/standard/.env.example' '.env.example' '0644'
copy_asset 'deploy/standard/bin/hermes-link' 'bin/hermes-link' '0755'
copy_asset 'scripts/deployment_helpers.py' 'bin/lib/deployment_helpers.py' '0755'
copy_asset 'scripts/bootstrap-hermes-agent-access.sh' 'bin/lib/bootstrap-hermes-agent-access.sh' '0755'
copy_asset 'scripts/manage-internal-credential.py' 'bin/lib/manage-internal-credential.py' '0755'
copy_asset 'scripts/release_manifest.py' 'bin/lib/release_manifest.py' '0755'

helper="$stage_dir/bin/lib/deployment_helpers.py"
release_manifest_helper="$stage_dir/bin/lib/release_manifest.py"

set_existing_environment_value() {
  local key="$1"
  local value="$2"
  python3 - "$install_dir/.env" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
prefix = f"{key}="
lines = path.read_text(encoding="utf-8").splitlines()
updated = False
result = []
for line in lines:
    if line.startswith(prefix):
        result.append(prefix + value)
        updated = True
    else:
        result.append(line)
if not updated:
    result.append(prefix + value)
path.write_text("\n".join(result) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
}

remove_existing_environment_value() {
  local key="$1"
  python3 - "$install_dir/.env" "$key" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
prefix = f"{sys.argv[2]}="
lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith(prefix)]
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
}

migrate_local_existing_installation() {
  [[ "$skip_image_pull" == true ]] || \
    fail 'A local-source upgrade requires --skip-image-pull with an already-built local image.'
  [[ -n "$reuse_agent_credential" ]] || \
    fail 'A local-source upgrade requires --reuse-agent-credential to leave the Hermes Agent unchanged.'
  docker image inspect "$image" >/dev/null || fail "Local Server image is unavailable: $image"

  local backup_dir old_server_id old_profiles legacy_proxy_file
  local old_compose=(docker compose --env-file "$install_dir/.env" --project-directory "$install_dir" -f "$install_dir/compose.yaml")
  backup_dir="$install_dir/backups/$(date -u +%Y%m%dT%H%M%SZ)-pre-direct-http"
  old_server_id="$(python3 "$helper" server-id --identity-file "$install_dir/data/server/server-identity.json")" || \
    fail 'Cannot read the existing Server identity before upgrade.'
  old_profiles="$(awk -F= '$1 == "HERMES_LINK_PROFILE_IDS" {print $2; exit}' "$install_dir/.env")"

  "${old_compose[@]}" stop || fail 'Could not stop the managed runtime for a consistent upgrade backup.'
  if ! {
    install -d -m 0700 "$backup_dir/config"
    cp -a "$install_dir/.env" "$install_dir/compose.yaml" "$install_dir/.env.example" "$backup_dir/config/"
    cp -a "$install_dir/bin" "$backup_dir/config/bin"
    legacy_proxy_file="$(find "$install_dir" -maxdepth 1 -type f -iname 'caddyfile' -print -quit)"
    if [[ -n "$legacy_proxy_file" ]]; then cp -a "$legacy_proxy_file" "$backup_dir/config/legacy-proxy.conf"; fi
    if [[ -f "$install_dir/release-manifest.json" ]]; then cp -a "$install_dir/release-manifest.json" "$backup_dir/config/release-manifest.json"; fi
    tar -czf "$backup_dir/server-state.tar.gz" -C "$install_dir/data" server
  }; then
    "${old_compose[@]}" start >/dev/null 2>&1 || true
    fail 'Could not create a consistent upgrade backup.'
  fi

  local restore_needed=true
  restore_existing_installation() {
    [[ "$restore_needed" == true ]] || return 0
    docker compose --env-file "$install_dir/.env" --project-directory "$install_dir" -f "$install_dir/compose.yaml" down --remove-orphans >/dev/null 2>&1 || true
    cp -a "$backup_dir/config/." "$install_dir/"
    if [[ -d "$install_dir/data/server" ]]; then mv "$install_dir/data/server" "$backup_dir/failed-server-state"; fi
    tar -xzf "$backup_dir/server-state.tar.gz" -C "$install_dir/data"
    "${old_compose[@]}" up -d --remove-orphans >/dev/null
    restore_needed=false
  }

  if ! {
    cp -a "$stage_dir/compose.yaml" "$stage_dir/.env.example" "$install_dir/"
    cp -a "$stage_dir/bin/." "$install_dir/bin/"
    find "$install_dir" -maxdepth 1 -type f -iname 'caddyfile' -delete
    rm -f -- "$install_dir/release-manifest.json"
    set_existing_environment_value HERMES_LINK_VERSION "$version"
    set_existing_environment_value HERMES_LINK_IMAGE "$image"
    set_existing_environment_value HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL "$release_download_base_url"
    set_existing_environment_value HERMES_LINK_RELEASE_API_URL 'https://api.github.com/repos/yhvspm/hermes-link-server/releases/latest'
    set_existing_environment_value HERMES_LINK_PUBLIC_HOST "$public_host"
    set_existing_environment_value HERMES_LINK_PUBLIC_PORT "$public_port"
    set_existing_environment_value HERMES_LINK_PUBLIC_URL "$public_url"
    set_existing_environment_value HERMES_LINK_LISTEN_HOST "$listen_host"
    set_existing_environment_value HERMES_LINK_LISTEN_PORT "$listen_port"
    set_existing_environment_value HERMES_LINK_AGENT_HOME_HOST "$hermes_home"
    set_existing_environment_value HERMES_LINK_INTERNAL_ENV_FILE "$agent_credential_file"
    set_existing_environment_value HERMES_LINK_MOBILE_ENV_FILE "$mobile_credential_file"
    set_existing_environment_value HERMES_LINK_FIREWALL_MANAGED '0'
    remove_existing_environment_value HERMES_LINK_PROXY_MODE
    remove_existing_environment_value HERMES_LINK_BRIDGE_PORT
    install -d -m 0700 "$install_dir/data/server"
    chown 10001:10001 "$install_dir/data/server"
    install -d -m 0750 "$install_dir/data/server/model-config"
    chown 0:10001 "$install_dir/data/server/model-config"
    docker compose --env-file "$install_dir/.env" --project-directory "$install_dir" -f "$install_dir/compose.yaml" up -d --pull never --remove-orphans
    for _ in {1..30}; do
      curl --fail --silent --max-time 3 "http://127.0.0.1:$listen_port/health" >/dev/null && break
      sleep 2
    done
    curl --fail --silent --max-time 3 "http://127.0.0.1:$listen_port/health" >/dev/null
    [[ "$(python3 "$helper" server-id --identity-file "$install_dir/data/server/server-identity.json")" == "$old_server_id" ]]
    [[ "$(awk -F= '$1 == "HERMES_LINK_PROFILE_IDS" {print $2; exit}' "$install_dir/.env")" == "$old_profiles" ]]
  }; then
    restore_existing_installation
    fail 'Local-source upgrade failed and the previous installation was restored.'
  fi
  restore_needed=false
  note "Local-source upgrade completed. Server identity and Profiles were retained; App URL is $public_url."
}

import_release_image_archive() {
  [[ -n "$release_manifest" ]] || fail 'OCI image archive fallback requires a verified release manifest.'
  [[ "$(uname -m)" == 'x86_64' || "$(uname -m)" == 'amd64' ]] || \
    fail 'OCI image archive fallback is currently available only on Linux amd64; restore GHCR pull connectivity for this host.'
  command -v ctr >/dev/null 2>&1 || \
    fail 'OCI image archive fallback requires the containerd ctr command used by Docker Engine.'
  local archive_name=''
  local archive_path=''
  archive_name="$("$python_bin" "$release_manifest_helper" image-archive \
    --manifest "$release_manifest" --version "$version" \
    --image-repository "$DEFAULT_IMAGE_REPOSITORY")" || \
    fail 'Release manifest does not provide a valid OCI image archive.'
  archive_path="$stage_dir/$archive_name"
  note 'GHCR image pull failed; downloading the manifest-verified OCI image archive from GitHub Release.'
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$release_download_base_url/v$version/$archive_name" -o "$archive_path" || \
    fail 'Could not download the OCI image archive fallback.'
  "$python_bin" "$release_manifest_helper" verify-image-archive \
    --manifest "$release_manifest" --version "$version" \
    --image-repository "$DEFAULT_IMAGE_REPOSITORY" --file "$archive_path" || \
    fail 'OCI image archive integrity verification failed.'
  ctr -n moby images import --base-name "$DEFAULT_IMAGE_REPOSITORY" --digests \
    --index-name "$image" --platform linux/amd64 "$archive_path" || \
    fail 'Could not import the verified OCI image archive into Docker containerd.'
  docker image inspect "$image" >/dev/null || \
    fail 'The imported OCI image is unavailable under the verified immutable digest.'
  image_loaded_from_archive=true
}

pull_or_import_server_image() {
  if docker pull "$image"; then
    return
  fi
  import_release_image_archive
}

resolve_endpoint() {
  local resolved=''
  while true; do
    if [[ -n "$public_url_input" ]]; then
      resolved="$("$python_bin" "$helper" endpoint --url "$public_url_input" --port "$public_port" 2>&1)" || true
    else
      if [[ -z "$public_host" ]]; then
        local detected_host=''
        if command -v ip >/dev/null 2>&1; then
          detected_host="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (index = 1; index <= NF; index++) if ($index == "src") { print $(index + 1); exit }}')"
        fi
        public_host="$(prompt_value '请输入 App 可访问的 IP 或域名' "$detected_host")" || \
          fail "Pass --host or --public-url when no terminal is available"
      fi
      if [[ -z "$public_port" ]]; then
        public_port="$(prompt_value '请输入公网 HTTP 端口' '18766')" || \
          fail "Pass --public-port when no terminal is available"
      fi
      resolved="$("$python_bin" "$helper" endpoint --host "$public_host" --port "$public_port" --scheme http 2>&1)" || true
    fi
    if [[ "$resolved" == *$'\t'* ]]; then
      IFS=$'\t' read -r public_host public_port public_url public_scheme <<< "$resolved"
      return
    fi
    printf '%s\n' "$resolved" >&2
    public_host=''
    public_url_input=''
    public_port=''
  done
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

resolve_listener() {
  if [[ -z "$listen_port" ]]; then
    if [[ "$public_scheme" == 'http' ]]; then listen_port="$public_port"; else listen_port='18766'; fi
  fi
  if [[ ! "$listen_port" =~ ^[0-9]+$ ]] || (( 10#$listen_port < 1024 || 10#$listen_port > 65535 )); then
    fail "--listen-port must be an unprivileged TCP port in 1024..65535"
  fi
  if [[ -z "$listen_host" ]]; then
    if [[ "$public_scheme" == 'http' ]]; then listen_host='0.0.0.0'; else listen_host='127.0.0.1'; fi
  fi
  [[ "$listen_host" == '127.0.0.1' || "$listen_host" == '0.0.0.0' ]] || \
    fail "--listen-host must be 127.0.0.1 or 0.0.0.0"
  if [[ "$dry_run" == false ]] && ! port_is_free "$listen_port"; then
    local existing_listener_port=''
    if [[ "$existing_install" == true && "$upgrade_existing" == true ]]; then
      existing_listener_port="$(awk -F= '$1 == "HERMES_LINK_LISTEN_PORT" {print $2; exit}' "$install_dir/.env")"
    fi
    [[ "$existing_listener_port" == "$listen_port" ]] || \
      fail "Server HTTP listener port $listen_port is already in use"
  fi
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
  agent_home="$(getent passwd "$agent_user" 2>/dev/null | cut -d: -f6 || true)"
  if [[ -z "$agent_home" && "$dry_run" == true ]]; then
    agent_home="/home/$agent_user"
    if [[ "$agent_user" == 'root' ]]; then agent_home='/root'; fi
  fi
  [[ -n "$agent_home" ]] || fail "Cannot determine the home directory for $agent_user"
  if [[ -z "$hermes_home" ]]; then
    hermes_home="$agent_home/.hermes"
  fi
  [[ "$hermes_home" == /* ]] || fail '--hermes-home must be an absolute path'
}

validate_reused_agent_credential() {
  [[ -n "$reuse_agent_credential" ]] || return 0
  [[ -f "$reuse_agent_credential" && ! -L "$reuse_agent_credential" ]] || fail "--reuse-agent-credential must be a regular file"
  local ownership=''
  ownership="$(stat -c '%u %a' -- "$reuse_agent_credential")" || fail "Cannot inspect --reuse-agent-credential"
  [[ "$ownership" == '0 600' ]] || fail "--reuse-agent-credential must be owned by root with mode 0600"
  grep -q '^HERMES_LINK_AGENT_TOKEN=.' -- "$reuse_agent_credential" || fail "--reuse-agent-credential does not contain a usable Agent credential"
}

ensure_mobile_api_credential() {
  local credential_file="$1"
  if [[ -f "$credential_file" ]]; then
    local ownership=''
    ownership="$(stat -c '%u %a' -- "$credential_file")" || fail 'Cannot inspect the mobile API credential file.'
    [[ "$ownership" == '0 600' ]] || fail 'The mobile API credential file must be owned by root with mode 0600.'
    grep -q '^HERMES_LINK_MOBILE_API_TOKEN=.' -- "$credential_file" || \
      fail 'The mobile API credential file does not contain a usable token.'
    return
  fi
  install -d -m 0700 "$(dirname -- "$credential_file")"
  local token=''
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" || fail 'Could not generate the mobile API credential.'
  printf 'HERMES_LINK_MOBILE_API_TOKEN=%s\n' "$token" | install -m 0600 /dev/stdin "$credential_file"
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
  [[ -n "$state_import_dir" ]] || return 0
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
  [[ -n "$state_import_dir" ]] || return 0
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
resolve_listener
resolve_agent_context
validate_reused_agent_credential
validate_state_import_dir

agent_credential_file="$INTERNAL_CREDENTIAL_FILE"
if [[ -n "$reuse_agent_credential" ]]; then
  agent_credential_file="$reuse_agent_credential"
elif [[ "$agent_service_scope" == 'user' ]]; then
  agent_credential_file="$agent_home/.config/hermes-link-server/internal-agent.env"
fi
mobile_credential_file="$MOBILE_CREDENTIAL_FILE"

if [[ "$existing_install" == true && "$upgrade_existing" == true ]]; then
  if [[ "$dry_run" == true ]]; then
    note "DRY RUN: verify release $version and bootstrap the managed update without changing Server identity or pairing state."
    exit 0
  fi
  [[ "${EUID}" -eq 0 ]] || fail "Run the installer as root, for example with sudo."
  if [[ -n "$source_dir" ]]; then
    ensure_mobile_api_credential "$mobile_credential_file"
    migrate_local_existing_installation
    exit
  fi
  note "Bootstrapping the verified update command for the managed installation at $install_dir."
  install -m 0755 "$stage_dir/bin/hermes-link" "$install_dir/bin/hermes-link"
  install -m 0755 "$stage_dir/bin/lib/deployment_helpers.py" "$install_dir/bin/lib/deployment_helpers.py"
  install -m 0755 "$stage_dir/bin/lib/release_manifest.py" "$install_dir/bin/lib/release_manifest.py"
  "$install_dir/bin/hermes-link" update --version "$version"
  exit
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
  note "DRY RUN: start the Server HTTP listener on $listen_host:$listen_port."
  if [[ "$public_scheme" == 'http' ]]; then
    note "DRY RUN: App connects directly to $public_url without TLS; use only a trusted network."
  else
    note "DRY RUN: external HTTPS proxy is user-managed and must route to http://$listen_host:$listen_port."
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
install -d -m 0750 "$install_dir/data/server/model-config"
chown 0:10001 "$install_dir/data/server/model-config"
install -d -m 0700 "$install_dir/backups"

import_server_state
ensure_mobile_api_credential "$mobile_credential_file"
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
  printf 'HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL=%s\n' "$release_download_base_url"
  printf 'HERMES_LINK_RELEASE_API_URL=https://api.github.com/repos/yhvspm/hermes-link-server/releases/latest\n'
  printf 'HERMES_LINK_PUBLIC_HOST=%s\n' "$public_host"
  printf 'HERMES_LINK_PUBLIC_PORT=%s\n' "$public_port"
  printf 'HERMES_LINK_PUBLIC_URL=%s\n' "$public_url"
  printf 'HERMES_LINK_LISTEN_HOST=%s\n' "$listen_host"
  printf 'HERMES_LINK_LISTEN_PORT=%s\n' "$listen_port"
  printf 'HERMES_LINK_AGENT_HOME_HOST=%s\n' "$hermes_home"
  printf 'HERMES_LINK_PROFILE_IDS=%s\n' "$profile_list"
  printf 'HERMES_LINK_INTERNAL_ENV_FILE=%s\n' "$agent_credential_file"
  printf 'HERMES_LINK_MOBILE_ENV_FILE=%s\n' "$mobile_credential_file"
  printf 'HERMES_LINK_FIREWALL_MANAGED=0\n'
} > "$environment_tmp"
install -m 0600 "$environment_tmp" "$install_dir/.env"
rm -f -- "$environment_tmp"

compose=(docker compose --env-file "$install_dir/.env" --project-directory "$install_dir" -f "$install_dir/compose.yaml")
if [[ "$skip_image_pull" == true ]]; then
  docker image inspect "$image" >/dev/null || fail "Local Server image is unavailable: $image"
else
  pull_or_import_server_image
fi
if [[ "$image_loaded_from_archive" == true ]]; then
  "${compose[@]}" up -d --pull never --remove-orphans
else
  "${compose[@]}" up -d --remove-orphans
fi

wait_for_local_health() {
  local attempt
  for attempt in {1..30}; do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$listen_port/health" >/dev/null; then
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
server_info="$(curl --fail --silent --max-time 5 "http://127.0.0.1:$listen_port/hermes-link/v1/server-info")"
IFS=$'\t' read -r gateway_state active_agents server_id cloud_multi_binding <<< "$(printf '%s' "$server_info" | "$python_bin" "$install_dir/bin/lib/deployment_helpers.py" server-info)"
[[ -n "$server_id" ]] || fail 'Server identity was not created in persistent state'

ln -s "$install_dir/bin/hermes-link" /usr/local/bin/hermes-link
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  if [[ "$listen_host" == '0.0.0.0' ]]; then
    note "Firewall is active. Allow TCP $listen_port yourself if the App connects from another device; the installer did not change firewall rules."
  fi
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
if [[ "$public_scheme" == 'http' ]]; then
  note 'Transport    ! HTTP is unencrypted; use only a trusted network'
else
  note 'Transport    ✓ External HTTPS is user-managed'
fi
if [[ "$cloud_multi_binding" == 'true' ]]; then note 'Cloud V3     ✓ Supported'; else note 'Cloud V3     ! Identity capability not reported'; fi
note ''
note 'App 地址：'
note "$public_url"
note ''
note '下一步：'
note '打开 Hermes Link App → 设置 → 服务器 → 扫码配置'
"$install_dir/bin/hermes-link" pair || note '二维码生成失败；运行 sudo hermes-link pair 重试。'
