# Compatibility policy

App, Server and Cloud versions are independent. Compatibility is determined only by protocol versions and feature flags.

- Hermes Link Protocol v1 is negotiated by `/hermes-link/v1/server-info`.
- Cloud Protocol v2 and Event Protocol v1 are negotiated at the HTTP/schema boundary.
- Hermes Agent version differences are handled only in `integrations/hermes_agent/`.
- Existing v0.19 patches remain temporary migration inputs under `compat/`; new compatibility logic belongs in the adapter. They may not import Cloud implementation modules. The historical Cloud-binding patch path is intentionally excluded: Server-to-Cloud setup uses the public Cloud Protocol instead.

The supported Hermes Agent matrix and its mandatory checks live in
[`../compatibility-matrix.md`](../compatibility-matrix.md). An unknown Agent
release remains unverified until the matrix row and negative adapter checks are
added.

A breaking protocol change requires a new version and an Accepted ADR covering affected repositories, compatibility, rollout and rollback.
