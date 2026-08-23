"""Hermes Server-owned Cloud identity and installation configuration.

The private Ed25519 key is generated and stored by the user's Hermes Server.
Only the server id and public key are returned to the mobile client. Cloud
notification configuration contains identifiers only and never API tokens.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover - deployment configuration failure
    serialization = None
    Ed25519PrivateKey = Any  # type: ignore[assignment,misc]


SERVER_ID_PATTERN = re.compile(r"^server_[A-Za-z0-9]{32}$")
INSTALLATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ATTESTATION_NONCE_PATTERN = re.compile(r"^att_[A-Za-z0-9_-]{24,128}$")
ATTESTATION_TTL_SECONDS = 300


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _validate_server_id(value: str) -> str:
    server_id = str(value or "").strip()
    if not SERVER_ID_PATTERN.fullmatch(server_id):
        raise ValueError("server_id is invalid")
    return server_id


def _validate_public_key(value: str) -> str:
    public_key = str(value or "").strip()
    try:
        padding = "=" * (-len(public_key) % 4)
        decoded = base64.urlsafe_b64decode(public_key + padding)
    except (ValueError, TypeError) as exc:
        raise ValueError("server public key is invalid") from exc
    if len(decoded) != 32:
        raise ValueError("server public key is invalid")
    return public_key


def _validate_cloud_url(value: object) -> str:
    cloud_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(cloud_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("cloud_url must be an HTTPS origin without credentials or query data")
    return cloud_url


def _validate_installation_id(value: object) -> str:
    installation_id = str(value or "").strip()
    if not INSTALLATION_ID_PATTERN.fullmatch(installation_id):
        raise ValueError("installation_id is invalid")
    return installation_id


def _normalize_profiles(values: object) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("profiles must be an array")
    profiles: list[str] = []
    for value in values:
        profile_id = str(value or "").strip()
        if not PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise ValueError("profile_id is invalid")
        if profile_id not in profiles:
            profiles.append(profile_id)
    if not profiles:
        raise ValueError("at least one profile is required")
    return profiles


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sign_attestation(private_key_pem: str, payload: Mapping[str, Any]) -> str:
    if serialization is None:
        raise RuntimeError("Cloud V2 identity requires cryptography")
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Cloud attestation key must be Ed25519")
    return "ed25519:" + _base64url(private_key.sign(_canonical_json(payload)))


def _identity_path() -> Path:
    configured = os.environ.get("HERMES_LINK_SERVER_IDENTITY_FILE", "").strip()
    return Path(configured).expanduser() if configured else Path("~/.hermes/hermes_link_server_identity.json").expanduser()


def _config_path() -> Path:
    configured = os.environ.get("HERMES_LINK_CLOUD_CONFIG_FILE", "").strip()
    return Path(configured).expanduser() if configured else Path("~/.hermes/hermes_link_cloud_config.json").expanduser()


def _write_restricted(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def get_or_create_identity() -> dict[str, str]:
    path = _identity_path()
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            server_id = _validate_server_id(str(value["server_id"]))
            private_key_pem = str(value["private_key_pem"])
            public_key = _validate_public_key(str(value["public_key"]))
            if not private_key_pem:
                raise ValueError("private key missing")
            return {
                "schema_version": "2",
                "server_id": server_id,
                "public_key": public_key,
                "private_key_pem": private_key_pem,
            }
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Hermes Server Cloud identity file is invalid") from exc
    if serialization is None:
        raise RuntimeError("Cloud V2 identity requires cryptography")
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    identity = {
        "schema_version": "2",
        "server_id": f"server_{secrets.token_hex(16)}",
        "public_key": _base64url(public_key),
        "private_key_pem": private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8"),
    }
    _write_restricted(path, identity)
    return identity


def public_identity() -> dict[str, str]:
    identity = get_or_create_identity()
    return {
        "schema_version": "2",
        "server_id": identity["server_id"],
        "public_key": identity["public_key"],
    }


def configure_cloud(payload: Mapping[str, Any]) -> dict[str, Any]:
    cloud_url = _validate_cloud_url(payload.get("cloud_url"))
    installation_id = _validate_installation_id(payload.get("installation_id"))
    identity = get_or_create_identity()
    requested_server_id = str(payload.get("server_id", identity["server_id"]))
    server_id = _validate_server_id(requested_server_id)
    if server_id != identity["server_id"]:
        raise ValueError("server_id does not match this Hermes Server")
    _write_restricted(
        _config_path(),
        {
            "schema_version": 2,
            "cloud_url": cloud_url,
            "installation_id": installation_id,
            "server_id": server_id,
        },
    )
    return {
        "ok": True,
        "schema_version": 2,
        "cloud_url": cloud_url,
        "installation_id": installation_id,
        "server_id": server_id,
    }


def create_cloud_binding_attestation(
    payload: Mapping[str, Any],
    profiles: list[str],
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Sign a short-lived, scoped Cloud binding assertion for one device.

    The caller supplies only the target Cloud URL and device installation id.
    The Server derives the Profile allowlist from the authenticated device
    token, signs the complete assertion, and never returns its private key.
    """

    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("Cloud attestation schema_version is unsupported")
    cloud_url = _validate_cloud_url(payload.get("cloud_url"))
    installation_id = _validate_installation_id(payload.get("installation_id"))
    normalized_profiles = _normalize_profiles(profiles)
    issued_at = int(time.time() if now is None else now)
    identity = get_or_create_identity()
    attestation = {
        "schema_version": 1,
        "server_id": identity["server_id"],
        "public_key": identity["public_key"],
        "installation_id": installation_id,
        "cloud_url": cloud_url,
        "profiles": normalized_profiles,
        "issued_at": issued_at,
        "expires_at": issued_at + ATTESTATION_TTL_SECONDS,
        "nonce": f"att_{secrets.token_urlsafe(24)}",
    }
    if not ATTESTATION_NONCE_PATTERN.fullmatch(str(attestation["nonce"])):
        raise RuntimeError("Cloud attestation nonce generation failed")
    return {
        "schema_version": 1,
        "attestation": attestation,
        "attestation_signature": _sign_attestation(identity["private_key_pem"], attestation),
    }


def clear_cloud_config() -> dict[str, bool]:
    """Remove only this Server's optional Cloud delivery configuration."""

    try:
        _config_path().unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


def load_cloud_config() -> dict[str, str]:
    try:
        value = json.loads(_config_path().read_text(encoding="utf-8"))
        return {
            "cloud_url": str(value["cloud_url"]),
            "installation_id": str(value["installation_id"]),
            "server_id": _validate_server_id(str(value["server_id"])),
        }
    except (OSError, KeyError, TypeError, ValueError):
        return {}
