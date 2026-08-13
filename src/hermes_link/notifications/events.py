"""Versioned Event Protocol v1 validation shared by DIRECT and Cloud senders."""

from __future__ import annotations

import re
from typing import Any, Mapping


ALLOWED_EVENT_TYPES = frozenset({"chat.completed", "job.completed", "job.failed"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
FORBIDDEN_FIELDS = frozenset(
    {
        "prompt",
        "messages",
        "response",
        "full_response",
        "api_token",
        "push_token",
        "private_key",
        "credentials",
        "click_url",
        "command",
        "file_path",
    }
)


def _identifier(payload: Mapping[str, Any], name: str, *, required: bool = True) -> str:
    value = str(payload.get(name, "")).strip()
    if not value and not required:
        return ""
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} is invalid")
    return value


def validate_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("event must be an object")
    forbidden = FORBIDDEN_FIELDS.intersection(str(key) for key in payload)
    if forbidden:
        raise ValueError("event contains forbidden sensitive fields")
    event_type = str(payload.get("event_type", "")).strip()
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("event_type is not allowed")
    event = {
        "event_id": _identifier(payload, "event_id"),
        "event_type": event_type,
        "profile_id": _identifier(payload, "profile_id"),
        "run_id": _identifier(payload, "run_id", required=False),
        "dedupe_key": _identifier(payload, "dedupe_key"),
    }
    if event_type == "chat.completed":
        event["session_id"] = _identifier(payload, "session_id")
    else:
        event["job_id"] = _identifier(payload, "job_id")
        event["session_id"] = _identifier(payload, "session_id", required=False)
    if "created_at" in payload:
        event["created_at"] = float(payload["created_at"])
    return event

