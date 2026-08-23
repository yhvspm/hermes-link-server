"""Audit the Server tree and Git history before making a repository public.

The scanner deliberately reports only a file and a finding category. It never
prints a matched secret, IP address, hostname, or local path.
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {".git", "build", "dist", "node_modules", "__pycache__"}
TEXT_SUFFIXES = {
    "", ".py", ".sh", ".json", ".json5", ".md", ".toml", ".txt", ".yml", ".yaml",
    ".service", ".conf", ".example", ".patch", ".properties",
}
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?token|push[_-]?token|password|private[_-]?key|client[_-]?secret|app[_-]?secret)\b"
    r"\s*[:=]\s*(['\"])([^'\"]{12,})\1"
)
FORBIDDEN_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("known deployment hostname", re.compile(r"(?i)\bhermes-api\.jusonxl\.com\b")),
    ("known deployment IP range", re.compile(r"\b58\.210\.\d{1,3}\.\d{1,3}\b")),
    ("Windows development path", re.compile(r"(?i)\b[A-Z]:[\\/](?:Users|DATA)[\\/]")),
    ("SSH identity path", re.compile(r"(?i)(?:\.ssh[\\/]|\bssh\s+-i\s+)")),
)


def entropy(value: str) -> float:
    if not value:
        return 0.0
    return -sum((value.count(char) / len(value)) * math.log2(value.count(char) / len(value)) for char in set(value))


def text_findings(text: str) -> set[str]:
    findings: set[str] = set()
    if PRIVATE_KEY.search(text):
        findings.add("private-key literal")
    for match in SENSITIVE_ASSIGNMENT.finditer(text):
        value = match.group(2).strip()
        if not value.startswith(("${", "<")) and "example" not in value.lower() and "change" not in value.lower():
            if len(value) >= 20 and entropy(value) >= 3.5:
                findings.add("credential-like literal")
    for name, pattern in FORBIDDEN_MARKERS:
        if pattern.search(text):
            findings.add(name)
    return findings


def path_findings(path: str) -> set[str]:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if name == ".env" or name.endswith((".pem", ".key")):
        return {"tracked sensitive configuration file"}
    return set()


def is_text_path(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in TEXT_SUFFIXES


def scan_current_tree() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_DIRECTORIES for part in path.parts):
            continue
        relative = path.relative_to(ROOT).as_posix()
        for finding in path_findings(relative):
            findings.append((relative, finding))
        if not is_text_path(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for finding in text_findings(text):
            findings.append((relative, finding))
    return findings


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "-c", f"safe.directory={ROOT.as_posix()}", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def scan_history() -> list[tuple[str, str]]:
    findings: set[tuple[str, str]] = set()
    try:
        commits = [value for value in git_output("rev-list", "--all").splitlines() if value]
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("full Git history is unavailable") from error
    for commit in commits:
        try:
            paths = git_output("ls-tree", "-r", "--name-only", commit).splitlines()
        except subprocess.CalledProcessError as error:
            raise RuntimeError("full Git history is unavailable") from error
        for path in paths:
            for finding in path_findings(path):
                findings.add((path, f"history: {finding}"))
            if not is_text_path(path):
                continue
            try:
                text = git_output("show", f"{commit}:{path}")
            except subprocess.CalledProcessError:
                continue
            for finding in text_findings(text):
                findings.add((path, f"history: {finding}"))
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Link Server public release gate")
    parser.add_argument("--current-only", action="store_true", help="skip full Git history audit")
    args = parser.parse_args(argv)

    findings = [("current", *finding) for finding in scan_current_tree()]
    if not args.current_only:
        try:
            findings.extend(("history", *finding) for finding in scan_history())
        except RuntimeError as error:
            print("Public release gate: BLOCKED")
            print(str(error))
            return 1
    if findings:
        print("Public release gate: FAILED")
        for scope, path, finding in findings:
            print(f"{scope}: {path} ({finding})")
        return 1
    print("Public release gate: PASSED")
    print("Current tree and requested Git history contain no detected secret, known deployment, SSH-path, or tracked sensitive-file markers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
