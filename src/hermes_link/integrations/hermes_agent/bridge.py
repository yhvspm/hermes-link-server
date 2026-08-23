#!/usr/bin/env python3
"""Hermes Link Protocol facade and Hermes Agent compatibility adapter."""

from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import threading
import uuid
from collections import deque
from collections.abc import Callable
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
from hermes_link.identity import (
    clear_cloud_config,
    configure_cloud,
    create_cloud_binding_attestation,
    get_or_create_identity,
    load_cloud_config,
    public_identity,
)
from hermes_link.integrations.hermes_agent.adapter import (
    DeviceAuthorizationError,
    HermesAgentAdapter,
    _bearer_token,
    _profile_id_for_protocol_path,
    prepare_agent_headers,
    protocol_to_agent_path,
)
from hermes_link.notifications.cloud_sender import CloudEventSender, CloudTransportError
from hermes_link.pairing.http import exchange_pairing_payload
from hermes_link.pairing.store import device_profile_ids, revoke_device_token


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
PROXY_UPSTREAM_TIMEOUT_SECONDS = 300
CHAT_STREAM_UPSTREAM_TIMEOUT_SECONDS = 3600


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


def _chat_stream_terminal_state(event_block: str) -> str:
    """Return the terminal state of one OpenAI-compatible chat SSE block."""

    data_parts: list[str] = []
    for line in event_block.split("\n"):
        if line.startswith("data:"):
            data_parts.append(line[5:].strip())
    data = "\n".join(data_parts).strip()
    if data == "[DONE]":
        return "completed"
    if not data:
        return ""
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    finish_reason = choices[0].get("finish_reason")
    if finish_reason is None:
        return ""
    normalized_reason = str(finish_reason).strip().lower()
    if normalized_reason in {"error", "cancel", "cancelled", "canceled"}:
        return "failed"
    return "completed"


def _relay_chat_stream(
    response: object,
    write_chunk: Callable[[bytes], bool],
) -> str:
    """Relay a chat stream while draining Agent output after client disconnect."""

    sse_buffer = ""
    chat_terminal_state = ""
    client_connected = True
    stream_read = getattr(response, "read1", None)
    if stream_read is None:
        stream_read = response.read  # type: ignore[attr-defined]
    while True:
        chunk = stream_read(1024)
        if not chunk:
            break
        sse_buffer += chunk.decode("utf-8", errors="replace").replace("\r", "")
        while "\n\n" in sse_buffer:
            event_block, sse_buffer = sse_buffer.split("\n\n", 1)
            terminal_state = _chat_stream_terminal_state(event_block)
            if terminal_state:
                chat_terminal_state = terminal_state
            normalized = _normalize_chat_sse_event(event_block)
            if client_connected:
                try:
                    client_connected = write_chunk(f"{normalized}\n\n".encode("utf-8"))
                except OSError:
                    client_connected = False
    if sse_buffer.strip():
        terminal_state = _chat_stream_terminal_state(sse_buffer)
        if terminal_state:
            chat_terminal_state = terminal_state
        normalized = _normalize_chat_sse_event(sse_buffer)
        if client_connected:
            try:
                write_chunk(f"{normalized}\n\n".encode("utf-8"))
            except OSError:
                pass
    return chat_terminal_state


def _publish_cloud_chat_completed(profile_id: str, session_id: str) -> None:
    """Publish a content-free Cloud event after a completed chat stream."""

    if not profile_id or not session_id:
        return
    try:
        config = load_cloud_config()
        if not config:
            return
        identity = get_or_create_identity()
        if config.get("server_id") != identity["server_id"]:
            return
        run_id = f"run_{uuid.uuid4().hex}"
        CloudEventSender(
            config["cloud_url"],
            identity["server_id"],
            identity["private_key_pem"],
        ).publish(
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "event_type": "chat.completed",
                "profile_id": profile_id,
                "session_id": session_id,
                "run_id": run_id,
                "dedupe_key": f"chat:{session_id}:{run_id}",
            },
            config["installation_id"],
        )
    except (CloudTransportError, KeyError, OSError, RuntimeError, ValueError):
        return


def _schedule_cloud_chat_completed(profile_id: str, session_id: str) -> None:
    if not profile_id or not session_id:
        return
    threading.Thread(
        target=_publish_cloud_chat_completed,
        args=(profile_id, session_id),
        daemon=True,
    ).start()


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

    def _cloud_control_profiles(self) -> list[str] | None:
        """Authorize a local Cloud control request without forwarding it to Agent."""

        token = _bearer_token(self.headers)
        if token.startswith("hmd_"):
            profiles = device_profile_ids(token)
            if profiles is None:
                return None
            return profiles or discover_profile_ids()
        expected = (
            os.environ.get("HERMES_LINK_MOBILE_API_TOKEN", "").strip()
            or os.environ.get("HERMES_LINK_AGENT_TOKEN", "").strip()
        )
        if len(expected) < 8 or not token or not hmac.compare_digest(token, expected):
            return None
        return discover_profile_ids()

    def _read_local_json(self, *, limit: int = 16 * 1024) -> dict[str, object] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": {"message": "Invalid Content-Length", "code": "cloud_request_invalid"}})
            return None
        if content_length < 0 or content_length > limit:
            self._send_json(413, {"error": {"message": "Cloud payload is too large", "code": "cloud_request_invalid"}})
            return None
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": {"message": "Invalid Cloud JSON", "code": "cloud_request_invalid"}})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": {"message": "Cloud payload must be an object", "code": "cloud_request_invalid"}})
            return None
        return payload

    def _write_chat_stream_chunk(self, chunk: bytes) -> bool:
        try:
            self.wfile.write(chunk)
            self.wfile.flush()
            return True
        except OSError:
            return False

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
        is_chat_request = path.endswith("/v1/chat/completions")
        try:
            response = urlopen(
                request,
                timeout=(
                    CHAT_STREAM_UPSTREAM_TIMEOUT_SECONDS
                    if is_chat_request else PROXY_UPSTREAM_TIMEOUT_SECONDS
                ),
            )
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
            client_connected = True
            try:
                self.end_headers()
            except OSError:
                if not is_chat_stream:
                    return True
                client_connected = False
            chat_terminal_state = ""
            if is_chat_stream:
                if client_connected:
                    client_connected = self._write_chat_stream_chunk(
                        _execution_sse_event({
                            "type": "agent",
                            "phase": "accepted",
                            "summary": "Agent 已接收任务",
                        }).encode("utf-8") + b"\n\n"
                    )
                chat_terminal_state = _relay_chat_stream(
                    response,
                    self._write_chat_stream_chunk if client_connected else lambda _chunk: False,
                )
            else:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        finally:
            response.close()
        if is_chat_stream and chat_terminal_state == "completed":
            _schedule_cloud_chat_completed(
                _profile_id_for_protocol_path(parsed.path),  # type: ignore[attr-defined]
                str(self.headers.get("X-Hermes-Session-Id", "")).strip(),
            )
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/hermes-link/v1/server-info":
            adapter = HermesAgentAdapter(
                os.environ.get("HERMES_AGENT_BASE_URL", "http://127.0.0.1:8642")
            )
            runtime = adapter.runtime_status()
            identity: dict[str, str] | None = None
            try:
                identity = public_identity()
            except (OSError, RuntimeError, ValueError):
                identity = None
            self._send_json(
                200,
                server_info(
                    str(runtime.get("hermes_version") or "unknown"),
                    runtime=runtime,
                    features={"cloudMultiBinding": identity is not None},
                    server_id=identity["server_id"] if identity is not None else None,
                ),
            )
            return
        if parsed.path == "/hermes-link/v1/cloud/identity":
            profiles = self._cloud_control_profiles()
            if profiles is None:
                self._send_json(401, {"error": {"message": "Cloud control authorization failed", "code": "cloud_control_unauthorized"}})
                return
            try:
                identity = public_identity()
            except (OSError, RuntimeError, ValueError):
                self._send_json(503, {"error": {"message": "Hermes Server Cloud identity is unavailable", "code": "cloud_identity_unavailable"}})
                return
            self._send_json(
                200,
                {
                    "schema_version": 2,
                    "server_id": identity["server_id"],
                    "public_key": identity["public_key"],
                    "profiles": profiles,
                },
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
        if parsed.path == "/hermes-link/v1/cloud/attestation":
            profiles = self._cloud_control_profiles()
            if profiles is None:
                self._send_json(401, {"error": {"message": "Cloud control authorization failed", "code": "cloud_control_unauthorized"}})
                return
            payload = self._read_local_json()
            if payload is None:
                return
            if set(payload) - {"schema_version", "cloud_url", "installation_id"}:
                self._send_json(400, {"error": {"message": "Cloud attestation fields are invalid", "code": "cloud_attestation_invalid"}})
                return
            try:
                result = create_cloud_binding_attestation(payload, profiles)
            except (OSError, RuntimeError, ValueError):
                self._send_json(400, {"error": {"message": "Cloud attestation is invalid", "code": "cloud_attestation_invalid"}})
                return
            self._send_json(200, result)
            return
        if parsed.path == "/hermes-link/v1/cloud/configure":
            if self._cloud_control_profiles() is None:
                self._send_json(401, {"error": {"message": "Cloud control authorization failed", "code": "cloud_control_unauthorized"}})
                return
            payload = self._read_local_json()
            if payload is None:
                return
            if set(payload) - {"schema_version", "cloud_url", "installation_id", "server_id"}:
                self._send_json(400, {"error": {"message": "Cloud configuration fields are invalid", "code": "cloud_config_invalid"}})
                return
            try:
                self._send_json(200, configure_cloud(payload))
            except ValueError:
                self._send_json(400, {"error": {"message": "Cloud configuration is invalid", "code": "cloud_config_invalid"}})
            except (OSError, RuntimeError):
                self._send_json(503, {"error": {"message": "Cloud configuration is unavailable", "code": "cloud_config_unavailable"}})
            return
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
        if parsed.path == "/hermes-link/v1/cloud/configure":
            if self._cloud_control_profiles() is None:
                self._send_json(401, {"error": {"message": "Cloud control authorization failed", "code": "cloud_control_unauthorized"}})
                return
            try:
                self._send_json(200, clear_cloud_config())
            except OSError:
                self._send_json(503, {"error": {"message": "Cloud configuration is unavailable", "code": "cloud_config_unavailable"}})
            return
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
