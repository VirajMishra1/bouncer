import unittest

from bouncer_eval.bouncer import BouncerEvaluator
from bouncer_eval.models import Case, Decision


def case(*, effect: str, metadata: dict[str, object]) -> Case:
    return Case("x", "family", "goal", "action", effect, (), "BLOCK", True, metadata)


class RecordingEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _case: Case) -> Decision:
        self.calls += 1
        return Decision("ALLOW", "model decision")


class BouncerEvaluatorTests(unittest.TestCase):
    def test_blocks_secret_send_without_calling_model(self) -> None:
        model = RecordingEvaluator()
        evaluator = BouncerEvaluator(model)  # type: ignore[arg-type]

        decision = evaluator.evaluate(case(effect="SEND", metadata={"data_class": "secret"}))

        self.assertEqual(decision.verdict, "BLOCK")
        self.assertEqual(model.calls, 0)

    def test_blocks_untrusted_execution_without_calling_model(self) -> None:
        model = RecordingEvaluator()
        evaluator = BouncerEvaluator(model)  # type: ignore[arg-type]

        decision = evaluator.evaluate(case(effect="EXECUTE", metadata={"source": "untrusted_content"}))

        self.assertEqual(decision.verdict, "BLOCK")
        self.assertEqual(model.calls, 0)

    def test_delegates_semantic_decision_to_model(self) -> None:
        model = RecordingEvaluator()
        evaluator = BouncerEvaluator(model)  # type: ignore[arg-type]

        decision = evaluator.evaluate(case(effect="READ", metadata={}))

        self.assertEqual(decision.verdict, "ALLOW")
        self.assertEqual(model.calls, 1)


if __name__ == "__main__":
    unittest.main()
