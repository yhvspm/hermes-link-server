# Server migration map

| Migration source | New path | Notes |
| --- | --- | --- |
| `bridge/hermes_link_bridge.py` | `src/hermes_link/integrations/hermes_agent/bridge.py` | Bridge retained inside compatibility boundary |
| `server/hermes_link_pairing.py` | `src/hermes_link/pairing/store.py` | Pairing and device token store |
| `server/hermes_link_server_identity.py` | `src/hermes_link/identity/server.py` | CloudStore dependency removed |
| `server/hermes_link_push.py` DIRECT behavior | `src/hermes_link/notifications/direct.py` | Server-owned DIRECT event stream; Huawei code not copied |
| `server/hermes_link_cloud.py` Cloud V2 client behavior | `src/hermes_link/notifications/cloud_sender.py` | HTTPS protocol sender only; no Cloud DB/module dependency |
| `compat/*.patch` | `compat/hermes_agent_v0_19/` | Temporary compatibility foundation; Cloud binding uses the public Cloud Protocol rather than a Cloud Python import |
| `bridge/*.service` and Nginx example | `deploy/` | Public deployment templates |

Cloud database/admin/worker files remain outside this repository.
