from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hermes_link.api.capabilities import server_info
from hermes_link.notifications.cloud_sender import CloudEventSender
from hermes_link.notifications.events import validate_event


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "docs" / "protocol" / "schemas"
FIXTURE_ROOT = ROOT / "docs" / "protocol" / "fixtures"


def _read_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _private_key_pem() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


class PublicContractTests(unittest.TestCase):
    def test_protocol_schemas_are_versioned_and_restrict_unknown_fields(self) -> None:
        server_schema = _read_schema("server-info-v1.schema.json")
        event_schema = _read_schema("event-v1.schema.json")
        cloud_schema = _read_schema("cloud-v2-event-request.schema.json")
        provision_schema = _read_schema("cloud-v3-provision-request.schema.json")
        self.assertEqual(server_schema["properties"]["protocolVersion"]["const"], 1)
        self.assertEqual(event_schema["$id"], "urn:hermes-link:event:v1")
        self.assertEqual(cloud_schema["$id"], "urn:hermes-link:cloud:v2:event-request")
        self.assertEqual(provision_schema["$id"], "urn:hermes-link:cloud:v3:provision-request")
        self.assertFalse(server_schema["additionalProperties"])
        self.assertFalse(event_schema["additionalProperties"])
        self.assertFalse(cloud_schema["additionalProperties"])
        self.assertFalse(provision_schema["additionalProperties"])

    def test_server_info_matches_app_capability_contract(self) -> None:
        payload = server_info(
            "0.20.0",
            runtime={
                "gateway_state": "ready",
                "active_agents": 2,
                "gateway_busy": True,
            },
        )
        self.assertEqual(
            set(payload),
            {
                "serverVersion",
                "protocolVersion",
                "hermesVersion",
                "gateway_state",
                "active_agents",
                "gateway_busy",
                "features",
            },
        )
        self.assertEqual(payload["protocolVersion"], 1)
        self.assertEqual(payload["gateway_state"], "ready")
        self.assertEqual(payload["active_agents"], 2)
        self.assertTrue(payload["gateway_busy"])
        features = payload["features"]
        self.assertIsInstance(features, dict)
        self.assertEqual(
            set(features),
            {
                "chat",
                "sessions",
                "models",
                "jobs",
                "cron",
                "pairing",
                "executionTrace",
                "directNotifications",
                "cloudNotifications",
                "cloudMultiBinding",
                "chatAttachments",
            },
        )
        self.assertTrue(all(isinstance(value, bool) for value in features.values()))

    def test_versioned_fixtures_match_protocol_capabilities_and_event_allowlist(self) -> None:
        server_fixture = json.loads((FIXTURE_ROOT / "server-info-v1.json").read_text(encoding="utf-8"))
        event_fixture = json.loads((FIXTURE_ROOT / "event-v1-chat-completed.json").read_text(encoding="utf-8"))
        self.assertEqual(server_fixture["protocolVersion"], 1)
        self.assertEqual(set(server_fixture["features"]), set(server_info("0.20.0")["features"]))
        self.assertEqual(validate_event(event_fixture), event_fixture)

    def test_event_contract_accepts_allowlist_and_rejects_sensitive_fields(self) -> None:
        event = {
            "event_id": "evt_contract_1",
            "event_type": "chat.completed",
            "profile_id": "profile_1",
            "session_id": "session_1",
            "run_id": "run_1",
            "dedupe_key": "chat:session_1:run_1",
        }
        self.assertEqual(validate_event(event), event)
        with self.assertRaises(ValueError):
            validate_event({**event, "response": "full reply must not cross the boundary"})
        with self.assertRaises(ValueError):
            validate_event({**event, "event_type": "agent.error"})

    def test_server_cloud_sender_emits_only_public_wire_contract(self) -> None:
        event = {
            "event_id": "evt_wire_1",
            "event_type": "job.failed",
            "profile_id": "profile_1",
            "job_id": "job_1",
            "session_id": "session_1",
            "run_id": "run_1",
            "dedupe_key": "job:job_1:run_1",
        }

        class Response:
            def read(self, _limit: int) -> bytes:
                return b'{"state":"accepted"}'

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with patch("hermes_link.notifications.cloud_sender.urlopen", return_value=Response()) as mocked:
            result = CloudEventSender(
                "https://cloud.example.test/hermes-link-cloud",
                "server_" + "a" * 32,
                _private_key_pem(),
            ).publish(event, "installation_1")

        self.assertEqual(result["state"], "accepted")
        request = mocked.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "https://cloud.example.test/hermes-link-cloud/v1/events")
        self.assertEqual(body["installation_id"], "installation_1")
        self.assertEqual(body["schema_version"], 2)
        self.assertEqual(body["server_id"], "server_" + "a" * 32)
        self.assertEqual(body["event_id"], event["event_id"])
        self.assertEqual(body["event_type"], event["event_type"])
        self.assertEqual(body["profile_id"], event["profile_id"])
        self.assertEqual(body["job_id"], event["job_id"])
        self.assertEqual(body["session_id"], event["session_id"])
        self.assertEqual(body["run_id"], event["run_id"])
        self.assertEqual(body["dedupe_key"], event["dedupe_key"])
        self.assertEqual(body["data"], {
            "event_type": event["event_type"],
            "event_id": event["event_id"],
            "profile_id": event["profile_id"],
            "server_id": "server_" + "a" * 32,
            "session_id": event["session_id"],
            "job_id": event["job_id"],
        })
        self.assertEqual(set(body), {
            "schema_version",
            "server_id",
            "event_id",
            "event_type",
            "profile_id",
            "session_id",
            "job_id",
            "run_id",
            "occurred_at",
            "dedupe_key",
            "title",
            "body",
            "data",
            "installation_id",
        })
        self.assertTrue(headers["x-hermes-link-signature"].startswith("ed25519:"))
        self.assertTrue(headers["x-hermes-link-timestamp"])
        self.assertTrue(headers["x-hermes-link-nonce"])
        self.assertNotIn("response", body)
        self.assertNotIn("prompt", body)
        self.assertNotIn("api_token", body)


if __name__ == "__main__":
    unittest.main()
