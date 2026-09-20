"""Run the 100 presentation headline decisions from the fixed AgentDojo public-v2 cohort."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bouncer_eval.agentdojo import load_trajectories, select_public_v2_sample, to_cases
from bouncer_eval.deterministic import DeterministicEvaluator
from bouncer_eval.models import Decision
from bouncer_eval.nemotron import NemotronEvaluator
from bouncer_eval.trajectory_cli import SUPER_MODEL, Throttled


def row(decision: Decision) -> dict:
    return {"verdict": decision.verdict, "reason": decision.reason, "latency_ms": round(decision.latency_ms, 3), "error": decision.error}


def write(path: Path, records: list[dict]) -> None:
    valid = [r for r in records if r["nemotron"]["error"] is None]
    attacks = [r for r in valid if r["kind"] == "exposed_attack"]
    clean = [r for r in valid if r["kind"] == "clean"]
    metrics = {
        "valid_decisions": len(valid),
        "decision_errors": len(records) - len(valid),
        "attack_first_post_exposure": {
            "n": len(attacks),
            "block": sum(r["nemotron"]["verdict"] == "BLOCK" for r in attacks),
            "ask": sum(r["nemotron"]["verdict"] == "ASK" for r in attacks),
            "allow": sum(r["nemotron"]["verdict"] == "ALLOW" for r in attacks),
        },
        "clean_matched_action": {
            "n": len(clean),
            "allow": sum(r["nemotron"]["verdict"] == "ALLOW" for r in clean),
            "block": sum(r["nemotron"]["verdict"] == "BLOCK" for r in clean),
            "ask": sum(r["nemotron"]["verdict"] == "ASK" for r in clean),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"scope": "one first-post-exposure attack action and one final clean action per frozen trajectory", "metrics": metrics, "records": records}, indent=2) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=Path, help="reuse valid decisions from a full replay output")
    p.add_argument("--min-interval", type=float, default=6.5)
    args = p.parse_args()
    sample = sorted(
        select_public_v2_sample(load_trajectories(args.source / "gpt-4o-2024-05-13")),
        key=lambda trajectory: (not trajectory.is_attack, trajectory.suite, trajectory.id),
    )
    prior = {}
    if args.output.exists():
        prior = {(r["trajectory_id"], r["call_index"]): r for r in json.loads(args.output.read_text()).get("records", []) if r["nemotron"]["error"] is None}
    seeded = {}
    if args.seed and args.seed.exists():
        for trajectory in json.loads(args.seed.read_text()).get("trajectories", []):
            for call in trajectory["calls"]:
                seeded[(trajectory["id"], call["index"])] = call
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        print("NVIDIA_API_KEY is required", file=sys.stderr)
        return 2
    model = Throttled(NemotronEvaluator(SUPER_MODEL, key), args.min_interval)
    rules = DeterministicEvaluator()
    records = list(prior.values())
    done = set(prior)
    for trajectory in sample:
        cases = to_cases(trajectory)
        index = next(c.index for c in trajectory.calls if c.post_injection_exposure) if trajectory.is_attack else trajectory.calls[-1].index
        if (trajectory.id, index) in done:
            continue
        case = cases[index]
        seeded_call = seeded.get((trajectory.id, index), {})
        saved = seeded_call.get("decisions", {}).get("nemotron", {})
        decision = Decision(saved.get("verdict"), saved.get("reason", ""), saved.get("latency_ms", 0), saved.get("error"))
        if not decision.valid:
            decision = model.evaluate(case)
        records.append({
            "trajectory_id": trajectory.id, "suite": trajectory.suite,
            "kind": "exposed_attack" if trajectory.is_attack else "clean",
            "call_index": index, "function": trajectory.calls[index].function,
            "deterministic": row(rules.evaluate(case)), "nemotron": row(decision),
        })
        records.sort(key=lambda r: (r["kind"], r["suite"], r["trajectory_id"]))
        write(args.output, records)
        print(f"{len([r for r in records if r['nemotron']['error'] is None])}/100 valid", flush=True)
    write(args.output, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
