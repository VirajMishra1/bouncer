from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import os
import sys
import time

from .baselines import HybridTextEvaluator, NoDefenseEvaluator, TextRulesEvaluator
from .bouncer import BouncerEvaluator
from .deterministic import DeterministicEvaluator
from .models import Case, Decision
from .nemotron import NemotronEvaluator
from .overseer import OverseerEvaluator
from .report import write_trajectory_report
from .trajectories import (
    compare_trajectory_outcomes,
    load_trajectories,
    run_trajectories,
    summarize_trajectories,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "eval/datasets/trajectory_v1.jsonl"
DEFAULT_FREEZE_MANIFEST = ROOT / "eval/datasets/trajectory_v1.freeze.json"
DEFAULT_JSON = ROOT / "eval/results/trajectory_deterministic.json"
DEFAULT_MARKDOWN = ROOT / "eval/results/trajectory_deterministic.md"


SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
OFFLINE_SYSTEMS = ("deterministic", "text-rules", "no-defense")
LIVE_SYSTEMS = ("super", "bouncer", "bouncer-text", "overseer", "overseer-hybrid")
SYSTEMS = OFFLINE_SYSTEMS + LIVE_SYSTEMS
# Output names. `deterministic` decides from curator labels the model never sees (an oracle-label
# rules baseline); `text-rules` decides from text only and is the realistic rules baseline.
OUTPUT_NAMES = {
    "super": "nemotron-super",
    "bouncer": "bouncer-super",
    "bouncer-text": "bouncer-text-super",
    "overseer": "nemotron-overseer",
    "overseer-hybrid": "overseer-hybrid-super",
}


class Throttled:
    """Space hosted-API requests so a long run stays inside the free tier's rate limit."""

    def __init__(self, evaluator: object, min_interval: float) -> None:
        self._evaluator, self._interval, self._last = evaluator, max(0.0, min_interval), 0.0
        self.wants_history = bool(getattr(evaluator, "wants_history", False))

    def evaluate(self, case: Case) -> Decision:
        wait = self._interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        return self._evaluator.evaluate(case)  # type: ignore[attr-defined]


def _build_evaluator(system: str, api_key: str, min_interval: float) -> object:
    if system == "deterministic":
        return DeterministicEvaluator()
    if system == "text-rules":
        return TextRulesEvaluator()
    if system == "no-defense":
        return NoDefenseEvaluator()
    if system == "overseer":
        return Throttled(OverseerEvaluator(SUPER_MODEL, api_key), min_interval)
    if system == "overseer-hybrid":
        return Throttled(HybridTextEvaluator(OverseerEvaluator(SUPER_MODEL, api_key)), min_interval)
    model = NemotronEvaluator(SUPER_MODEL, api_key)
    if system == "bouncer":
        return Throttled(BouncerEvaluator(model), min_interval)
    if system == "bouncer-text":
        return Throttled(HybridTextEvaluator(model), min_interval)
    return Throttled(model, min_interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Bouncer's offline end-to-end trajectory benchmark."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_FREEZE_MANIFEST)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument(
        "--systems", nargs="+", choices=SYSTEMS, default=["deterministic"],
        help="offline: deterministic (oracle labels), text-rules, no-defense. "
        "hosted (need NVIDIA_API_KEY): super (stateless judge), bouncer, bouncer-text, overseer (context-aware), overseer-hybrid.",
    )
    parser.add_argument("--baseline", default=None, help="add paired win/loss + bootstrap CI of every other system vs this one")
    parser.add_argument("--min-interval", type=float, default=1.6, help="seconds between hosted-API requests")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset_bytes = args.dataset.read_bytes()
    dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
    trajectories = load_trajectories(args.dataset)
    _verify_freeze_manifest(
        args.freeze_manifest,
        dataset_hash=dataset_hash,
        byte_count=len(dataset_bytes),
        trajectory_count=len(trajectories),
        families={trajectory.family for trajectory in trajectories},
    )

    systems = list(dict.fromkeys(args.systems))
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if any(system in LIVE_SYSTEMS for system in systems) and not api_key:
        print("NVIDIA_API_KEY is required for the hosted systems (super, bouncer, bouncer-text).", file=sys.stderr)
        return 2
    all_outcomes = {}
    for system in systems:
        name = OUTPUT_NAMES.get(system, system)
        if system in LIVE_SYSTEMS:
            print(f"Running {name} on {len(trajectories)} trajectories (hosted API)...")
        all_outcomes[name] = run_trajectories(trajectories, _build_evaluator(system, api_key, args.min_interval))
    summaries = {name: summarize_trajectories(trajectories, outcomes) for name, outcomes in all_outcomes.items()}
    comparisons = {}
    if args.baseline is not None:
        baseline = OUTPUT_NAMES.get(args.baseline, args.baseline)
        if baseline not in all_outcomes:
            raise ValueError(f"--baseline {args.baseline!r} was not among the systems run")
        for name, outcomes in all_outcomes.items():
            if name != baseline:
                comparisons[f"{name} vs {baseline}"] = compare_trajectory_outcomes(trajectories, outcomes, all_outcomes[baseline])
    write_trajectory_report(
        trajectories,
        all_outcomes,
        summaries,
        args.json_output,
        args.markdown_output,
        dataset_hash=dataset_hash,
        comparisons=comparisons,
    )
    for name, summary in summaries.items():
        print(
            f"{name}: "
            f"{summary['attacker_objective_prevented']}/{summary['attack_total']} attacks prevented; "
            f"{summary['benign_completed']}/{summary['benign_total']} benign tasks completed"
        )
    print(f"Reports: {args.json_output} and {args.markdown_output}")
    return 0


def _verify_freeze_manifest(
    path: Path,
    *,
    dataset_hash: str,
    byte_count: int,
    trajectory_count: int,
    families: set[str],
) -> None:
    try:
        manifest: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid freeze manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("invalid freeze manifest: expected an object")
    expected = {
        "sha256": dataset_hash,
        "bytes": byte_count,
        "trajectories": trajectory_count,
        "families": sorted(families),
    }
    actual = {key: manifest.get(key) for key in expected}
    if actual != expected:
        raise ValueError("dataset does not match freeze manifest")


if __name__ == "__main__":
    raise SystemExit(main())
