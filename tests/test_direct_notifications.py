from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_link.integrations.hermes_agent import bridge
from hermes_link.notifications.direct import DirectNotificationStore


class DirectNotificationTests(unittest.TestCase):
    @staticmethod
    def _event(
        event_id: str,
        profile_id: str,
        session_id: str,
    ) -> dict[str, str]:
        return {
            "event_id": event_id,
            "event_type": "chat.completed",
            "profile_id": profile_id,
            "session_id": session_id,
            "run_id": f"run_{event_id}",
            "dedupe_key": f"chat:{session_id}:run_{event_id}",
        }

    def test_cursor_reads_are_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DirectNotificationStore(Path(directory) / "direct.db")
            store.publish(self._event("evt_a1", "profile_a", "session_a1"))
            store.publish(self._event("evt_b1", "profile_b", "session_b1"))
            store.publish(self._event("evt_a2", "profile_a", "session_a2"))

            events = store.read_after_event_id(["profile_a"], "evt_a1")

        self.assertEqual([event["event_id"] for event in events], ["evt_a2"])

    def test_completed_chat_creates_a_direct_event_without_cloud_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DirectNotificationStore(Path(directory) / "direct.db")
            with patch.object(bridge, "_DIRECT_NOTIFICATION_STORE", store), patch.object(
                bridge, "_publish_cloud_event"
            ):
                bridge._publish_chat_completed("default", "session_direct")

            events = store.read_after("default")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "chat.completed")
        self.assertEqual(events[0]["session_id"], "session_direct")
        self.assertNotIn("prompt", events[0])

    def test_direct_sse_rejects_cross_profile_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DirectNotificationStore(Path(directory) / "direct.db")
            store.publish(self._event("evt_a", "profile_a", "session_a"))
            store.publish(self._event("evt_b", "profile_b", "session_b"))
            with self._server(store, device_profiles=["profile_a"]) as address:
                connection = http.client.HTTPConnection(*address, timeout=3)
                connection.request(
                    "GET",
                    "/hermes-link/v1/notifications/direct",
                    headers={"Authorization": f"Bearer hmd_{'a' * 32}"},
                )
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                connection.close()

        self.assertEqual(response.status, 200)
        self.assertIn('"event_id":"evt_a"', body)
        self.assertNotIn("evt_b", body)
        self.assertNotIn('"sequence"', body)

    def test_direct_sse_rejects_an_unknown_device_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DirectNotificationStore(Path(directory) / "direct.db")
            with self._server(store, device_profiles=None) as address:
                connection = http.client.HTTPConnection(*address, timeout=3)
                connection.request(
                    "GET",
                    "/hermes-link/v1/notifications/direct",
                    headers={"Authorization": f"Bearer hmd_{'a' * 32}"},
                )
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                connection.close()

        self.assertEqual(response.status, 401)
        self.assertIn("notification_unauthorized", body)

    def _server(
        self,
        store: DirectNotificationStore,
        *,
        device_profiles: list[str] | None,
    ):
        return _DirectServerContext(store, device_profiles)


class _DirectServerContext:
    def __init__(self, store: DirectNotificationStore, device_profiles: list[str] | None):
        self.store = store
        self.device_profiles = device_profiles
        self.server: bridge.ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.patches: list[object] = []

    def __enter__(self) -> tuple[str, int]:
        self.patches = [
            patch.object(bridge, "_DIRECT_NOTIFICATION_STORE", self.store),
            patch.object(bridge, "device_profile_ids", return_value=self.device_profiles),
            patch.object(bridge, "discover_profile_ids", return_value=["profile_a", "profile_b"]),
            patch.object(bridge, "DIRECT_NOTIFICATION_MAX_WAIT_SECONDS", 0.02),
            patch.object(bridge, "DIRECT_NOTIFICATION_POLL_SECONDS", 0.001),
        ]
        for item in self.patches:
            item.start()  # type: ignore[union-attr]
        self.server = bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge.HermesLinkHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return str(self.server.server_address[0]), int(self.server.server_address[1])

    def __exit__(self, *_args: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=3)
        for item in reversed(self.patches):
            item.stop()  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
