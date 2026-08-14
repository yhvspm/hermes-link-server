#!/usr/bin/env python3
"""Hermes Link Protocol facade and Hermes Agent compatibility adapter."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import yaml

try:
    from agent.redact import redact_sensitive_text
except ImportError:
    from hermes_link.security.redaction import redact_sensitive_text
from hermes_link.api.capabilities import server_info
from hermes_link.integrations.hermes_agent.adapter import (
    DeviceAuthorizationError,
    HermesAgentAdapter,
    _bearer_token,
    prepare_agent_headers,
    protocol_to_agent_path,
)
from hermes_link.pairing.http import exchange_pairing_payload
from hermes_link.pairing.store import revoke_device_token


HOST = "127.0.0.1"


def _bridge_port() -> int:
    raw_value = os.environ.get("HERMES_LINK_BRIDGE_PORT", "8765")
    try:
        port = int(raw_value)
    except ValueError as error:
        raise RuntimeError("HERMES_LINK_BRIDGE_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("HERMES_LINK_BRIDGE_PORT must be in 1..65535")
    return port


PORT = _bridge_port()
HERMES_HOME = Path(
    os.environ.get(
        "HERMES_LINK_AGENT_HOME",
        os.environ.get("HERMES_HOME", "/root/.hermes"),
    )
)
REDACTED_LOG_DIRECTORY = Path(
    os.environ.get("HERMES_LINK_REDACTED_LOG_DIR", "").strip()
)
LOG_FILES = {
    "agent": "agent.log",
    "errors": "errors.log",
    "gateway": "gateway.log",
}
LOG_PATTERN = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)"
    r"\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"(?:\s+\[[^\]]+\])?\s+(?P<source>[^:]+):\s*(?P<message>.*)$"
)
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
TRACE_TOOL_PATTERN = re.compile(r"^[a-z0-9._-]{1,40}$")
TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
TRACE_DETAIL_MAX_LENGTH = 280


def discover_profile_ids(hermes_home: Path = HERMES_HOME) -> list[str]:
    """Return the Server-visible Hermes Profile IDs without reading their data."""
    configured_profiles = os.environ.get("HERMES_LINK_PROFILE_IDS", "")
    configured_ids: list[str] = []
    for value in configured_profiles.split(","):
        profile_id = value.strip()
        if profile_id and PROFILE_ID_PATTERN.fullmatch(profile_id) and profile_id not in configured_ids:
            configured_ids.append(profile_id)
    if configured_ids:
        return configured_ids

    profile_ids = ["default"]
    profiles_directory = hermes_home / "profiles"
    try:
        candidates = sorted(profiles_directory.iterdir(), key=lambda path: path.name)
    except OSError:
        return profile_ids
    for candidate in candidates:
        profile_id = candidate.name
        if (
            candidate.is_dir()
            and profile_id != "default"
            and PROFILE_ID_PATTERN.fullmatch(profile_id)
        ):
            profile_ids.append(profile_id)
    return profile_ids


def _read_tail(path: Path, limit: int) -> list[str]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=limit))


def _log_path(log_key: str) -> Path:
    directory = REDACTED_LOG_DIRECTORY if str(REDACTED_LOG_DIRECTORY) != "." else HERMES_HOME / "logs"
    return directory / LOG_FILES[log_key]


def _parse_line(line: str, index: int) -> dict[str, str]:
    safe_line = redact_sensitive_text(
        line.rstrip(),
        force=True,
        redact_url_credentials=True,
    )
    if len(safe_line) > 2000:
        safe_line = f"{safe_line[:2000]}…"
    match = LOG_PATTERN.match(safe_line)
    if match:
        return {
            "id": f"log-{index}",
            "level": match.group("level"),
            "source": match.group("source").strip(),
            "message": match.group("message").strip(),
            "time": match.group("time"),
        }
    return {
        "id": f"log-{index}",
        "level": "INFO",
        "source": "Hermes",
        "message": safe_line,
        "time": "",
    }


def _read_tasks(limit: int) -> list[dict[str, object]]:
    database_path = HERMES_HOME / "kanban.db"
    if not database_path.is_file():
        return []
    connection = sqlite3.connect(
        f"file:{database_path}?mode=ro",
        uri=True,
        timeout=3,
    )
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, title, assignee, status, priority, created_at,
                   started_at, completed_at
            FROM tasks
            WHERE status != 'archived'
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        tasks: list[dict[str, object]] = []
        for row in rows:
            title = redact_sensitive_text(str(row["title"]), force=True)
            assignee = redact_sensitive_text(
                str(row["assignee"] or ""),
                force=True,
            )
            tasks.append(
                {
                    "id": str(row["id"]),
                    "title": title[:500],
                    "assignee": assignee[:100],
                    "status": str(row["status"]),
                    "priority": int(row["priority"] or 0),
                    "created_at": int(row["created_at"] or 0),
                    "started_at": int(row["started_at"] or 0),
                    "completed_at": int(row["completed_at"] or 0),
                }
            )
        return tasks
    finally:
        connection.close()


def _read_model_config(profile_id: str) -> dict[str, str] | None:
    config_path = (
        HERMES_HOME / "config.yaml"
        if profile_id == "default"
        else HERMES_HOME / "profiles" / profile_id / "config.yaml"
    )
    if not config_path.is_file():
        return None
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    model_config = payload.get("model", {})
    if isinstance(model_config, dict):
        model = str(
            model_config.get("default") or model_config.get("name") or ""
        ).strip()
        provider = str(model_config.get("provider") or "").strip()
    else:
        model = str(model_config or "").strip()
        provider = ""
    return {
        "profile": profile_id,
        "model": model[:200],
        "provider": provider[:100],
    }


def _normalize_trace_tool(raw_tool: object) -> str:
    tool = str(raw_tool or "agent-tool").strip().lower()
    return tool if TRACE_TOOL_PATTERN.fullmatch(tool) else "agent-tool"


def _normalize_trace_status(raw_status: object) -> str:
    return "completed" if str(raw_status or "").strip().lower() == "completed" else "running"


def _normalize_trace_detail(raw_detail: object) -> str:
    """Return the redacted, bounded execution detail emitted by Hermes Agent."""
    detail = str(raw_detail or "").strip()
    if not detail:
        return ""
    try:
        detail = redact_sensitive_text(detail)
    except Exception:
        return ""
    return " ".join(detail.split())[:TRACE_DETAIL_MAX_LENGTH]


def _execution_sse_event(payload: dict[str, object]) -> str:
    return "event: hermes.execution.event\ndata: " + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalize_chat_sse_event(event_block: str) -> str:
    """Publish a stable, current-task execution event from Hermes Agent callbacks."""
    event_name = "message"
    data_parts: list[str] = []
    for line in event_block.split("\n"):
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].strip())
    if event_name != "hermes.tool.progress" or not data_parts:
        return event_block
    try:
        upstream = json.loads("\n".join(data_parts))
    except json.JSONDecodeError:
        return event_block
    if not isinstance(upstream, dict):
        return event_block
    tool = _normalize_trace_tool(upstream.get("tool"))
    status = _normalize_trace_status(upstream.get("status"))
    raw_id = str(upstream.get("toolCallId") or "").strip()
    trace_id = raw_id if TRACE_ID_PATTERN.fullmatch(raw_id) else ""
    action = "已完成工具调用" if status == "completed" else "正在调用工具"
    payload = {
        "id": trace_id,
        "type": "tool",
        "phase": "completed" if status == "completed" else "started",
        "tool": tool,
        "status": status,
        "summary": f"{action}：{tool}",
    }
    detail = _normalize_trace_detail(upstream.get("label"))
    if detail:
        payload["detail"] = detail
    return _execution_sse_event(payload)


class HermesLinkHandler(BaseHTTPRequestHandler):
    server_version = "HermesLinkBridge/1.0"

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy_agent(self, parsed: object) -> bool:
        path = protocol_to_agent_path(parsed.path)  # type: ignore[attr-defined]
        if path is None:
            return False
        agent_origin = os.environ.get("HERMES_AGENT_BASE_URL", "http://127.0.0.1:8642").rstrip("/")
        origin = urlparse(agent_origin)
        if origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost"}:
            self._send_json(500, {"error": "Hermes Agent adapter origin is invalid"})
            return True
        query = parsed.query  # type: ignore[attr-defined]
        target = f"{agent_origin}{path}" + (f"?{query}" if query else "")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length"})
            return True
        if content_length < 0 or content_length > 8 * 1024 * 1024:
            self._send_json(413, {"error": "Request body is too large"})
            return True
        body = self.rfile.read(content_length) if content_length else None
        try:
            headers = prepare_agent_headers(self.headers, parsed.path)  # type: ignore[attr-defined]
        except DeviceAuthorizationError as error:
            self._send_json(
                error.status,
                {"error": {"message": error.message, "code": error.code}},
            )
            return True
        headers["Accept"] = self.headers.get("Accept", "application/json")
        request = Request(target, data=body, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=300)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, OSError):
            self._send_json(502, {"error": "Hermes Agent is unavailable"})
            return True
        try:
            self.send_response(int(response.status))
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-store")
            profile_header = response.headers.get("X-Hermes-Profiles")
            if not profile_header:
                profile_header = ",".join(discover_profile_ids())
            self.send_header("X-Hermes-Profiles", profile_header)
            is_chat_stream = (
                path.endswith("/v1/chat/completions")
                and response.headers.get("Content-Type", "").lower().startswith("text/event-stream")
            )
            response_length = response.headers.get("Content-Length")
            if response_length and not is_chat_stream:
                self.send_header("Content-Length", response_length)
            self.end_headers()
            if is_chat_stream:
                self.wfile.write(_execution_sse_event({
                    "type": "agent",
                    "phase": "accepted",
                    "summary": "Agent 已接收任务",
                }).encode("utf-8") + b"\n\n")
                self.wfile.flush()
            sse_buffer = ""
            stream_read = getattr(response, "read1", response.read)
            while True:
                chunk = stream_read(1024) if is_chat_stream else response.read(65536)
                if not chunk:
                    break
                if not is_chat_stream:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    continue
                sse_buffer += chunk.decode("utf-8", errors="replace").replace("\r", "")
                while "\n\n" in sse_buffer:
                    event_block, sse_buffer = sse_buffer.split("\n\n", 1)
                    normalized = _normalize_chat_sse_event(event_block)
                    self.wfile.write(f"{normalized}\n\n".encode("utf-8"))
                    self.wfile.flush()
            if is_chat_stream and sse_buffer.strip():
                normalized = _normalize_chat_sse_event(sse_buffer)
                self.wfile.write(f"{normalized}\n\n".encode("utf-8"))
                self.wfile.flush()
        finally:
            response.close()
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/hermes-link/v1/server-info":
            adapter = HermesAgentAdapter(
                os.environ.get("HERMES_AGENT_BASE_URL", "http://127.0.0.1:8642")
            )
            runtime = adapter.runtime_status()
            self._send_json(
                200,
                server_info(
                    str(runtime.get("hermes_version") or "unknown"),
                    runtime=runtime,
                ),
            )
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True})
            return
        if parsed.path == "/hermes-link/v1/tasks":
            query = parse_qs(parsed.query)
            try:
                requested_limit = int(query.get("limit", ["200"])[0])
            except ValueError:
                self._send_json(400, {"error": "Invalid limit"})
                return
            limit = max(1, min(requested_limit, 500))
            self._send_json(200, {"tasks": _read_tasks(limit)})
            return
        if parsed.path == "/hermes-link/v1/model-config":
            query = parse_qs(parsed.query)
            profile_id = query.get("profile", ["default"])[0].strip()
            if not PROFILE_ID_PATTERN.fullmatch(profile_id):
                self._send_json(400, {"error": "Invalid profile"})
                return
            model_config = _read_model_config(profile_id)
            if model_config is None:
                self._send_json(404, {"error": "Profile not found"})
                return
            self._send_json(200, model_config)
            return
        if parsed.path == "/hermes-link/v1/logs":
            query = parse_qs(parsed.query)
            log_key = query.get("file", ["gateway"])[0]
            if log_key not in LOG_FILES:
                self._send_json(400, {"error": "Unsupported log file"})
                return
            try:
                requested_limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                self._send_json(400, {"error": "Invalid limit"})
                return
            limit = max(1, min(requested_limit, 200))
            log_path = _log_path(log_key)
            try:
                is_log_file = log_path.is_file()
            except OSError:
                is_log_file = False
            if not is_log_file:
                self._send_json(200, {"file": log_key, "lines": []})
                return
            try:
                lines = _read_tail(log_path, limit)
            except OSError:
                self._send_json(200, {"file": log_key, "lines": []})
                return
            entries = [_parse_line(line, index) for index, line in enumerate(lines)]
            self._send_json(200, {"file": log_key, "lines": entries})
            return
        if self._proxy_agent(parsed):
            return
        if parsed.path != "/hermes-link/v1/logs":
            self._send_json(404, {"error": "Not found"})
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/hermes-link/v1/pairing":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": {"message": "Invalid Content-Length", "code": "pairing_invalid"}})
                return
            if content_length < 0 or content_length > 16 * 1024:
                self._send_json(413, {"error": {"message": "Pairing payload is too large", "code": "pairing_invalid"}})
                return
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": {"message": "Invalid pairing JSON", "code": "pairing_invalid"}})
                return
            status, response = exchange_pairing_payload(payload)
            self._send_json(status, response)
            return
        if not self._proxy_agent(parsed):
            self._send_json(404, {"error": "Not found"})

    def do_PUT(self) -> None:
        if not self._proxy_agent(urlparse(self.path)):
            self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
        if not self._proxy_agent(urlparse(self.path)):
            self._send_json(404, {"error": "Not found"})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/hermes-link/v1/pairing/device":
            token = _bearer_token(self.headers)
            if token.startswith("hmd_"):
                if not revoke_device_token(token):
                    self._send_json(
                        401,
                        {
                            "error": {
                                "message": "Invalid or revoked Hermes Link device token",
                                "code": "device_token_invalid",
                            }
                        },
                    )
                else:
                    self._send_json(200, {"revoked": True})
                return
        if not self._proxy_agent(parsed):
            self._send_json(404, {"error": "Not found"})

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), HermesLinkHandler).serve_forever()
