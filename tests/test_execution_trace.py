from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from hermes_link.integrations.hermes_agent.bridge import (
    _chat_stream_terminal_state,
    _normalize_chat_sse_event,
    _publish_cloud_chat_completed,
    _relay_chat_stream,
)


class ExecutionTraceTests(unittest.TestCase):
    def test_tool_progress_is_normalized_as_a_redacted_runtime_event(self) -> None:
        event = _normalize_chat_sse_event(
            'event: hermes.tool.progress\n'
            'data: {"tool":"shell","status":"running","toolCallId":"call_1",'
            '"label":"run date","command":"date","stdout":"Fri"}'
        )
        self.assertTrue(event.startswith("event: hermes.execution.event\n"))
        payload = json.loads(event.split("data: ", 1)[1])
        self.assertEqual(payload, {
            "id": "call_1",
            "type": "tool",
            "phase": "started",
            "tool": "shell",
            "status": "running",
            "summary": "正在调用工具：shell",
            "detail": "run date",
        })

    def test_non_trace_sse_chunk_is_preserved(self) -> None:
        event = 'data: {"choices":[{"delta":{"content":"hello"}}]}'
        self.assertEqual(_normalize_chat_sse_event(event), event)


class CloudChatCompletionTests(unittest.TestCase):
    def test_only_successful_terminal_chunks_are_notifiable(self) -> None:
        self.assertEqual(_chat_stream_terminal_state("data: [DONE]"), "completed")
        self.assertEqual(
            _chat_stream_terminal_state(
                'data: {"choices":[{"finish_reason":"stop"}]}'
            ),
            "completed",
        )
        self.assertEqual(
            _chat_stream_terminal_state(
                'data: {"choices":[{"finish_reason":"error"}]}'
            ),
            "failed",
        )

    def test_cloud_chat_event_is_scoped_and_contains_no_chat_content(self) -> None:
        with patch(
            "hermes_link.integrations.hermes_agent.bridge.load_cloud_config",
            return_value={
                "cloud_url": "https://cloud.example.test/hermes-link-cloud",
                "installation_id": "installation_1",
                "server_id": "server_" + "a" * 32,
            },
        ), patch(
            "hermes_link.integrations.hermes_agent.bridge.get_or_create_identity",
            return_value={
                "server_id": "server_" + "a" * 32,
                "private_key_pem": "test-private-key",
            },
        ), patch(
            "hermes_link.integrations.hermes_agent.bridge.CloudEventSender"
        ) as sender_type:
            _publish_cloud_chat_completed("mobiletest", "session_1")

        sender_type.assert_called_once_with(
            "https://cloud.example.test/hermes-link-cloud",
            "server_" + "a" * 32,
            "test-private-key",
        )
        event, installation_id = sender_type.return_value.publish.call_args[0]
        self.assertEqual(installation_id, "installation_1")
        self.assertEqual(event["event_type"], "chat.completed")
        self.assertEqual(event["profile_id"], "mobiletest")
        self.assertEqual(event["session_id"], "session_1")
        self.assertTrue(event["event_id"].startswith("evt_"))
        self.assertTrue(event["run_id"].startswith("run_"))
        self.assertEqual(event["dedupe_key"], f"chat:session_1:{event['run_id']}")
        self.assertFalse({"prompt", "messages", "response", "body"}.intersection(event))

    def test_cloud_event_uses_outbound_override_without_changing_mobile_cloud_url(self) -> None:
        with patch(
            "hermes_link.integrations.hermes_agent.bridge.load_cloud_config",
            return_value={
                "cloud_url": "https://cloud.example.test/public",
                "installation_id": "installation_1",
                "server_id": "server_" + "a" * 32,
            },
        ), patch(
            "hermes_link.integrations.hermes_agent.bridge.get_or_create_identity",
            return_value={
                "server_id": "server_" + "a" * 32,
                "private_key_pem": "test-private-key",
            },
        ), patch(
            "hermes_link.integrations.hermes_agent.bridge.CloudEventSender"
        ) as sender_type, patch.dict(
            os.environ,
            {"HERMES_LINK_CLOUD_OUTBOUND_URL": "https://cloud.example.test/internal"},
            clear=False,
        ):
            _publish_cloud_chat_completed("mobiletest", "session_1")

        sender_type.assert_called_once_with(
            "https://cloud.example.test/internal",
            "server_" + "a" * 32,
            "test-private-key",
        )


class ChatStreamRelayTests(unittest.TestCase):
    def test_client_disconnect_still_drains_agent_completion(self) -> None:
        class ChunkedResponse:
            def __init__(self) -> None:
                self.chunks = [
                    b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
                    b'data: [DONE]\n\n',
                    b"",
                ]
                self.read_count = 0

            def read1(self, _size: int) -> bytes:
                self.read_count += 1
                return self.chunks.pop(0)

        response = ChunkedResponse()
        emitted: list[bytes] = []

        def disconnected_client(chunk: bytes) -> bool:
            emitted.append(chunk)
            raise BrokenPipeError()

        terminal_state = _relay_chat_stream(response, disconnected_client)

        self.assertEqual(terminal_state, "completed")
        self.assertEqual(response.read_count, 3)
        self.assertEqual(len(emitted), 1)
