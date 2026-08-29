"""Write non-secret Hermes model configuration snapshots for the Bridge.

The exporter is intentionally a separate, network-isolated Server component.
It can read the Agent-owned metadata directory as root, but it writes only a
small allowlist of non-secret fields for the unprivileged Bridge to serve.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml


PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MODEL_FIELD_LIMIT = 200
PROVIDER_FIELD_LIMIT = 100
AGENT_FIELD_LIMIT = 20


def _profile_ids(value: str) -> list[str]:
    profile_ids: list[str] = []
    for raw_profile_id in value.split(","):
        profile_id = raw_profile_id.strip()
        if (
            profile_id
            and PROFILE_ID_PATTERN.fullmatch(profile_id)
            and profile_id not in profile_ids
        ):
            profile_ids.append(profile_id)
    return profile_ids or ["default"]


def _config_path(hermes_home: Path, profile_id: str) -> Path:
    if profile_id == "default":
        return hermes_home / "config.yaml"
    return hermes_home / "profiles" / profile_id / "config.yaml"


def _safe_text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _public_model_config(
    profile_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    model_config = payload.get("model", {})
    if isinstance(model_config, Mapping):
        model = _safe_text(
            model_config.get("default") or model_config.get("name"),
            MODEL_FIELD_LIMIT,
        )
        provider = _safe_text(model_config.get("provider"), PROVIDER_FIELD_LIMIT)
        max_tokens = model_config.get("max_tokens", 0)
    else:
        model = _safe_text(model_config, MODEL_FIELD_LIMIT)
        provider = ""
        max_tokens = 0
    agent_config = payload.get("agent", {})
    if not isinstance(agent_config, Mapping):
        agent_config = {}
    return {
        "profile": profile_id,
        "model": model,
        "provider": provider,
        "max_tokens": (
            max_tokens
            if isinstance(max_tokens, int) and not isinstance(max_tokens, bool)
            else 0
        ),
        "reasoning_effort": _safe_text(
            agent_config.get("reasoning_effort"), AGENT_FIELD_LIMIT
        ),
        "service_tier": _safe_text(agent_config.get("service_tier"), AGENT_FIELD_LIMIT),
    }


def _snapshot_path(output_directory: Path, profile_id: str) -> Path:
    if not PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise ValueError("invalid Hermes profile")
    return output_directory / f"{profile_id}.json"


def _prepare_output_directory(
    output_directory: Path,
    *,
    owner_uid: int | None,
    owner_gid: int | None,
) -> None:
    output_directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chmod(output_directory, 0o750)
    if owner_uid is not None and owner_gid is not None:
        os.chown(output_directory, owner_uid, owner_gid)


def _write_snapshot(
    output_directory: Path,
    profile_id: str,
    payload: Mapping[str, object],
    *,
    owner_uid: int | None,
    owner_gid: int | None,
) -> None:
    destination = _snapshot_path(output_directory, profile_id)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{profile_id}.", suffix=".json", dir=output_directory
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o640)
        if owner_uid is not None and owner_gid is not None and hasattr(os, "chown"):
            os.chown(temporary_path, owner_uid, owner_gid)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _remove_snapshot(output_directory: Path, profile_id: str) -> None:
    try:
        _snapshot_path(output_directory, profile_id).unlink()
    except FileNotFoundError:
        return


def sync_model_config_snapshots(
    hermes_home: Path,
    output_directory: Path,
    profile_ids: Iterable[str],
    *,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> None:
    """Atomically refresh one safe JSON snapshot for every exposed Profile."""

    _prepare_output_directory(
        output_directory,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    for profile_id in profile_ids:
        if not PROFILE_ID_PATTERN.fullmatch(profile_id):
            continue
        try:
            with _config_path(hermes_home, profile_id).open(
                "r", encoding="utf-8"
            ) as handle:
                source_payload = yaml.safe_load(handle) or {}
            if not isinstance(source_payload, Mapping):
                raise ValueError("Hermes configuration must be a mapping")
            _write_snapshot(
                output_directory,
                profile_id,
                _public_model_config(profile_id, source_payload),
                owner_uid=owner_uid,
                owner_gid=owner_gid,
            )
        except (OSError, ValueError, yaml.YAMLError):
            _remove_snapshot(output_directory, profile_id)


def _environment_integer(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value >= minimum else default


def main() -> int:
    hermes_home = Path(os.environ.get("HERMES_HOME", "/root/.hermes"))
    output_directory = Path(
        os.environ.get(
            "HERMES_LINK_MODEL_CONFIG_DIR",
            "/var/lib/hermes-link-server/model-config",
        )
    )
    profile_ids = _profile_ids(os.environ.get("HERMES_LINK_PROFILE_IDS", ""))
    interval_seconds = _environment_integer(
        "HERMES_LINK_MODEL_CONFIG_EXPORT_INTERVAL_SECONDS", 30, 5
    )
    owner_uid = _environment_integer("HERMES_LINK_MODEL_CONFIG_UID", 0, 0)
    owner_gid = _environment_integer("HERMES_LINK_MODEL_CONFIG_GID", 10001, 0)
    while True:
        sync_model_config_snapshots(
            hermes_home,
            output_directory,
            profile_ids,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
