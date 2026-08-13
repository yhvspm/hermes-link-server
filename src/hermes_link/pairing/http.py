"""HTTP boundary helpers for Hermes Link pairing."""

from __future__ import annotations

from pathlib import Path

from hermes_link.pairing.store import PairingError, exchange_pairing_code


def exchange_pairing_payload(
    payload: object,
    *,
    pairing_path: Path | str | None = None,
) -> tuple[int, object]:
    """Exchange a pairing payload at the Server boundary, without Agent auth."""

    if not isinstance(payload, dict):
        return 400, {
            "error": {
                "message": "Pairing payload must be an object",
                "code": "pairing_invalid",
            }
        }
    if payload.get("schema_version", 1) != 1:
        return 400, {
            "error": {
                "message": "Unsupported pairing schema",
                "code": "pairing_schema_unsupported",
            }
        }
    code = payload.get("code")
    if not isinstance(code, str):
        return 400, {
            "error": {
                "message": "Pairing code is required",
                "code": "pairing_invalid",
            }
        }
    try:
        return 200, exchange_pairing_code(code, path=pairing_path)
    except PairingError as error:
        return error.status, {"error": {"message": str(error), "code": error.code}}
    except Exception:
        return 503, {
            "error": {
                "message": "Pairing service is unavailable",
                "code": "pairing_unavailable",
            }
        }
