import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from hermes_link.api.capabilities import server_info
from hermes_link.integrations.hermes_agent import HermesAgentAdapter, protocol_to_agent_path
from hermes_link.integrations.hermes_agent.adapter import (
    DeviceAuthorizationError,
    forward_agent_headers,
    prepare_agent_headers,
)
from hermes_link.notifications.direct import DirectNotificationStore
from hermes_link.notifications.events import validate_event
from hermes_link.pairing import PairingStore
from hermes_link.pairing.http import exchange_pairing_payload
from hermes_link.security.redaction import redact_sensitive_text


class ProtocolTests(unittest.TestCase):
    def test_capabilities_are_protocol_and_feature_based(self):
        info = server_info("0.20.0")
        self.assertEqual(info["protocolVersion"], 1)
        self.assertTrue(info["features"]["chat"])
        self.assertNotEqual(info["serverVersion"], info["hermesVersion"])

    def test_event_allowlist_and_sensitive_fields(self):
        event = {
            "event_id": "evt_1",
            "event_type": "chat.completed",
            "profile_id": "default",
            "session_id": "session_1",
            "run_id": "run_1",
            "dedupe_key": "chat:session_1:run_1",
        }
        self.assertEqual(validate_event(event)["event_type"], "chat.completed")
        with self.assertRaises(ValueError):
            validate_event({**event, "event_type": "agent.error"})
        with self.assertRaises(ValueError):
            validate_event({**event, "prompt": "not allowed"})

    def test_direct_store_is_profile_isolated_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DirectNotificationStore(Path(directory) / "direct.db")
            event = {
                "event_id": "evt_1",
                "event_type": "chat.completed",
                "profile_id": "profile_a",
                "session_id": "session_1",
                "run_id": "run_1",
                "dedupe_key": "chat:session_1:run_1",
            }
            first = store.publish(event)
            duplicate = store.publish(event)
            self.assertEqual(first["sequence"], duplicate["sequence"])
            self.assertEqual(len(store.read_after("profile_a")), 1)
            self.assertEqual(store.read_after("profile_b"), [])

    def test_agent_adapter_rejects_non_loopback_and_unknown_operations(self):
        with self.assertRaises(ValueError):
            HermesAgentAdapter("https://example.com")
        adapter = HermesAgentAdapter()
        self.assertEqual(adapter.base_url, "http://127.0.0.1:8642")
        with self.assertRaises(ValueError):
            adapter.request("rawInternalPath")

    def test_agent_runtime_status_is_reduced_to_public_fields(self):
        class Response:
            def read(self, _limit: int) -> bytes:
                return b'{"status":"ready","gateway_state":"running","active_agents":2,"gateway_busy":true,"version":"0.20.0","raw":"not-public"}'

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with patch(
            "hermes_link.integrations.hermes_agent.adapter.urlopen",
            return_value=Response(),
        ):
            status = HermesAgentAdapter().runtime_status(token="server-agent-key-123")

        self.assertEqual(status, {
            "gateway_state": "running",
            "active_agents": 2,
            "gateway_busy": True,
            "hermes_version": "0.20.0",
        })

    def test_agent_runtime_status_is_unavailable_without_internal_token(self):
        with patch.dict("os.environ", {}, clear=True):
            status = HermesAgentAdapter().runtime_status()
        self.assertEqual(status["gateway_state"], "unavailable")
        self.assertEqual(status["active_agents"], 0)

    def test_protocol_paths_are_translated_only_inside_adapter(self):
        self.assertEqual(
            protocol_to_agent_path("/hermes-link/v1/profiles/work/sessions/session_1"),
            "/p/work/api/sessions/session_1",
        )
        self.assertEqual(
            protocol_to_agent_path("/hermes-link/v1/chat/completions"),
            "/v1/chat/completions",
        )
        self.assertIsNone(protocol_to_agent_path("/hermes-link/v1/raw/internal"))

    def test_bridge_preserves_session_identity_header(self):
        headers = forward_agent_headers(
            {
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
                "X-Hermes-Session-Id": "session_1",
                "X-Not-Allowed": "ignored",
            }
        )
        self.assertEqual(headers["X-Hermes-Session-Id"], "session_1")
        self.assertNotIn("X-Not-Allowed", headers)

    def test_bridge_translates_scoped_device_token_to_agent_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.db"
            store = PairingStore(path)
            ticket = store.create_ticket(
                "https://hermes.example.test",
                "server-agent-key-123",
                now=int(time.time()),
            )
            code = ticket.pairing_url.split("code=", 1)[1].split("&", 1)[0]
            exchanged = store.exchange(code, now=int(time.time()))
            device_token = str(exchanged["device_token"])

            prepared = prepare_agent_headers(
                {"Authorization": f"Bearer {device_token}"},
                "/hermes-link/v1/models",
                pairing_path=path,
                upstream_token="server-agent-key-123",
            )

            self.assertEqual(
                prepared["Authorization"],
                "Bearer server-agent-key-123",
            )

    def test_bridge_rejects_invalid_scoped_device_token(self):
        with self.assertRaises(DeviceAuthorizationError) as context:
            prepare_agent_headers(
                {"Authorization": "Bearer hmd_invalid-token"},
                "/hermes-link/v1/models",
                pairing_path=Path(tempfile.gettempdir()) / "missing-hermes-pairing.db",
                upstream_token="server-agent-key-123",
            )
        self.assertEqual(context.exception.status, 401)
        self.assertEqual(context.exception.code, "device_token_invalid")

    def test_server_pairing_boundary_does_not_require_agent_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.db"
            store = PairingStore(path)
            ticket = store.create_ticket(
                "https://hermes.example.test",
                "server-agent-key-123",
                now=int(time.time()),
            )
            code = ticket.pairing_url.split("code=", 1)[1].split("&", 1)[0]
            status, response = exchange_pairing_payload(
                {"schema_version": 1, "code": code},
                pairing_path=path,
            )
            self.assertEqual(status, 200)
            self.assertIsInstance(response, dict)
            self.assertTrue(str(response["device_token"]).startswith("hmd_"))

    def test_bridge_port_defaults_and_rejects_invalid_values(self):
        from hermes_link.integrations.hermes_agent.bridge import _bridge_port

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_bridge_port(), 8765)
        with patch.dict("os.environ", {"HERMES_LINK_BRIDGE_PORT": "18765"}, clear=True):
            self.assertEqual(_bridge_port(), 18765)
        with patch.dict("os.environ", {"HERMES_LINK_BRIDGE_PORT": "0"}, clear=True):
            with self.assertRaises(RuntimeError):
                _bridge_port()

    def test_server_discovers_profile_ids_without_reading_profile_contents(self):
        from hermes_link.integrations.hermes_agent.bridge import discover_profile_ids

        with tempfile.TemporaryDirectory() as directory:
            hermes_home = Path(directory)
            profiles = hermes_home / "profiles"
            (profiles / "mobiletest").mkdir(parents=True)
            (profiles / "cto").mkdir()
            (profiles / "bad profile").mkdir()
            (profiles / "README").write_text("not a profile", encoding="utf-8")

            self.assertEqual(
                discover_profile_ids(hermes_home),
                ["default", "cto", "mobiletest"],
            )

    def test_server_uses_deployment_profile_ids_when_agent_home_is_unreadable(self):
        from hermes_link.integrations.hermes_agent.bridge import discover_profile_ids

        with patch.dict(
            "os.environ",
            {"HERMES_LINK_PROFILE_IDS": "default, cto, invalid profile, cto"},
            clear=True,
        ):
            self.assertEqual(discover_profile_ids(Path("/restricted")), ["default", "cto"])

    def test_server_redaction_fallback_does_not_require_agent_package(self):
        self.assertNotIn("example-token-value", redact_sensitive_text("token=example-token-value"))
        self.assertNotIn("secret-value", redact_sensitive_text("Bearer secret-value"))


if __name__ == "__main__":
    unittest.main()
