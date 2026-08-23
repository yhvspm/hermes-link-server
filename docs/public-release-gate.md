# Public release gate

Run this gate before changing repository visibility, creating a release, or
publishing a container image:

```bash
python scripts/secret_scan.py
python scripts/public_release_gate.py
git diff --check
```

The automated gate scans the current tree and every reachable Git revision for
private-key literals, credential-like values, tracked `.env`/key files, known
deployment host markers, Windows development paths, and SSH identity paths. It
reports only file locations and finding categories, never matched values.

The review still requires a human check for:

- Intended public repository history and the absence of unreviewed generated
  artifacts
- The canonical Apache-2.0 `LICENSE`, `SECURITY.md`, `.gitignore`, and
  `.env.example`
- Immediately after changing the repository to public and before announcing it:
  enable GitHub Private Vulnerability Reporting in **Settings → Advanced
  Security**, then verify that **Security → Advisories → Report a
  vulnerability** is visible. GitHub provides this feature for public
  repositories, so it cannot be enabled while the repository remains private.
- Before creating the first release, enable **Settings → Releases → Enable
  release immutability**. The release workflow publishes assets through a
  draft and then asserts the GitHub release API reports `immutable: true`; do
  not announce a release whose workflow did not pass that check.
- Confirm that `release-manifest.json`, `release-manifest.json.sha256`, all
  named standard deployment assets, and the Linux amd64 OCI image archive are
  attached to the release. The manifest must bind the exact Git commit, all
  standard deployment assets, the archive SHA-256, and a
  `ghcr.io/yhvspm/hermes-link-server@sha256:...` image. Runtime installation
  and updates reject a mismatched asset, archive, or mutable image reference.
- Docker image contents, the generated SBOM/provenance records, the exact
  image digest rather than a mutable package tag, and an OCI archive whose
  embedded root descriptor retains that exact digest. The release workflow
  logs out of GHCR and verifies anonymous digest access before creating the
  GitHub Release; do not bypass a failure here by relying on authenticated
  access.
- Installer, custom-port, external-proxy, update/rollback, and stream-disconnect
  test evidence
- Current real-device App regression if runtime, HTTPS, or public-port behavior
  changes

If the complete history gate reports a sensitive historical revision, do not
make the existing private repository public. Create a new public repository
from a reviewed release tree and begin a clean history there. Repository
visibility, commits, pushes, GHCR publication, and releases each require their
own explicit authorization.
