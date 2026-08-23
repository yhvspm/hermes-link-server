# Changelog

## 1.0.1 - Immutable archive fallback

- Publish verified standard deployment assets directly on each immutable GitHub Release.
- Bind a Linux amd64 OCI image archive and its SHA-256 to the release manifest.
- Fall back to the verified archive only when normal immutable GHCR pulls fail.

## 1.0.0 - Initial public release

- Established Hermes Link Protocol v1 and feature capability discovery.
- Migrated Pairing, Server Identity, DIRECT notification storage and Cloud Protocol v2 sender.
- Concentrated Hermes Agent-specific paths and compatibility patches under the compatibility boundary.
- Preserved client Session identity through the Agent adapter to prevent duplicate chat Sessions.
- Added machine-readable Protocol v1/Event v1 schemas and cross-repository wire tests.
- Normalized Cloud Protocol v2 events into the signed notification envelope required by Cloud,
  including controlled metadata only and a job-event `run_id` guard.
