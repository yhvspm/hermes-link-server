# Cloud Protocol v3: multi-Hermes binding

Status: Stable extension to Cloud Protocol v2

This contract lets one Hermes Link App installation associate several
independent Hermes Servers with optional Cloud delivery. It does not introduce
a global active Server: sessions, agents and tasks remain App-side aggregates;
Cloud configuration, authorization, subscription and notification routing are
scoped by immutable `server_id`.

## Capability discovery

`GET /hermes-link/v1/server-info` keeps `protocolVersion: 1`. A Server that
can load or create its Ed25519 identity returns its stable `serverId` and sets
`features.cloudMultiBinding` to `true`.

```json
{
  "protocolVersion": 1,
  "serverId": "server_0123456789abcdef0123456789abcdef",
  "features": {
    "cloudNotifications": true,
    "cloudMultiBinding": true
  }
}
```

Clients must treat a missing `serverId` or `cloudMultiBinding: false` as an
older Server and keep the existing single-Server/Direct fallback. `serverId`
is stable across restart and configuration edits; it must never be generated
by the App.

## Server-issued binding attestation

The App sends an authenticated request to each target Hermes Server:

```text
POST /hermes-link/v1/cloud/attestation
Authorization: Bearer <paired-device-token>
```

Request body:

```json
{
  "schema_version": 1,
  "cloud_url": "https://cloud.example.com/hermes-link-cloud",
  "installation_id": "installation_abc"
}
```

The Server derives `profiles` from the paired device token (an unrestricted
token receives the Server-visible profile set), creates a new random nonce and
returns:

```json
{
  "schema_version": 1,
  "attestation": {
    "schema_version": 1,
    "server_id": "server_0123456789abcdef0123456789abcdef",
    "public_key": "<base64url-ed25519-public-key>",
    "installation_id": "installation_abc",
    "cloud_url": "https://cloud.example.com/hermes-link-cloud",
    "profiles": ["default", "cto"],
    "issued_at": 1700000000,
    "expires_at": 1700000300,
    "nonce": "att_<random>"
  },
  "attestation_signature": "ed25519:<base64url-signature>"
}
```

The signature is Ed25519 over canonical UTF-8 JSON (sorted keys, compact
separators) of `attestation`. It is valid for at most five minutes. The Server
never returns or transmits its private key.

## Cloud provisioning and lifecycle

The App forwards the attestation to `POST /v1/provision` as
`schema_version: 3`, together with only device metadata and an optional Huawei
Push token. It does **not** independently submit `server_id`, public key,
installation id or Profile scope.

Cloud must:

1. Require its configured public HTTPS base URL to match `attestation.cloud_url`.
2. Verify the signature, five-minute issue/expiry window and one-time
   `(server_id, nonce)` use.
3. Require an existing Installation credential before binding an additional
   Server to that Installation.
4. Persist the association as `(installation_id, server_id)` with its own
   attested Profile scope and subscriptions.
5. Keep entitlement and Cloud queue state per `server_id`.

The scoped endpoints are:

- `GET /v1/installation/status?installation_id=...&server_id=...`
- `POST /v1/installation/register?installation_id=...` with `server_id` in
  the body
- `POST /v1/installation/reapply?installation_id=...&server_id=...`
- `DELETE /v1/installation/servers/{server_id}?installation_id=...`

The delete route removes only the selected local Cloud association and its
subscriptions/device queue record. It does not delete the Hermes Server, any
remote Hermes data, or other bindings on the device. The App may additionally
call `DELETE /hermes-link/v1/cloud/configure` on that selected Server to clear
its local optional Cloud configuration.

## Event routing

New Server-to-Cloud events use the existing `POST /v1/events` HTTP signature
headers plus envelope `schema_version: 2`:

```json
{
  "schema_version": 2,
  "server_id": "server_0123456789abcdef0123456789abcdef",
  "event_id": "evt_123",
  "event_type": "chat.completed",
  "profile_id": "default",
  "session_id": "session_123",
  "run_id": "run_123",
  "dedupe_key": "chat:session_123:run_123",
  "occurred_at": "2026-08-17T12:00:00Z",
  "title": "Hermes Link",
  "body": "Chat completed",
  "data": {
    "event_type": "chat.completed",
    "event_id": "evt_123",
    "profile_id": "default",
    "session_id": "session_123",
    "server_id": "server_0123456789abcdef0123456789abcdef"
  },
  "installation_id": "installation_abc"
}
```

Cloud verifies both body `server_id` values equal
`X-Hermes-Link-Server`, verifies the Server signature and the scoped
Installation/Profile subscription, then forwards only the verified identifiers
to Huawei. Deduplication is `(server_id, event_id)`, so similarly named events
from two Hermes Servers remain separate. Cloud accepts prior schema v1 events
only as a compatibility input and scopes them from the authenticated header.

No envelope may contain prompts, messages, Agent output, API tokens, push
tokens, private keys, credentials, URLs with credentials or arbitrary Server
instance identifiers.
