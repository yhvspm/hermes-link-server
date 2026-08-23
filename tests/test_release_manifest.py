from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_manifest", ROOT / "scripts" / "release_manifest.py"
)
assert SPEC is not None and SPEC.loader is not None
release_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_manifest)


class ReleaseManifestTests(unittest.TestCase):
    version = "1.0.1"
    source_commit = "a" * 40

    @staticmethod
    def write_archive_member(archive: tarfile.TarFile, name: str, contents: bytes) -> None:
        member = tarfile.TarInfo(name)
        member.size = len(contents)
        archive.addfile(member, io.BytesIO(contents))

    def write_image_archive(self, root: Path) -> tuple[Path, str]:
        config = json.dumps(
            {"architecture": "amd64", "os": "linux"}, separators=(",", ":")
        ).encode("utf-8")
        layer = b"hermes-link-server-test-layer\n"
        config_digest = release_manifest.hashlib.sha256(config).hexdigest()
        layer_digest = release_manifest.hashlib.sha256(layer).hexdigest()
        image_manifest = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": f"sha256:{config_digest}",
                    "size": len(config),
                },
                "layers": [
                    {
                        "mediaType": "application/vnd.oci.image.layer.v1.tar",
                        "digest": f"sha256:{layer_digest}",
                        "size": len(layer),
                    }
                ],
            },
            separators=(",", ":"),
        ).encode("utf-8")
        image_digest = release_manifest.hashlib.sha256(image_manifest).hexdigest()
        index = json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": f"sha256:{image_digest}",
                        "size": len(image_manifest),
                        "platform": {"architecture": "amd64", "os": "linux"},
                    }
                ],
            },
            separators=(",", ":"),
        ).encode("utf-8")
        archive_path = root / release_manifest.image_archive_name(self.version)
        with tarfile.open(archive_path, mode="w") as archive:
            self.write_archive_member(archive, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
            self.write_archive_member(archive, "index.json", index)
            self.write_archive_member(
                archive, f"blobs/sha256/{config_digest}", config
            )
            self.write_archive_member(
                archive, f"blobs/sha256/{layer_digest}", layer
            )
            self.write_archive_member(
                archive, f"blobs/sha256/{image_digest}", image_manifest
            )
        return (
            archive_path,
            "ghcr.io/yhvspm/hermes-link-server@sha256:" + image_digest,
        )

    def write_release_tree(self, root: Path) -> None:
        for relative_path in release_manifest.RELEASE_ASSET_PATHS:
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"asset: {relative_path}\n", encoding="utf-8")

    def create_manifest(self, root: Path) -> dict[str, object]:
        archive, image = self.write_image_archive(root)
        return release_manifest.create_manifest(
            root=root,
            version=self.version,
            source_commit=self.source_commit,
            image=image,
            image_archive=archive,
            image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
        )

    def test_create_manifest_binds_every_required_asset_and_image_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            manifest = self.create_manifest(root)
            manifest_path = root / "release-manifest.json"
            release_manifest.write_manifest(manifest_path, manifest)

            loaded = release_manifest.load_manifest(
                manifest_path,
                image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                version=self.version,
            )

            self.assertEqual(loaded["image"], manifest["image"])
            self.assertEqual(set(loaded["files"]), set(release_manifest.RELEASE_ASSET_PATHS))
            self.assertEqual(
                loaded["image_archive"]["name"],
                release_manifest.image_archive_name(self.version),
            )
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["source_commit"],
                self.source_commit,
            )

    def test_manifest_rejects_mutable_image_missing_assets_and_invalid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            manifest = self.create_manifest(root)
            manifest["image"] = "ghcr.io/yhvspm/hermes-link-server:1.0.1"
            with self.assertRaises(release_manifest.ManifestError):
                release_manifest.validate_manifest(
                    manifest,
                    image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                )

            manifest = self.create_manifest(root)
            manifest["files"].pop("install.sh")
            with self.assertRaises(release_manifest.ManifestError):
                release_manifest.validate_manifest(
                    manifest,
                    image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                )

            manifest = self.create_manifest(root)
            manifest["image_archive"]["name"] = "unexpected.tar"
            with self.assertRaises(release_manifest.ManifestError):
                release_manifest.validate_manifest(
                    manifest,
                    image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                )

            manifest = self.create_manifest(root)
            manifest["schema_version"] = 2.0
            with self.assertRaises(release_manifest.ManifestError):
                release_manifest.validate_manifest(
                    manifest,
                    image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                )

    def test_verify_file_and_archive_fail_after_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            manifest = self.create_manifest(root)
            manifest_path = root / "release-manifest.json"
            release_manifest.write_manifest(manifest_path, manifest)
            asset = root / "install.sh"
            file_arguments = [
                "verify-file",
                "--manifest",
                str(manifest_path),
                "--version",
                self.version,
                "--path",
                "install.sh",
                "--file",
                str(asset),
            ]

            self.assertEqual(release_manifest.main(file_arguments), 0)
            asset.write_text("changed\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_manifest.main(file_arguments), 1)

            archive = root / manifest["image_archive"]["name"]
            archive_arguments = [
                "verify-image-archive",
                "--manifest",
                str(manifest_path),
                "--version",
                self.version,
                "--file",
                str(archive),
            ]
            self.assertEqual(release_manifest.main(archive_arguments), 0)
            with archive.open("ab") as handle:
                handle.write(b"tampered")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_manifest.main(archive_arguments), 1)

    def test_schema_one_manifest_remains_readable_for_existing_installations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            manifest = self.create_manifest(root)
            manifest["schema_version"] = 1
            manifest.pop("image_archive")

            validated = release_manifest.validate_manifest(
                manifest,
                image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
            )

            self.assertEqual(validated["schema_version"], 1)

    def test_release_asset_names_cover_every_verified_source_asset(self) -> None:
        self.assertEqual(
            set(release_manifest.RELEASE_DOWNLOAD_ASSET_NAMES),
            set(release_manifest.RELEASE_ASSET_PATHS),
        )
        self.assertEqual(
            len(set(release_manifest.RELEASE_DOWNLOAD_ASSET_NAMES.values())),
            len(release_manifest.RELEASE_ASSET_PATHS),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                release_manifest.main(
                    ["release-asset-name", "--path", "deploy/standard/compose.yaml"]
                ),
                0,
            )

    def test_create_rejects_an_invalid_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            archive, image = self.write_image_archive(root)
            with self.assertRaises(release_manifest.ManifestError):
                release_manifest.create_manifest(
                    root=root,
                    version=self.version,
                    source_commit="not-a-git-sha",
                    image=image,
                    image_archive=archive,
                    image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                )
