# Hermes Agent compatibility matrix

The stable compatibility target is Hermes Link Protocol v1, not a matching
product version. A Hermes Agent version is supported only when its matrix row
has the required checks in `compat/matrix.json` and those checks pass against
that Agent release.

| Hermes Agent | State | Boundary |
| --- | --- | --- |
| 0.19.x | Migration-only | Existing patches remain an upgrade input; do not add new App coupling. |
| 0.20.x | Supported | `integrations/hermes_agent` translates every public operation. |
| Future version | Unverified | Add a row, adapter tests, compatibility evidence, and an ADR if a protocol change is needed. |

No client feature branches on `hermesVersion`. Clients consume
`protocolVersion` and `features`; the Server owns all Agent adaptation.
