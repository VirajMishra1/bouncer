"""Replay AgentDojo's published run logs through a Bouncer judge.

    python3 -m eval.run_agentdojo --source /path/to/agentdojo/runs --model-dir gpt-4o-2024-05-13 \
        --limit 40 --systems deterministic

Reports REPLAY INTERCEPTION, not native AgentDojo end-to-end prevention: the judge scores tool calls
the logged agent proposed; the agent never sees a verdict and nothing is re-run. Hosted systems
(`nemotron`, `hybrid`) read NVIDIA_API_KEY from the environment; the key is never written anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):  # allow `python3 eval/run_agentdojo.py` as well as `-m eval.run_agentdojo`
    sys.path.insert(0, str(ROOT))

from bouncer_eval.agentdojo import (  # noqa: E402
    CAVEAT,
    METRIC_FAMILY,
    PUBLIC_V2_CLEAN_QUOTAS,
    PUBLIC_V2_EXPECTED_MANIFEST_HASHES,
    PUBLIC_V2_MODEL,
    PUBLIC_V2_SEED,
    ReplayTrajectory,
    eligible,
    load_trajectories,
    public_v2_manifest_hashes,
    replay_metrics,
    select_public_v2_sample,
    select_sample,
    to_cases,
)
from bouncer_eval.bouncer import BouncerEvaluator  # noqa: E402
from bouncer_eval.deterministic import DeterministicEvaluator  # noqa: E402
from bouncer_eval.models import Decision  # noqa: E402
from bouncer_eval.nemotron import NemotronEvaluator  # noqa: E402
from bouncer_eval.trajectory_cli import SUPER_MODEL, Throttled  # noqa: E402

DEFAULT_OUTPUT = ROOT / "eval/results/agentdojo_replay.json"
DEFAULT_MANIFEST = ROOT / "eval/agentdojo_manifest.json"
SYSTEMS = ("deterministic", "nemotron", "hybrid")
HOSTED = {"nemotron", "hybrid"}

EvaluatorFactory = Callable[[str], Any]


def default_factory(api_key: str, min_interval: float) -> EvaluatorFactory:
    def build(system: str) -> Any:
        if system == "deterministic":
            return DeterministicEvaluator()
        model = NemotronEvaluator(SUPER_MODEL, api_key)
        return Throttled(BouncerEvaluator(model) if system == "hybrid" else model, min_interval)

    return build


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay AgentDojo published run logs through Bouncer (replay interception).")
    parser.add_argument("--source", type=Path, required=True, help="AgentDojo `runs` directory (or any directory of run logs)")
    parser.add_argument("--model-dir", default=None, help="model directory under --source (or a path) to restrict to one model")
    parser.add_argument("--limit", type=int, default=40, help="trajectories to sample, balanced across suites")
    parser.add_argument(
        "--sample-mode",
        choices=("successful-attacks", "public-v2"),
        default="successful-attacks",
        help="successful-attacks is the existing balanced replay sample; public-v2 is the fixed 50-clean/50-exposed cohort",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--systems", nargs="+", choices=SYSTEMS, default=["deterministic"])
    parser.add_argument("--min-interval", type=float, default=1.6, help="seconds between hosted-API requests")
    return parser


def _resolve_root(source: Path, model_dir: str | None) -> Path:
    if model_dir is None:
        return source
    for candidate in (source / model_dir, Path(model_dir)):
        if candidate.is_dir():
            return candidate
    raise ValueError(f"--model-dir {model_dir!r} not found under {source}")


def _decide(evaluator: Any, case: Any) -> Decision:
    try:
        return evaluator.evaluate(case)
    except Exception as exc:  # keep the run alive; never echo the message, it could carry a credential
        return Decision(None, "", error=f"evaluator raised {type(exc).__name__}")


def _decision_row(decision: Decision) -> dict[str, Any]:
    return {
        "verdict": decision.verdict,
        "reason": decision.reason,
        "latency_ms": round(decision.latency_ms, 3),
        "error": decision.error,
    }


def build_manifest(
    selected: list[ReplayTrajectory], *, source: Path, model_dir: str | None, limit: int,
    available: int, eligible_count: int, sample_mode: str = "successful-attacks",
) -> dict[str, Any]:
    by_suite: dict[str, int] = {}
    for trajectory in selected:
        by_suite[trajectory.suite] = by_suite.get(trajectory.suite, 0) + 1
    public_v2 = sample_mode == "public-v2"
    manifest = {
        "schema": 2 if public_v2 else 1,
        "metric_family": METRIC_FAMILY,
        "source": str(source),
        "model_dir": model_dir,
        "limit": limit,
        "sample_mode": sample_mode,
        "selection": (
            "fixed public-v2 sha256 cohort: 50 clean user-task logs plus 50 exposed attack logs; "
            "the payload must appear before a later proposed tool call; utility/security are not selection criteria"
            if public_v2
            else "deterministic sha256(id) order; balanced across suites; half successful-attack "
            "(attack_type set, security=true) and half clean; DoS attack types and errored runs excluded"
        ),
        "counts": {"available": available, "eligible": eligible_count, "selected": len(selected), "by_suite": dict(sorted(by_suite.items()))},
        "selected": [
            {
                "id": t.id,
                "path": t.source_path,
                "sha256": t.sha256,
                "suite": t.suite,
                "user_task": t.user_task,
                "injection_task": t.injection_task,
                "attack_type": t.attack_type,
                "kind": "exposed_attack" if public_v2 and t.is_attack else "successful_attack" if t.attack_succeeded else "clean",
                "injection_exposed": t.injection_exposed,
            }
            for t in selected
        ],
    }
    if public_v2:
        manifest["selection_seed"] = PUBLIC_V2_SEED
        manifest["cohort_manifest_sha256"] = public_v2_manifest_hashes(selected)
        manifest["expected_cohort_manifest_sha256"] = PUBLIC_V2_EXPECTED_MANIFEST_HASHES
        manifest["counts"]["by_kind"] = {
            "clean": sum(not t.is_attack for t in selected),
            "exposed_attack": sum(t.is_attack for t in selected),
        }
        manifest["counts"]["clean_quotas"] = PUBLIC_V2_CLEAN_QUOTAS
    return manifest


def main(argv: Sequence[str] | None = None, *, evaluator_factory: EvaluatorFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    systems = list(dict.fromkeys(args.systems))
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if evaluator_factory is None:
        if any(system in HOSTED for system in systems) and not api_key:
            print("NVIDIA_API_KEY is required for the hosted systems (nemotron, hybrid).", file=sys.stderr)
            return 2
        evaluator_factory = default_factory(api_key, args.min_interval)
    if args.limit < 1:
        print("--limit must be at least 1.", file=sys.stderr)
        return 2
    if args.sample_mode == "public-v2" and args.limit != 100:
        print("--sample-mode public-v2 requires --limit 100 (50 clean + 50 exposed attacks).", file=sys.stderr)
        return 2

    try:
        root = _resolve_root(args.source, args.model_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    trajectories = load_trajectories(root)
    try:
        sample = select_public_v2_sample(trajectories) if args.sample_mode == "public-v2" else select_sample(trajectories, args.limit)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not sample:
        print(f"No eligible AgentDojo run logs under {root}.", file=sys.stderr)
        return 2

    cases = {t.id: to_cases(t) for t in sample}
    decisions: dict[str, dict[str, list[Decision]]] = {}
    for system in systems:
        evaluator = evaluator_factory(system)
        if system in HOSTED:
            print(f"Replaying {len(sample)} trajectories through {system} (hosted API)...")
        decisions[system] = {t.id: [_decide(evaluator, case) for case in cases[t.id]] for t in sample}

    rows = []
    for trajectory in sample:
        calls = []
        for call, case in zip(trajectory.calls, cases[trajectory.id]):
            calls.append(
                {
                    "index": call.index,
                    "function": call.function,
                    "args": call.args,
                    "effect": case.effect,
                    "metadata": case.metadata,
                    "injection_linked": case.attack,
                    "context_chars": [len(item) for item in call.context],
                    "decisions": {s: _decision_row(decisions[s][trajectory.id][call.index]) for s in systems},
                }
            )
        rows.append(
            {
                "id": trajectory.id,
                "model": trajectory.model,
                "suite": trajectory.suite,
                "user_task": trajectory.user_task,
                "injection_task": trajectory.injection_task,
                "attack_type": trajectory.attack_type,
                "goal": trajectory.goal,
                "utility": trajectory.utility,
                "security": trajectory.security,
                "attack_succeeded": trajectory.attack_succeeded,
                "injection_exposed": trajectory.injection_exposed,
                "calls": calls,
            }
        )
    metrics = {s: replay_metrics(sample, decisions[s]) for s in systems}
    payload = {
        "metric_family": METRIC_FAMILY,
        "caveat": CAVEAT,
        "systems": systems,
        "limit": args.limit,
        "trajectories": rows,
        "metrics": metrics,
    }
    manifest = build_manifest(
        sample,
        source=args.source,
        model_dir=args.model_dir,
        limit=args.limit,
        available=len(trajectories),
        eligible_count=(
            sum(
                t.model == PUBLIC_V2_MODEL and t.user_task.startswith("user_task_") and not t.error and bool(t.calls)
                for t in trajectories
            )
            if args.sample_mode == "public-v2"
            else sum(1 for t in trajectories if eligible(t))
        ),
        sample_mode=args.sample_mode,
    )
    for path, data in ((args.output, payload), (args.manifest, manifest)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for system, m in metrics.items():
        print(
            f"{system} [replay interception, not native AgentDojo prevention]: "
            f"linked attack call intercepted {m['replay_attack_linked_call_intercepted']}/"
            f"{m['successful_attack_trajectories_with_linked_call']}; "
            f"clean trajectories with a false intercept {m['replay_clean_trajectories_with_intercept']}/{m['clean_trajectories']}; "
            f"decision errors {m['decision_errors']}"
        )
    print(f"Wrote {args.output} and {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
