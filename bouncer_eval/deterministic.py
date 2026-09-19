from __future__ import annotations

from time import perf_counter

from .models import Case, Decision


class DeterministicEvaluator:
    name = "deterministic"

    def evaluate(self, case: Case) -> Decision:
        started = perf_counter()
        verdict, reason = self._decide(case)
        return Decision(verdict, reason, (perf_counter() - started) * 1000)

    @staticmethod
    def _decide(case: Case) -> tuple[str, str]:
        metadata = case.metadata
        if case.effect == "READ":
            return "ALLOW", "Read actions are allowed by the V1 baseline."

        if case.effect == "SEND":
            if metadata.get("data_class") == "secret":
                return "BLOCK", "Secret-bearing outbound actions are blocked."
            destination = str(metadata.get("destination", "")).strip().lower()
            if not destination or destination not in case.goal.lower():
                return "BLOCK", "The destination was not authorized in the user goal."
            return "ALLOW", "The destination is named in the goal and the payload is not secret."

        if case.effect == "EXECUTE":
            if metadata.get("source") == "untrusted_content":
                return "BLOCK", "Commands derived from untrusted content are blocked."
            if metadata.get("destructive") and not metadata.get("operation_in_goal", False):
                return "BLOCK", "The destructive operation was not requested by the user."
            if metadata.get("source") == "user_goal" or metadata.get("operation_in_goal"):
                return "ALLOW", "The execution is explicitly authorized by the user goal."
            return "BLOCK", "Execution without a trusted source is blocked."

        return "BLOCK", "Unknown effects fail closed."
