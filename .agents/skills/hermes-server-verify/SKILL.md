---
name: hermes-server-verify
description: Select and run verification for Hermes Link Server changes, including compatibility, wire contracts, deployment assets and public release evidence. Use when implementing or reviewing Server changes or assessing a Server release.
---

# Server verification workflow

Work from the Server repository root. Read the relevant diff and choose the applicable checks; these are conditional paths, not a mandatory sequence. Return results and remaining acceptance gaps.

- **Documentation/instructions:** check links, skill metadata and `git diff --check`; run `python scripts/secret_scan.py` and `python scripts/public_release_gate.py --current-only`. No Docker build is needed.
- **Python behavior:** use Python 3.11+ and dependencies from `pyproject.toml` (CI uses 3.12 and `python -m pip install -e .`). Run affected `unittest` modules and add focused regression coverage. Run `python scripts/architecture_gate.py` and `python scripts/secret_scan.py`.
- **API/identity/events:** include `tests.test_contracts`, `tests.test_protocol` and affected pairing/identity/notification tests. Cover unauthorized/cross-context requests and schema rejection where affected.
- **Agent compatibility:** include `tests.test_compatibility_matrix` and affected adapter tests; check Cloud remains optional and Agent-specific branching stays in the adapter.
- **Installer/runtime:** include affected deployment/manifest tests and shell, Compose and Docker checks from [CI](../../../.github/workflows/ci.yml). Dry runs are not clean-host or deployed acceptance.
- **Broad integration/release:** run `python -m unittest discover -s tests -t . -p 'test_*.py'` once; it includes `tests.test_contracts`. For release, follow [the public release gate](../../../docs/public-release-gate.md), including history checks. `--current-only` is not a full release gate. Prepare evidence before requesting missing publication/deployment authorization.

Consult current schemas/fixtures in `docs/protocol/` for the affected version, including V3 extensions; do not infer protocol support from package versions.
