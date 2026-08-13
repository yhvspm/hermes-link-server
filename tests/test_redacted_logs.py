from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_link.observability.redacted_logs import export_redacted_logs


class RedactedLogExporterTests(unittest.TestCase):
    def test_exporter_writes_only_allowlisted_redacted_logs(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as destination:
            source_directory = Path(source)
            (source_directory / "gateway.log").write_text(
                "Bearer test-value\napi_token=private-value\n",
                encoding="utf-8",
            )
            (source_directory / "unrelated.log").write_text("must not copy", encoding="utf-8")

            exported = export_redacted_logs(source_directory, Path(destination))

            output = (Path(destination) / "gateway.log").read_text(encoding="utf-8")
            self.assertEqual(set(exported), {"agent.log", "errors.log", "gateway.log"})
            self.assertNotIn("test-value", output)
            self.assertNotIn("private-value", output)
            self.assertFalse((Path(destination) / "unrelated.log").exists())


if __name__ == "__main__":
    unittest.main()
