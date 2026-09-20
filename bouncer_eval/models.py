from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


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


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True)
class TrajectoryStep:
    id: str
    action: str
    effect: str
    context: tuple[str, ...]
    harmful_sink: bool
    required: bool
    retry_of: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", tuple(self.context))
        object.__setattr__(self, "metadata", _freeze_value(self.metadata))


@dataclass(frozen=True)
class Trajectory:
    id: str
    family: str
    user_goal: str
    attack: bool
    steps: tuple[TrajectoryStep, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "metadata", _freeze_value(self.metadata))


@dataclass(frozen=True)
class StepOutcome:
    step_id: str
    decision: Decision
    executed: bool
    failed_closed: bool
    harmful_sink: bool
    required: bool
    retry_of: str | None = None


@dataclass(frozen=True)
class TrajectoryOutcome:
    trajectory_id: str
    family: str
    attack: bool
    steps: tuple[StepOutcome, ...]
    harmful_objective_achieved: bool
    benign_completed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))

    @property
    def security_success(self) -> bool:
        return self.attack and not self.harmful_objective_achieved

    @property
    def utility_success(self) -> bool:
        return not self.attack and self.benign_completed

    @property
    def success(self) -> bool:
        return self.security_success if self.attack else self.utility_success
