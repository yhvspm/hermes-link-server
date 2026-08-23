#!/usr/bin/env python3
"""Create and verify immutable Hermes Link Server release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, SCHEMA_VERSION}
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
RELEASE_DOWNLOAD_ASSET_NAMES = {
    "install.sh": "hermes-link-server-install.sh",
    "deploy/standard/compose.yaml": "hermes-link-server-compose.yaml",
    "deploy/standard/Caddyfile": "hermes-link-server-Caddyfile",
    "deploy/standard/.env.example": "hermes-link-server-env.example",
    "deploy/standard/bin/hermes-link": "hermes-link-server-cli",
    "scripts/deployment_helpers.py": "hermes-link-server-deployment-helpers.py",
    "scripts/bootstrap-hermes-agent-access.sh": "hermes-link-server-bootstrap-agent-access.sh",
    "scripts/manage-internal-credential.py": "hermes-link-server-manage-internal-credential.py",
    "scripts/release_manifest.py": "hermes-link-server-release-manifest.py",
}
IMAGE_ARCHIVE_PLATFORM = "linux/amd64"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

OCI_INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
OCI_IMAGE_MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}


class ManifestError(ValueError):
    """Raised when release metadata or an image archive is malformed."""


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


def _image_digest(image: str) -> str:
    return image.rsplit(":", maxsplit=1)[1]


def _validate_relative_path(value: str) -> str:
    if value not in RELEASE_ASSET_PATHS:
        raise ManifestError(f"Unexpected release asset path: {value}")
    return value


def release_asset_name(relative_path: str) -> str:
    _validate_relative_path(relative_path)
    return RELEASE_DOWNLOAD_ASSET_NAMES[relative_path]


def image_archive_name(version: str) -> str:
    _validate_version(version)
    return f"hermes-link-server-{version}-linux-amd64.oci.tar"


def _asset_from_root(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ManifestError(f"Release asset escapes the source root: {relative_path}") from error
    return candidate


def _validate_image_archive(value: Any, *, version: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"name", "sha256", "platform"}:
        raise ManifestError("Release manifest image_archive has unexpected or missing fields")
    name = value["name"]
    digest = value["sha256"]
    platform = value["platform"]
    if name != image_archive_name(version):
        raise ManifestError("Release manifest image_archive name is invalid")
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise ManifestError("Release manifest image_archive has an invalid SHA-256 digest")
    if platform != IMAGE_ARCHIVE_PLATFORM:
        raise ManifestError("Release manifest image_archive platform is unsupported")
    return {"name": name, "sha256": digest, "platform": platform}


def _descriptor_digest(descriptor: Any, *, context: str) -> tuple[str, int]:
    if not isinstance(descriptor, dict):
        raise ManifestError(f"OCI archive {context} descriptor is invalid")
    digest = descriptor.get("digest")
    size = descriptor.get("size")
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise ManifestError(f"OCI archive {context} descriptor has an invalid digest")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ManifestError(f"OCI archive {context} descriptor has an invalid size")
    return digest, size


def _archive_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if member.name.startswith("/") or ".." in path.parts:
            raise ManifestError("OCI archive contains an unsafe path")
        if member.name in members:
            raise ManifestError("OCI archive contains duplicate entries")
        if not member.isdir() and not member.isfile():
            raise ManifestError("OCI archive contains a non-regular entry")
        members[member.name] = member
    return members


def _read_member(
    archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str
) -> bytes:
    member = members.get(name)
    if member is None or not member.isfile():
        raise ManifestError(f"OCI archive is missing required entry: {name}")
    handle = archive.extractfile(member)
    if handle is None:
        raise ManifestError(f"OCI archive cannot read entry: {name}")
    with handle:
        return handle.read()


def _read_json(data: bytes, *, context: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"OCI archive {context} is not valid JSON") from error


def _verify_descriptor_blob(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    descriptor: Any,
    *,
    context: str,
    return_bytes: bool = False,
) -> bytes | None:
    digest, expected_size = _descriptor_digest(descriptor, context=context)
    digest_hex = digest.removeprefix("sha256:")
    name = f"blobs/sha256/{digest_hex}"
    member = members.get(name)
    if member is None or not member.isfile():
        raise ManifestError(f"OCI archive is missing required entry: {name}")
    handle = archive.extractfile(member)
    if handle is None:
        raise ManifestError(f"OCI archive cannot read entry: {name}")
    actual_size = 0
    digest_value = hashlib.sha256()
    chunks: list[bytes] = []
    with handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            actual_size += len(chunk)
            digest_value.update(chunk)
            if return_bytes:
                chunks.append(chunk)
    if actual_size != expected_size or digest_value.hexdigest() != digest_hex:
        raise ManifestError(f"OCI archive {context} blob does not match its descriptor")
    return b"".join(chunks) if return_bytes else None


def _read_descriptor_blob(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    descriptor: Any,
    *,
    context: str,
) -> bytes:
    data = _verify_descriptor_blob(
        archive, members, descriptor, context=context, return_bytes=True
    )
    assert isinstance(data, bytes)
    return data


def _platform_matches(descriptor: Any, *, platform: str) -> bool:
    if not isinstance(descriptor, dict):
        return False
    platform_data = descriptor.get("platform")
    if not isinstance(platform_data, dict):
        return False
    operating_system, architecture = platform.split("/", maxsplit=1)
    return (
        platform_data.get("os") == operating_system
        and platform_data.get("architecture") == architecture
    )


def _verify_image_manifest(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    manifest: Any,
    *,
    platform: str,
) -> None:
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
        raise ManifestError("OCI archive image manifest is invalid")
    config = manifest.get("config")
    config_data = _read_descriptor_blob(archive, members, config, context="image config")
    config_json = _read_json(config_data, context="image config")
    operating_system, architecture = platform.split("/", maxsplit=1)
    if not isinstance(config_json, dict) or (
        config_json.get("os") != operating_system
        or config_json.get("architecture") != architecture
    ):
        raise ManifestError("OCI archive image config does not match the required platform")
    layers = manifest.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ManifestError("OCI archive image manifest has no layers")
    for index, layer in enumerate(layers):
        _verify_descriptor_blob(archive, members, layer, context=f"image layer {index}")


def verify_oci_archive(*, archive_path: Path, image: str, platform: str) -> None:
    """Verify the archive retains the registry digest and requested platform image."""

    if platform != IMAGE_ARCHIVE_PLATFORM:
        raise ManifestError(f"Unsupported OCI archive platform: {platform}")
    expected_digest = "sha256:" + _image_digest(image)
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = _archive_members(archive)
            index = _read_json(
                _read_member(archive, members, "index.json"), context="index"
            )
            if not isinstance(index, dict) or index.get("schemaVersion") != 2:
                raise ManifestError("OCI archive index is invalid")
            descriptors = index.get("manifests")
            if not isinstance(descriptors, list):
                raise ManifestError("OCI archive index has no manifests")
            root_descriptors = [
                descriptor
                for descriptor in descriptors
                if isinstance(descriptor, dict) and descriptor.get("digest") == expected_digest
            ]
            if len(root_descriptors) != 1:
                raise ManifestError("OCI archive does not retain the expected registry image digest")
            root_descriptor = root_descriptors[0]
            root_payload = _read_json(
                _read_descriptor_blob(
                    archive, members, root_descriptor, context="root image"
                ),
                context="root image",
            )
            media_type = root_descriptor.get("mediaType")
            if media_type in OCI_INDEX_MEDIA_TYPES:
                if not isinstance(root_payload, dict) or root_payload.get("schemaVersion") != 2:
                    raise ManifestError("OCI archive image index is invalid")
                child_descriptors = root_payload.get("manifests")
                if not isinstance(child_descriptors, list):
                    raise ManifestError("OCI archive image index has no manifests")
                platform_descriptors = [
                    descriptor
                    for descriptor in child_descriptors
                    if _platform_matches(descriptor, platform=platform)
                ]
                if len(platform_descriptors) != 1:
                    raise ManifestError("OCI archive does not contain exactly one required platform image")
                image_manifest = _read_json(
                    _read_descriptor_blob(
                        archive,
                        members,
                        platform_descriptors[0],
                        context="platform image",
                    ),
                    context="platform image",
                )
            elif media_type in OCI_IMAGE_MANIFEST_MEDIA_TYPES:
                image_manifest = root_payload
            else:
                raise ManifestError("OCI archive root image has an unsupported media type")
            _verify_image_manifest(
                archive, members, image_manifest, platform=platform
            )
    except (OSError, tarfile.TarError) as error:
        raise ManifestError(f"Cannot read OCI image archive: {archive_path}") from error


def create_manifest(
    *,
    root: Path,
    version: str,
    source_commit: str,
    image: str,
    image_archive: Path,
    image_repository: str,
) -> dict[str, Any]:
    _validate_version(version)
    if COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ManifestError("Source commit must be a lowercase 40-character Git SHA")
    _validate_image(image, image_repository)
    if image_archive.name != image_archive_name(version):
        raise ManifestError("OCI image archive name does not match the release version")
    verify_oci_archive(
        archive_path=image_archive, image=image, platform=IMAGE_ARCHIVE_PLATFORM
    )
    files = {
        relative_path: _sha256(_asset_from_root(root, relative_path))
        for relative_path in RELEASE_ASSET_PATHS
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "source_commit": source_commit,
        "image": image,
        "image_archive": {
            "name": image_archive.name,
            "sha256": _sha256(image_archive),
            "platform": IMAGE_ARCHIVE_PLATFORM,
        },
        "files": files,
    }
    validate_manifest(manifest, image_repository=image_repository, version=version)
    return manifest


def validate_manifest(
    manifest: Any, *, image_repository: str, version: str | None = None
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ManifestError("Release manifest must be a JSON object")
    schema_version = manifest.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise ManifestError(f"Unsupported release manifest schema: {schema_version!r}")
    expected_keys = {"schema_version", "version", "source_commit", "image", "files"}
    if schema_version == SCHEMA_VERSION:
        expected_keys.add("image_archive")
    if set(manifest) != expected_keys:
        raise ManifestError("Release manifest has unexpected or missing fields")
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
    if schema_version == SCHEMA_VERSION:
        _validate_image_archive(manifest["image_archive"], version=manifest["version"])
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
    create.add_argument("--image-archive", type=Path, required=True)
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

    image_archive = subcommands.add_parser(
        "image-archive", help="print the verified OCI image archive name"
    )
    image_archive.add_argument("--manifest", type=Path, required=True)
    image_archive.add_argument("--version")
    image_archive.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)

    verify_file = subcommands.add_parser("verify-file", help="verify one downloaded release asset")
    verify_file.add_argument("--manifest", type=Path, required=True)
    verify_file.add_argument("--version")
    verify_file.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)
    verify_file.add_argument("--path", required=True)
    verify_file.add_argument("--file", type=Path, required=True)

    verify_archive = subcommands.add_parser(
        "verify-image-archive", help="verify a manifest-bound OCI image archive"
    )
    verify_archive.add_argument("--manifest", type=Path, required=True)
    verify_archive.add_argument("--version")
    verify_archive.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)
    verify_archive.add_argument("--file", type=Path, required=True)

    verify_oci = subcommands.add_parser(
        "verify-oci-archive", help="verify an OCI archive retains an immutable image digest"
    )
    verify_oci.add_argument("--archive", type=Path, required=True)
    verify_oci.add_argument("--image", required=True)
    verify_oci.add_argument("--platform", default=IMAGE_ARCHIVE_PLATFORM)
    verify_oci.add_argument("--image-repository", default=OFFICIAL_IMAGE_REPOSITORY)

    asset_name = subcommands.add_parser(
        "release-asset-name", help="print the GitHub Release asset name for a source asset"
    )
    asset_name.add_argument("--path", required=True)
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
                image_archive=args.image_archive,
                image_repository=args.image_repository,
            )
            write_manifest(args.output, manifest)
            return 0
        if args.command == "release-asset-name":
            print(release_asset_name(args.path))
            return 0
        if args.command == "verify-oci-archive":
            _validate_image(args.image, args.image_repository)
            verify_oci_archive(
                archive_path=args.archive, image=args.image, platform=args.platform
            )
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
        if args.command == "image-archive":
            image_archive = manifest.get("image_archive")
            if image_archive is None:
                raise ManifestError("Release manifest does not contain an OCI image archive")
            print(image_archive["name"])
            return 0
        if args.command == "verify-file":
            relative_path = _validate_relative_path(args.path)
            actual = _sha256(args.file)
            if actual != manifest["files"][relative_path]:
                raise ManifestError(f"SHA-256 mismatch for {relative_path}")
            return 0
        if args.command == "verify-image-archive":
            image_archive = manifest.get("image_archive")
            if image_archive is None:
                raise ManifestError("Release manifest does not contain an OCI image archive")
            if _sha256(args.file) != image_archive["sha256"]:
                raise ManifestError("OCI image archive SHA-256 mismatch")
            verify_oci_archive(
                archive_path=args.file,
                image=manifest["image"],
                platform=image_archive["platform"],
            )
            return 0
    except ManifestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
