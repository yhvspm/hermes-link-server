"""One-time HTTPS pairing tickets for Hermes Link mobile setup.

The QR payload contains only a short-lived random code.  The corresponding
API token remains in this root-only SQLite database and is returned once over
the HTTPS exchange endpoint.  This module never logs or prints the token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


PAIRING_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
DEVICE_ID_PATTERN = re.compile(r"^dev_[A-Za-z0-9]{32}$")
DEVICE_TOKEN_PATTERN = re.compile(r"^hmd_[A-Za-z0-9_-]{32,128}$")
BASE_URL_PATTERN = re.compile(r"^https://[^/?#]+(?:/[^?#]*)?$")
DEFAULT_TTL_SECONDS = 600


class PairingError(ValueError):
    def __init__(self, message: str, *, status: int = 400, code: str = "pairing_invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class PairingTicket:
    pairing_url: str
    expires_at: int


def _db_path() -> Path:
    configured = os.environ.get("HERMES_LINK_PAIRING_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    return hermes_home / "hermes_link_pairing.db"


def _validate_base_url(base_url: str) -> str:
    normalized = str(base_url).strip().rstrip("/")
    if not BASE_URL_PATTERN.fullmatch(normalized) or "@" in normalized:
        raise PairingError("Pairing base URL must use HTTPS", code="pairing_url_invalid")
    return normalized


def _validate_code(code: str) -> str:
    normalized = str(code).strip()
    if not PAIRING_CODE_PATTERN.fullmatch(normalized):
        raise PairingError("Pairing code is invalid", code="pairing_invalid")
    return normalized


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_profiles(values: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        profile_id = str(value).strip()
        if profile_id and profile_id not in result and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", profile_id):
            result.append(profile_id)
    return result


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pairing_tickets (
            code_hash TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            api_token TEXT NOT NULL,
            api_token_hash TEXT,
            profiles_json TEXT NOT NULL DEFAULT '[]',
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(pairing_tickets)").fetchall()
    }
    if "api_token_hash" not in columns:
        connection.execute("ALTER TABLE pairing_tickets ADD COLUMN api_token_hash TEXT")
    if "profiles_json" not in columns:
        connection.execute("ALTER TABLE pairing_tickets ADD COLUMN profiles_json TEXT NOT NULL DEFAULT '[]'")
    legacy_rows = connection.execute(
        "SELECT code_hash, api_token FROM pairing_tickets "
        "WHERE (api_token_hash IS NULL OR api_token_hash = '') AND api_token <> ''"
    ).fetchall()
    for row in legacy_rows:
        connection.execute(
            "UPDATE pairing_tickets SET api_token_hash = ?, api_token = '' WHERE code_hash = ?",
            (_token_hash(str(row["api_token"])), str(row["code_hash"])),
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pairing_devices (
            device_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            base_url TEXT NOT NULL,
            profiles_json TEXT NOT NULL DEFAULT '[]',
            created_at INTEGER NOT NULL,
            last_used_at INTEGER NOT NULL,
            revoked_at INTEGER
        )
        """
    )
    device_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(pairing_devices)").fetchall()
    }
    if "profiles_json" not in device_columns:
        connection.execute(
            "ALTER TABLE pairing_devices ADD COLUMN profiles_json TEXT NOT NULL DEFAULT '[]'"
        )
    connection.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


class PairingStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else _db_path()

    def create_ticket(
        self,
        base_url: str,
        api_token: str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: int | None = None,
        profile_ids: Iterable[str] | None = None,
    ) -> PairingTicket:
        normalized_url = _validate_base_url(base_url)
        normalized_token = str(api_token).strip()
        if len(normalized_token) < 8 or len(normalized_token) > 4096:
            raise PairingError("Pairing API token is invalid", code="pairing_token_invalid")
        if not isinstance(ttl_seconds, int) or ttl_seconds < 30 or ttl_seconds > 3600:
            raise PairingError("Pairing TTL must be between 30 and 3600 seconds")

        issued_at = int(time.time() if now is None else now)
        expires_at = issued_at + ttl_seconds
        code = secrets.token_urlsafe(32)
        code_hash = _code_hash(code)
        profiles = _normalize_profiles(profile_ids)
        connection = _connect(self.path)
        try:
            connection.execute(
                "INSERT INTO pairing_tickets "
                "(code_hash, base_url, api_token, api_token_hash, profiles_json, created_at, expires_at, used_at) "
                "VALUES (?, ?, '', ?, ?, ?, ?, NULL)",
                (
                    code_hash,
                    normalized_url,
                    _token_hash(normalized_token),
                    json.dumps(profiles, ensure_ascii=False, separators=(",", ":")),
                    issued_at,
                    expires_at,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        pairing_url = (
            f"{normalized_url}/api/mobile/pair?code={quote(code, safe='')}&v=1"
        )
        return PairingTicket(pairing_url=pairing_url, expires_at=expires_at)

    def exchange(self, code: str, *, now: int | None = None) -> dict[str, object]:
        normalized_code = _validate_code(code)
        current_time = int(time.time() if now is None else now)
        connection = _connect(self.path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT base_url, profiles_json, expires_at, used_at "
                "FROM pairing_tickets WHERE code_hash = ?",
                (_code_hash(normalized_code),),
            ).fetchone()
            if row is None:
                raise PairingError("Pairing code is invalid", code="pairing_invalid")
            if row["used_at"] is not None:
                raise PairingError(
                    "Pairing code has already been used",
                    code="pairing_used",
                )
            if int(row["expires_at"]) <= current_time:
                raise PairingError("Pairing code has expired", code="pairing_expired")
            connection.execute(
                "UPDATE pairing_tickets SET used_at = ? WHERE code_hash = ?",
                (current_time, _code_hash(normalized_code)),
            )
            device_id = f"dev_{secrets.token_hex(16)}"
            device_token = f"hmd_{secrets.token_urlsafe(32)}"
            try:
                profiles = _normalize_profiles(json.loads(str(row["profiles_json"])))
            except (TypeError, ValueError):
                profiles = []
            connection.execute(
                """
                INSERT INTO pairing_devices (
                    device_id, token_hash, base_url, profiles_json,
                    created_at, last_used_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    device_id,
                    _token_hash(device_token),
                    str(row["base_url"]),
                    json.dumps(profiles, ensure_ascii=False, separators=(",", ":")),
                    current_time,
                    current_time,
                ),
            )
            connection.commit()
            return {
                "schema_version": 2,
                "base_url": str(row["base_url"]),
                "device_id": device_id,
                "device_token": device_token,
                "profiles": profiles,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def device_profile_ids(self, token: str) -> list[str] | None:
        """Return the authenticated device scope; an empty list means all Profiles."""

        normalized = str(token or "").strip()
        if not DEVICE_TOKEN_PATTERN.fullmatch(normalized):
            return None
        now = int(time.time())
        connection = _connect(self.path)
        try:
            row = connection.execute(
                "SELECT device_id, profiles_json FROM pairing_devices "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (_token_hash(normalized),),
            ).fetchone()
            if row is None:
                return None
            try:
                profiles = _normalize_profiles(json.loads(str(row["profiles_json"])))
            except (TypeError, ValueError):
                profiles = []
            connection.execute(
                "UPDATE pairing_devices SET last_used_at = ? WHERE device_id = ?",
                (now, str(row["device_id"])),
            )
            connection.commit()
            return profiles
        finally:
            connection.close()

    def authenticate_device_token(self, token: str, profile_id: str = "default") -> bool:
        profiles = self.device_profile_ids(token)
        if profiles is None:
            return False
        current_profile = str(profile_id or "default").strip() or "default"
        return not profiles or current_profile in profiles

    def revoke_device_token(self, token: str) -> bool:
        normalized = str(token or "").strip()
        if not DEVICE_TOKEN_PATTERN.fullmatch(normalized):
            return False
        connection = _connect(self.path)
        try:
            result = connection.execute(
                "UPDATE pairing_devices SET revoked_at = ? "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (int(time.time()), _token_hash(normalized)),
            )
            connection.commit()
            return result.rowcount > 0
        finally:
            connection.close()


def create_pairing_ticket(
    base_url: str,
    api_token: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    path: Path | str | None = None,
    profile_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    ticket = PairingStore(path).create_ticket(
        base_url,
        api_token,
        ttl_seconds=ttl_seconds,
        profile_ids=profile_ids,
    )
    return {
        "schema_version": 1,
        "pairing_url": ticket.pairing_url,
        "expires_at": ticket.expires_at,
    }


def exchange_pairing_code(code: str, *, path: Path | str | None = None) -> dict[str, object]:
    return PairingStore(path).exchange(code)


def authenticate_device_token(token: str, profile_id: str = "default", *, path: Path | str | None = None) -> bool:
    return PairingStore(path).authenticate_device_token(token, profile_id)


def device_profile_ids(token: str, *, path: Path | str | None = None) -> list[str] | None:
    return PairingStore(path).device_profile_ids(token)


def revoke_device_token(token: str, *, path: Path | str | None = None) -> bool:
    return PairingStore(path).revoke_device_token(token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Hermes Link one-time pairing URL")
    parser.add_argument("--base-url", required=True, help="Public HTTPS Hermes API URL")
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--db", default=None)
    parser.add_argument("--profiles", default="", help="Comma-separated Profile scope for the device token")
    parser.add_argument(
        "--token-env",
        default="HERMES_LINK_MOBILE_API_TOKEN",
        help="Environment variable containing the mobile API token",
    )
    parser.add_argument(
        "--qr",
        action="store_true",
        help="Render the short-lived pairing URL as an ASCII QR code without printing the URL",
    )
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"Missing {args.token_env}; token is never accepted as a command argument")
    result = create_pairing_ticket(
        args.base_url,
        token,
        ttl_seconds=args.ttl,
        path=args.db,
        profile_ids=[item.strip() for item in args.profiles.split(",") if item.strip()],
    )
    if args.qr:
        try:
            import qrcode
        except ImportError as error:
            raise SystemExit("QR support is unavailable; install the hermes-link-server package dependencies") from error
        qr = qrcode.QRCode(border=1)
        qr.add_data(str(result["pairing_url"]))
        qr.make(fit=True)
        print("Scan this short-lived pairing QR code in Hermes Link. Do not copy it to chat or logs.")
        qr.print_ascii(invert=True)
        print(f"Expires at Unix time: {result['expires_at']}")
        return
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
