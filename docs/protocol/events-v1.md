# Event Protocol v1

Allowed event types are exactly:

- `chat.completed`
- `job.completed`
- `job.failed`

Common fields: `event_id`, `event_type`, `profile_id`, `run_id` when available, `dedupe_key`, and `created_at`. Chat completion requires `session_id`; job events require `job_id` and may include the bound `session_id`.

Forbidden fields include full messages, Prompt, Agent response, API/Push tokens, credentials, private keys, arbitrary click URLs, commands and file paths. Unknown fields that expand the trust boundary require a protocol revision and ADR.

Delivery is at-least-once. Consumers deduplicate using the canonical event ID/dedupe key and tolerate delayed or out-of-order delivery.

Machine-readable references are kept under `docs/protocol/schemas/`. The Cloud
request envelope adds `installation_id`; it does not expand the Event Protocol
allowlist or permit content, credentials, provider tokens, URLs, commands or
file paths.
