# Hermes Link Protocol v1

Status: Stable baseline

The App communicates with Hermes Link Server, never Hermes Agent internals. All requests use authenticated HTTPS in deployment and JSON unless an endpoint explicitly defines SSE.

## Capability discovery

`GET /hermes-link/v1/server-info`

```json
{
  "serverVersion": "1.0.0",
  "protocolVersion": 1,
  "hermesVersion": "0.20.0",
  "gateway_state": "ready",
  "active_agents": 0,
  "gateway_busy": false,
  "features": {
    "chat": true,
    "sessions": true,
    "models": true,
    "jobs": true,
    "cron": true,
    "pairing": true,
    "directNotifications": true,
    "cloudNotifications": true
  }
}
```

Clients reject unsupported `protocolVersion` values and gate optional UI/requests by `features`. `hermesVersion` is a diagnostic value read by the Server from the authenticated Hermes Agent runtime health response; it must not control client behavior.

`gateway_state`, `active_agents`, and `gateway_busy` are a runtime snapshot
for read-only status UI. Hermes Link Server obtains them through its Agent
compatibility adapter and exposes no Agent internal fields, credentials, URLs,
or process details. If the adapter cannot obtain the snapshot,
`gateway_state` is `unavailable` and `active_agents` is `0`; clients must not
treat that fallback as an Agent version or feature decision.

## Stable resource families

- `/hermes-link/v1/chat`
- `/hermes-link/v1/sessions`
- `/hermes-link/v1/models`
- `/hermes-link/v1/jobs`
- `/hermes-link/v1/pairing`
- `/hermes-link/v1/notifications/direct`

The Hermes Agent adapter may translate these operations to version-specific internal paths. Internal paths are not part of this protocol.

## Chat session continuity

`POST /hermes-link/v1/chat/completions` continues the Session created through
`/hermes-link/v1/sessions` when the client sends `X-Hermes-Session-Id`. The
Server must preserve that identity while translating the request inside the
Hermes Agent adapter. It must not silently create a second Session or require
the App to know the Agent's internal session API.

## Isolation

Every Profile-scoped operation is authorized against the authenticated device token. Session/Job operations must additionally verify Profile ownership. Unknown or cross-Profile identifiers return a stable error and never fall back to a default Profile.
