import json
import tempfile
import unittest
from pathlib import Path

from bouncer_eval.cli import main


class CliTests(unittest.TestCase):
    def test_dry_run_validates_dataset_and_writes_rule_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "result.json"
            md_path = Path(directory) / "result.md"
            exit_code = main(
                ["--dry-run", "--json-output", str(json_path), "--markdown-output", str(md_path)],
                environ={},
            )
            payload = json.loads(json_path.read_text())

        self.assertEqual(exit_code, 0)
        self.assertEqual(set(payload["summaries"]), {"deterministic"})
        self.assertEqual(payload["gate"]["decision"], "NOT-RUN")

    def test_live_model_run_requires_api_key(self) -> None:
        exit_code = main(["--systems", "super"], environ={})
        self.assertEqual(exit_code, 2)

    def test_system_selection_can_run_deterministic_without_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code = main(
                [
                    "--systems",
                    "deterministic",
                    "--json-output",
                    str(Path(directory) / "result.json"),
                    "--markdown-output",
                    str(Path(directory) / "result.md"),
                ],
                environ={},
            )
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
