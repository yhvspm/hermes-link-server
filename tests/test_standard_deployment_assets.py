from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
GATE_SPEC = importlib.util.spec_from_file_location(
    "public_release_gate", ROOT / "scripts" / "public_release_gate.py"
)
assert GATE_SPEC is not None and GATE_SPEC.loader is not None
public_release_gate = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(public_release_gate)


class StandardDeploymentAssetTests(unittest.TestCase):
    def test_standard_compose_preserves_server_state_and_uses_a_private_bridge_port(self) -> None:
        compose_path = ROOT / "deploy" / "standard" / "compose.yaml"
        compose = compose_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(compose)
        self.assertIn("server", parsed["services"])
        self.assertIn("caddy", parsed["services"])
        self.assertNotIn("build:", compose)
        self.assertIn("network_mode: host", compose)
        self.assertIn(
            "HERMES_LINK_BRIDGE_PORT: ${HERMES_LINK_BRIDGE_PORT:?Set HERMES_LINK_BRIDGE_PORT through install.sh.}",
            compose,
        )
        self.assertIn("os.environ['HERMES_LINK_BRIDGE_PORT']", compose)
        self.assertIn("HERMES_LINK_SERVER_IDENTITY_FILE", compose)
        self.assertIn("HERMES_LINK_CLOUD_CONFIG_FILE", compose)
        self.assertIn("./data/server:/var/lib/hermes-link-server", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("restart: unless-stopped", compose)

    def test_public_configuration_defaults_are_generic_and_port_aware(self) -> None:
        environment = (ROOT / "deploy" / "standard" / ".env.example").read_text(encoding="utf-8")
        self.assertIn("HERMES_LINK_PUBLIC_PORT=443", environment)
        self.assertIn("HERMES_LINK_PUBLIC_URL=https://hermes.example.com", environment)
        self.assertNotIn("HERMES_LINK_BRIDGE_PORT", environment)
        self.assertNotIn("18443", environment)
        self.assertNotIn("24443", environment)
        self.assertNotIn("8765", environment)
        self.assertNotIn("jusonxl.com", environment)
        self.assertEqual(environment, (ROOT / ".env.example").read_text(encoding="utf-8"))

    def test_release_version_stays_pinned_across_install_assets(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = project["project"]["version"]
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        environment = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn(f"DEFAULT_VERSION='{version}'", install)
        self.assertIn(f"HERMES_LINK_VERSION={version}", environment)
        self.assertIn(f"hermes-link-server:{version}", environment)
        self.assertIn("DEFAULT_RELEASE_DOWNLOAD_BASE_URL", install)
        self.assertIn("release-manifest.json", install)
        self.assertIn("verify_release_asset", install)
        self.assertIn("HERMES_LINK_RELEASE_DOWNLOAD_BASE_URL", environment)

    def test_standard_release_assets_require_verified_digests(self) -> None:
        cli = (ROOT / "deploy" / "standard" / "bin" / "hermes-link").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("download_release_manifest", cli)
        self.assertIn("verify-file", cli)
        self.assertIn("Release manifest and immutable image digest", cli)
        self.assertNotIn("image_repository()", cli)
        self.assertIn("provenance: mode=max", workflow)
        self.assertIn("sbom: true", workflow)
        self.assertIn("release-manifest.json.sha256", workflow)
        self.assertIn(".immutable')\" = true", workflow)
        self.assertIn("docker logout ghcr.io", workflow)

    def test_caddy_flushes_streams_to_the_selected_loopback_bridge(self) -> None:
        caddyfile = (ROOT / "deploy" / "standard" / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:${HERMES_LINK_BRIDGE_PORT}", caddyfile)
        self.assertIn("flush_interval -1", caddyfile)
        self.assertIn("/hermes-link/v1/*", caddyfile)

    def test_standard_cli_resolves_the_install_root_from_its_bin_directory(self) -> None:
        cli = (ROOT / "deploy" / "standard" / "bin" / "hermes-link").read_text(encoding="utf-8")
        self.assertIn('root_dir="$(cd -- "$script_dir/.." && pwd)"', cli)
        self.assertNotIn('root_dir="$(cd -- "$script_dir/../.." && pwd)"', cli)

    def test_install_supports_newer_ubuntu_and_reviewed_state_migration(self) -> None:
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("ubuntu_version_supported", install)
        self.assertIn("Ubuntu 22.04 and newer", install)
        self.assertIn("--reuse-agent-credential", install)
        self.assertIn("--state-import-dir", install)
        self.assertIn("--skip-image-pull", install)
        self.assertIn("server-identity.json hermes_link_server_identity.json", install)
        self.assertIn("cloud-config.json hermes_link_cloud_config.json", install)
        self.assertIn('"$state_identity_source" "$install_dir/data/server/server-identity.json"', install)
        self.assertIn("HERMES_LINK_BRIDGE_PORT=%s", install)
        self.assertIn("chown 10001:10001", install)
        self.assertNotIn("install -d -m 0700 -o 10001", install)
        dockerfile = (ROOT / "deploy" / "docker" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("pip install --no-cache-dir --retries 5 --timeout 120 .", dockerfile)

    def test_public_release_gate_classifies_known_private_deployment_markers(self) -> None:
        hostname = "hermes-api." + "jusonxl.com"
        ip_address = "58." + "210.12.34"
        windows_path = "C:" + "/Users/example"
        ssh_path = ".s" + "sh/id"
        findings = public_release_gate.text_findings(
            f"{hostname}\n{ip_address}\n{windows_path}\n{ssh_path}"
        )
        self.assertIn("known deployment hostname", findings)
        self.assertIn("known deployment IP range", findings)
        self.assertIn("Windows development path", findings)
        self.assertIn("SSH identity path", findings)

    def test_shell_entrypoints_parse_and_show_help(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not available on this test host")
        install = ROOT / "install.sh"
        cli = ROOT / "deploy" / "standard" / "bin" / "hermes-link"
        for path in (install, cli):
            subprocess.run([bash, "-n", str(path)], check=True, capture_output=True, text=True)
            completed = subprocess.run([bash, str(path), "--help"], check=True, capture_output=True, text=True)
            self.assertIn("Usage:", completed.stdout)
