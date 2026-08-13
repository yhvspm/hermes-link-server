"""Export fixed Hermes diagnostic logs after mandatory redaction.

This process is intended for the Docker log-exporter sidecar. It can read only
the mounted ``logs/`` directory and writes redacted copies for the unprivileged
Hermes Link Server container. It never prints raw log content.
"""

from __future__ import annotations

import os
import time
from collections import deque
from pathlib import Path

from hermes_link.security.redaction import redact_sensitive_text


LOG_FILES = ("agent.log", "errors.log", "gateway.log")
DEFAULT_LIMIT = 200


def _redacted_tail(path: Path, limit: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            source_lines = list(deque(handle, maxlen=limit))
    except OSError:
        return []
    return [
        redact_sensitive_text(
            line.rstrip("\n"),
            force=True,
            redact_url_credentials=True,
        )[:2000]
        for line in source_lines
    ]


def export_redacted_logs(source_directory: Path, output_directory: Path, *, limit: int = DEFAULT_LIMIT) -> dict[str, int]:
    """Atomically export only the fixed log allowlist as redacted text."""
    output_directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        output_directory.chmod(0o755)
    except OSError:
        pass
    exported: dict[str, int] = {}
    for filename in LOG_FILES:
        lines = _redacted_tail(source_directory / filename, limit)
        temporary_path = output_directory / f".{filename}.tmp"
        destination = output_directory / filename
        temporary_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        temporary_path.chmod(0o644)
        temporary_path.replace(destination)
        exported[filename] = len(lines)
    return exported


def main() -> None:
    source_directory = Path(os.environ.get("HERMES_LINK_RAW_LOG_DIR", "/var/lib/hermes-agent-logs"))
    output_directory = Path(os.environ.get("HERMES_LINK_REDACTED_LOG_DIR", "/var/lib/hermes-link-server/redacted-logs"))
    try:
        interval_seconds = max(1, min(int(os.environ.get("HERMES_LINK_LOG_EXPORT_INTERVAL", "2")), 60))
    except ValueError:
        interval_seconds = 2
    while True:
        export_redacted_logs(source_directory, output_directory)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
