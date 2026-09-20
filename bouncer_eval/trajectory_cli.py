from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .deterministic import DeterministicEvaluator
from .report import write_trajectory_report
from .trajectories import load_trajectories, run_trajectories, summarize_trajectories


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "eval/datasets/trajectory_v1.jsonl"
DEFAULT_FREEZE_MANIFEST = ROOT / "eval/datasets/trajectory_v1.freeze.json"
DEFAULT_JSON = ROOT / "eval/results/trajectory_deterministic.json"
DEFAULT_MARKDOWN = ROOT / "eval/results/trajectory_deterministic.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Bouncer's offline end-to-end trajectory benchmark."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_FREEZE_MANIFEST)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
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

    evaluator = DeterministicEvaluator()
    outcomes = run_trajectories(trajectories, evaluator)
    summaries = {"deterministic": summarize_trajectories(trajectories, outcomes)}
    write_trajectory_report(
        trajectories,
        {"deterministic": outcomes},
        summaries,
        args.json_output,
        args.markdown_output,
        dataset_hash=dataset_hash,
    )
    summary = summaries["deterministic"]
    print(
        "deterministic: "
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
