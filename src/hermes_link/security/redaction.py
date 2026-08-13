"""Minimal redaction fallback for Server-owned diagnostic output."""

from __future__ import annotations

import re


_URL_CREDENTIALS = re.compile(r"(https?://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SENSITIVE_VALUE = re.compile(
    r"\b(api[_-]?(?:key|token)|access[_-]?token|token|password|secret|authorization)\b\s*([=:])\s*([^\s,;]+)",
    re.IGNORECASE,
)


def redact_sensitive_text(
    value: str,
    *,
    force: bool = False,
    redact_url_credentials: bool = False,
) -> str:
    """Redact credential-shaped fragments without depending on Hermes Agent code."""
    del force
    result = str(value)
    if redact_url_credentials:
        result = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", result)
    result = _BEARER.sub("Bearer [REDACTED]", result)
    return _SENSITIVE_VALUE.sub(r"\1\2[REDACTED]", result)
