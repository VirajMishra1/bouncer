"""Build the single-file Bouncer evidence dashboard (``dashboard/index.html``).

Stdlib only, no network. The page is generated from the real result files and
keeps three evidence tiers visibly separate:

* A  end-to-end trajectories (headline tier),
* B  per-call diagnostic (leak-fixed re-run) -- not end-to-end evidence,
* C  archived original run (labels leaked into the prompt) -- do not cite.

Regenerate with ``python3 eval/build_dashboard.py``.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAJECTORY = ROOT / "eval" / "results" / "trajectory_deterministic.json"
DEFAULT_PER_CALL = ROOT / "eval" / "results" / "go_no_go_noleak.json"
DEFAULT_ARCHIVED = ROOT / "eval" / "results" / "go_no_go_v1.json"
DEFAULT_OUTPUT = ROOT / "dashboard" / "index.html"

TIER_A_LABEL = "end-to-end (headline tier)"
TIER_B_LABEL = "per-call diagnostic — not end-to-end evidence"
TIER_C_LABEL = "original run — labels leaked into the prompt; archived, do not cite"

REASON_LIMIT = 160
VISIBLE_FAILURES = 6

_URL_RE = re.compile(r"(https?)://", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _defang(text: str) -> str:
    """Neutralise URL schemes so the page contains no live links or fetches."""
    return _URL_RE.sub(lambda m: m.group(1) + "[:]//", text)


def esc(value: Any) -> str:
    return html.escape(_defang(str(value)), quote=True)


def _clean(value: Any, limit: int | None = None) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value if value is not None else ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit is not None and len(text) > limit:
        cut = text[: limit - 1]
        if " " in cut[limit // 2 :]:
            cut = cut.rsplit(" ", 1)[0]
        text = cut.rstrip(" ,;:.") + "…"
    return text


def _pct(num: float, den: float, digits: int = 1) -> str:
    if not den:
        return "n/a"
    quant = Decimal(1).scaleb(-digits)
    q = (Decimal(str(num)) * 100 / Decimal(str(den))).quantize(quant, rounding=ROUND_HALF_UP)
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + "%"


def _ms(value: float) -> str:
    if value < 0.01:
        return "~0 ms"
    if value >= 1000:
        return f"{value / 1000:.2f} s"
    return f"{value:.0f} ms"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _order_systems(names: Any) -> list[str]:
    return sorted(names, key=lambda n: (n != "deterministic", n))


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(message)


def _defang_tree(value: Any) -> Any:
    if isinstance(value, str):
        return _defang(value)
    if isinstance(value, list):
        return [_defang_tree(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _defang_tree(v) for k, v in value.items()}
    return value


def _json_for_script(data: Any) -> str:
    text = json.dumps(_defang_tree(data), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    # "<" / ">" / "&" as unicode escapes: JSON.parse restores them, but the HTML
    # parser can never see "</script>" or "<!--" inside the block.
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# --------------------------------------------------------------------------- #
# validation / normalisation
# --------------------------------------------------------------------------- #
def _int(mapping: dict[str, Any], key: str, where: str, default: int | None = None) -> int:
    if key not in mapping:
        _require(default is not None, f"{where}: missing required key {key!r}")
        return int(default)  # type: ignore[arg-type]
    value = mapping[key]
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0,
        f"{where}: {key!r} must be a non-negative number",
    )
    return int(round(value))


def _float(mapping: dict[str, Any], key: str, where: str, default: float | None = None) -> float:
    if key not in mapping:
        _require(default is not None, f"{where}: missing required key {key!r}")
        return float(default)  # type: ignore[arg-type]
    value = mapping[key]
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0,
        f"{where}: {key!r} must be a non-negative number",
    )
    return float(value)


def _validate_trajectory(traj: Any) -> None:
    _require(isinstance(traj, dict), "trajectory: expected a JSON object")
    _require(isinstance(traj.get("dataset_sha256"), str) and traj["dataset_sha256"], "trajectory: missing 'dataset_sha256'")
    systems = traj.get("systems")
    _require(isinstance(systems, dict) and systems, "trajectory: 'systems' must be a non-empty object")
    for name, system in systems.items():
        where = f"trajectory.systems[{name!r}]"
        _require(isinstance(system, dict), f"{where}: expected an object")
        summary = system.get("summary")
        _require(isinstance(summary, dict), f"{where}: missing 'summary'")
        for key in ("attack_total", "attacker_objective_prevented", "benign_completed", "benign_total"):
            _int(summary, key, f"{where}.summary")
        outcomes = system.get("outcomes")
        _require(isinstance(outcomes, list) and outcomes, f"{where}: 'outcomes' must be a non-empty list")
        for i, outcome in enumerate(outcomes):
            w = f"{where}.outcomes[{i}]"
            _require(isinstance(outcome, dict), f"{w}: expected an object")
            _require(isinstance(outcome.get("family"), str), f"{w}: missing 'family'")
            _require(isinstance(outcome.get("attack"), bool), f"{w}: 'attack' must be true/false")
            steps = outcome.get("steps")
            _require(isinstance(steps, list), f"{w}: 'steps' must be a list")
            for j, step in enumerate(steps):
                _require(isinstance(step, dict), f"{w}.steps[{j}]: expected an object")


def _validate_per_call(data: Any, label: str) -> None:
    _require(isinstance(data, dict), f"{label}: expected a JSON object")
    summaries = data.get("summaries")
    _require(isinstance(summaries, dict) and summaries, f"{label}: 'summaries' must be a non-empty object")
    for name, summary in summaries.items():
        where = f"{label}.summaries[{name!r}]"
        _require(isinstance(summary, dict), f"{where}: expected an object")
        norm_per_call(summary, where)
    failures = data.get("failures", [])
    _require(isinstance(failures, list), f"{label}: 'failures' must be a list")
    for i, failure in enumerate(failures):
        _require(
            isinstance(failure, dict) and "system" in failure and "case_id" in failure,
            f"{label}.failures[{i}]: needs 'system' and 'case_id'",
        )
    gate = data.get("gate")
    _require(gate is None or isinstance(gate, dict), f"{label}: 'gate' must be an object")


def norm_per_call(summary: dict[str, Any], where: str = "summary") -> dict[str, Any]:
    at = _int(summary, "attack_total", where)
    bt = _int(summary, "benign_total", where)
    total = _int(summary, "total", where, default=at + bt)
    if "attack_blocked" in summary:
        ab = _int(summary, "attack_blocked", where)
    else:
        ab = int(round(_float(summary, "attack_block_rate", where) * at))
    if "benign_allowed" in summary:
        ba = _int(summary, "benign_allowed", where)
    else:
        ba = int(round(_float(summary, "benign_allow_rate", where) * bt))
    if "correct" in summary:
        correct = _int(summary, "correct", where)
    else:
        correct = int(round(_float(summary, "accuracy", where) * total))
    if "invalid" in summary:
        invalid = _int(summary, "invalid", where)
    else:
        invalid = int(round(_float(summary, "invalid_rate", where, 0.0) * total))
    return {
        "attack_total": at,
        "benign_total": bt,
        "total": total,
        "attack_blocked": ab,
        "benign_allowed": ba,
        "correct": correct,
        "invalid": invalid,
        "p50": _float(summary, "latency_p50_ms", where),
        "p95": _float(summary, "latency_p95_ms", where),
    }


def norm_trajectory_summary(summary: dict[str, Any], where: str = "summary") -> dict[str, int]:
    return {
        "attack_total": _int(summary, "attack_total", where),
        "prevented": _int(summary, "attacker_objective_prevented", where),
        "benign_total": _int(summary, "benign_total", where),
        "benign_completed": _int(summary, "benign_completed", where),
        "ask": _int(summary, "ask_total", where, 0),
        "false_blocks": _int(summary, "false_blocks", where, 0),
        "invalid": _int(summary, "invalid_total", where, 0),
        "steps": _int(summary, "step_total", where, 0),
        "total": _int(summary, "total", where, 0),
    }


# --------------------------------------------------------------------------- #
# tier A: gate lane
# --------------------------------------------------------------------------- #
_SEND = {"send", "post", "email", "mail", "upload", "forward", "share", "publish", "exfil", "transfer"}
_EXEC = {"run", "execute", "exec", "shell", "command", "cmd", "test", "tests"}
_DELETE = {"delete", "remove", "rm", "drop", "wipe"}
_READ = {"open", "read", "fetch", "get", "list", "view", "load", "search", "inspect"}


def infer_kind(step_id: str) -> str:
    tokens = [t for t in re.split(r"[^a-z0-9]+", step_id.lower()) if t]
    for group, kind in ((_SEND, "send"), (_EXEC, "execute"), (_DELETE, "delete"), (_READ, "read")):
        if tokens and tokens[0] in group:
            return kind
    for group, kind in ((_SEND, "send"), (_EXEC, "execute"), (_DELETE, "delete"), (_READ, "read")):
        if any(t in group for t in tokens):
            return kind
    return "action"


_GLYPH = {"read": "R", "send": "S", "execute": "X", "delete": "D", "action": "A"}


def episode_id(outcome: dict[str, Any], index: int) -> str:
    return _clean(outcome.get("id") or outcome.get("trajectory_id") or f"episode-{index + 1}")


def _step_state(step: dict[str, Any]) -> str:
    if step.get("executed"):
        return "pass"
    if step.get("failed_closed"):
        return "failed"
    if str(step.get("verdict", "")).upper() == "ASK":
        return "ask"
    return "stop"


_STATE_WORD = {
    "pass": "executed",
    "stop": "stopped at the gate",
    "ask": "held for confirmation (ASK)",
    "failed": "failed closed at the gate",
}


def _row_outcome(outcome: dict[str, Any]) -> tuple[str, str]:
    steps = outcome["steps"]
    harmful_run = sum(1 for s in steps if s.get("harmful_sink") and s.get("executed"))
    harmful_stopped = sum(1 for s in steps if s.get("harmful_sink") and not s.get("executed"))
    if outcome["attack"]:
        if outcome.get("harmful_objective_achieved") or harmful_run:
            return "bad", "Harmful sink EXECUTED — attacker objective achieved"
        return "good", f"{_plural(harmful_stopped, 'harmful attempt')} stopped — objective not achieved"
    if outcome.get("benign_completed"):
        return "good", "Benign task completed"
    return "bad", "Benign task NOT completed (utility loss)"


def render_lane(name: str, system: dict[str, Any]) -> str:
    rows: list[str] = []
    for r, outcome in enumerate(system["outcomes"]):
        eid = episode_id(outcome, r)
        kind = "attack" if outcome["attack"] else "benign"
        tone, text = _row_outcome(outcome)
        chips: list[str] = []
        passed = stopped = 0
        for s, step in enumerate(outcome["steps"]):
            state = _step_state(step)
            if state == "pass":
                x = f"calc(var(--gate) + 24px + {passed * 32}px)"
                passed += 1
            else:
                x = f"calc(var(--gate) - 38px - {stopped * 32}px)"
                stopped += 1
            sid = _clean(step.get("step_id") or f"step-{s + 1}")
            action = infer_kind(sid)
            harmful = bool(step.get("harmful_sink"))
            verdict = _clean(step.get("verdict") or "n/a")
            label = (
                f"{eid}, step {sid}: {action} action"
                f"{', harmful sink' if harmful else ''}, verdict {verdict}, {_STATE_WORD[state]}"
            )
            delay = f"{r * 0.14 + s * 0.42:.2f}s"
            chips.append(
                f'<button type="button" class="chip st-{state}{" harm" if harmful else ""}" '
                f'style="--x:{x};--d:{delay}" data-sys="{esc(name)}" data-ep="{r}" data-step="{s}" '
                f'aria-label="{esc(label)}" title="{esc(label)}">{_GLYPH[action]}</button>'
            )
        rows.append(
            f'<li class="row {kind}">'
            f'<div class="row-label"><span class="pill pill-{kind}">{kind}</span>'
            f'<code class="eid">{esc(eid)}</code><span class="fam">{esc(outcome["family"].replace("_", " "))}</span></div>'
            f'<div class="track">{"".join(chips)}</div>'
            f'<div class="row-out {tone}">{esc(text)}</div></li>'
        )
    return "\n".join(rows)


def render_episode_table(name: str, system: dict[str, Any]) -> str:
    body = []
    for r, outcome in enumerate(system["outcomes"]):
        steps = outcome["steps"]
        executed = sum(1 for s in steps if s.get("executed"))
        sinks = [s for s in steps if s.get("harmful_sink")]
        stopped = sum(1 for s in sinks if not s.get("executed"))
        ran = sum(1 for s in sinks if s.get("executed"))
        result = "n/a"
        if outcome["attack"]:
            result = "achieved" if (outcome.get("harmful_objective_achieved") or ran) else "not achieved"
        body.append(
            "<tr>"
            f'<th scope="row"><code>{esc(episode_id(outcome, r))}</code></th>'
            f'<td>{esc(outcome["family"].replace("_", " "))}</td>'
            f'<td>{"attack" if outcome["attack"] else "benign"}</td>'
            f"<td>{executed} of {len(steps)}</td>"
            f"<td>{stopped} stopped, {ran} executed</td>"
            f'<td>{esc(result if outcome["attack"] else ("completed" if outcome.get("benign_completed") else "not completed"))}</td>'
            "</tr>"
        )
    return (
        '<div class="tablewrap"><table>'
        f"<caption>Every episode for {esc(name)}, straight from the result file</caption>"
        '<thead><tr><th scope="col">Episode</th><th scope="col">Family</th><th scope="col">Kind</th>'
        '<th scope="col">Steps executed</th><th scope="col">Harmful sinks</th>'
        '<th scope="col">Attacker objective / benign task</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def render_tier_a(traj: dict[str, Any]) -> str:
    out: list[str] = []
    names = _order_systems(traj["systems"])
    sha = traj["dataset_sha256"]
    fam = traj.get("dataset", {}).get("families") if isinstance(traj.get("dataset"), dict) else None
    saturated: list[str] = []
    pairs_note = ""
    for name in names:
        summary = norm_trajectory_summary(traj["systems"][name]["summary"], f"trajectory.systems[{name!r}].summary")
        if summary["prevented"] == summary["attack_total"] and summary["benign_completed"] == summary["benign_total"]:
            saturated.append(name)
    first = norm_trajectory_summary(traj["systems"][names[0]]["summary"])
    episodes = first["attack_total"] + first["benign_total"]
    n_fam = len(fam) if isinstance(fam, list) else None
    if n_fam and first["attack_total"] == first["benign_total"] == n_fam:
        pairs_note = (
            f"This set is small: {episodes} episodes = {n_fam} attack/benign pairs, one pair per attack family."
        )
    else:
        pairs_note = (
            f"This set is small: {episodes} episodes ({first['attack_total']} attack, {first['benign_total']} benign)"
            + (f" across {n_fam} families." if n_fam else ".")
        )

    hosted = any(("nemotron" in n or "hybrid" in n) for n in names)
    if hosted:
        scope = f"Systems run end-to-end on this page: {esc(', '.join(names))}."
    elif len(names) == 1:
        scope = (
            f"Only the <code>{esc(names[0])}</code> baseline was run end-to-end, offline. "
            "Nemotron and hybrid trajectory runs need the hosted API and are <strong>not included</strong> on this page."
        )
    else:
        scope = (
            f"Systems run end-to-end on this page: {esc(', '.join(names))}. "
            "No Nemotron or hybrid trajectory run is included (hosted API required)."
        )

    out.append(
        '<section id="tier-a" class="tier tier-a" aria-labelledby="h-a">'
        f'<p class="tier-tag tag-a"><span class="tag-k">Tier A</span> {esc(TIER_A_LABEL)}</p>'
        '<h2 id="h-a">Did the attack succeed, and did the real task still finish?</h2>'
        '<p class="lede">Whole multi-step episodes, scored on outcomes: was the attacker’s objective achieved, '
        "and was the legitimate task completed. This is the tier the headline claim has to rest on.</p>"
        f'<p class="scope"><strong>Scope.</strong> {scope}</p>'
    )
    for name in names:
        system = traj["systems"][name]
        s = norm_trajectory_summary(system["summary"], f"trajectory.systems[{name!r}].summary")
        out.append(f'<div class="sys-block"><h3 class="sys-h"><code>{esc(name)}</code> <span class="sys-sub">end-to-end</span></h3>')
        out.append(
            '<div class="tiles">'
            '<div class="tile ok-tile"><p class="tile-k">Attacker objective prevented</p>'
            f'<p class="num"><span class="n">{s["prevented"]}</span><span class="d">/{s["attack_total"]}</span></p>'
            f'<p class="tile-s">{_pct(s["prevented"], s["attack_total"])} of attack episodes</p></div>'
            '<div class="tile ok-tile"><p class="tile-k">Benign tasks completed</p>'
            f'<p class="num"><span class="n">{s["benign_completed"]}</span><span class="d">/{s["benign_total"]}</span></p>'
            f'<p class="tile-s">{_pct(s["benign_completed"], s["benign_total"])} of benign episodes</p></div>'
            '<div class="tile"><p class="tile-k">Other counts</p>'
            f'<p class="tile-list">false blocks <b>{s["false_blocks"]}</b><br>ASK <b>{s["ask"]}</b><br>'
            f'invalid <b>{s["invalid"]}</b><br>steps recorded <b>{s["steps"] or sum(len(o["steps"]) for o in system["outcomes"])}</b></p></div>'
            "</div>"
        )
        out.append(
            '<div class="lane-wrap">'
            f'<div class="lane-top"><h4 class="lane-h">Action stream at the authorization gate</h4>'
            '<button type="button" class="replay js-only" data-replay>Replay</button></div>'
            '<p class="lane-note">One chip per recorded step. Executed steps pass through the gate; blocked, '
            "held and failed-closed steps stop in front of it. Red-tinted chips are harmful sinks. "
            "Action type (R/S/X/D/A) is inferred from the step id; the result file does not store it.</p>"
            '<ul class="legend" aria-label="Chip legend">'
            '<li><span class="chip st-pass demo" aria-hidden="true">R</span> passed (executed)</li>'
            '<li><span class="chip st-stop harm demo" aria-hidden="true">S</span> harmful sink, blocked</li>'
            '<li><span class="chip st-ask demo" aria-hidden="true">A</span> held (ASK)</li>'
            '<li><span class="chip st-failed demo" aria-hidden="true">X</span> failed closed</li>'
            "<li>R read · S send · X execute · D delete · A other</li></ul>"
            f'<div class="lane play" data-lane role="group" aria-label="Action stream for {esc(name)}, {len(system["outcomes"])} episodes">'
            '<div class="lane-head" aria-hidden="true"><span>episode</span>'
            '<span class="lh-mid"><span class="lh-l">proposed by agent \u2192</span>'
            '<span class="lh-gate"><svg class="door" viewBox="0 0 30 40" width="20" height="27" focusable="false">'
            '<path d="M4 38V15a11 11 0 0 1 22 0v23z" fill="none" stroke="currentColor" stroke-width="2.4"/>'
            '<circle cx="21" cy="27" r="1.8" fill="currentColor"/></svg>'
            "<span>gate</span></span>"
            '<span class="lh-r">\u2192 executed</span></span><span>outcome</span></div>'
            f'<ol class="rows">{render_lane(name, system)}</ol></div>'
            '<div id="step-detail" class="detail" aria-live="polite" tabindex="-1">'
            "<p>Select a chip to read the recorded decision for that step.</p></div>"
            "</div>"
        )
        out.append(
            '<details class="alt"><summary>Text alternative: all episodes as a table</summary>'
            f"{render_episode_table(name, system)}</details></div>"
        )

    if saturated:
        honesty = (
            f"The <strong>{esc(', '.join(saturated))}</strong> baseline already scores perfectly on this set "
            f"({first['prevented']}/{first['attack_total']} attacker objectives prevented, "
            f"{first['benign_completed']}/{first['benign_total']} benign tasks completed), "
            "so the set <strong>cannot separate systems yet</strong>."
        )
    else:
        honesty = "No system saturates this set, but with so few episodes a one-episode gap is not evidence of a real difference."
    out.append(
        '<aside class="callout warn" aria-labelledby="h-a-note"><h3 id="h-a-note">Read this before citing tier A</h3><ul>'
        f"<li>{esc(pairs_note)}</li>"
        f"<li>{honesty}</li>"
        "<li>This is <strong>not</strong> proof that Bouncer beats anything. It shows the pipeline runs end-to-end and the "
        "scoring is auditable; the comparative claim still needs a harder, larger set and the runs listed under "
        "“Not yet shown”.</li>"
        f'<li>Dataset SHA-256: <abbr class="hash" title="{esc(sha)}" aria-label="SHA-256 {esc(sha)}">{esc(sha[:12])}…</abbr></li>'
        "</ul></aside></section>"
    )
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# tier B: per-call diagnostic
# --------------------------------------------------------------------------- #
def render_per_call_table(per_call: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    names = _order_systems(per_call["summaries"])
    norm = {n: norm_per_call(per_call["summaries"][n], f"per_call.summaries[{n!r}]") for n in names}
    head = "".join(f'<th scope="col"><code>{esc(n)}</code></th>' for n in names)

    def row(label: str, cells: list[str], note: str = "") -> str:
        tds = "".join(f"<td>{c}</td>" for c in cells)
        extra = f'<span class="rn">{esc(note)}</span>' if note else ""
        return f'<tr><th scope="row">{esc(label)}{extra}</th>{tds}</tr>'

    rows = [
        row("Accuracy", [f'<b>{_pct(m["correct"], m["total"])}</b> <span class="raw">{m["correct"]}/{m["total"]}</span>' for m in norm.values()]),
        row(
            "Attacks blocked",
            [f'<b>{_pct(m["attack_blocked"], m["attack_total"])}</b> <span class="raw">{m["attack_blocked"]}/{m["attack_total"]}</span>' for m in norm.values()],
            "security",
        ),
        row(
            "Benign allowed",
            [f'<b>{_pct(m["benign_allowed"], m["benign_total"])}</b> <span class="raw">{m["benign_allowed"]}/{m["benign_total"]}</span>' for m in norm.values()],
            "utility",
        ),
        row(
            "Unusable replies",
            [f'<b>{_pct(m["invalid"], m["total"])}</b> <span class="raw">{m["invalid"]}/{m["total"]}</span>' for m in norm.values()],
            "invalid rate",
        ),
        row("Latency p50", [_ms(m["p50"]) for m in norm.values()]),
        row("Latency p95", [_ms(m["p95"]) for m in norm.values()]),
    ]
    table = (
        '<div class="tablewrap"><table class="cmp">'
        "<caption>Per-call results, leak-fixed re-run: one proposed action, one verdict, scored against a label</caption>"
        f'<thead><tr><th scope="col">Metric</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return table, norm


def render_tier_b(per_call: dict[str, Any], norm: dict[str, dict[str, Any]], table: str) -> str:
    gate = per_call.get("gate") or {}
    sentence = ""
    if "deterministic" in norm and "nemotron-super" in norm:
        d, s = norm["deterministic"], norm["nemotron-super"]
        gap = s["benign_allowed"] - d["benign_allowed"]
        sentence = (
            f"Attacks blocked: {s['attack_blocked']}/{s['attack_total']} (nemotron-super) vs "
            f"{d['attack_blocked']}/{d['attack_total']} (deterministic). Benign allowed: {s['benign_allowed']}/{s['benign_total']} vs "
            f"{d['benign_allowed']}/{d['benign_total']}, a gap of {_plural(abs(gap), 'case')}"
            f"{'' if gap >= 0 else ' in the other direction'}. "
            f"nemotron-super returned {_plural(s['invalid'], 'unusable reply', 'unusable replies')}. "
            f"With only {d['attack_total']} attack and {d['benign_total']} benign cases, a gap this size is directional at best."
        )
    gate_html = ""
    if gate:
        gate_html = (
            '<p class="gate-read"><span class="gk">Dev gate readout (per-call thresholds, wording from the run script, not end-to-end):</span> '
            f'<b>{esc(gate.get("decision", "n/a"))}</b> — {esc(_clean(gate.get("reason", ""), 200))}</p>'
        )
    return (
        '<section id="tier-b" class="tier tier-b" aria-labelledby="h-b">'
        f'<p class="tier-tag tag-b"><span class="tag-k">Tier B</span> {esc(TIER_B_LABEL)}</p>'
        '<h2 id="h-b">Single-decision accuracy, after fixing the label leak</h2>'
        '<p class="lede">Each row of the dataset is one proposed action judged in isolation. Useful for finding where a '
        "judge is weak; it cannot tell you whether an attacker’s multi-step goal succeeded.</p>"
        f"{table}"
        f'<p class="read">{esc(sentence)}</p>'
        f"{gate_html}"
        '<p class="fine">Latency for hosted models includes the network round trip; the deterministic baseline is local rule evaluation. '
        "An unusable reply is scored as a miss for its class (a benign action not allowed, or an attack not confirmed blocked).</p>"
        "</section>"
    )


# --------------------------------------------------------------------------- #
# scatter
# --------------------------------------------------------------------------- #
_SC_W, _SC_H = 620, 380
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 68, 30, 50, 66


def scatter_points(traj: dict[str, Any], per_call: dict[str, Any]) -> list[dict[str, Any]]:
    pts: list[dict[str, Any]] = []
    for name in _order_systems(per_call["summaries"]):
        m = norm_per_call(per_call["summaries"][name])
        pts.append(
            {
                "tier": "per-call",
                "system": name,
                "x": m["benign_allowed"] / m["benign_total"] if m["benign_total"] else 0.0,
                "y": m["attack_blocked"] / m["attack_total"] if m["attack_total"] else 0.0,
                "xn": m["benign_allowed"],
                "xd": m["benign_total"],
                "yn": m["attack_blocked"],
                "yd": m["attack_total"],
            }
        )
    for name in _order_systems(traj["systems"]):
        s = norm_trajectory_summary(traj["systems"][name]["summary"])
        pts.append(
            {
                "tier": "end-to-end",
                "system": name,
                "x": s["benign_completed"] / s["benign_total"] if s["benign_total"] else 0.0,
                "y": s["prevented"] / s["attack_total"] if s["attack_total"] else 0.0,
                "xn": s["benign_completed"],
                "xd": s["benign_total"],
                "yn": s["prevented"],
                "yd": s["attack_total"],
            }
        )
    return pts


def _axis_lo(pts: list[dict[str, Any]]) -> float:
    low = min(min(p["x"], p["y"]) for p in pts)
    lo = math.floor((low - 0.03) * 10) / 10
    return min(0.8, max(0.0, lo))


def render_scatter(traj: dict[str, Any], per_call: dict[str, Any]) -> str:
    pts = scatter_points(traj, per_call)
    lo = _axis_lo(pts)
    span = 1.0 - lo
    pw = _SC_W - _PAD_L - _PAD_R
    ph = _SC_H - _PAD_T - _PAD_B

    def px(v: float) -> float:
        return _PAD_L + (v - lo) / span * pw

    def py(v: float) -> float:
        return _PAD_T + (1.0 - (v - lo) / span) * ph

    step = 0.05 if span <= 0.3 + 1e-9 else 0.1
    ticks = [round(lo + i * step, 4) for i in range(int(round(span / step)) + 1)]
    g: list[str] = []
    for t in ticks:
        label = _pct(t, 1, 0)
        g.append(f'<line class="grid" x1="{px(t):.1f}" y1="{_PAD_T}" x2="{px(t):.1f}" y2="{_SC_H - _PAD_B}"/>')
        g.append(f'<line class="grid" x1="{_PAD_L}" y1="{py(t):.1f}" x2="{_SC_W - _PAD_R}" y2="{py(t):.1f}"/>')
        g.append(f'<text class="tick" x="{px(t):.1f}" y="{_SC_H - _PAD_B + 18}" text-anchor="middle">{label}</text>')
        g.append(f'<text class="tick" x="{_PAD_L - 10}" y="{py(t) + 4:.1f}" text-anchor="end">{label}</text>')
    g.append(f'<rect class="frame" x="{_PAD_L}" y="{_PAD_T}" width="{pw}" height="{ph}"/>')
    # target corner: top-right
    g.append(f'<text class="corner" x="{_SC_W - _PAD_R - 6}" y="{_PAD_T + 16}" text-anchor="end">safe and useful ↗</text>')
    g.append(
        f'<text class="axis-t" x="{_PAD_L + pw / 2:.1f}" y="{_SC_H - 14}" text-anchor="middle">'
        f"benign allowed / completed (utility) →</text>"
    )
    g.append(
        f'<text class="axis-t" transform="translate(16 {_PAD_T + ph / 2:.1f}) rotate(-90)" text-anchor="middle">'
        f"attacks blocked / prevented (safety) →</text>"
    )

    # greedy label placement without overlaps
    placed: list[tuple[float, float, float, float]] = []

    def overlaps(box: tuple[float, float, float, float]) -> bool:
        return any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in placed)

    for p in pts:
        placed.append((px(p["x"]) - 11, py(p["y"]) - 11, px(p["x"]) + 11, py(p["y"]) + 11))
    marks: list[str] = []
    for p in pts:
        cx, cy = px(p["x"]), py(p["y"])
        text = p["system"] if p["tier"] == "per-call" else f'{p["system"]} (e2e)'
        width = 8.2 * len(text)
        cands = []
        for dy in (-16, 24, -34, 42, -52, 60):
            cands.append(("middle", dy))
            cands.append(("end", dy))
            cands.append(("start", dy))
        chosen = None
        for anchor, dy in cands:
            x0 = cx - width / 2 if anchor == "middle" else (cx - width if anchor == "end" else cx)
            box = (x0, cy + dy - 11, x0 + width, cy + dy + 3)
            if box[0] < 4 or box[2] > _SC_W - 4 or box[1] < 4 or box[3] > _SC_H - _PAD_B + 4:
                continue
            if overlaps(box):
                continue
            chosen = (anchor, dy, box)
            break
        if chosen is None:
            chosen = ("middle", -16, (cx - width / 2, cy - 27, cx + width / 2, cy - 13))
        anchor, dy, box = chosen
        placed.append(box)
        pct_x = _pct(p["xn"], p["xd"])
        pct_y = _pct(p["yn"], p["yd"])
        tip = (
            f'{p["system"]} — {p["tier"]}: safety {p["yn"]}/{p["yd"]} ({pct_y}), '
            f'utility {p["xn"]}/{p["xd"]} ({pct_x})'
        )
        if p["tier"] == "per-call":
            shape = f'<circle class="pt pc" cx="{cx:.1f}" cy="{cy:.1f}" r="7.5"/>'
        else:
            shape = (
                f'<path class="pt e2e" d="M{cx:.1f} {cy - 9:.1f}L{cx + 9:.1f} {cy:.1f}L{cx:.1f} {cy + 9:.1f}L{cx - 9:.1f} {cy:.1f}Z"/>'
            )
        marks.append(
            f'<g class="mark"><title>{esc(tip)}</title>{shape}'
            f'<text class="plabel" x="{cx:.1f}" y="{cy + dy:.1f}" text-anchor="{anchor}">{esc(text)}</text></g>'
        )
    desc = "; ".join(
        f'{p["system"]} ({p["tier"]}): {p["yn"]}/{p["yd"]} attacks blocked or prevented, {p["xn"]}/{p["xd"]} benign allowed or completed'
        for p in pts
    )
    svg = (
        f'<svg class="scatter" viewBox="0 0 {_SC_W} {_SC_H}" role="img" aria-labelledby="sc-t sc-d" focusable="false" '
        'xmlns="http://www.w3.org/2000/svg">'
        "<title id=\"sc-t\">Safety versus utility, by evidence tier</title>"
        f'<desc id="sc-d">Scatter plot with both axes starting at {_pct(lo, 1, 0)}. Circles are per-call diagnostic points; '
        f"diamonds are end-to-end points. Points: {esc(desc)}.</desc>"
        f'{"".join(g)}{"".join(marks)}</svg>'
    )
    rows = "".join(
        f'<tr><th scope="row"><code>{esc(p["system"])}</code></th><td>{esc(p["tier"])}</td>'
        f'<td>{p["yn"]}/{p["yd"]} ({_pct(p["yn"], p["yd"])})</td><td>{p["xn"]}/{p["xd"]} ({_pct(p["xn"], p["xd"])})</td></tr>'
        for p in pts
    )
    table = (
        '<div class="tablewrap"><table><caption>Plotted points</caption>'
        '<thead><tr><th scope="col">System</th><th scope="col">Tier</th><th scope="col">Safety (attacks blocked / prevented)</th>'
        '<th scope="col">Utility (benign allowed / completed)</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )
    legend = (
        '<ul class="legend plot-legend" aria-label="Plot legend">'
        '<li><svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false"><circle class="pt pc" cx="9" cy="9" r="6.5"/></svg>'
        " per-call diagnostic (tier B)</li>"
        '<li><svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false"><path class="pt e2e" d="M9 1.5L16.5 9L9 16.5L1.5 9Z"/></svg>'
        " end-to-end (tier A)</li></ul>"
    )
    return (
        '<section id="safety-utility" class="tier plain" aria-labelledby="h-sc">'
        '<h2 id="h-sc">Safety versus utility, tiers kept apart</h2>'
        '<p class="lede">Top-right is the goal: block every attack without blocking the real work. '
        f"<strong>Both axes start at {_pct(lo, 1, 0)}, not zero</strong>, because every point sits near the top. "
        "The two marker shapes measure different things, so read them side by side, never as one ranking. "
        "The archived leaked run is deliberately not plotted.</p>"
        f'<figure class="fig">{svg}<figcaption>{legend}</figcaption></figure>'
        f'<details class="alt"><summary>Text alternative: plotted values</summary>{table}</details>'
        "</section>"
    )


# --------------------------------------------------------------------------- #
# failures
# --------------------------------------------------------------------------- #
def classify_failure(failure: dict[str, Any]) -> tuple[str, str]:
    expected = str(failure.get("expected", "")).upper()
    got_raw = failure.get("actual", failure.get("got"))
    got = str(got_raw).upper() if got_raw not in (None, "") else None
    if expected == "ALLOW":
        if got is None:
            return "utility", "Benign action not allowed: reply unusable — utility loss"
        return "utility", f"Benign action not allowed (got {got}) — utility loss"
    if expected == "BLOCK":
        if got is None:
            return "unconfirmed", "Attack: no usable verdict, block not confirmed — counted against attack-block rate"
        return "security", f"Attack not blocked (got {got}) — security loss"
    return "other", "Verdict differs from the label"


def _failure_rows(failures: list[dict[str, Any]]) -> str:
    rows = []
    for f in failures:
        group, headline = classify_failure(f)
        expected = esc(_clean(f.get("expected", "?")))
        got_raw = f.get("actual", f.get("got"))
        got = esc(_clean(got_raw)) if got_raw not in (None, "") else "no verdict"
        reason = _clean(f.get("reason", ""), REASON_LIMIT)
        error = _clean(f.get("error", ""), 120)
        why = f'<span class="fh {group}">{esc(headline)}</span>'
        if error:
            why += f'<span class="fe">Output rejected: {esc(error)}.</span>'
        if reason:
            why += f'<span class="fr">{"Model reasoning" if error else "Reason"}: “{esc(reason)}”</span>'
        fam = _clean(f.get("family", "")).replace("_", " ")
        fam_html = '<span class="fam">' + esc(fam) + "</span>" if fam else ""
        rows.append(
            "<tr>"
            f'<th scope="row"><code>{esc(_clean(f.get("case_id")))}</code>{fam_html}</th>'
            f'<td class="eg"><span class="exp">{expected}</span> <span aria-hidden="true">→</span><span class="sr-only"> got </span> <span class="got">{got}</span></td>'
            f"<td>{why}</td></tr>"
        )
    return "".join(rows)


def _failure_table(caption: str, failures: list[dict[str, Any]]) -> str:
    return (
        '<div class="tablewrap"><table class="fail">'
        f"<caption>{esc(caption)}</caption>"
        '<thead><tr><th scope="col">Case</th><th scope="col">Expected → got</th><th scope="col">What happened</th></tr></thead>'
        f"<tbody>{_failure_rows(failures)}</tbody></table></div>"
    )


def render_failures(per_call: dict[str, Any]) -> str:
    names = _order_systems(per_call["summaries"])
    by: dict[str, list[dict[str, Any]]] = {n: [] for n in names}
    for f in per_call.get("failures", []):
        by.setdefault(str(f["system"]), []).append(f)
    blocks: list[str] = []
    for name in _order_systems(by):
        items = by[name]
        counts = {"utility": 0, "security": 0, "unconfirmed": 0, "other": 0}
        for f in items:
            counts[classify_failure(f)[0]] += 1
        if not items:
            blocks.append(
                f'<div class="fail-sys"><h3><code>{esc(name)}</code></h3><p class="none">No failures in this run.</p></div>'
            )
            continue
        parts = [
            f"{_plural(counts['utility'], 'benign action')} not allowed (<b>utility loss</b>)",
            f"{_plural(counts['security'], 'attack')} missed (<b>security loss</b>)",
        ]
        if counts["unconfirmed"]:
            parts.append(f"{_plural(counts['unconfirmed'], 'attack')} with no usable verdict (block <b>not confirmed</b>)")
        if counts["other"]:
            parts.append(f"{counts['other']} other")
        head = f'<h3><code>{esc(name)}</code> <span class="sys-sub">{_plural(len(items), "failure")}</span></h3><p class="tally">{"; ".join(parts)}.</p>'
        first, rest = items[:VISIBLE_FAILURES], items[VISIBLE_FAILURES:]
        body = _failure_table(f"Failures for {name}", first)
        if rest:
            body += (
                f'<details class="more"><summary>Show {len(rest)} more</summary>'
                f'{_failure_table(f"Failures for {name}, continued", rest)}</details>'
            )
        blocks.append(f'<div class="fail-sys">{head}{body}</div>')
    return (
        '<section id="failures" class="tier plain" aria-labelledby="h-f">'
        '<h2 id="h-f">Where it went wrong</h2>'
        '<p class="lede">Every miss from the leak-fixed per-call run, grouped by system. '
        "<b>Utility loss</b> means a legitimate action was not allowed, so real work would be blocked or delayed. "
        "<b>Security loss</b> means an attack was not blocked. These are per-call cases, not end-to-end episodes.</p>"
        f'{"".join(blocks)}</section>'
    )


# --------------------------------------------------------------------------- #
# not yet shown / archived / footer
# --------------------------------------------------------------------------- #
NOT_YET = [
    ("AgentDojo", "No external agent-security benchmark has been run."),
    ("Post-freeze adaptive attacks", "No attacks were written against the frozen system after seeing how it decides."),
    ("NeMo Guardrails comparison", "No head-to-head against a third-party guardrail product."),
    ("Hybrid / Nemotron trajectory run", "End-to-end runs of the Nemotron and hybrid systems need the hosted API and are not included."),
    ("Paired bootstrap confidence intervals across systems", "Not computed, so no claim of a statistically supported difference between systems."),
]


def render_not_yet() -> str:
    items = "".join(f"<li><b>{esc(t)}</b><span>{esc(d)}</span></li>" for t, d in NOT_YET)
    return (
        '<section id="not-yet" class="tier plain" aria-labelledby="h-n">'
        '<h2 id="h-n">Not yet shown</h2>'
        '<p class="lede">Evidence a skeptical reviewer should expect and will not find on this page.</p>'
        f'<ul class="notyet">{items}</ul></section>'
    )


def render_archived(per_call: dict[str, Any], archived: dict[str, Any] | None) -> str:
    if archived is None:
        return (
            '<section id="archived" class="tier archived" aria-labelledby="h-c">'
            f'<p class="tier-tag tag-c"><span class="tag-k">Tier C</span> {esc(TIER_C_LABEL)}</p>'
            '<h2 id="h-c">Why we don’t trust the first run</h2>'
            "<p>No archived original run was supplied to this build. It is excluded from every number on this page.</p></section>"
        )
    fixed = {n: norm_per_call(s) for n, s in per_call["summaries"].items()}
    rows = []
    notes = []
    for name in _order_systems(archived["summaries"]):
        o = norm_per_call(archived["summaries"][name], f"archived.summaries[{name!r}]")
        new = fixed.get(name)
        if new is None:
            cell = "not re-run"
        else:
            cell = f'{new["correct"]}/{new["total"]} ({_pct(new["correct"], new["total"])})'
            if (new["correct"], new["total"]) != (o["correct"], o["total"]):
                notes.append(
                    f'{name}: {o["correct"]}/{o["total"]} in the original run, {new["correct"]}/{new["total"]} after the fix'
                )
        rows.append(
            f'<tr><th scope="row"><code>{esc(name)}</code></th>'
            f'<td class="muted-num">{o["correct"]}/{o["total"]} ({_pct(o["correct"], o["total"])})</td><td>{cell}</td></tr>'
        )
    summary_line = (
        "Where the two runs differ: " + "; ".join(notes) + "."
        if notes
        else "The two runs agree on every shared system."
    )
    return (
        '<section id="archived" class="tier archived" aria-labelledby="h-c">'
        f'<p class="tier-tag tag-c"><span class="tag-k">Tier C</span> {esc(TIER_C_LABEL)}</p>'
        '<details class="arch"><summary><h2 id="h-c">Why we don’t trust the first run</h2></summary>'
        "<p>In the original run the expected labels were leaked into the prompt the model saw, so its scores were inflated. "
        "That run is archived only so the correction is auditable. It is not plotted and no headline number comes from it.</p>"
        '<div class="tablewrap"><table><caption>Accuracy, original leaked run against the leak-fixed re-run</caption>'
        '<thead><tr><th scope="col">System</th><th scope="col">Original run (leaked, do not cite)</th>'
        '<th scope="col">Leak-fixed re-run</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        f'<p class="read">{esc(summary_line)}</p></details></section>'
    )


def render_footer(traj: dict[str, Any]) -> str:
    sha = traj["dataset_sha256"]
    return (
        '<footer id="provenance" class="foot">'
        "<h2 class=\"sr-only\">Provenance</h2>"
        f'<p>Trajectory dataset SHA-256 <abbr class="hash" title="{esc(sha)}" aria-label="SHA-256 {esc(sha)}">{esc(sha[:12])}…</abbr> '
        f'· result schema v{esc(traj.get("schema_version", "?"))}.</p>'
        "<p>Generated by <code>eval/build_dashboard.py</code> from the committed result files; every number above is read "
        "from them, none is typed in. URLs inside model text are shown defanged (<code>https[:]//</code>). "
        "The page makes no network requests. Rebuild: <code>python3 eval/build_dashboard.py</code>.</p></footer>"
    )


# --------------------------------------------------------------------------- #
# assets
# --------------------------------------------------------------------------- #
CSS = r"""
:root{color-scheme:dark;
--bg:#080d1b;--bg-2:#0d1428;--panel:#101a33;--panel-2:#152144;--line:#243259;--line-2:#33447a;
--text:#e9eefb;--muted:#a3b0d0;--dim:#8794b8;--accent:#5ad1ff;--accent-ink:#04121c;
--ok:#3ddc97;--ask:#f5b73b;--bad:#ff6b7a;--ok-bg:rgba(61,220,151,.12);--bad-bg:rgba(255,107,122,.16);--warn-bg:rgba(245,183,59,.14);
--serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
--glow:radial-gradient(56rem 26rem at 88% -8%,rgba(90,209,255,.14),transparent 70%),radial-gradient(40rem 22rem at -10% 8%,rgba(90,209,255,.06),transparent 70%)}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){color-scheme:light;
--bg:#f3f6fc;--bg-2:#e9eef8;--panel:#ffffff;--panel-2:#eef2fa;--line:#cdd6ea;--line-2:#a9b6d6;
--text:#0d1730;--muted:#44547a;--dim:#5a6a90;--accent:#0a6a9e;--accent-ink:#ffffff;
--ok:#0d7a52;--ask:#8a5700;--bad:#b0203a;--ok-bg:rgba(13,122,82,.1);--bad-bg:rgba(176,32,58,.1);--warn-bg:rgba(138,87,0,.1);
--glow:radial-gradient(56rem 26rem at 88% -8%,rgba(10,106,158,.08),transparent 70%)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background-color:var(--bg);background-image:var(--glow);background-repeat:no-repeat;color:var(--text);font:400 1rem/1.55 var(--sans);overflow-wrap:anywhere}
a{color:var(--accent)}
code,.eid,.hash{font-family:var(--mono);font-size:.9em}
code{background:var(--panel-2);border:1px solid var(--line);border-radius:4px;padding:.05em .35em}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:3px}
.sr-only{position:absolute!important;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.skip{position:absolute;left:12px;top:-64px;background:var(--accent);color:var(--accent-ink);padding:.6rem .9rem;border-radius:0 0 8px 8px;font-weight:700;z-index:10;text-decoration:none}
.skip:focus{top:0}
.wrap{max-width:70rem;margin:0 auto;padding:0 16px}
header.top{padding:28px 0 8px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:.6rem;font:600 .8rem/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0 0 14px}
.brand svg{color:var(--accent)}
h1{font:700 clamp(2rem,6.4vw,3.4rem)/1.04 var(--serif);letter-spacing:-.01em;margin:0 0 .5rem;max-width:22ch}
.sub{color:var(--muted);max-width:46rem;margin:0 0 18px;font-size:1.05rem}
nav.toc ul{list-style:none;margin:0;padding:0 0 14px;display:flex;flex-wrap:wrap;gap:6px 8px}
nav.toc a{display:inline-block;font:500 .82rem/1 var(--mono);padding:.55rem .7rem;border:1px solid var(--line);border-radius:999px;color:var(--text);text-decoration:none;background:var(--bg-2)}
nav.toc a:hover{border-color:var(--accent);color:var(--accent)}
main{padding-bottom:32px}
.ledger{margin:22px 0;padding:0;list-style:none;display:grid;gap:10px}
.ledger li{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;align-items:baseline;padding:10px 14px;background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px}
.ledger .k{font:700 .78rem/1 var(--mono);letter-spacing:.06em}
.ledger .l-a{border-left-color:var(--accent)}.ledger .l-b{border-left-color:var(--ask)}.ledger .l-c{border-left-color:var(--dim)}
.ledger .t{font-weight:600}.ledger .x{grid-column:2;color:var(--muted);font-size:.92rem}
section.tier{margin:34px 0;padding:22px 0 0;border-top:1px solid var(--line)}
h2{font:700 clamp(1.4rem,4.2vw,2rem)/1.15 var(--serif);margin:.3rem 0 .5rem}
h3{font:650 1.05rem/1.3 var(--sans);margin:0 0 .4rem}
h4{margin:0;font:600 .95rem/1.3 var(--sans)}
.lede{color:var(--muted);max-width:52rem;margin:.2rem 0 1rem}
.tier-tag{display:inline-flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:0 0 .4rem;padding:.35rem .7rem;border:1px solid;border-radius:6px;font:600 .78rem/1.25 var(--mono);letter-spacing:.03em}
.tag-k{font-weight:800;letter-spacing:.1em;text-transform:uppercase}
.tag-a{color:var(--accent);border-color:var(--accent)}
.tag-b{color:var(--ask);border-color:var(--ask)}
.tag-c{color:var(--dim);border-color:var(--dim);border-style:dashed}
.scope{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;max-width:56rem}
.sys-block{margin:22px 0}
.sys-h{font:700 1.1rem/1.2 var(--sans);display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap}
.sys-sub{font:500 .8rem var(--mono);color:var(--dim)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr));gap:12px;margin:12px 0 18px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.ok-tile{border-color:color-mix(in srgb,var(--ok) 45%,var(--line))}
.tile-k{margin:0;color:var(--muted);font-size:.86rem;font-weight:600}
.num{margin:.15rem 0 .1rem;font:800 clamp(2.6rem,11vw,4rem)/1 var(--sans);font-variant-numeric:tabular-nums lining-nums;letter-spacing:-.02em}
.num .d{color:var(--dim);font-weight:600}
.ok-tile .n{color:var(--ok)}
.tile-s{margin:0;color:var(--muted);font-size:.88rem}
.tile-list{margin:.4rem 0 0;font:.9rem/1.7 var(--mono);color:var(--muted)}.tile-list b{color:var(--text);font-variant-numeric:tabular-nums}
.lane-wrap{margin:16px 0}
.lane-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.lane-note{color:var(--muted);font-size:.88rem;max-width:52rem;margin:.3rem 0 .6rem}
.replay{font:600 .85rem/1 var(--mono);background:transparent;color:var(--accent);border:1px solid var(--accent);border-radius:999px;padding:.55rem .95rem;cursor:pointer;min-height:36px}
.replay:hover{background:var(--accent);color:var(--accent-ink)}
.js-only{display:none}.js .js-only{display:inline-block}
.legend{list-style:none;margin:0 0 10px;padding:0;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.84rem;color:var(--muted);align-items:center}
.legend li{display:inline-flex;align-items:center;gap:.4rem}
.lane{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.lane-head{display:grid;grid-template-columns:14rem 1fr 11rem;align-items:end;padding:10px 12px 6px;font:600 .72rem/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}
.lh-mid{position:relative;height:34px;display:block}
.lh-mid .lh-l{position:absolute;left:0;bottom:4px}
.lh-mid .lh-r{position:absolute;right:14px;bottom:4px}
.lh-gate{position:absolute;left:var(--gate,60%);bottom:0;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:2px;color:var(--accent)}
.lh-mid{--gate:60%}
.rows{list-style:none;margin:0;padding:0}
.row{display:grid;grid-template-columns:14rem 1fr 11rem;align-items:center;border-top:1px solid var(--line);padding:0 12px}
.row-label{display:flex;flex-direction:column;gap:2px;padding:8px 8px 8px 0;min-width:0}
.eid{color:var(--text);font-size:.8rem}
.fam{font-size:.78rem;color:var(--dim)}
.pill{align-self:flex-start;font:700 .66rem/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;padding:.25rem .45rem;border-radius:4px}
.pill-attack{background:var(--bad-bg);color:var(--bad);border:1px solid var(--bad)}
.pill-benign{background:var(--ok-bg);color:var(--ok);border:1px solid var(--ok)}
.track{position:relative;height:52px;--gate:60%}
.track::before{content:"";position:absolute;top:0;bottom:0;left:var(--gate);width:6px;margin-left:-3px;background:repeating-linear-gradient(180deg,var(--accent) 0 8px,transparent 8px 11px);opacity:.9}
.track::after{content:"";position:absolute;top:0;bottom:0;left:var(--gate);width:34px;margin-left:-17px;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--accent) 16%,transparent),transparent);pointer-events:none}
.chip{position:absolute;top:12px;left:var(--x);width:28px;height:28px;padding:0;border-radius:7px;border:2px solid var(--ok);background:var(--ok-bg);color:var(--ok);font:800 .8rem/1 var(--mono);display:grid;place-items:center;cursor:pointer;z-index:1}
.chip.demo{position:static;width:22px;height:22px;font-size:.7rem;cursor:default;display:inline-grid}
.chip.harm{background:var(--bad-bg)}
.chip.st-pass.harm{border-color:var(--bad);color:var(--bad)}
.chip.st-stop{border-color:var(--bad);color:var(--bad);background:repeating-linear-gradient(135deg,var(--bad-bg) 0 4px,transparent 4px 8px)}
.chip.st-ask{border-color:var(--ask);color:var(--ask);background:var(--warn-bg)}
.chip.st-failed{border-color:var(--ask);border-style:dashed;color:var(--ask);background:var(--warn-bg)}
.chip:not(.demo):hover{transform:translateY(-1px);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}
.chip[aria-pressed="true"],.chip.sel{box-shadow:0 0 0 3px var(--accent)}
.row-out{font-size:.84rem;padding:8px 0 8px 10px}
.row-out.good{color:var(--ok)}.row-out.bad{color:var(--bad);font-weight:700}
.lane.play .chip:not(.demo){animation:cross 1.5s cubic-bezier(.2,.7,.2,1) var(--d) backwards}
.lane.play .chip.st-stop:not(.demo),.lane.play .chip.st-failed:not(.demo),.lane.play .chip.st-ask:not(.demo){animation:cross 1.5s cubic-bezier(.2,.7,.2,1) var(--d) backwards,bump .5s ease-out calc(var(--d) + 1.4s) 1}
@keyframes cross{from{left:6px;opacity:0}14%{opacity:1}to{left:var(--x);opacity:1}}
@keyframes bump{0%{box-shadow:0 0 0 0 var(--bad)}100%{box-shadow:0 0 0 12px transparent}}
.detail{border-top:1px solid var(--line);padding:10px 14px;background:var(--panel-2);font-size:.9rem;min-height:3.6rem}
.detail p{margin:0}.detail dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 12px}.detail dt{color:var(--dim)}.detail dd{margin:0}
.callout{margin:22px 0 0;border:1px solid var(--ask);border-left-width:5px;border-radius:10px;background:var(--warn-bg);padding:14px 18px;max-width:56rem}
.callout h3{margin:0 0 .3rem;color:var(--ask)}
.callout ul{margin:0;padding-left:1.1rem;display:grid;gap:.35rem}
.tablewrap{overflow-x:auto;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:.92rem}
caption{caption-side:top;text-align:left;color:var(--muted);font-size:.86rem;padding:0 0 6px}
th,td{padding:.6rem .7rem;text-align:left;vertical-align:top;border-top:1px solid var(--line)}
thead th{font:600 .74rem/1.2 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--dim);border-top:0;border-bottom:2px solid var(--line-2)}
tbody th{font-weight:600}
.cmp td,.cmp th{font-variant-numeric:tabular-nums}
.cmp td b{font-size:1.25rem}
.raw{color:var(--dim);font-family:var(--mono);font-size:.82rem}
.rn{display:block;font:500 .72rem var(--mono);color:var(--dim);letter-spacing:.04em}
.read{max-width:56rem}.fine{color:var(--dim);font-size:.85rem;max-width:56rem}
.gate-read{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:.6rem .9rem;max-width:56rem;font-size:.9rem}
.gk{color:var(--dim)}
details.alt,details.more{margin:10px 0}
summary{cursor:pointer;color:var(--accent);font-weight:600;padding:.4rem 0;min-height:32px}
summary h2{display:inline;font-size:clamp(1.2rem,3.6vw,1.6rem)}
.fig{margin:10px 0;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px}
.scatter{width:100%;height:auto;display:block;max-width:44rem;margin:0 auto}
.scatter .grid{stroke:var(--line);stroke-width:1}
.scatter .frame{fill:none;stroke:var(--line-2);stroke-width:1.5}
.scatter .tick{fill:var(--dim);font:13px var(--mono)}
.scatter .axis-t{fill:var(--muted);font:600 14px var(--sans)}
.scatter .corner{fill:var(--ok);font:600 12.5px var(--mono)}
.scatter .plabel{fill:var(--text);font:600 13.5px var(--mono);paint-order:stroke;stroke:var(--panel);stroke-width:4px;stroke-linejoin:round}
.pt.pc{fill:var(--accent);stroke:var(--panel);stroke-width:2}
.pt.e2e{fill:none;stroke:var(--ok);stroke-width:3;stroke-linejoin:round}
.plot-legend{padding:6px 4px 2px;justify-content:center}
.fail-sys{margin:18px 0;padding:14px 16px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.tally{margin:.1rem 0 .4rem;color:var(--muted)}.none{color:var(--ok);margin:.2rem 0 0}
.fail td .fh,.fail td .fe,.fail td .fr{display:block}
.fh{font-weight:700}.fh.utility{color:var(--ask)}.fh.security,.fh.unconfirmed{color:var(--bad)}
.fe{color:var(--muted);font-size:.86rem}.fr{color:var(--dim);font-size:.86rem}
.fail th .fam{display:block;font-weight:400}
.eg{font-family:var(--mono);font-size:.85rem;min-width:7rem}
.fail tbody th{min-width:5.6rem;overflow-wrap:normal;word-break:normal}
@media (max-width:480px){.fail-sys{padding:10px 10px}th,td{padding:.5rem .45rem}}
.exp,.got{font-weight:700}
.notyet{list-style:none;margin:0;padding:0;display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(min(100%,19rem),1fr))}
.notyet li{background:var(--panel);border:1px dashed var(--line-2);border-radius:10px;padding:12px 14px;display:grid;gap:2px}
.notyet li b::before{content:"\25CB  ";color:var(--dim)}
.notyet span{color:var(--muted);font-size:.9rem}
section.archived{opacity:.88}
.archived .arch{background:transparent;border:1px dashed var(--line-2);border-radius:12px;padding:10px 16px;color:var(--muted)}
.archived .muted-num{color:var(--dim);text-decoration:line-through;text-decoration-thickness:1px}
.archived table{color:var(--muted)}
footer.foot{margin-top:34px;padding:18px 0 40px;border-top:1px solid var(--line);color:var(--dim);font-size:.86rem}
.hash{cursor:help;border-bottom:1px dotted currentColor;text-decoration:none}
@media (max-width:760px){
 .lane-head{display:none}
 .row{grid-template-columns:1fr;padding:0 10px}
 .row-label{flex-direction:row;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:8px 0 0}
 .row-out{padding:0 0 8px}
}
@media (max-width:420px){.chip{width:26px;height:26px}}
@media (prefers-reduced-motion:reduce){
 *,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
 .replay{display:none!important}
}
@media (forced-colors:active){.chip{border-color:CanvasText;forced-color-adjust:none}}
"""

JS = r"""
(function () {
  'use strict';
  document.documentElement.classList.add('js');
  var dataEl = document.getElementById('bouncer-data');
  var data = null;
  try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var panel = document.getElementById('step-detail');
  var selected = null;

  function add(dl, k, v) {
    var dt = document.createElement('dt'); dt.textContent = k;
    var dd = document.createElement('dd'); dd.textContent = v;
    dl.appendChild(dt); dl.appendChild(dd);
  }
  function show(chip) {
    if (!panel || !data || !data.trajectory) { return; }
    var sys = data.trajectory.systems[chip.getAttribute('data-sys')];
    if (!sys) { return; }
    var ep = sys.outcomes[+chip.getAttribute('data-ep')];
    var st = ep && ep.steps[+chip.getAttribute('data-step')];
    if (!st) { return; }
    if (selected) { selected.classList.remove('sel'); }
    selected = chip; chip.classList.add('sel');
    var dl = document.createElement('dl');
    add(dl, 'Episode', String(ep.trajectory_id || ep.id || '') + ' (' + (ep.attack ? 'attack' : 'benign') + ', ' + String(ep.family).replace(/_/g, ' ') + ')');
    add(dl, 'Step', String(st.step_id) + (st.retry_of ? ' (retry of ' + st.retry_of + ')' : ''));
    add(dl, 'Verdict', String(st.verdict) + (st.executed ? ' — executed' : ' — not executed') + (st.failed_closed ? ', failed closed' : '') + (st.harmful_sink ? ', harmful sink' : ''));
    add(dl, 'Reason', String(st.reason || 'none recorded'));
    if (typeof st.latency_ms === 'number') { add(dl, 'Latency', st.latency_ms < 0.01 ? '~0 ms' : st.latency_ms.toFixed(2) + ' ms'); }
    if (st.error) { add(dl, 'Error', String(st.error)); }
    while (panel.firstChild) { panel.removeChild(panel.firstChild); }
    panel.appendChild(dl);
  }
  document.addEventListener('click', function (ev) {
    var t = ev.target;
    while (t && t !== document) {
      if (t.classList && t.classList.contains('chip') && t.hasAttribute('data-step')) { show(t); return; }
      t = t.parentNode;
    }
  });
  var lanes = document.querySelectorAll('[data-lane]');
  var btns = document.querySelectorAll('[data-replay]');
  Array.prototype.forEach.call(btns, function (b) {
    b.addEventListener('click', function () {
      Array.prototype.forEach.call(lanes, function (l) {
        l.classList.remove('play'); void l.offsetWidth; l.classList.add('play');
      });
    });
  });
})();
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Bouncer Evidence Ledger</title>
<meta name="description" content="What Bouncer's evaluation has and has not shown, split into end-to-end, per-call diagnostic, and archived tiers.">
<style>%%CSS%%</style>
</head>
<body>
<a class="skip" href="#main">Skip to main content</a>
<header class="top"><div class="wrap">
<p class="brand"><svg width="22" height="28" viewBox="0 0 30 40" aria-hidden="true" focusable="false"><path d="M4 38V15a11 11 0 0 1 22 0v23z" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M15 4v8" stroke="currentColor" stroke-width="2"/><circle cx="21" cy="27" r="2" fill="currentColor"/></svg>Bouncer &middot; evidence ledger</p>
<h1>What we have measured, and what we have not.</h1>
<p class="sub">An action firewall for AI agents, checked at three evidence tiers that this page never blends. Everything below is read from the committed result files.</p>
<nav class="toc" aria-label="Sections"><ul>
<li><a href="#tier-a">A &middot; End-to-end</a></li>
<li><a href="#tier-b">B &middot; Per-call</a></li>
<li><a href="#safety-utility">Safety vs utility</a></li>
<li><a href="#failures">Failures</a></li>
<li><a href="#not-yet">Not yet shown</a></li>
<li><a href="#archived">C &middot; Archived</a></li>
</ul></nav>
</div></header>
<main id="main" class="wrap" tabindex="-1">
<h2 class="sr-only">Evidence tiers</h2>
<ol class="ledger" aria-label="Evidence tiers at a glance">
<li class="l-a"><span class="k">A</span><span class="t">%%TIER_A%%</span><span class="x">Whole episodes, scored on outcomes. The only tier a headline claim may rest on.</span></li>
<li class="l-b"><span class="k">B</span><span class="t">%%TIER_B%%</span><span class="x">One action, one verdict, scored against a label. Finds weak spots; proves nothing end-to-end.</span></li>
<li class="l-c"><span class="k">C</span><span class="t">%%TIER_C%%</span><span class="x">Kept only so the correction is auditable. Not plotted, not in any headline.</span></li>
</ol>
%%BODY%%
</main>
<div class="wrap">%%FOOTER%%</div>
<script id="bouncer-data" type="application/json">%%DATA%%</script>
<script>%%JS%%</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def render_html(
    trajectory: dict[str, Any],
    per_call: dict[str, Any],
    archived_per_call: dict[str, Any] | None,
) -> str:
    _validate_trajectory(trajectory)
    _validate_per_call(per_call, "per_call")
    if archived_per_call is not None:
        _validate_per_call(archived_per_call, "archived_per_call")

    table, norm = render_per_call_table(per_call)
    body = "\n".join(
        [
            render_tier_a(trajectory),
            render_tier_b(per_call, norm, table),
            render_scatter(trajectory, per_call),
            render_failures(per_call),
            render_not_yet(),
            render_archived(per_call, archived_per_call),
        ]
    )
    data = {
        "archived_per_call": archived_per_call,
        "per_call": per_call,
        "trajectory": trajectory,
    }
    values = {
        "CSS": CSS,
        "TIER_A": esc(TIER_A_LABEL),
        "TIER_B": esc(TIER_B_LABEL),
        "TIER_C": esc(TIER_C_LABEL),
        "BODY": body,
        "FOOTER": render_footer(trajectory),
        "JS": JS,
        "DATA": _json_for_script(data),
    }
    # One pass: substituted text is never re-scanned for placeholders.
    return re.sub(r"%%([A-Z_]+)%%", lambda m: values[m.group(1)], TEMPLATE)


def build_dashboard(
    trajectory: dict,
    per_call: dict,
    archived_per_call: dict | None,
    output: Path,
) -> None:
    """Validate the inputs and write a single self-contained HTML file."""
    page = render_html(trajectory, per_call, archived_per_call)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8", newline="\n")


def _load(path: Path, label: str) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{label} file not found: {path}") from None
    except OSError as exc:
        raise ValueError(f"cannot read {label} file {path}: {exc}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} file {path} is not valid JSON: {exc}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Bouncer evidence dashboard from result files.")
    parser.add_argument("--trajectory-json", type=Path, default=DEFAULT_TRAJECTORY)
    parser.add_argument("--per-call-json", type=Path, default=DEFAULT_PER_CALL)
    parser.add_argument("--archived-per-call-json", type=Path, default=None)
    parser.add_argument("--no-archived", action="store_true", help="omit the archived-run tier")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        trajectory = _load(args.trajectory_json, "trajectory")
        per_call = _load(args.per_call_json, "per-call")
        archived = None
        if not args.no_archived:
            if args.archived_per_call_json is not None:
                archived = _load(args.archived_per_call_json, "archived per-call")
            elif DEFAULT_ARCHIVED.exists():
                archived = _load(DEFAULT_ARCHIVED, "archived per-call")
            else:
                print(f"warning: {DEFAULT_ARCHIVED} not found; building without the archived tier", file=sys.stderr)
        build_dashboard(trajectory, per_call, archived, args.out)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
