"""Render the safety/utility Pareto chart from a results JSON.

Dependency-free (stdlib only, matching the rest of bouncer_eval) so it runs
anywhere and the SVG drops straight into the deck/README. x = benign allowed
(or completed), y = attacks blocked (or attacker objectives prevented); the
top-right quadrant is "secure AND usable".

Two result shapes are accepted and are labelled differently, because they are
different kinds of evidence:
  * per-call go/no-go JSON (`summaries`)      -> diagnostic
  * end-to-end trajectory JSON (`systems`)    -> end-to-end
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = ROOT / "eval/results/go_no_go_v1.json"
DEFAULT_SVG = ROOT / "eval/results/pareto.svg"

W = H = 540
PAD = 70  # axis margin
HIGHLIGHT = "#12b886"  # the winning system
MUTED = "#868e96"


PER_CALL_LABELS = {
    "title": "Bouncer: safety vs. usability (per-call diagnostic)",
    "x": "Benign task completion →",
    "y": "Attacks blocked →",
}
END_TO_END_LABELS = {
    "title": "Bouncer: safety vs. usability (end-to-end)",
    "x": "Benign tasks completed →",
    "y": "Attacker objectives prevented →",
}


def points(summaries: dict[str, dict[str, Any]]) -> list[tuple[str, float, float]]:
    """(label, benign rate, attack-prevented rate) per system.

    Reads per-call keys (`benign_allow_rate`, `attack_block_rate`) or end-to-end
    keys (`benign_completion_rate`, `attacker_objective_prevented_rate`).
    """
    out = []
    for name, s in summaries.items():
        benign = s.get("benign_allow_rate", s.get("benign_completion_rate", 0.0))
        attack = s.get("attack_block_rate", s.get("attacker_objective_prevented_rate", 0.0))
        out.append((name, benign, attack))
    return out


def summaries_from_payload(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Return (per-system summaries, axis/title labels) for either result shape."""
    if isinstance(payload.get("summaries"), dict):
        return payload["summaries"], PER_CALL_LABELS
    if isinstance(payload.get("systems"), dict):
        return {name: system["summary"] for name, system in payload["systems"].items()}, END_TO_END_LABELS
    raise ValueError("unrecognized results JSON: expected a 'summaries' or 'systems' object")


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _xy(benign: float, attack: float) -> tuple[float, float]:
    """Data (0..1, 0..1) -> SVG pixels, with y flipped (0 at bottom)."""
    x = PAD + benign * (W - 2 * PAD)
    y = (H - PAD) - attack * (H - 2 * PAD)
    return x, y


def build_svg(summaries: dict[str, dict[str, Any]], labels: dict[str, str] | None = None) -> str:
    labels = labels or PER_CALL_LABELS
    plot = W - 2 * PAD
    desc = "; ".join(
        f"{name}: {benign:.0%} benign, {attack:.0%} attacks stopped"
        for name, benign, attack in points(summaries)
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="system-ui,sans-serif" role="img" '
        f'aria-labelledby="pareto-title pareto-desc">',
        f'<title id="pareto-title">{_esc(labels["title"])}</title>',
        f'<desc id="pareto-desc">{_esc(desc)}</desc>',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        # "good" quadrant (top-right): high benign, high attack-block
        f'<rect x="{PAD + plot/2:.0f}" y="{PAD:.0f}" width="{plot/2:.0f}" '
        f'height="{plot/2:.0f}" fill="#12b88618"/>',
        f'<text x="{W - PAD - 6:.0f}" y="{PAD + 16:.0f}" text-anchor="end" '
        f'font-size="11" fill="{HIGHLIGHT}">secure &amp; usable</text>',
        # axes
        f'<line x1="{PAD}" y1="{H-PAD}" x2="{W-PAD}" y2="{H-PAD}" stroke="#343a40" stroke-width="1.5"/>',
        f'<line x1="{PAD}" y1="{PAD}" x2="{PAD}" y2="{H-PAD}" stroke="#343a40" stroke-width="1.5"/>',
        f'<text x="{W/2:.0f}" y="{H-24:.0f}" text-anchor="middle" font-size="13" '
        f'fill="#343a40">{_esc(labels["x"])}</text>',
        f'<text x="22" y="{H/2:.0f}" text-anchor="middle" font-size="13" fill="#343a40" '
        f'transform="rotate(-90 22 {H/2:.0f})">{_esc(labels["y"])}</text>',
        f'<text x="{W/2:.0f}" y="26" text-anchor="middle" font-size="15" '
        f'font-weight="600" fill="#212529">{_esc(labels["title"])}</text>',
    ]
    # gridlines at 0/50/100%
    for frac in (0.0, 0.5, 1.0):
        gx, _ = _xy(frac, 0)
        _, gy = _xy(0, frac)
        parts.append(f'<line x1="{gx:.0f}" y1="{PAD}" x2="{gx:.0f}" y2="{H-PAD}" stroke="#e9ecef"/>')
        parts.append(f'<line x1="{PAD}" y1="{gy:.0f}" x2="{W-PAD}" y2="{gy:.0f}" stroke="#e9ecef"/>')
        parts.append(f'<text x="{gx:.0f}" y="{H-PAD+18:.0f}" text-anchor="middle" font-size="10" fill="{MUTED}">{int(frac*100)}%</text>')
        parts.append(f'<text x="{PAD-8:.0f}" y="{gy+4:.0f}" text-anchor="end" font-size="10" fill="{MUTED}">{int(frac*100)}%</text>')
    # points
    for name, benign, attack in points(summaries):
        cx, cy = _xy(benign, attack)
        win = "super" in name.lower() or "bouncer" in name.lower()
        color = HIGHLIGHT if win else MUTED
        r = 8 if win else 6
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{color}" '
                     f'fill-opacity="0.85" stroke="#fff" stroke-width="1.5"/>')
        parts.append(f'<text x="{cx:.1f}" y="{cy-12:.1f}" text-anchor="middle" font-size="11" '
                     f'font-weight="{"700" if win else "400"}" fill="{color}">{_esc(name)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Bouncer Pareto chart as SVG.")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--out", type=Path, default=DEFAULT_SVG)
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    summaries, labels = summaries_from_payload(payload)
    svg = build_svg(summaries, labels)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding="utf-8")
    print(f"Wrote {args.out} ({len(summaries)} systems)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
