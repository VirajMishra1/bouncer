import json
import shutil
import tempfile
import unittest
from pathlib import Path

from eval import run_eval

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval/results"


def _load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


class FailuresReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trajectory = _load("trajectory_deterministic.json")
        self.per_call = _load("go_no_go_noleak.json")
        self.archived = _load("go_no_go_v1.json")
        self.text = run_eval.build_failures_markdown(self.trajectory, self.per_call, self.archived)

    def test_tiers_are_labelled_and_never_blended(self) -> None:
        self.assertIn("End-to-end (trajectory) results", self.text)
        self.assertIn("per-call diagnostic", self.text.lower())
        self.assertIn("do not cite", self.text)

    def test_saturated_benchmark_is_called_out(self) -> None:
        self.assertIn("cannot yet separate them", self.text)
        self.assertIn("not a strength claim", self.text)

    def test_per_call_failures_are_classified(self) -> None:
        self.assertIn("benign blocked (utility loss)", self.text)
        self.assertIn("invalid or unresolved output", self.text)
        self.assertIn("INVALID", self.text)
        self.assertNotIn("| None |", self.text)

    def test_archived_run_is_contrasted_with_the_leak_fixed_run(self) -> None:
        self.assertIn("| nemotron-super | 100.0% | 93.8% |", self.text)

    def test_not_yet_shown_items_are_listed(self) -> None:
        for item in run_eval.NOT_YET_SHOWN:
            self.assertIn(item, self.text)

    def test_output_is_deterministic(self) -> None:
        again = run_eval.build_failures_markdown(self.trajectory, self.per_call, self.archived)
        self.assertEqual(self.text, again)

    def test_security_loss_is_reported_when_an_attack_succeeds(self) -> None:
        bad = json.loads(json.dumps(self.trajectory))
        outcome = next(o for o in bad["systems"]["deterministic"]["outcomes"] if o["attack"])
        outcome["harmful_objective_achieved"] = True
        bad["systems"]["deterministic"]["summary"]["attacker_objective_prevented"] -= 1
        text = run_eval.build_failures_markdown(bad, self.per_call, None)
        self.assertIn("SECURITY LOSS", text)
        self.assertNotIn("cannot yet separate them", text)
        self.assertNotIn("Original per-call run", text)

    def test_long_reasons_are_trimmed_and_pipes_escaped(self) -> None:
        self.assertLessEqual(len(run_eval._clean("x" * 500)), run_eval.REASON_LIMIT)
        self.assertEqual(run_eval._clean("a | b"), "a \\| b")


class CommandTests(unittest.TestCase):
    def test_one_command_writes_every_artifact_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "results"
            results.mkdir()
            for name in ("go_no_go_noleak.json", "go_no_go_v1.json"):
                shutil.copy(RESULTS / name, results / name)
            dashboard = Path(tmp) / "dashboard" / "index.html"
            self.assertEqual(run_eval.main(["--results-dir", str(results), "--dashboard", str(dashboard)]), 0)
            for name in (
                "trajectory_deterministic.json",
                "trajectory_deterministic.md",
                "failures.md",
                "pareto.svg",
                "pareto_trajectory.svg",
            ):
                self.assertTrue((results / name).read_text(encoding="utf-8").strip(), name)
            self.assertIn("<html", dashboard.read_text(encoding="utf-8"))
            self.assertIn("end-to-end", (results / "pareto_trajectory.svg").read_text(encoding="utf-8"))

    def test_missing_per_call_results_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as caught:
                run_eval.main(["--results-dir", tmp, "--skip-dashboard"])
            self.assertIn("go_no_go_noleak.json", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
