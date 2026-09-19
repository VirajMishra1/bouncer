from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import Case


VALID_EFFECTS = {"READ", "SEND", "EXECUTE"}
VALID_VERDICTS = {"ALLOW", "BLOCK"}


def load_cases(path: str | Path) -> list[Case]:
    cases: list[Case] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                cases.append(
                    Case(
                        id=raw["id"],
                        family=raw["family"],
                        goal=raw["goal"],
                        action=raw["action"],
                        effect=raw["effect"],
                        context=tuple(raw.get("context", [])),
                        expected=raw["expected"],
                        attack=raw["attack"],
                        metadata=dict(raw.get("metadata", {})),
                    )
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid case at line {line_number}: {exc}") from exc
    return cases


def validate_cases(cases: Iterable[Case]) -> None:
    materialized = list(cases)
    ids = [case.id for case in materialized]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case id")
    if any(not case.id or not case.family or not case.goal or not case.action for case in materialized):
        raise ValueError("case fields must not be empty")
    if any(case.effect not in VALID_EFFECTS for case in materialized):
        raise ValueError("invalid effect")
    if any(case.expected not in VALID_VERDICTS for case in materialized):
        raise ValueError("invalid expected verdict")
    if any(case.attack != (case.expected == "BLOCK") for case in materialized):
        raise ValueError("attack flag must match BLOCK expectation")
