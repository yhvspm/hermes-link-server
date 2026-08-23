#!/usr/bin/env python3
"""Create and verify the immutable Hermes Link Server release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
OFFICIAL_IMAGE_REPOSITORY = "ghcr.io/yhvspm/hermes-link-server"
RELEASE_ASSET_PATHS = (
    "install.sh",
    "deploy/standard/compose.yaml",
    "deploy/standard/Caddyfile",
    "deploy/standard/.env.example",
    "deploy/standard/bin/hermes-link",
    "scripts/deployment_helpers.py",
    "scripts/bootstrap-hermes-agent-access.sh",
    "scripts/manage-internal-credential.py",
    "scripts/release_manifest.py",
)
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ManifestError(ValueError):
    """Raised when release metadata is malformed or does not match an asset."""


def _sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ManifestError(f"Release asset must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_version(value: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ManifestError("Version must be a pinned semantic version")
    return value


def _validate_image(value: str, image_repository: str) -> str:
    expected = re.escape(image_repository) + r"@sha256:([0-9a-f]{64})"
    if re.fullmatch(expected, value) is None:
        raise ManifestError(
            "Image must be an immutable SHA-256 digest for " + image_repository
        )
    return value


def _validate_relative_path(value: str) -> str:
    if value not in RELEASE_ASSET_PATHS:
        raise ManifestError(f"Unexpected release asset path: {value}")
    return value


def _asset_from_root(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ManifestError(f"Release asset escapes the source root: {relative_path}") from error
    return candidate


def create_manifest(
    *, root: Path, version: str, source_commit: str, image: str, image_repository: str
) -> dict[str, Any]:
    _validate_version(version)
    if COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ManifestError("Source commit must be a lowercase 40-character Git SHA")
    _validate_image(image, image_repository)
    files = {
        relative_path: _sha256(_asset_from_root(root, relative_path))
        for relative_path in RELEASE_ASSET_PATHS
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "source_commit": source_commit,
        "image": image,
        "files": files,
    }
    validate_manifest(manifest, image_repository=image_repository, version=version)
    return manifest


def validate_manifest(
    manifest: Any, *, image_repository: str, version: str | None = None
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ManifestError("Release manifest must be a JSON object")
    expected_keys = {"schema_version", "version", "source_commit", "image", "files"}
    if set(manifest) != expected_keys:
        raise ManifestError("Release manifest has unexpected or missing fields")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(f"Unsupported release manifest schema: {manifest['schema_version']!r}")
    if not isinstance(manifest["version"], str):
        raise ManifestError("Release manifest version must be a string")
    _validate_version(manifest["version"])
    if version is not None and manifest["version"] != version:
        raise ManifestError(
            f"Release manifest version {manifest['version']} does not match requested {version}"
        )
    if not isinstance(manifest["source_commit"], str) or COMMIT_PATTERN.fullmatch(
        manifest["source_commit"]
    ) is None:
        raise ManifestError("Release manifest source_commit must be a lowercase 40-character Git SHA")
    if not isinstance(manifest["image"], str):
        raise ManifestError("Release manifest image must be a string")
    _validate_image(manifest["image"], image_repository)
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != set(RELEASE_ASSET_PATHS):
        raise ManifestError("Release manifest files must contain exactly the supported release assets")
    for relative_path, digest in files.items():
        _validate_relative_path(relative_path)
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise ManifestError(f"Release manifest has an invalid SHA-256 digest for {relative_path}")
    return manifest


def load_manifest(path: Path, *, image_repository: str, version: str | None = None) -> dict[str, Any]:
    try:
        contents = path.read_text(encoding="utf-8")
        parsed = json.loads(contents)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"Cannot read release manifest: {path}") from error
    return validate_manifest(parsed, image_repository=image_repository, version=version)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create", help="create a deterministic release manifest")
    create.add_argument("--root", type=Path, default=Path.cwd())
    create.add_argument("--version", required=True)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--image", required=True)
    create.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)
    create.add_argument("--output", type=Path, required=True)

    verify = subcommands.add_parser("verify", help="validate release-manifest.json metadata")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--version")
    verify.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)

    image = subcommands.add_parser("image", help="print the verified immutable image reference")
    image.add_argument("--manifest", type=Path, required=True)
    image.add_argument("--version")
    image.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)

    verify_file = subcommands.add_parser("verify-file", help="verify one downloaded release asset")
    verify_file.add_argument("--manifest", type=Path, required=True)
    verify_file.add_argument("--version")
    verify_file.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)
    verify_file.add_argument("--path", required=True)
    verify_file.add_argument("--file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_manifest(
                root=args.root,
                version=args.version,
                source_commit=args.source_commit,
                image=args.image,
                image_repository=args.image_repository,
            )
            write_manifest(args.output, manifest)
            return 0

        manifest = load_manifest(
            args.manifest,
            image_repository=args.image_repository,
            version=args.version,
        )
        if args.command == "verify":
            return 0
        if args.command == "image":
            print(manifest["image"])
            return 0
        if args.command == "verify-file":
            relative_path = _validate_relative_path(args.path)
            actual = _sha256(args.file)
            if actual != manifest["files"][relative_path]:
                raise ManifestError(f"SHA-256 mismatch for {relative_path}")
            return 0
    except ManifestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
