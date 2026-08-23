"""Small dependency-free secret gate that never prints matched values."""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".hvigor", ".test", "build", "dist", "node_modules", "oh_modules", "__pycache__"}
TEXT_SUFFIXES = {
    "", ".py", ".sh", ".ets", ".ts", ".js", ".json", ".json5", ".md", ".yml", ".yaml",
    ".toml", ".txt", ".service", ".conf", ".example", ".patch", ".properties",
}
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?token|push[_-]?token|password|private[_-]?key|client[_-]?secret|app[_-]?secret)\b"
    r"\s*[:=]\s*(['\"])([^'\"]{12,})\1"
)


def entropy(value: str) -> float:
    if not value:
        return 0.0
    return -sum((value.count(char) / len(value)) * math.log2(value.count(char) / len(value)) for char in set(value))


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            if PRIVATE_KEY.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{number}: private-key literal")
            for match in SENSITIVE_ASSIGNMENT.finditer(line):
                value = match.group(2).strip()
                if value.startswith(("${", "<")) or "example" in value.lower() or "change" in value.lower():
                    continue
                if len(value) >= 20 and entropy(value) >= 3.5:
                    findings.append(f"{path.relative_to(ROOT)}:{number}: credential-like literal")
    if findings:
        print("Secret scan: FOUND")
        for finding in findings:
            print(finding)
        return 1
    print("Secret scan: NOT FOUND")
    return 0


if __name__ == "__main__":
    sys.exit(main())
