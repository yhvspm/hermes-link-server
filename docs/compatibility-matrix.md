# Hermes Agent compatibility matrix

The stable compatibility target is Hermes Link Protocol v1, not a matching
product version. A Hermes Agent version is supported only when its matrix row
has the required checks in `compat/matrix.json` and those checks pass against
that Agent release.

| Hermes Agent | State | Boundary |
| --- | --- | --- |
| 0.19.x | Migration-only | Standard deployment does not patch Hermes Agent; verify any migration through the Server adapter before use. |
| 0.20.x | Supported | `integrations/hermes_agent` translates every public operation. Model configuration is served read-only by Hermes Link Server; write support requires a separately verified upstream contract. |
| Future version | Unverified | Add a row, adapter tests, compatibility evidence, and an ADR if a protocol change is needed. |

No client feature branches on `hermesVersion`. Clients consume
`protocolVersion` and `features`; the Server owns all Agent adaptation.
