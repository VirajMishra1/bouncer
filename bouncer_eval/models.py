from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Case:
    id: str
    family: str
    goal: str
    action: str
    effect: str
    context: tuple[str, ...]
    expected: str
    attack: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    verdict: str | None
    reason: str
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None and self.verdict in {"ALLOW", "BLOCK", "ASK"}
