from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Case, Decision, Trajectory, TrajectoryOutcome


def write_reports(
    cases: list[Case],
    all_decisions: dict[str, dict[str, Decision]],
    summaries: dict[str, dict[str, Any]],
    gate: dict[str, str],
    json_path: str | Path,
    markdown_path: str | Path,
    dataset_hash: str | None = None,
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

    payload = {"gate": gate, "summaries": summaries, "failures": failures, "dataset_sha256": dataset_hash}
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
    ]
    if dataset_hash:
        lines.extend([f"_Frozen dataset sha256: `{dataset_hash[:16]}…`_", ""])
    lines.extend([
        "| System | Accuracy | Attacks blocked (95% CI) | Benign allowed (95% CI) | Ask | Invalid | p50 | p95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for system, summary in summaries.items():
        lines.append(
            f"| {system} | {_pct(summary['accuracy'])} | "
            f"{_pct(summary['attack_block_rate'])} {_ci(summary.get('attack_block_rate_ci'))} | "
            f"{_pct(summary['benign_allow_rate'])} {_ci(summary.get('benign_allow_rate_ci'))} | "
            f"{_pct(summary.get('ask_rate', 0.0))} | {_pct(summary['invalid_rate'])} | "
            f"{summary['latency_p50_ms']:.0f} ms | {summary['latency_p95_ms']:.0f} ms |"
        )

    # Per-family breakdown (uses the last-listed system with family data, typically Bouncer/Super)
    family_source = next((s for name, s in reversed(list(summaries.items())) if s.get("by_family")), None)
    if family_source:
        lines.extend(["", "## Per-family breakdown", "",
                      "| Family | n | Attacks blocked | Benign allowed |", "|---|---:|---:|---:|"])
        for fam, stats in sorted(family_source["by_family"].items()):
            lines.append(f"| {fam} | {stats['n']} | {_pct(stats['attack_block_rate'])} | {_pct(stats['benign_allow_rate'])} |")

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


def _ci(bounds: list[float] | None) -> str:
    if not bounds:
        return ""
    return f"[{bounds[0] * 100:.0f}–{bounds[1] * 100:.0f}]"


def write_trajectory_report(
    trajectories: list[Trajectory],
    all_outcomes: dict[str, dict[str, TrajectoryOutcome]],
    summaries: dict[str, dict[str, Any]],
    json_path: str | Path,
    markdown_path: str | Path,
    *,
    dataset_hash: str,
    comparisons: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Write stable, complete end-to-end trajectory artifacts.

    The raw step decisions are deliberately retained so a headline metric can
    always be audited back to the exact sink that did or did not execute.
    """
    pairwise = comparisons or {}
    systems: dict[str, Any] = {}
    for system, outcomes in all_outcomes.items():
        systems[system] = {
            "summary": summaries[system],
            "outcomes": [_trajectory_outcome_json(outcomes[episode.id]) for episode in trajectories],
        }
    payload = {
        "schema_version": 1,
        "dataset_sha256": dataset_hash,
        "dataset": {
            "trajectories": len(trajectories),
            "families": sorted({episode.family for episode in trajectories}),
        },
        "systems": systems,
        "paired_comparisons": pairwise,
    }
    json_target = Path(json_path)
    markdown_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Bouncer End-to-End Trajectory Result",
        "",
        f"_Dataset sha256: `{dataset_hash}`_",
        "",
        "| System | Attacker objective prevented | Benign tasks completed | False blocks | ASK | Invalid |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for system, summary in summaries.items():
        lines.append(
            f"| {system} | {summary['attacker_objective_prevented']}/{summary['attack_total']} "
            f"({_pct(summary['attacker_objective_prevented_rate'])}) | "
            f"{summary['benign_completed']}/{summary['benign_total']} "
            f"({_pct(summary['benign_completion_rate'])}) | "
            f"{summary['false_blocks']} ({_pct(summary['false_block_rate'])}) | "
            f"{summary['ask_total']} ({_pct(summary['ask_rate'])}) | "
            f"{summary['invalid_total']} ({_pct(summary['invalid_rate'])}) |"
        )
    if pairwise:
        lines.extend(
            [
                "",
                "## Paired episode comparisons",
                "",
                "| Comparison | Wins | Losses | Ties | Success-rate difference (95% CI) |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for name, comparison in pairwise.items():
            lines.append(
                f"| {name} | {comparison['wins']} | {comparison['losses']} | {comparison['ties']} | "
                f"{_pct(comparison['difference'])} {_ci(comparison['difference_ci'])} |"
            )
    lines.extend(["", "## Raw episode outcomes", ""])
    for system, outcomes in all_outcomes.items():
        lines.extend(
            [
                f"### {system}",
                "",
                "| Episode | Family | Kind | Success | Harmful sink executed | Benign completed |",
                "|---|---|---|---:|---:|---:|",
            ]
        )
        for episode in trajectories:
            result = outcomes[episode.id]
            lines.append(
                f"| `{episode.id}` | {episode.family} | {'attack' if episode.attack else 'benign'} | "
                f"{'yes' if result.success else 'no'} | "
                f"{'yes' if result.harmful_objective_achieved else 'no'} | "
                f"{'yes' if result.benign_completed else 'no'} |"
            )
        lines.append("")
    markdown_target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_trajectory_reports(*args: Any, **kwargs: Any) -> None:
    """Backward-compatible plural spelling for artifact builders."""
    write_trajectory_report(*args, **kwargs)


def _trajectory_outcome_json(outcome: TrajectoryOutcome) -> dict[str, Any]:
    return {
        "trajectory_id": outcome.trajectory_id,
        "family": outcome.family,
        "attack": outcome.attack,
        "success": outcome.success,
        "security_success": outcome.security_success,
        "utility_success": outcome.utility_success,
        "harmful_objective_achieved": outcome.harmful_objective_achieved,
        "benign_completed": outcome.benign_completed,
        "steps": [
            {
                "step_id": step.step_id,
                "verdict": step.decision.verdict,
                "reason": step.decision.reason,
                "latency_ms": step.decision.latency_ms,
                "error": step.decision.error,
                "executed": step.executed,
                "failed_closed": step.failed_closed,
                "harmful_sink": step.harmful_sink,
                "required": step.required,
                "retry_of": step.retry_of,
            }
            for step in outcome.steps
        ],
    }
