from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "hermes_link"
COMPAT = ROOT / "compat"


def main() -> int:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        if re.search(r"(?m)^\s*(?:from|import)\s+hermes_link_cloud\b", text):
            violations.append(f"Cloud internal import: {relative}")
        if "CloudStore" in text or "HuaweiPushClient" in text:
            violations.append(f"Cloud storage/provider implementation reference: {relative}")
        if re.search(r"(?m)^\s*(?:from|import)\s+agent\b", text) and "integrations/hermes_agent" not in relative.as_posix():
            violations.append(f"Hermes Agent import outside adapter: {relative}")
        if re.search(r"['\"]/(?:api/|v1/chat/)", text) and "integrations/hermes_agent" not in relative.as_posix():
            violations.append(f"Hermes Agent path outside adapter: {relative}")
    for path in COMPAT.rglob("*.patch"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        if re.search(r"(?m)^\+.*\b(?:from|import)\s+hermes_link_cloud\b", text):
            violations.append(f"Cloud internal import in compatibility patch: {relative}")
    required = [
        ROOT / "docs/protocol/hermes-link-v1.md",
        ROOT / "docs/protocol/cloud-v2.md",
        ROOT / "docs/protocol/events-v1.md",
        ROOT / "src/hermes_link/integrations/hermes_agent/adapter.py",
    ]
    for path in required:
        if not path.is_file():
            violations.append(f"missing required boundary file: {path.relative_to(ROOT)}")
    if violations:
        print("Architecture gate: FAILED")
        for violation in violations:
            print(violation)
        return 1
    print("Architecture gate: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
