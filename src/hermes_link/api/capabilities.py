"""Protocol capability document exposed to every Hermes Link client."""

from __future__ import annotations

from typing import Mapping

from hermes_link import __version__


DEFAULT_FEATURES: dict[str, bool] = {
    "chat": True,
    "sessions": True,
    "models": True,
    "jobs": True,
    "cron": True,
    "pairing": True,
    "executionTrace": True,
    "directNotifications": True,
    "cloudNotifications": True,
    "cloudMultiBinding": False,
    "chatAttachments": True,
}


def server_info(
    hermes_version: str,
    *,
    features: Mapping[str, bool] | None = None,
    runtime: Mapping[str, object] | None = None,
    server_id: str | None = None,
) -> dict[str, object]:
    resolved = dict(DEFAULT_FEATURES)
    if features:
        for name in resolved:
            if name in features:
                resolved[name] = bool(features[name])
    payload: dict[str, object] = {
        "serverVersion": __version__,
        "protocolVersion": 1,
        "hermesVersion": str(hermes_version or "unknown"),
        "features": resolved,
    }
    if runtime:
        payload["gateway_state"] = str(
            runtime.get("gateway_state") or "unavailable"
        )
        active_agents = runtime.get("active_agents", 0)
        payload["active_agents"] = (
            active_agents
            if isinstance(active_agents, int)
            and not isinstance(active_agents, bool)
            and active_agents >= 0
            else 0
        )
        payload["gateway_busy"] = bool(runtime.get("gateway_busy", False))
    if server_id:
        payload["serverId"] = str(server_id)
    return payload
