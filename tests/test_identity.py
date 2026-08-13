from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
