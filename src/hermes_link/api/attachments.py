"""Validate Hermes Link chat attachments before forwarding them upstream."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any


MAX_ATTACHMENTS = 4
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_TEXT_FILE_BYTES = 512 * 1024
_SAFE_FILENAME = re.compile(r"^[^\\/\x00-\x1f]{1,128}$")
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_TEXT_FILE_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/xml",
    "application/json",
    "application/xml",
    "application/yaml",
    "text/yaml",
}


class ChatAttachmentError(ValueError):
    """A stable, client-safe validation failure for the attachment envelope."""

    def __init__(self, message: str, code: str = "attachment_invalid") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ChatAttachmentError(f"Attachment {field} is required")
    return value


def _decode_attachment(value: object, *, maximum: int) -> bytes:
    encoded = _string(value, "data_base64")
    # Bound encoded input too, before base64 decoding allocates a large buffer.
    if len(encoded) > ((maximum + 2) // 3) * 4 + 8:
        raise ChatAttachmentError("Attachment is too large", "attachment_too_large")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ChatAttachmentError("Attachment data is not valid base64") from None
    if len(decoded) > maximum:
        raise ChatAttachmentError("Attachment is too large", "attachment_too_large")
    return decoded


def _attachment_name(value: object) -> str:
    name = _string(value, "name")
    if not _SAFE_FILENAME.fullmatch(name) or name in {".", ".."}:
        raise ChatAttachmentError("Attachment name is invalid")
    return name


def _append_text_file(content: str, name: str, raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ChatAttachmentError("Text attachment must be UTF-8") from None
    if not text.strip():
        raise ChatAttachmentError("Text attachment is empty")
    prefix = f"[附件：{name}]\n"
    suffix = "\n[附件结束]"
    return f"{content}\n\n{prefix}{text}{suffix}" if content else f"{prefix}{text}{suffix}"


def normalize_chat_attachment_request(payload: bytes | None) -> bytes | None:
    """Convert the Link-only ``attachments`` field to upstream chat content.

    Image attachments retain their native OpenAI ``image_url`` representation.
    The documented file form intentionally accepts only small UTF-8 text-like
    files; Hermes Agent's public chat endpoint does not provide arbitrary file
    upload semantics, so binaries are rejected rather than persisted or exposed.
    """

    if not payload:
        return payload
    try:
        import json

        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise ChatAttachmentError("Chat request must be valid JSON", "chat_request_invalid") from None
    if not isinstance(body, dict):
        raise ChatAttachmentError("Chat request must be a JSON object", "chat_request_invalid")
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise ChatAttachmentError("Chat request messages are required", "chat_request_invalid")

    total_bytes = 0
    for message in messages:
        if not isinstance(message, dict):
            raise ChatAttachmentError("Chat message is invalid", "chat_request_invalid")
        raw_attachments = message.pop("attachments", None)
        if raw_attachments is None:
            continue
        if message.get("role") != "user":
            raise ChatAttachmentError("Only user messages may include attachments")
        if not isinstance(raw_attachments, list) or not raw_attachments:
            raise ChatAttachmentError("Attachments must be a non-empty list")
        if len(raw_attachments) > MAX_ATTACHMENTS:
            raise ChatAttachmentError("Too many attachments", "attachment_count_exceeded")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ChatAttachmentError("Attachment messages must use text content")
        image_parts: list[dict[str, object]] = []
        for attachment in raw_attachments:
            if not isinstance(attachment, dict):
                raise ChatAttachmentError("Attachment is invalid")
            kind = _string(attachment.get("kind"), "kind").lower()
            name = _attachment_name(attachment.get("name"))
            media_type = _string(attachment.get("media_type"), "media_type").lower()
            if kind == "image":
                if media_type not in _IMAGE_TYPES:
                    raise ChatAttachmentError("Unsupported image type", "attachment_type_unsupported")
                raw = _decode_attachment(attachment.get("data_base64"), maximum=MAX_IMAGE_BYTES)
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"},
                    }
                )
            elif kind == "text":
                if media_type not in _TEXT_FILE_TYPES:
                    raise ChatAttachmentError(
                        "Only UTF-8 text, Markdown, JSON, CSV, XML and YAML files are supported",
                        "attachment_type_unsupported",
                    )
                raw = _decode_attachment(attachment.get("data_base64"), maximum=MAX_TEXT_FILE_BYTES)
                content = _append_text_file(content, name, raw)
            else:
                raise ChatAttachmentError("Unsupported attachment kind", "attachment_type_unsupported")
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_BYTES:
                raise ChatAttachmentError("Attachments are too large", "attachment_too_large")
        if image_parts:
            parts: list[dict[str, object]] = []
            if content.strip():
                parts.append({"type": "text", "text": content})
            parts.extend(image_parts)
            message["content"] = parts
        else:
            message["content"] = content
    return json.dumps(body, separators=(",", ":")).encode("utf-8")
