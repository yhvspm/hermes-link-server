from __future__ import annotations

import json
import os
import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from hermes_link.identity import server as hermes_link_server_identity


class HermesServerIdentityTests(unittest.TestCase):
    def test_public_identity_does_not_expose_private_key_and_config_is_identifier_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "HERMES_LINK_SERVER_IDENTITY_FILE": str(root / "identity.json"),
                    "HERMES_LINK_CLOUD_CONFIG_FILE": str(root / "cloud.json"),
                },
                clear=False,
            ):
                public = hermes_link_server_identity.public_identity()
                self.assertIn("server_id", public)
                self.assertIn("public_key", public)
                self.assertNotIn("private_key_pem", public)
                configured = hermes_link_server_identity.configure_cloud(
                    {
                        "cloud_url": "https://cloud.example.test:24443/hermes-link-cloud",
                        "installation_id": "identity-install-1",
                        "server_id": public["server_id"],
                    }
                )
                self.assertEqual(configured["server_id"], public["server_id"])
                stored = json.loads((root / "cloud.json").read_text(encoding="utf-8"))
                self.assertNotIn("private_key_pem", stored)
                loaded = hermes_link_server_identity.load_cloud_config()
                self.assertEqual(loaded["installation_id"], "identity-install-1")
                self.assertTrue(hermes_link_server_identity.clear_cloud_config()["ok"])
                self.assertEqual(hermes_link_server_identity.load_cloud_config(), {})

    def test_cloud_binding_attestation_is_short_lived_and_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {"HERMES_LINK_SERVER_IDENTITY_FILE": str(root / "identity.json")},
                clear=False,
            ):
                result = hermes_link_server_identity.create_cloud_binding_attestation(
                    {
                        "schema_version": 1,
                        "cloud_url": "https://cloud.example.test/hermes-link-cloud",
                        "installation_id": "device-attestation-1",
                    },
                    ["default", "cto"],
                    now=1_700_000_000,
                )

        attestation = result["attestation"]
        self.assertEqual(attestation["profiles"], ["default", "cto"])
        self.assertEqual(attestation["issued_at"], 1_700_000_000)
        self.assertEqual(attestation["expires_at"], 1_700_000_300)
        self.assertNotIn("private_key_pem", json.dumps(result))
        signature = str(result["attestation_signature"]).split(":", 1)[1]
        signature_bytes = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        public_key = str(attestation["public_key"])
        public_bytes = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature_bytes,
            hermes_link_server_identity._canonical_json(attestation),
        )


if __name__ == "__main__":
    unittest.main()
