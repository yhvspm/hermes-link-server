from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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
    version = "1.0.0"
    source_commit = "a" * 40
    image = "ghcr.io/yhvspm/hermes-link-server@sha256:" + "b" * 64

    def write_release_tree(self, root: Path) -> None:
        for relative_path in release_manifest.RELEASE_ASSET_PATHS:
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"asset: {relative_path}\n", encoding="utf-8")

    def create_manifest(self, root: Path) -> dict[str, object]:
        return release_manifest.create_manifest(
            root=root,
            version=self.version,
            source_commit=self.source_commit,
            image=self.image,
            image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
        )

    def test_create_manifest_binds_every_required_asset_and_digest_image(self) -> None:
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

            self.assertEqual(loaded["image"], self.image)
            self.assertEqual(set(loaded["files"]), set(release_manifest.RELEASE_ASSET_PATHS))
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["source_commit"],
                self.source_commit,
            )

    def test_manifest_rejects_mutable_image_and_missing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            manifest = self.create_manifest(root)
            manifest["image"] = "ghcr.io/yhvspm/hermes-link-server:1.0.0"
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

    def test_verify_file_fails_after_an_asset_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            manifest_path = root / "release-manifest.json"
            release_manifest.write_manifest(manifest_path, self.create_manifest(root))
            asset = root / "install.sh"
            arguments = [
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

            self.assertEqual(release_manifest.main(arguments), 0)
            asset.write_text("changed\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_manifest.main(arguments), 1)

    def test_create_rejects_an_invalid_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_release_tree(root)
            with self.assertRaises(release_manifest.ManifestError):
                release_manifest.create_manifest(
                    root=root,
                    version=self.version,
                    source_commit="not-a-git-sha",
                    image=self.image,
                    image_repository=release_manifest.OFFICIAL_IMAGE_REPOSITORY,
                )
