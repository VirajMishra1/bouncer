from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from .dataset import load_cases, validate_cases
from .deterministic import DeterministicEvaluator
from .metrics import classify_gate, summarize
from .models import Case, Decision
from .nemotron import NemotronEvaluator
from .report import write_reports


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "eval/datasets/go_no_go_v1.jsonl"
DEFAULT_JSON = ROOT / "eval/results/go_no_go_v1.json"
DEFAULT_MARKDOWN = ROOT / "eval/results/go_no_go_v1.md"
MODELS = {
    "lightning": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "super": "nvidia/nemotron-3-super-120b-a12b",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Bouncer go/no-go evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument(
        "--systems",
        nargs="+",
        choices=("deterministic", "lightning", "super"),
        default=["deterministic", "lightning", "super"],
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate data and run rules without API calls.")
    parser.add_argument("--min-interval", type=float, default=1.6, help="Minimum seconds between API request starts.")
    return parser


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    cases = load_cases(args.dataset)
    validate_cases(cases)
    systems = ["deterministic"] if args.dry_run else list(dict.fromkeys(args.systems))
    needs_api = any(system in MODELS for system in systems)
    api_key = env.get("NVIDIA_API_KEY", "")
    if needs_api and not api_key:
        print("NVIDIA_API_KEY is required for Lightning or Super.", file=sys.stderr)
        return 2

    all_decisions: dict[str, dict[str, Decision]] = {}
    for system in systems:
        if system == "deterministic":
            evaluator = DeterministicEvaluator()
            output_name = "deterministic"
            interval = 0.0
        else:
            evaluator = NemotronEvaluator(MODELS[system], api_key)
            output_name = f"nemotron-{system}"
            interval = max(0.0, args.min_interval)
        print(f"Running {output_name} on {len(cases)} cases...")
        all_decisions[output_name] = run_evaluator(cases, evaluator, interval)

    summaries = {name: summarize(cases, decisions) for name, decisions in all_decisions.items()}
    gate = (
        {"decision": "NOT-RUN", "reason": "Dry run validates data and rules only."}
        if args.dry_run
        else classify_gate(summaries)
    )
    write_reports(cases, all_decisions, summaries, gate, args.json_output, args.markdown_output)
    print(f"Decision: {gate['decision']}")
    print(f"Reports: {args.json_output} and {args.markdown_output}")
    return 0


def run_evaluator(cases: list[Case], evaluator: object, min_interval: float) -> dict[str, Decision]:
    decisions: dict[str, Decision] = {}
    previous_start = 0.0
    for index, case in enumerate(cases, start=1):
        wait = min_interval - (time.monotonic() - previous_start)
        if wait > 0:
            time.sleep(wait)
        previous_start = time.monotonic()
        decision = evaluator.evaluate(case)  # type: ignore[attr-defined]
        decisions[case.id] = decision
        if min_interval:
            verdict = decision.verdict or "INVALID"
            print(f"  {index:02d}/{len(cases)} {case.id}: {verdict}")
    return decisions


if __name__ == "__main__":
    raise SystemExit(main())
