import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bouncer_eval.cli import DEFAULT_DATASET, MODELS, main
from bouncer_eval.models import Decision


class FakeNemotronEvaluator:
    created: list["FakeNemotronEvaluator"] = []

    def __init__(self, model: str, api_key: str, *, reasoning: bool = False) -> None:
        self.model = model
        self.api_key = api_key
        self.reasoning = reasoning
        self.created.append(self)

    def evaluate(self, _case: object) -> Decision:
        return Decision("ALLOW", "test")


class FakeBouncerEvaluator:
    created: list["FakeBouncerEvaluator"] = []

    def __init__(self, model: FakeNemotronEvaluator) -> None:
        self.model = model
        self.created.append(self)

    def evaluate(self, case: object) -> Decision:
        return self.model.evaluate(case)


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
        self.assertEqual(payload["dataset_sha256"], hashlib.sha256(DEFAULT_DATASET.read_bytes()).hexdigest())

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

    def test_reasoning_variant_enables_thinking(self) -> None:
        FakeNemotronEvaluator.created.clear()
        with tempfile.TemporaryDirectory() as directory, patch(
            "bouncer_eval.cli.NemotronEvaluator", FakeNemotronEvaluator
        ):
            exit_code = main(
                [
                    "--systems",
                    "super-thinking",
                    "--min-interval",
                    "0",
                    "--json-output",
                    str(Path(directory) / "result.json"),
                    "--markdown-output",
                    str(Path(directory) / "result.md"),
                ],
                environ={"NVIDIA_API_KEY": "test-key"},
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(FakeNemotronEvaluator.created), 1)
        evaluator = FakeNemotronEvaluator.created[0]
        self.assertEqual(evaluator.model, MODELS["super"])
        self.assertTrue(evaluator.reasoning)

    def test_bouncer_wraps_non_reasoning_super(self) -> None:
        FakeNemotronEvaluator.created.clear()
        FakeBouncerEvaluator.created.clear()
        with tempfile.TemporaryDirectory() as directory, patch(
            "bouncer_eval.cli.NemotronEvaluator", FakeNemotronEvaluator
        ), patch("bouncer_eval.cli.BouncerEvaluator", FakeBouncerEvaluator):
            exit_code = main(
                [
                    "--systems",
                    "bouncer",
                    "--min-interval",
                    "0",
                    "--json-output",
                    str(Path(directory) / "result.json"),
                    "--markdown-output",
                    str(Path(directory) / "result.md"),
                ],
                environ={"NVIDIA_API_KEY": "test-key"},
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(FakeBouncerEvaluator.created), 1)
        model = FakeBouncerEvaluator.created[0].model
        self.assertEqual(model.model, MODELS["super"])
        self.assertFalse(model.reasoning)


if __name__ == "__main__":
    unittest.main()
