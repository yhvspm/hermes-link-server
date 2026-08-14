from __future__ import annotations

import json
import unittest

from hermes_link.integrations.hermes_agent.bridge import _normalize_chat_sse_event


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
