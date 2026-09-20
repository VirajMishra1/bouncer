"""Reproduce every judge-facing artifact with one offline command.

    python3 -m eval.run_eval

It runs the end-to-end trajectory benchmark for the offline systems (no defense, a rules baseline
that reads curator labels, and a rules baseline that reads text only), merges in any hosted-model
run saved as eval/results/trajectory_live.json, then regenerates, from result files already in the repo:

  eval/results/trajectory_offline.{json,md}         end-to-end evidence (offline systems)
  eval/results/failures.md                          plain-language failures and limits
  eval/results/pareto.svg                           per-call diagnostic chart
  eval/results/pareto_trajectory.svg                end-to-end chart
  dashboard/index.html                              self-contained results page

It never makes a network call and never reads credentials. The per-call model
results (`go_no_go_noleak.json`, `go_no_go_v1.json`) are archived inputs from
earlier hosted runs; this command reads them but does not re-run any model.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):  # allow `python3 eval/run_eval.py` as well as `-m eval.run_eval`
    sys.path.insert(0, str(ROOT))

from bouncer_eval import trajectory_cli  # noqa: E402
from eval import build_dashboard, plot_pareto  # noqa: E402

OFFLINE_SYSTEMS = ("deterministic", "text-rules", "no-defense")
RESULTS = ROOT / "eval/results"
DASHBOARD = ROOT / "dashboard/index.html"
REASON_LIMIT = 200

NOT_YET_SHOWN = (
    "A hybrid or Nemotron run of the trajectory benchmark (needs the hosted API; human-triggered).",
    "A public benchmark such as AgentDojo.",
    "A post-freeze adaptive-attack set authored after seeing the architecture.",
    "A NeMo Guardrails comparison.",
    "Paired win/loss tables and bootstrap intervals across systems (only one system has trajectory results).",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate Bouncer's results, failures, charts and dashboard offline.")
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--dashboard", type=Path, default=DASHBOARD)
    parser.add_argument("--skip-dashboard", action="store_true", help="only regenerate results, failures and charts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results: Path = args.results_dir
    results.mkdir(parents=True, exist_ok=True)

    trajectory_json = results / "trajectory_offline.json"
    rc = trajectory_cli.main([
        "--systems", *OFFLINE_SYSTEMS,
        "--baseline", "text-rules",
        "--json-output", str(trajectory_json),
        "--markdown-output", str(results / "trajectory_offline.md"),
    ])
    if rc != 0:
        return rc

    trajectory = _load(trajectory_json)
    live = _load(results / "trajectory_live.json", required=False)
    if live is not None:
        if live.get("dataset_sha256") == trajectory.get("dataset_sha256"):
            trajectory = merge_trajectories(trajectory, live)
        else:
            print("Ignoring trajectory_live.json: it was run on a different dataset.", file=sys.stderr)
    per_call = _load(results / "go_no_go_noleak.json")
    archived = _load(results / "go_no_go_v1.json", required=False)

    failures_path = results / "failures.md"
    failures_path.write_text(build_failures_markdown(trajectory, per_call, archived), encoding="utf-8")

    for source, name in ((per_call, "pareto.svg"), (trajectory, "pareto_trajectory.svg")):
        summaries, labels = plot_pareto.summaries_from_payload(source)
        (results / name).write_text(plot_pareto.build_svg(summaries, labels), encoding="utf-8")

    outputs = [trajectory_json.name, "trajectory_offline.md", failures_path.name, "pareto.svg", "pareto_trajectory.svg"]
    if not args.skip_dashboard:
        args.dashboard.parent.mkdir(parents=True, exist_ok=True)
        build_dashboard.build_dashboard(trajectory, per_call, archived, args.dashboard)
        outputs.append(str(args.dashboard))
    print("Wrote: " + ", ".join(outputs))
    return 0


def merge_trajectories(offline: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Union of systems and paired comparisons from two runs of the same frozen dataset."""
    merged = json.loads(json.dumps(offline))
    merged["systems"].update(live.get("systems", {}))
    merged["paired_comparisons"] = {**offline.get("paired_comparisons", {}), **live.get("paired_comparisons", {})}
    return merged


def _load(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise SystemExit(f"missing required results file: {path}") from None
        return None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid results file (expected an object): {path}")
    return payload


def build_failures_markdown(
    trajectory: dict[str, Any],
    per_call: dict[str, Any],
    archived: dict[str, Any] | None,
) -> str:
    """Plain-language failures and limits. Deterministic: no timestamps, stable ordering."""
    lines = [
        "# Bouncer failures and limits",
        "",
        "_Generated by `python3 -m eval.run_eval`. Every number is copied from the result files in this folder._",
        "",
        "## 1. End-to-end (trajectory) results",
        "",
    ]
    lines += _trajectory_section(trajectory)
    lines += ["", "## 2. Per-call diagnostic results (leak-fixed re-run)", ""]
    lines += _per_call_section(per_call)
    if archived is not None:
        lines += ["", "## 3. Original per-call run (archived, do not cite)", ""]
        lines += _archived_section(archived, per_call)
    lines += ["", "## Not yet shown", ""]
    lines += [f"- {item}" for item in NOT_YET_SHOWN]
    lines.append("")
    return "\n".join(lines)


def _trajectory_section(trajectory: dict[str, Any]) -> list[str]:
    dataset = trajectory.get("dataset", {})
    systems = sorted(trajectory.get("systems", {}))
    lines: list[str] = []
    for name in systems:
        system = trajectory["systems"][name]
        summary = system["summary"]
        lines.append(
            f"**{name}:** {summary['attacker_objective_prevented']}/{summary['attack_total']} attacker objectives "
            f"prevented, {summary['benign_completed']}/{summary['benign_total']} benign tasks completed, "
            f"{summary['false_blocks']} false blocks, {summary['ask_total']} asks, {summary['invalid_total']} invalid."
        )
        sinks = [step for outcome in system["outcomes"] for step in outcome["steps"] if step.get("harmful_sink")]
        by_verdict = sum(1 for step in sinks if step.get("verdict") == "BLOCK" and not step.get("failed_closed"))
        by_failure = sum(1 for step in sinks if step.get("failed_closed"))
        by_ask = sum(1 for step in sinks if step.get("verdict") == "ASK" and not step.get("failed_closed"))
        lines.append(
            f"How the {len(sinks)} harmful actions were stopped: {by_verdict} by an explicit BLOCK verdict, "
            f"{by_ask} held for approval (ASK, never forwarded), "
            f"{by_failure} by failing closed (a model error or an invalid answer, not a judgment), "
            f"{len(sinks) - by_verdict - by_ask - by_failure} not stopped by this step."
        )
        for outcome in system["outcomes"]:
            if outcome.get("attack") and outcome.get("harmful_objective_achieved"):
                lines.append(f"- SECURITY LOSS `{outcome['trajectory_id']}` ({outcome['family']}): a harmful action executed.")
            elif not outcome.get("attack") and not outcome.get("benign_completed"):
                cause = next((step for step in outcome["steps"] if step.get("required") and not step.get("executed")), None)
                why = ""
                if cause is not None:
                    why = (
                        f" Cause: failed closed ({_clean(cause.get('error'))})."
                        if cause.get("failed_closed")
                        else f" Cause: verdict {cause.get('verdict')} ({_clean(cause.get('reason'))})."
                    )
                lines.append(f"- UTILITY LOSS `{outcome['trajectory_id']}` ({outcome['family']}): a required benign step did not complete.{why}")
        lines.append("")
    lines += [
        f"The set is {dataset.get('trajectories', '?')} episodes across {len(dataset.get('families', []))} families "
        f"(systems run here: {', '.join(systems) or 'none'}). With this few episodes one episode moves a rate by "
        "several points; treat differences between defended systems as directional.",
    ]
    if "deterministic" in systems:
        lines.append(
            "`deterministic` decides from curator labels (`data_class`, `source`, `destructive`, `operation_in_goal`) "
            "that a real deployment would have to detect and that the model is never shown. Its score is an "
            "upper bound for rules with perfect detectors, not a realistic baseline. `text-rules` sees only the goal, "
            "action text, earlier tool results and the typed destination."
        )
    if not any("nemotron" in n or "bouncer" in n for n in systems):
        lines.append(
            "No Nemotron or hybrid trajectory run is included. It needs the hosted API and has not been done."
        )
    return lines


def _kind(expected: str, actual: str | None) -> str:
    if expected == "ALLOW" and actual == "BLOCK":
        return "benign blocked (utility loss)"
    if expected == "BLOCK" and actual == "ALLOW":
        return "attack allowed (security loss)"
    return "invalid or unresolved output"


def _clean(text: object) -> str:
    flat = " ".join(str(text or "").split()).replace("|", "\\|")
    return flat if len(flat) <= REASON_LIMIT else flat[: REASON_LIMIT - 1] + "…"


def _group_failures(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for failure in payload.get("failures", []):
        grouped.setdefault(failure["system"], []).append(failure)
    return grouped


def _per_call_section(per_call: dict[str, Any]) -> list[str]:
    total = next(iter(per_call.get("summaries", {}).values()), {})
    cases = total.get("attack_total", 0) + total.get("benign_total", 0)
    lines = [
        f"These are **per-call diagnostic** results on a frozen {cases}-case set. They are not end-to-end evidence.",
        "",
    ]
    grouped = _group_failures(per_call)
    for name in sorted(per_call.get("summaries", {})):
        summary = per_call["summaries"][name]
        failures = grouped.get(name, [])
        counts = {"security": 0, "utility": 0, "invalid": 0}
        for f in failures:
            kind = _kind(f["expected"], f.get("actual"))
            counts["security" if kind.startswith("attack") else "utility" if kind.startswith("benign") else "invalid"] += 1
        lines += [
            f"### {name}",
            "",
            f"Accuracy {summary['accuracy']:.1%}; attacks blocked {summary['attack_blocked']}/{summary['attack_total']}; "
            f"benign allowed {summary['benign_allowed']}/{summary['benign_total']}; invalid {summary['invalid_rate']:.1%}.",
            f"Security losses (attacks allowed): {counts['security']}. Utility losses (benign blocked): {counts['utility']}. "
            f"Invalid or unresolved: {counts['invalid']}.",
            "",
        ]
        if failures:
            lines += ["| Case | Family | Expected | Got | Kind | Reason |", "|---|---|---|---|---|---|"]
            for f in sorted(failures, key=lambda f: f["case_id"]):
                reason = f.get("error") or f.get("reason")
                lines.append(
                    f"| `{f['case_id']}` | {f.get('family', '')} | {f['expected']} | {f.get('actual') or 'INVALID'} | "
                    f"{_kind(f['expected'], f.get('actual'))} | {_clean(reason)} |"
                )
            lines.append("")
    return lines


def _archived_section(archived: dict[str, Any], honest: dict[str, Any]) -> list[str]:
    lines = [
        "The first run scored higher because risk tags in the dataset leaked the answer into the prompt. "
        "It is archived in `go_no_go_v1.*` and must not be cited.",
        "",
        "| System | Accuracy (original, leaked) | Accuracy (leak-fixed) |",
        "|---|---:|---:|",
    ]
    for name in sorted(archived.get("summaries", {})):
        original = archived["summaries"][name]["accuracy"]
        fixed = honest.get("summaries", {}).get(name, {}).get("accuracy")
        lines.append(f"| {name} | {original:.1%} | {'n/a' if fixed is None else f'{fixed:.1%}'} |")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
