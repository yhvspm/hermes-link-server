# Hermes Link Server deployment

This repository is installed independently of Hermes Link Cloud.

1. Create a dedicated `hermes-link` service account and clone/copy the reviewed Server release to `/opt/hermes-link-server`.
2. Create a virtual environment and install the package with `pip install .` plus the supported Hermes Agent integration dependency.
3. Store device-token, identity and optional Cloud configuration outside Git with mode `0600` and service-account ownership.
4. Install `deploy/systemd/hermes-link-server.service` with a direct unprivileged HTTP listener, or configure an HTTPS proxy yourself when required.
5. Keep Hermes Agent services loopback-only. Expose only the authenticated Hermes Link Protocol surface; never expose the Agent itself.
6. Run unit/protocol tests, architecture and secret gates before restart. Verify `/hermes-link/v1/server-info` and a self-hosted DIRECT scenario before enabling optional Cloud.

Rollback restores the previous Server package/service unit. Cloud may be disabled independently; do not roll back or modify Hermes Agent data to disable notifications.
