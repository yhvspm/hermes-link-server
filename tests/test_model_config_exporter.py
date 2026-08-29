from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hermes_link.integrations.hermes_agent.model_config_exporter import (
    sync_model_config_snapshots,
)


class ModelConfigExporterTests(unittest.TestCase):
    def test_exporter_writes_only_safe_model_configuration_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hermes_home = root / "agent"
            output_directory = root / "snapshots"
            hermes_home.mkdir()
            (hermes_home / "config.yaml").write_text(
                "\n".join(
                    [
                        "model:",
                        "  provider: openai",
                        "  default: gpt-test",
                        "  max_tokens: 4096",
                        "  api_key: must-not-leak",
                        "agent:",
                        "  reasoning_effort: high",
                        "  service_tier: priority",
                    ]
                ),
                encoding="utf-8",
            )

            sync_model_config_snapshots(
                hermes_home,
                output_directory,
                ["default"],
            )

            snapshot = output_directory / "default.json"
            self.assertTrue(snapshot.is_file())
            self.assertNotIn("must-not-leak", snapshot.read_text(encoding="utf-8"))
            self.assertEqual(
                json.loads(snapshot.read_text(encoding="utf-8")),
                {
                    "max_tokens": 4096,
                    "model": "gpt-test",
                    "profile": "default",
                    "provider": "openai",
                    "reasoning_effort": "high",
                    "service_tier": "priority",
                },
            )

    def test_exporter_removes_stale_snapshot_when_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_directory = root / "snapshots"
            output_directory.mkdir()
            stale_snapshot = output_directory / "default.json"
            stale_snapshot.write_text('{"model":"stale"}\n', encoding="utf-8")

            sync_model_config_snapshots(root / "missing", output_directory, ["default"])

            self.assertFalse(stale_snapshot.exists())
