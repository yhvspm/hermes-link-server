# ADR 0004: Cloud Protocol v2

Status: Accepted

## Decision

Server-to-Cloud events use HTTPS, Server-owned Ed25519 identity, timestamp, nonce, replay protection, entitlement and Event Protocol v1. Default accounts/installations/bindings/subscriptions are created automatically; username/password mode is compatibility/recovery only.

## Rollback

Stop Cloud submission and fall back to DIRECT mode without changing App/Server core data.

