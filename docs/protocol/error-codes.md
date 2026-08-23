# Error codes

Errors are JSON objects with stable `code`, safe `message`, optional `requestId`, and an appropriate HTTP status. Messages never contain credentials or internal paths.

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `protocol_unsupported` | 426 | Client/server protocol version is unsupported |
| `feature_disabled` | 409 | Capability is not enabled |
| `auth_required` | 401 | Authentication missing or invalid |
| `resource_forbidden` | 403 | Cross-Profile/Server/Installation access rejected |
| `resource_not_found` | 404 | Scoped resource does not exist |
| `pairing_invalid` | 400 | Pairing code invalid, used or expired |
| `event_invalid` | 400 | Event schema/type rejected |
| `event_replay` | 409 | Timestamp/nonce/event replay rejected |
| `cloud_attestation_invalid` | 400 | Server binding attestation shape or scope rejected |
| `cloud_attestation_expired` | 401 | Server binding attestation is outside its short validity window |
| `cloud_attestation_replayed` | 409 | A signed binding nonce was already consumed |
| `cloud_event_server_mismatch` | 403 | Signed event header and routed Server identifier differ |
| `cloud_unavailable` | 503 | Optional Cloud delivery unavailable; self-hosted core remains available |
