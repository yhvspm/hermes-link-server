"""Cloud Protocol v2 HTTP sender; this module has no Cloud database dependency."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .events import validate_event

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover
    serialization = None
    Ed25519PrivateKey = None


EVENT_PATH = "/v1/events"
NOTIFICATION_COPY = {
    "chat.completed": "Chat completed",
    "job.completed": "Scheduled task completed",
    "job.failed": "Scheduled task failed",
}


class CloudTransportError(RuntimeError):
    pass


def _signature_message(timestamp: str, nonce: str, body: bytes) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(["POST", EVENT_PATH, timestamp, nonce, body_hash]).encode("utf-8")


def _sign(private_key_pem: str, timestamp: str, nonce: str, body: bytes) -> str:
    if serialization is None or Ed25519PrivateKey is None:
        raise RuntimeError("Cloud notifications require cryptography")
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Cloud event signing key must be Ed25519")
    signature = key.sign(_signature_message(timestamp, nonce, body))
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"ed25519:{encoded}"


class CloudEventSender:
    def __init__(self, base_url: str, server_id: str, private_key_pem: str, *, timeout: float = 15):
        parsed = urlparse(str(base_url).rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("base_url must be an HTTPS origin")
        self.base_url = str(base_url).rstrip("/")
        self.server_id = str(server_id)
        self.private_key_pem = private_key_pem
        self.timeout = max(3.0, min(float(timeout), 60.0))

    def publish(self, payload: Mapping[str, Any], installation_id: str) -> dict[str, Any]:
        event = validate_event(payload)
        event_type = str(event["event_type"])
        if event_type != "chat.completed" and not str(event.get("run_id", "")):
            raise ValueError("run_id is required for Cloud job events")
        data = {
            "event_type": event_type,
            "event_id": str(event["event_id"]),
            "profile_id": str(event["profile_id"]),
            "server_id": self.server_id,
        }
        for name in ("session_id", "job_id"):
            if str(event.get(name, "")):
                data[name] = str(event[name])
        cloud_event: dict[str, Any] = {
            "schema_version": 2,
            "server_id": self.server_id,
            "event_id": str(event["event_id"]),
            "event_type": event_type,
            "profile_id": str(event["profile_id"]),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "dedupe_key": str(event["dedupe_key"]),
            "title": "Hermes Link",
            "body": NOTIFICATION_COPY[event_type],
            "data": data,
            "installation_id": str(installation_id),
        }
        for name in ("session_id", "job_id", "run_id"):
            if str(event.get(name, "")):
                cloud_event[name] = str(event[name])
        body = json.dumps(cloud_event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        nonce = f"n_{secrets.token_urlsafe(24)}"
        request = Request(
            f"{self.base_url}{EVENT_PATH}",
            data=body,
            headers={
                "X-Hermes-Link-Server": self.server_id,
                "X-Hermes-Link-Timestamp": timestamp,
                "X-Hermes-Link-Nonce": nonce,
                "X-Hermes-Link-Signature": _sign(self.private_key_pem, timestamp, nonce, body),
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(65536)
            decoded = json.loads(raw.decode("utf-8")) if raw else {}
            return decoded if isinstance(decoded, dict) else {}
        except HTTPError as exc:
            raise CloudTransportError(f"Cloud returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise CloudTransportError("Cloud is unavailable or returned invalid data") from exc
