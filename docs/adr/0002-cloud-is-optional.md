# ADR 0002: Cloud is optional

Status: Accepted

## Decision

Self-hosted mode is the baseline. Chat, Sessions, Jobs, history and DIRECT notifications operate without Hermes Link Cloud. Cloud failure cannot disable core client/server behavior.

## Rollback

Disable `cloudNotifications` and retain DIRECT delivery; no core data migration is required.

