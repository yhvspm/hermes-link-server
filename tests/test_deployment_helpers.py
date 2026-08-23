from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deployment_helpers", ROOT / "scripts" / "deployment_helpers.py"
)
assert SPEC is not None and SPEC.loader is not None
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)


class DeploymentHelperTests(unittest.TestCase):
    def test_public_url_omits_default_https_port(self) -> None:
        host = helpers.normalize_public_host("Hermes.Example.com.")
        self.assertEqual(host, "hermes.example.com")
        self.assertEqual(helpers.public_url(host, 443), "https://hermes.example.com")
        self.assertEqual(
            helpers.public_url(host, helpers.normalize_public_port("18443")),
            "https://hermes.example.com:18443",
        )

    def test_public_endpoint_rejects_ip_and_invalid_port(self) -> None:
        with self.assertRaises(ValueError):
            helpers.normalize_public_host("203.0.113.42")
        with self.assertRaises(ValueError):
            helpers.normalize_public_port("70000")

    def test_profile_discovery_reads_names_not_profile_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            profiles = home / "profiles"
            (profiles / "coder").mkdir(parents=True)
            (profiles / "mobiletest").mkdir()
            (profiles / "invalid profile").mkdir()
            (profiles / "coder" / "private-data.txt").write_text("do not read", encoding="utf-8")
            self.assertEqual(
                helpers.discover_profile_ids(home),
                ["default", "coder", "mobiletest"],
            )

    def test_identity_and_server_info_expose_only_public_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            identity_file = Path(temporary) / "identity.json"
            expected_id = "server_" + "a" * 32
            identity_file.write_text(
                json.dumps({"server_id": expected_id, "private_key_pem": "not-read"}),
                encoding="utf-8",
            )
            self.assertEqual(helpers.read_server_id(identity_file), expected_id)
        self.assertEqual(
            helpers.inspect_server_info(
                {
                    "gateway_state": "connected",
                    "active_agents": 3,
                    "serverId": "server_" + "b" * 32,
                    "features": {"cloudMultiBinding": True},
                }
            ),
            ("connected", 3, "server_" + "b" * 32, True),
        )
