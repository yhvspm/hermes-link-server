# Pairing deployment

Pairing is provided by `hermes_link.pairing`. Configure its SQLite path in Server-owned storage and expose only the authenticated Pairing Protocol v1 routes.

- Generate short-lived one-time codes.
- Put only the HTTPS pairing URL/code in QR data, never a permanent API Token.
- Hash codes at rest and enforce single use, expiry and Profile allowlist.
- Return a scoped device token once and write it directly to App secure storage.
- Revoke a single device token without affecting unrelated Profiles or installations.

Pairing tests run with the normal Server test suite. Deployment logs must not print codes or returned tokens.

