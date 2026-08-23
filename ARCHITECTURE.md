# Hermes Link Server Architecture

> Self-hosted is the baseline. Cloud is optional. Hermes Link Server is the compatibility boundary between clients and Hermes Agent.

Repository visibility: **Public**. Server version: **1.0.1**.

```text
Hermes Link App
       │
       │ Hermes Link Protocol v1
       ▼
Hermes Link Server
       │
       ├───────────────> Hermes Link Cloud
       │                  Cloud Protocol v2
       ▼
Hermes Agent
```

## Self-hosted mode

```text
APP
 ↓
Hermes Link Server
 ↓
Hermes Agent
```

Cloud is absent. Chat, Sessions, Models, Jobs, Cron, history synchronization and DIRECT notifications remain functional.

## Cloud mode

```text
APP
 ↓
Hermes Link Server
 ↓
Hermes Agent

Hermes Link Server
 ↓
Hermes Link Cloud
 ↓
Huawei Push
 ↓
APP
```

## Internal boundaries

- `api/`: stable Hermes Link Protocol.
- `pairing/`, `identity/`, `notifications/`, `storage/`: Server-owned domains.
- `integrations/hermes_agent/`: the only package allowed to know Hermes Agent internal endpoints or versions.
- `notifications/cloud_sender.py`: HTTPS protocol client only; it cannot import Cloud code or access Cloud storage.
- `compat/`: temporary version patches retained for compatibility migration, not a permanent application dependency.
