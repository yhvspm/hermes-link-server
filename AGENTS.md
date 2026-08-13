# Hermes Link Server Agent Rules

## Architecture principle

Self-hosted is the baseline. Cloud is optional. Hermes Link Server is the compatibility boundary between clients and Hermes Agent.

Before implementing any feature, determine whether the requested change
belongs to App, Server, Cloud, or Protocol.

If the requested implementation would violate repository boundaries,
do not implement it directly.

Report the architecture conflict first and propose the correct
cross-repository design.

## Repository role

Public, self-hostable compatibility server between clients and Hermes Agent. Versioned independently as `1.0.0`.

## Allowed responsibilities

- Stable client API, pairing, device tokens, Server identity, Ed25519 event signing, nonce/timestamp, replay-oriented envelope, Profile/Server/Installation isolation.
- DIRECT notifications, Cloud Protocol sender, Sessions, Chat, Models, Jobs/Cron and task result writeback adapters.
- Hermes Agent version compatibility under `integrations/hermes_agent/`; temporary patches under `compat/`.
- Server deployment examples and public protocol documentation.

## Forbidden responsibilities

- Cloud Admin, Cloud Worker, provider credentials or Cloud database access.
- Importing `hermes_link_cloud` internal Python modules.
- HarmonyOS UI/client implementation or App secure-storage details.
- Exposing arbitrary internal URLs, commands, files, raw logs or Hermes credentials.

## Security rules

- Private keys and tokens remain in restricted server-side files and are never committed or logged.
- Validate every Profile, Server, Installation, Session, Job, Run and Event ownership boundary.
- Cloud events are restricted to `chat.completed`, `job.completed`, `job.failed` and exclude full content, prompts, replies and secrets.

## Protocol rules

- The public boundary is Hermes Link Protocol v1; outbound notification delivery uses Cloud Protocol v2 and Event Protocol v1.
- Return capability flags; never require App/Server/Cloud version equality.
- Hermes Agent version branching is allowed only inside the compatibility adapter.

## Testing requirements

- Run Python unit, Hermes compatibility, protocol, Secret Scan and Architecture Boundary Scan.
- Add negative tests for unauthorized/cross-context access and event/schema rejection when relevant.

## Git rules

- Inspect status, branch, HEAD, diff and untracked paths first.
- No reset, overwrite checkout, clean, deletion of user changes, commit, push, publish, deploy or credential action without explicit approval.

