# Cloud Protocol v2

Cloud is optional. The protocol connects Hermes Link Server and the Hermes Link Official Cloud Notification Platform by HTTPS; it does not expose Cloud Python modules or storage.

## Provisioning

The default V2 client flow automatically creates a Cloud Account, Installation, Server Binding and default Subscription, then waits for administrator review. Username/password CloudAccount login is compatibility/recovery only.

## Event submission

`POST /v1/events` carries a Cloud Protocol v2 notification envelope derived
from Event Protocol v1 plus `installation_id`. The legacy input envelope is
`schema_version: 1`; the multi-Hermes extension uses `schema_version: 2` with
the same verified `server_id` at the root and in `data`. The envelope contains only
generic notification metadata (`title`, `body`, and controlled `data` IDs);
it never carries the chat text, Prompt, Agent response or credentials.

Required headers:

- `X-Hermes-Link-Server`
- `X-Hermes-Link-Timestamp`
- `X-Hermes-Link-Nonce`
- `X-Hermes-Link-Signature: ed25519:<base64url>`

The signature covers uppercase method, exact path, timestamp, nonce and SHA-256 body hash separated by newlines. Cloud validates timestamp skew, consumes nonce once, verifies Server/Installation binding and entitlement, and deduplicates the event.

Cloud Protocol v3 adds Server-issued, short-lived attestations for associating
multiple Hermes Servers with one App Installation. It is an additive extension:
single-Server V2 provisioning and schema v1 event input remain compatible.
The authoritative contract is [`cloud-v3-multi-hermes.md`](cloud-v3-multi-hermes.md).

## Data minimization

Cloud receives identifiers and generic notification metadata needed for delivery. It never receives full chat text, full Prompt, full Agent response, Hermes API Token, Server credentials or private keys.
