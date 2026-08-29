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

    def test_docker_compose_binds_only_the_server_http_facade(self) -> None:
        compose = yaml.safe_load((ROOT / "deploy/docker/compose.yaml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(services["server"]["network_mode"], "host")
        self.assertEqual(services["server"]["build"]["context"], ".")
        self.assertNotIn("ports", services["server"])
        self.assertNotIn("caddy", services)
        self.assertEqual(services["server"]["environment"]["HERMES_LINK_BIND_HOST"], "${HERMES_LINK_BIND_HOST:-0.0.0.0}")
        self.assertEqual(
            services["server"]["environment"]["HERMES_LINK_DIRECT_EVENT_DB"],
            "/var/lib/hermes-link-server/direct-events.db",
        )
        self.assertTrue(services["server"]["read_only"])
        self.assertEqual(services["log-exporter"]["network_mode"], "none")
        self.assertEqual(services["log-exporter"]["user"], "0:0")
        self.assertTrue(services["log-exporter"]["read_only"])

    def test_dry_run_validates_custom_port_without_docker(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/docker-deploy.sh"),
                "--public-base-url", "http://203.0.113.42:18765",
                "--port", "18765",
                "--server-env", "/restricted/server.env",
                "--hermes-home", "/restricted/hermes-home",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=TEST_ENV,
        )
        self.assertIn("0.0.0.0:18765", result.stdout)
        self.assertIn("Docker", result.stdout)

    def test_dry_run_uses_app_port_as_direct_listener(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/docker-deploy.sh"),
                "--public-base-url", "http://203.0.113.42:18765",
                "--port", "18765",
                "--server-env", "/restricted/server.env",
                "--hermes-home", "/restricted/hermes-home",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=TEST_ENV,
        )
        self.assertIn("http://203.0.113.42:18765", result.stdout)
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
        self.assertIn("/root/.config/hermes-link-server/internal-agent.env", result.stdout)
        self.assertIn("private dedicated Hermes Link credential", result.stdout)
        bootstrap = (ROOT / "scripts/bootstrap-hermes-agent-access.sh").read_text(encoding="utf-8")
        self.assertIn('run_agent_systemctl restart "$agent_service"', bootstrap)

    def test_dry_run_accepts_legacy_agent_loopback_port(self) -> None:
        environment = {**TEST_ENV, "HERMES_AGENT_BASE_URL": "http://127.0.0.1:8080"}
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
            env=environment,
        )
        self.assertIn("Hermes Agent loopback origin http://127.0.0.1:8080", result.stdout)

    def test_docker_dry_run_uses_the_user_scoped_credential_path(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/docker-deploy.sh"),
                "--public-base-url", "http://203.0.113.42:18765",
                "--port", "18765",
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
        self.assertIn(
            "Docker will read the user-scoped private Agent credential at "
            "/root/.config/hermes-link-server/internal-agent.env",
            result.stdout,
        )

    def test_dry_run_rejects_port_mismatch(self) -> None:
        result = subprocess.run(
            [
                "bash", str(ROOT / "scripts/install-native.sh"),
                "--public-base-url", "http://203.0.113.42:18765",
                "--port", "18766",
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

    def test_isolated_verifier_uses_the_runtime_credential_fallback(self) -> None:
        source = (ROOT / "scripts/verify-isolated-compose.sh").read_text(encoding="utf-8")
        self.assertIn('HERMES_LINK_INTERNAL_ENV_FILE="${HERMES_LINK_INTERNAL_ENV_FILE:-$server_env}"', source)
        self.assertIn("HERMES_LINK_MOBILE_API_TOKEN') or os.environ.get('HERMES_LINK_AGENT_TOKEN", source)

    def test_internal_credential_manager_creates_private_file_without_printing_value(self) -> None:
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
            credential_values = {
                key: value
                for line in credential_file.read_text(encoding="utf-8").splitlines()
                if "=" in line
                for key, _, value in [line.partition("=")]
            }
            self.assertTrue(
                {
                    "HERMES_LINK_AGENT_TOKEN",
                    "HERMES_LINK_MOBILE_API_TOKEN",
                    "HERMES_AGENT_BASE_URL",
                    "API_SERVER_ENABLED",
                    "API_SERVER_KEY",
                    "API_SERVER_HOST",
                    "API_SERVER_PORT",
                }.issubset(credential_values)
            )
            self.assertEqual(credential_values["API_SERVER_ENABLED"], "true")
            self.assertEqual(credential_values["API_SERVER_HOST"], "127.0.0.1")
            self.assertEqual(credential_values["API_SERVER_PORT"], "8642")
            self.assertEqual(
                credential_values["API_SERVER_KEY"],
                credential_values["HERMES_LINK_AGENT_TOKEN"],
            )
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
