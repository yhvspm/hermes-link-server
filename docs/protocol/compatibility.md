# Compatibility policy

App, Server and Cloud versions are independent. Compatibility is determined only by protocol versions and feature flags.

- Hermes Link Protocol v1 is negotiated by `/hermes-link/v1/server-info`.
- Cloud Protocol v2, its schema v2 server-scoped event envelope, and V3 attested
  multi-Hermes provisioning are negotiated at the HTTP/schema boundary.
- An App uses V3 only when `server-info.features.cloudMultiBinding` is true and
  `serverId` is present; otherwise it retains the compatible V2/Direct path.
- Hermes Agent version differences are handled only in `integrations/hermes_agent/`.
- Existing v0.19 patches remain temporary migration inputs under `compat/`; new compatibility logic belongs in the adapter. They may not import Cloud implementation modules. The historical Cloud-binding patch path is intentionally excluded: Server-to-Cloud setup uses the public Cloud Protocol instead.

The supported Hermes Agent matrix and its mandatory checks live in
[`../compatibility-matrix.md`](../compatibility-matrix.md). An unknown Agent
release remains unverified until the matrix row and negative adapter checks are
added.

A breaking protocol change requires a new version and an Accepted ADR covering affected repositories, compatibility, rollout and rollback.
