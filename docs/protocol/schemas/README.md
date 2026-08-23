# Machine-readable protocol contracts

These JSON Schemas are the public contract for Hermes Link Protocol v1,
Event Protocol v1, and the Cloud Protocol v2/V3 envelopes. They describe
only cross-repository data; they are not shared Python modules or database
models.

- `server-info-v1.schema.json` is returned by `GET /hermes-link/v1/server-info`.
- `event-v1.schema.json` is the allowlisted notification event body.
- `cloud-v2-event-request.schema.json` defines the Cloud notification envelope
  and installation boundary used by `POST /v1/events`.
- `cloud-v3-provision-request.schema.json` defines the Server-attested,
  multi-Hermes provisioning request used by `POST /v1/provision`.

Changes to these schemas are protocol changes. Update the relevant protocol
document, add or update an Accepted ADR, and keep the Server, Cloud, and App
contract tests in sync before release.
