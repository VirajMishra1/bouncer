import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bouncer_eval.trajectory_cli import DEFAULT_DATASET, main


class TrajectoryCliTests(unittest.TestCase):
    def test_one_command_generates_raw_outcomes_and_headline_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "trajectory.json"
            markdown_path = Path(directory) / "trajectory.md"

            exit_code = main(
                [
                    "--json-output",
                    str(json_path),
                    "--markdown-output",
                    str(markdown_path),
                ]
            )
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["dataset_sha256"], hashlib.sha256(DEFAULT_DATASET.read_bytes()).hexdigest())
        self.assertEqual(set(payload["systems"]), {"deterministic"})
        system = payload["systems"]["deterministic"]
        self.assertEqual(len(system["outcomes"]), payload["dataset"]["trajectories"])
        self.assertIn("attacker_objective_prevented_rate", system["summary"])
        self.assertIn("benign_completion_rate", system["summary"])
        self.assertIn("End-to-End Trajectory Result", markdown)
        self.assertIn("Dataset sha256", markdown)

    def test_cli_rejects_dataset_when_freeze_hash_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "trajectory.jsonl"
            dataset.write_bytes(DEFAULT_DATASET.read_bytes() + b"\n")
            json_path = Path(directory) / "trajectory.json"
            markdown_path = Path(directory) / "trajectory.md"

            with self.assertRaisesRegex(ValueError, "freeze manifest"):
                main(
                    [
                        "--dataset",
                        str(dataset),
                        "--freeze-manifest",
                        "eval/datasets/trajectory_v1.freeze.json",
                        "--json-output",
                        str(json_path),
                        "--markdown-output",
                        str(markdown_path),
                    ]
                )

        self.assertFalse(json_path.exists())


if __name__ == "__main__":
    unittest.main()
