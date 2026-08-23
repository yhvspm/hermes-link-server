#!/usr/bin/env python3
"""Small, non-secret helpers shared by the standard installer and CLI.

The helpers intentionally operate on deployment metadata only.  In particular,
Profile discovery reads directory names but never Profile contents, and the
identity helper returns only the public server identifier.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any


PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SERVER_ID_PATTERN = re.compile(r"^server_[A-Za-z0-9_-]{16,128}$")
HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_public_host(value: str) -> str:
    """Return a normalized DNS hostname suitable for public HTTPS."""

    raw = str(value).strip().rstrip(".")
    if not raw:
        raise ValueError("domain is required")
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        pass
    else:
        raise ValueError("domain must be a DNS hostname, not an IP address")
    try:
        host = raw.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("domain is not a valid DNS hostname") from error
    if len(host) > 253 or "." not in host:
        raise ValueError("domain must be a public DNS hostname")
    labels = host.split(".")
    if any(not HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise ValueError("domain is not a valid DNS hostname")
    return host


def normalize_public_port(value: str | int) -> int:
    """Validate a user-selectable TCP port without reserving it."""

    try:
        port = int(str(value).strip())
    except ValueError as error:
        raise ValueError("public port must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("public port must be in 1..65535")
    return port


def public_url(host: str, port: int) -> str:
    """Build the App-facing origin, omitting the default HTTPS port."""

    return f"https://{host}" if port == 443 else f"https://{host}:{port}"


def discover_profile_ids(hermes_home: Path) -> list[str]:
    """Discover only valid Profile directory names, retaining ``default``."""

    if not hermes_home.is_dir():
        raise ValueError(f"Hermes metadata directory is unavailable: {hermes_home}")
    profile_ids = ["default"]
    profiles_directory = hermes_home / "profiles"
    try:
        candidates = sorted(profiles_directory.iterdir(), key=lambda path: path.name)
    except FileNotFoundError:
        return profile_ids
    except OSError as error:
        raise ValueError("Hermes Profile directory cannot be read") from error
    for candidate in candidates:
        profile_id = candidate.name
        try:
            is_directory = candidate.is_dir()
        except OSError:
            continue
        if (
            is_directory
            and profile_id != "default"
            and PROFILE_ID_PATTERN.fullmatch(profile_id)
        ):
            profile_ids.append(profile_id)
    return profile_ids


def read_server_id(identity_file: Path) -> str:
    """Read and validate only ``server_id`` from a persisted identity file."""

    try:
        payload = json.loads(identity_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Server identity file cannot be read") from error
    server_id = payload.get("server_id") if isinstance(payload, dict) else None
    if not isinstance(server_id, str) or not SERVER_ID_PATTERN.fullmatch(server_id):
        raise ValueError("Server identity file does not contain a valid server ID")
    return server_id


def inspect_server_info(payload: Any) -> tuple[str, int, str, bool]:
    """Extract non-sensitive diagnostic fields from ``/server-info``."""

    if not isinstance(payload, dict):
        raise ValueError("server-info response must be a JSON object")
    gateway_state = payload.get("gateway_state")
    if not isinstance(gateway_state, str) or not gateway_state:
        gateway_state = "unavailable"
    active_agents = payload.get("active_agents", 0)
    if isinstance(active_agents, bool) or not isinstance(active_agents, int) or active_agents < 0:
        active_agents = 0
    server_id = payload.get("serverId", "")
    if not isinstance(server_id, str) or not SERVER_ID_PATTERN.fullmatch(server_id):
        server_id = ""
    features = payload.get("features")
    cloud_multi_binding = bool(features.get("cloudMultiBinding", False)) if isinstance(features, dict) else False
    return gateway_state.replace("\t", " "), active_agents, server_id, cloud_multi_binding


def _endpoint_command(args: argparse.Namespace) -> int:
    host = normalize_public_host(args.host)
    port = normalize_public_port(args.port)
    print(f"{host}\t{port}\t{public_url(host, port)}")
    return 0


def _profiles_command(args: argparse.Namespace) -> int:
    print("\n".join(discover_profile_ids(Path(args.hermes_home))))
    return 0


def _server_id_command(args: argparse.Namespace) -> int:
    print(read_server_id(Path(args.identity_file)))
    return 0


def _server_info_command(_args: argparse.Namespace) -> int:
    gateway_state, active_agents, server_id, cloud_multi_binding = inspect_server_info(json.load(sys.stdin))
    print(f"{gateway_state}\t{active_agents}\t{server_id}\t{str(cloud_multi_binding).lower()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Link deployment metadata helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    endpoint = subparsers.add_parser("endpoint", help="validate a public HTTPS endpoint")
    endpoint.add_argument("--host", required=True)
    endpoint.add_argument("--port", required=True)
    endpoint.set_defaults(handler=_endpoint_command)

    profiles = subparsers.add_parser("profiles", help="list visible Hermes Profile IDs")
    profiles.add_argument("--hermes-home", required=True)
    profiles.set_defaults(handler=_profiles_command)

    server_id = subparsers.add_parser("server-id", help="read a persisted public server ID")
    server_id.add_argument("--identity-file", required=True)
    server_id.set_defaults(handler=_server_id_command)

    server_info = subparsers.add_parser("server-info", help="inspect a server-info JSON response")
    server_info.set_defaults(handler=_server_info_command)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
