import json
import tempfile
import unittest
from pathlib import Path

from bouncer_eval.models import Case, Decision
from bouncer_eval.report import write_reports


class ReportTests(unittest.TestCase):
    def test_writes_stable_json_and_markdown_with_failures(self) -> None:
        cases = [Case("x", "family", "goal", "action", "SEND", (), "BLOCK", True, {})]
        decisions = {"system": {"x": Decision("ALLOW", "missed", 12.34)}}
        summaries = {
            "system": {
                "total": 1,
                "correct": 0,
                "accuracy": 0.0,
                "attack_block_rate": 0.0,
                "benign_allow_rate": 0.0,
                "invalid_rate": 0.0,
                "latency_p50_ms": 12.34,
                "latency_p95_ms": 12.34,
            }
        }
        gate = {"decision": "NO-GO", "reason": "threshold failed"}

        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "result.json"
            md_path = Path(directory) / "result.md"
            write_reports(cases, decisions, summaries, gate, json_path, md_path)

            payload = json.loads(json_path.read_text())
            markdown = md_path.read_text()

        self.assertEqual(payload["gate"]["decision"], "NO-GO")
        self.assertEqual(payload["failures"][0]["case_id"], "x")
        self.assertNotIn("generated_at", payload)
        self.assertIn("NO-GO", markdown)
        self.assertIn("x", markdown)


if __name__ == "__main__":
    unittest.main()
