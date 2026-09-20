#!/usr/bin/env python3
"""Turn a Bouncer proxy audit log into a file Bouncer Live can replay.

    python3 live/audit_to_scenario.py bouncer-audit.jsonl --goal "Read my emails and summarize" -o replay.json

Then open live/index.html and use "Load audit log" (or the demo page at ?live=0). The proxy's audit
records deliberately omit goals and raw arguments, so you supply the goal and the page shows what the
log does contain: tool, effect, verdict, reason, destination/resource. `intent_relationship` is derived
from the verdict and `intent_match` is left out; neither was recorded by the judge.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules_judge import redact  # noqa: E402

RELATIONSHIP = {"ALLOW": "necessary_substep", "ASK": "ambiguous", "BLOCK": "unrelated"}


def convert(lines, goal):
    decisions, skipped = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            verdict = str(rec["verdict"]).upper()
            tool = str(rec["toolName"])
        except (ValueError, KeyError, TypeError):
            skipped += 1
            continue
        if verdict not in RELATIONSHIP:
            skipped += 1
            continue
        target = rec.get("destination") or rec.get("resource") or ""
        note = "" if rec.get("forwarded") or verdict != "ALLOW" else " (not forwarded)"
        decisions.append({
            "seq": len(decisions) + 1,
            "tool": tool,
            "summary": redact(str(target)),
            "effect": str(rec.get("effect", "EXECUTE")).upper(),
            "verdict": verdict,
            "intent_relationship": RELATIONSHIP[verdict],
            "reason": redact(str(rec.get("reason", ""))) + note,
            "evidence": {"user_goal": redact(goal), "proposed_action": f"{tool}({redact(str(target))})", "mismatch": None},
            "meta": {"source": "proxy-audit", "forwarded": bool(rec.get("forwarded")), "latency_ms": rec.get("latencyMs")},
        })
    return {"goal": redact(goal), "decisions": decisions}, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audit", type=Path, help="proxy audit JSONL (BOUNCER_AUDIT_LOG)")
    ap.add_argument("--goal", required=True, help="the user goal the session was run with (the log does not store it)")
    ap.add_argument("-o", "--out", type=Path, default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    payload, skipped = convert(args.audit.read_text(encoding="utf-8").splitlines(), args.goal)
    if not payload["decisions"]:
        print("no usable audit records found", file=sys.stderr)
        return 2
    text = json.dumps(payload, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if skipped:
        print(f"skipped {skipped} unreadable line(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
