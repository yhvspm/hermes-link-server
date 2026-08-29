# Compatibility policy

App, Server and Cloud versions are independent. Compatibility is determined only by protocol versions and feature flags.

- Hermes Link Protocol v1 is negotiated by `/hermes-link/v1/server-info`.
- Cloud Protocol v2, its schema v2 server-scoped event envelope, and V3 attested
  multi-Hermes provisioning are negotiated at the HTTP/schema boundary.
- An App uses V3 only when `server-info.features.cloudMultiBinding` is true and
  `serverId` is present; otherwise it retains the compatible V2/Direct path.
- `GET /hermes-link/v1/notifications/direct` is a Server-owned, paired-device
  SSE endpoint. It is never proxied to a Hermes Agent endpoint, replays only
  the current device's authorized Profiles, and exposes only the allowlisted
  event envelope (`chat.completed`, `job.completed`, `job.failed`).
- A completed streamed chat creates `chat.completed` once in the Server event
  store before optional Cloud delivery, so DIRECT remains usable with no Cloud
  configuration.
- Hermes Agent version differences are handled only in `integrations/hermes_agent/`.
- Standard deployments do not patch Hermes Agent. Historical v0.19 artifacts under `compat/` are not loaded or applied; active compatibility logic belongs in the Server adapter. Server-to-Cloud setup uses the public Cloud Protocol rather than a Cloud implementation import.
- The network-isolated Server model-configuration exporter reads Agent metadata and writes only allowlisted, non-secret snapshots for the unprivileged Bridge. Clients never receive Agent configuration files or provider credentials.

The supported Hermes Agent matrix and its mandatory checks live in
[`../compatibility-matrix.md`](../compatibility-matrix.md). An unknown Agent
release remains unverified until the matrix row and negative adapter checks are
added.

A breaking protocol change requires a new version and an Accepted ADR covering affected repositories, compatibility, rollout and rollback.
