# Pairing Protocol v1

Pairing uses an HTTPS one-time, short-lived code. A permanent Hermes API Token must never appear in a QR code, UI log or report.

1. Server creates a pairing ticket with expiry and allowed Profiles.
2. App scans or enters the pairing URL/code.
3. App exchanges the code once over HTTPS.
4. Server returns the public configuration and a scoped device token.
5. App writes the token to platform secure storage without displaying it.

Codes are hashed at rest, expire, are single-use, and cannot expand the Profile allowlist during exchange. Revocation invalidates only the targeted device token.

