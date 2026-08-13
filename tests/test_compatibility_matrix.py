import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CompatibilityMatrixTests(unittest.TestCase):
    def test_matrix_declares_current_supported_adapter_and_future_gate(self) -> None:
        matrix = json.loads((ROOT / "compat" / "matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(matrix["compatibilityMatrixVersion"], 1)
        self.assertEqual(matrix["protocolVersion"], 1)
        rows = {entry["hermesAgent"]: entry for entry in matrix["rows"]}
        self.assertEqual(rows["0.20.x"]["status"], "supported")
        self.assertIn("adapter", rows["0.20.x"]["implementation"])
        self.assertEqual(rows["future"]["status"], "unverified")
        self.assertEqual(rows["0.19.x"]["status"], "migration-only")

    def test_legacy_patches_do_not_import_cloud_implementation(self) -> None:
        patches = (ROOT / "compat").rglob("*.patch")
        for patch in patches:
            self.assertNotIn("from hermes_link_cloud import", patch.read_text(encoding="utf-8"))
