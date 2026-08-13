"""Compatibility boundary translating stable Hermes Link operations to Hermes Agent APIs."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request, urlopen

from hermes_link.pairing.store import authenticate_device_token


OPERATION_PATHS = {
    "chat": "/v1/chat/completions",
    "sessions": "/api/sessions",
    "models": "/v1/models",
    "modelOptions": "/api/model/options",
    "modelConfig": "/api/model/config",
    "jobs": "/api/jobs",
}
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
PROFILE_PROTOCOL_PATTERN = re.compile(r"^/hermes-link/v1/profiles/([^/]+)(/.*)$")
PROTOCOL_EXACT_PATHS = {
    "/hermes-link/v1/models": "/v1/models",
    "/hermes-link/v1/models/config": "/api/model/config",
    "/hermes-link/v1/models/options": "/api/model/options",
    "/hermes-link/v1/chat/completions": "/v1/chat/completions",
    "/hermes-link/v1/chat/cancel": "/api/mobile/chat/cancel",
    "/hermes-link/v1/pairing": "/api/mobile/pair",
    "/hermes-link/v1/pairing/device": "/api/mobile/pair/device",
    "/hermes-link/v1/cloud/identity": "/api/mobile/cloud/identity",
    "/hermes-link/v1/cloud/configure": "/api/mobile/cloud/configure",
    "/hermes-link/v1/cloud/binding": "/api/mobile/cloud/binding",
    "/hermes-link/v1/notifications/direct": "/api/mobile/notifications/stream",
}
PROTOCOL_PREFIX_PATHS = {
    "/hermes-link/v1/jobs": "/api/jobs",
    "/hermes-link/v1/sessions": "/api/sessions",
    "/hermes-link/v1/notifications/devices": "/api/mobile/push/devices",
}


class DeviceAuthorizationError(Exception):
    """A mobile device token cannot be used for the requested Server operation."""

    def __init__(self, message: str, *, status: int, code: str):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def forward_agent_headers(headers: object) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for name in (
        "Authorization",
        "Content-Type",
        "Last-Event-ID",
        "X-Hermes-Session-Id",
    ):
        value = headers.get(name)  # type: ignore[attr-defined]
        if value:
            forwarded[name] = value
    return forwarded


def _bearer_token(headers: object) -> str:
    value = headers.get("Authorization")  # type: ignore[attr-defined]
    if not value:
        return ""
    scheme, separator, token = str(value).partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return ""
    return token.strip()


def _server_agent_token() -> str:
    """Read the Server-only Agent credential without exposing its name to clients."""
    return (
        os.environ.get("HERMES_LINK_AGENT_TOKEN", "").strip()
        or os.environ.get("HERMES_LINK_MOBILE_API_TOKEN", "").strip()
    )


def _profile_id_for_protocol_path(protocol_path: str) -> str:
    match = PROFILE_PROTOCOL_PATTERN.fullmatch(protocol_path)
    if match is None:
        return "default"
    profile_id = unquote(match.group(1)).strip()
    return profile_id if PROFILE_ID_PATTERN.fullmatch(profile_id) else ""


def prepare_agent_headers(
    headers: object,
    protocol_path: str,
    *,
    pairing_path: Path | str | None = None,
    upstream_token: str | None = None,
) -> dict[str, str]:
    """Authorize paired devices and translate them to the Agent API key.

    Hermes Agent remains the compatibility target and only understands its
    configured API key. A paired App receives a scoped ``hmd_`` token, so the
    Server validates it locally and uses its server-only Agent key upstream.
    Legacy API tokens continue to pass through.
    """

    forwarded = forward_agent_headers(headers)
    token = _bearer_token(headers)
    if not token.startswith("hmd_"):
        return forwarded

    profile_id = _profile_id_for_protocol_path(protocol_path)
    if not profile_id or not authenticate_device_token(
        token,
        profile_id,
        path=pairing_path,
    ):
        raise DeviceAuthorizationError(
            "Invalid or revoked Hermes Link device token",
            status=401,
            code="device_token_invalid",
        )

    resolved_upstream_token = (
        str(upstream_token).strip()
        if upstream_token is not None
        else _server_agent_token()
    )
    if len(resolved_upstream_token) < 8:
        raise DeviceAuthorizationError(
            "Server Agent API token is not configured",
            status=503,
            code="device_token_upstream_unavailable",
        )
    forwarded["Authorization"] = f"Bearer {resolved_upstream_token}"
    return forwarded


def protocol_to_agent_path(protocol_path: str) -> str | None:
    profile_prefix = ""
    normalized_path = protocol_path
    profile_match = PROFILE_PROTOCOL_PATTERN.fullmatch(protocol_path)
    if profile_match:
        profile_id = unquote(profile_match.group(1)).strip()
        if not PROFILE_ID_PATTERN.fullmatch(profile_id):
            return None
        profile_prefix = f"/p/{quote(profile_id, safe='')}"
        normalized_path = f"/hermes-link/v1{profile_match.group(2)}"
    exact = PROTOCOL_EXACT_PATHS.get(normalized_path)
    if exact is not None:
        return f"{profile_prefix}{exact}"
    for public_prefix, internal_prefix in PROTOCOL_PREFIX_PATHS.items():
        if normalized_path == public_prefix or normalized_path.startswith(f"{public_prefix}/"):
            return f"{profile_prefix}{internal_prefix}{normalized_path[len(public_prefix):]}"
    return None


class HermesAgentAdapter:
    """Only this package may know Hermes Agent endpoint and version details."""

    def __init__(self, base_url: str = "http://127.0.0.1:8642", *, timeout: float = 30):
        normalized = str(base_url).rstrip("/")
        if normalized not in {
            "http://127.0.0.1:8642",
            "http://localhost:8642",
            "http://127.0.0.1:8080",
            "http://localhost:8080",
        }:
            raise ValueError("Hermes Agent adapter must use an approved loopback origin")
        self.base_url = normalized
        self.timeout = float(timeout)

    def request(
        self,
        operation: str,
        *,
        method: str = "GET",
        profile_id: str = "default",
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        if operation not in OPERATION_PATHS:
            raise ValueError("unsupported Hermes Agent operation")
        profile = str(profile_id or "default").strip()
        path = OPERATION_PATHS[operation]
        if profile != "default":
            path = f"/p/{profile}{path}"
        if query:
            path = f"{path}?{urlencode(dict(query))}"
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(f"{self.base_url}{path}", data=payload, headers=headers, method=method)
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read(4 * 1024 * 1024)
        result = json.loads(raw.decode("utf-8")) if raw else {}
        return result if isinstance(result, dict) else {"data": result}

    def runtime_status(self, *, token: str | None = None) -> dict[str, object]:
        """Return the small, public-safe runtime summary for Server clients.

        The detailed Agent response is an implementation contract.  Keep its
        shape inside the compatibility adapter and publish only the status
        fields that the Hermes Link protocol documents.
        """
        resolved_token = (
            str(token).strip()
            if token is not None
            else _server_agent_token()
        )
        if len(resolved_token) < 8:
            return {
                "gateway_state": "unavailable",
                "active_agents": 0,
                "gateway_busy": False,
                "hermes_version": "unknown",
            }

        request = Request(
            f"{self.base_url}/health/detailed",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {resolved_token}",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(64 * 1024)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                "gateway_state": "unavailable",
                "active_agents": 0,
                "gateway_busy": False,
                "hermes_version": "unknown",
            }

        if not isinstance(payload, dict):
            return {
                "gateway_state": "unavailable",
                "active_agents": 0,
                "gateway_busy": False,
                "hermes_version": "unknown",
            }

        raw_active_agents = payload.get("active_agents", 0)
        active_agents = (
            raw_active_agents
            if isinstance(raw_active_agents, int)
            and not isinstance(raw_active_agents, bool)
            and raw_active_agents >= 0
            else 0
        )
        gateway_state = str(
            payload.get("gateway_state") or payload.get("status") or "ready"
        ).strip()
        return {
            "gateway_state": gateway_state or "ready",
            "active_agents": active_agents,
            "gateway_busy": bool(payload.get("gateway_busy", active_agents > 0)),
            "hermes_version": str(payload.get("version") or "unknown").strip() or "unknown",
        }
