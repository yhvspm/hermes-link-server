from __future__ import annotations

import subprocess
import os
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEST_ENV = {**os.environ, "HERMES_LINK_PYTHON": sys.executable}


class DeploymentAssetTests(unittest.TestCase):
    def test_shell_scripts_have_valid_syntax(self) -> None:
        for relative_path in (
            "scripts/generate-pairing-qr.sh",
            "scripts/bootstrap-hermes-agent-access.sh",
            "scripts/install-native.sh",
            "scripts/docker-deploy.sh",
            "scripts/verify-isolated-compose.sh",
        ):
            with self.subTest(relative_path=relative_path):
                subprocess.run(
                    ["bash", "-n", str(ROOT / relative_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=TEST_ENV,
                )

    def test_docker_compose_keeps_agent_and_bridge_off_public_ports(self) -> None:
        compose = yaml.safe_load((ROOT / "deploy/docker/compose.yaml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(services["server"]["network_mode"], "host")
        self.assertEqual(services["caddy"]["network_mode"], "host")
        self.assertEqual(services["server"]["build"]["context"], ".")
        self.assertNotIn("ports", services["server"])
        self.assertTrue(services["server"]["read_only"])
        self.assertTrue(services["caddy"]["read_only"])
        self.assertEqual(services["caddy"]["profiles"], ["proxy"])
        self.assertEqual(services["log-exporter"]["network_mode"], "none")
        self.assertEqual(services["log-exporter"]["user"], "0:0")
        self.assertTrue(services["log-exporter"]["read_only"])

    def test_dry_run_validates_custom_port_without_docker(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/docker-deploy.sh"),
                "--public-base-url", "https://link.example.test:8443",
                "--port", "8443",
                "--server-env", "/restricted/server.env",
                "--hermes-home", "/restricted/hermes-home",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=TEST_ENV,
        )
        self.assertIn("HTTPS 8443", result.stdout)
        self.assertIn("Docker", result.stdout)

    def test_dry_run_accepts_isolated_bridge_port(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/docker-deploy.sh"),
                "--public-base-url", "https://link.example.test:8443",
                "--port", "8443",
                "--bridge-port", "18765",
                "--server-only",
                "--server-env", "/restricted/server.env",
                "--hermes-home", "/restricted/hermes-home",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=TEST_ENV,
        )
        self.assertIn("127.0.0.1:18765", result.stdout)
        self.assertIn("dedicated Hermes Link credential", result.stdout)

    def test_dry_run_accepts_user_scoped_agent_service(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/bootstrap-hermes-agent-access.sh"),
                "--agent-service-scope", "user",
                "--agent-user", "root",
                "--hermes-home", "/root/.hermes",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=TEST_ENV,
        )
        self.assertIn("user scope", result.stdout)

    def test_dry_run_rejects_port_mismatch(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/install-native.sh"),
                "--public-base-url", "https://link.example.test:8443",
                "--port", "443",
                "--server-env", "/restricted/server.env",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env=TEST_ENV,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must match", result.stderr)

    def test_pairing_qr_option_is_documented(self) -> None:
        source = (ROOT / "src/hermes_link/pairing/store.py").read_text(encoding="utf-8")
        self.assertIn('"--qr"', source)
        self.assertIn("HERMES_LINK_MOBILE_API_TOKEN", source)

    def test_internal_credential_manager_creates_root_only_file_without_printing_value(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            credential_file = temporary_root / "internal-agent.env"
            command = [
                sys.executable,
                str(ROOT / "scripts/manage-internal-credential.py"),
                "--credential-file",
                str(credential_file),
                "--hermes-home",
                str(temporary_root / "agent-home/.hermes"),
            ]
            created = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env=TEST_ENV,
            )
            self.assertTrue(credential_file.is_file())
            if os.name != "nt":
                self.assertEqual(credential_file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("hls_", created.stdout)
            refused = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env=TEST_ENV,
            )
            self.assertNotEqual(refused.returncode, 0)
            rotated = subprocess.run(
                [*command, "--rotate"],
                check=True,
                capture_output=True,
                text=True,
                env=TEST_ENV,
            )
            if os.name != "nt":
                self.assertEqual(credential_file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("hls_", rotated.stdout)
