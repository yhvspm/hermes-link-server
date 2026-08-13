# ADR 0001: Three-repository architecture

Status: Accepted

## Decision

Hermes Link is maintained as private App, public Server and private Cloud repositories. Cross-repository communication uses versioned HTTP APIs, protocols and event schemas only.

## Consequences

Internal models, databases and implementation modules cannot be shared across repositories. A boundary change requires a new ADR stating affected repositories, protocol/compatibility impact and rollback.

