# ADR 0003: Server is the Hermes adapter

Status: Accepted

## Decision

The App depends on Hermes Link Protocol, not Hermes Agent internals. All Hermes Agent version and endpoint compatibility is owned by `hermes-link-server/integrations/hermes_agent/`.

## Consequences

Server adapter tests cover supported Hermes versions. Client feature decisions use capabilities, never `hermesVersion` comparisons.

