from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Case, Decision


def write_reports(
    cases: list[Case],
    all_decisions: dict[str, dict[str, Decision]],
    summaries: dict[str, dict[str, Any]],
    gate: dict[str, str],
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    failures: list[dict[str, Any]] = []
    for system, decisions in all_decisions.items():
        for case in cases:
            decision = decisions.get(case.id, Decision(None, "", error="missing decision"))
            if decision.verdict != case.expected or not decision.valid:
                failures.append(
                    {
                        "system": system,
                        "case_id": case.id,
                        "family": case.family,
                        "expected": case.expected,
                        "actual": decision.verdict,
                        "reason": decision.reason,
                        "error": decision.error,
                    }
                )

    payload = {"gate": gate, "summaries": summaries, "failures": failures}
    json_target = Path(json_path)
    markdown_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Bouncer Go/No-Go Result",
        "",
        f"**Decision: {gate['decision']}**",
        "",
        gate["reason"],
        "",
        "| System | Accuracy | Attacks blocked | Benign allowed | Invalid | p50 latency | p95 latency |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for system, summary in summaries.items():
        lines.append(
            f"| {system} | {_pct(summary['accuracy'])} | {_pct(summary['attack_block_rate'])} | "
            f"{_pct(summary['benign_allow_rate'])} | {_pct(summary['invalid_rate'])} | "
            f"{summary['latency_p50_ms']:.2f} ms | {summary['latency_p95_ms']:.2f} ms |"
        )
    lines.extend(["", "## Failures", ""])
    if failures:
        for failure in failures:
            actual = failure["actual"] or "INVALID"
            detail = failure["error"] or failure["reason"]
            lines.append(
                f"- `{failure['system']}` / `{failure['case_id']}`: expected {failure['expected']}, got {actual} — {detail}"
            )
    else:
        lines.append("None.")
    markdown_target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"
