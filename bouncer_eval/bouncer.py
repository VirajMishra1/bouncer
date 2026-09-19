"""Bouncer = the hybrid reference monitor.

Crisp, high-confidence dangerous boundaries are enforced deterministically
(fail-closed, no model call needed); everything semantically ambiguous is
handed to Nemotron, which may ALLOW, BLOCK, or ASK.

We deliberately keep the deterministic layer to boundaries that are genuinely
crisp — secret-bearing sends and executing untrusted content. We do NOT put a
blunt "destination not a substring of the goal" rule here: that over-blocks
legitimate sends (e.g. a weather API that plainly serves "check the weather"),
which is exactly the failure mode of the rules baseline. Those judgments belong
to the model, which can ALLOW an unnamed-but-fitting destination or ASK when it
genuinely cannot tell.

In production the invariant signals come from real detectors (a secret scanner,
provenance tags); here they read the case metadata as a stand-in.
"""
from __future__ import annotations

from time import perf_counter

from .models import Case, Decision
from .nemotron import NemotronEvaluator


class BouncerEvaluator:
    def __init__(self, model: NemotronEvaluator, *, name: str = "bouncer") -> None:
        self._model = model
        self.name = name

    def evaluate(self, case: Case) -> Decision:
        started = perf_counter()
        invariant = self._invariant(case)
        if invariant is not None:
            verdict, reason = invariant
            return Decision(verdict, reason, (perf_counter() - started) * 1000)
        return self._model.evaluate(case)

    @staticmethod
    def _invariant(case: Case) -> tuple[str, str] | None:
        meta = case.metadata
        if case.effect == "SEND" and meta.get("data_class") == "secret":
            return "BLOCK", "Invariant: secret-bearing outbound action is never authorized."
        if case.effect == "EXECUTE" and meta.get("source") == "untrusted_content":
            return "BLOCK", "Invariant: executing commands derived from untrusted content."
        return None
