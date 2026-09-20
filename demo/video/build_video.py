#!/usr/bin/env python3
"""Rebuild demo/artifacts/bouncer-demo-v2.mp4 from the repo's own files.

    python3 demo/video/build_video.py                 # full rebuild (re-runs the live Nemotron demo)
    python3 demo/video/build_video.py --reuse-terminal  # reuse build/terminal_raw.txt from the last run
    python3 demo/video/build_video.py --skip-tts        # reuse narration audio in build/audio

Every number on screen is read from eval/results/*.json (and finetune/results/finetune_v1.json when it exists).
The NVIDIA key is only ever passed to the `npm run demo` subprocess environment; it is never printed or written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = HERE / "build"
OUT = ROOT / "demo" / "artifacts" / "bouncer-demo-v2.mp4"
FPS = 30
VOICE = "Samantha"
RATE = 168
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"

CATEGORY = ("Prompt filters ask whether content looks malicious. "
            "Bouncer asks whether the side effect is authorized by the user's goal.")


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def load_json(rel):
    p = ROOT / rel
    return json.loads(p.read_text()) if p.exists() else None


# ------------------------------------------------------------------ Act 3: real terminal output
def find_key_file() -> Path | None:
    cands = [os.environ.get("BOUNCER_ENV_FILE"), ROOT / ".env", ROOT.parent / "bouncer" / ".env"]
    for c in cands:
        if c and Path(c).is_file():
            return Path(c)
    return None


def read_key() -> str | None:
    if os.environ.get("NVIDIA_API_KEY", "").strip():
        return os.environ["NVIDIA_API_KEY"].strip()
    f = find_key_file()
    if not f:
        return None
    for line in f.read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?NVIDIA_API_KEY\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip("'\"") or None
    return None


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_demo(offline: bool, key: str | None) -> str:
    env = dict(os.environ)
    if key and not offline:
        env["NVIDIA_API_KEY"] = key
    script = "demo:offline" if offline else "demo"
    p = subprocess.run(["npm", "run", script, "--silent", "--", "--no-color"], cwd=ROOT / "packages" / "proxy",
                       env=env, capture_output=True, text=True, timeout=300)
    out = ANSI.sub("", p.stdout)
    if p.returncode != 0 or "DECISION TRACE" not in out or "BOUNCER ON" not in out:
        raise RuntimeError(f"demo run failed (exit {p.returncode}, {len(out)} bytes of stdout)")
    if key and key in (out + p.stderr):
        raise RuntimeError("API key appeared in demo output; refusing to continue")
    if re.search(r"nvapi-[A-Za-z0-9_\-]{8,}", out + p.stderr):
        raise RuntimeError("something key-shaped appeared in demo output; refusing to continue")
    return out


def get_terminal(reuse: bool) -> dict:
    raw_p, meta_p = BUILD / "terminal_raw.txt", BUILD / "terminal_meta.json"
    if reuse and raw_p.exists() and meta_p.exists():
        return {"raw": raw_p.read_text(), **json.loads(meta_p.read_text())}
    key = read_key()
    mode, err = "live", None
    out = None
    if key:
        try:
            out = run_demo(False, key)
        except Exception as e:  # noqa: BLE001
            err = str(e)
    else:
        err = "no NVIDIA_API_KEY available"
    if out is None:
        print(f"[terminal] live run unavailable ({err}); falling back to offline replay", file=sys.stderr)
        out = run_demo(True, None)
        mode = "offline"
    nem = (ROOT / "packages/proxy/src/nemotron.ts").read_text()
    model = (re.search(r'NEMOTRON_MODEL\s*=\s*"([^"]+)"', nem) or [None, "nvidia/nemotron-3-super-120b-a12b"])[1]
    meta = {"mode": mode, "model": model, "ran_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    raw_p.write_text(out)
    meta_p.write_text(json.dumps(meta))
    return {"raw": out, **meta}


def line_cls(t: str) -> str:
    s = t.strip()
    if "BOUNCER OFF" in t or "BOUNCER ON" in t or "DECISION TRACE" in t:
        return "h"
    if "[HARM]" in t:
        return "harm"
    if "[BLOCKED]" in t:
        return "blk"
    if "[COMPLETE]" in t:
        return "done"
    if t.startswith("BLOCK"):
        return "bad"
    if t.startswith("ALLOW"):
        return "ok"
    if t.startswith("[READ]"):
        return "read"
    if t.startswith("$"):
        return "dim"
    if s.startswith("Goal:") or t.startswith("   "):
        return "dim"
    return ""


def wrap_lines(logical: list[str], width=118) -> list[dict]:
    out, g = [], -1
    for t in logical:
        if t.strip() == "":
            continue  # blank lines are re-added between sections by the caller
        g += 1
        cls = line_cls(t)
        parts = textwrap.wrap(t, width=width, subsequent_indent="    ", replace_whitespace=False, drop_whitespace=True) or [""]
        for i, part in enumerate(parts):
            out.append({"text": part, "cls": cls, "g": g})
    return out


def terminal_pages(term: dict) -> dict:
    lines = term["raw"].splitlines()
    # start at first "BOUNCER OFF"
    start = next(i for i, l in enumerate(lines) if "BOUNCER OFF" in l)
    lines = lines[start:]
    i_on = next(i for i, l in enumerate(lines) if "BOUNCER ON" in l)
    i_tr = next(i for i, l in enumerate(lines) if "DECISION TRACE" in l)
    script = "npm run demo -- --no-color" if term["mode"] == "live" else "npm run demo:offline -- --no-color"
    prompt = f"$ cd packages/proxy && {script}"
    page0_src = [prompt] + [l for l in lines[:i_tr]]
    page1_src = [l for l in lines[i_tr:]]
    p0 = wrap_lines(page0_src)
    # re-insert a blank line before the ON banner for readability
    idx = next(k for k, l in enumerate(p0) if "BOUNCER ON" in l["text"])
    p0.insert(idx, {"text": "", "cls": "", "g": p0[idx]["g"]})
    for l in p0[idx + 1:]:
        pass
    # ensure groups are contiguous after insertion (blank shares the ON header's group)
    p1 = wrap_lines(page1_src)
    live = term["mode"] == "live"
    if live:
        pill = "LIVE NEMOTRON SUPER"
        cap0 = ("Same trajectory through the real MCP proxy, judged live by Nemotron Super",
                f"Real stdio MCP client and servers. Output of `{script}`, run at build time, model {term['model']}.")
        cap1 = ("Decision trace: what Nemotron decided, and why",
                "Reads are allowed. The injected send is blocked with a reason. Anything that is not a clean ALLOW fails closed.")
    else:
        pill = "OFFLINE REPLAY"
        cap0 = ("Offline replay with a scripted stand-in judge",
                "Not Nemotron's decision. Same real MCP client and servers; the judge is a deterministic stand-in.")
        cap1 = ("Decision trace from the scripted stand-in judge",
                "Offline replay: the verdicts come from a deterministic stand-in, not from Nemotron.")
    return {
        "live": live, "pill": pill, "mode": term["mode"],
        "pages": [
            {"title": "Bouncer · counterfactual MCP replay", "lines": p0, "cap": cap0[0], "sub": cap0[1]},
            {"title": "Bouncer · decision trace", "lines": p1, "cap": cap1[0], "sub": cap1[1]},
        ],
    }


# ------------------------------------------------------------------ evidence card (data-driven)
def frac(n, d):
    return [int(n), int(d)]


def e2e_block():
    off = load_json("eval/results/trajectory_offline.json")
    live = load_json("eval/results/trajectory_live.json")
    meta = {
        "no-defense": ("No defense", "offline, no model", "none"),
        "text-rules": ("Text-only rules", "offline, keyword rules over text only", "plain"),
        "deterministic": ("Label-reading rules", "offline, reads curator labels: an upper bound, not a fair competitor", "upper"),
        "nemotron-super": ("Nemotron Super alone", "hosted NVIDIA API, no labels", "hosted"),
        "bouncer-text-super": ("Hybrid: label-free invariants + Nemotron", "hosted, no labels", "hosted"),
        "bouncer-super": ("Hybrid: label-reading invariants + Nemotron", "hosted, reads curator labels: not a fair number", "upper"),
    }
    order = ["no-defense", "text-rules", "deterministic", "nemotron-super", "bouncer-text-super", "bouncer-super"]
    sources = {}
    for name, d in ((off or {}).get("systems", {}) | {}).items():
        sources[name] = ("offline", d["summary"])
    for name, d in ((live or {}).get("systems", {})).items():
        if name not in sources:
            sources[name] = ("hosted", d["summary"])
    rows = []
    for name in order + [n for n in sources if n not in order]:
        if name not in sources:
            continue
        src, s = sources[name]
        label, note, kind = meta.get(name, (name, src, "plain"))
        rows.append({"key": name, "label": label, "note": note, "kind": kind, "hi": name == "nemotron-super",
                     "prevented": frac(s["attacker_objective_prevented"], s["attack_total"]),
                     "benign": frac(s["benign_completed"], s["benign_total"]),
                     "invalid": s.get("invalid_total")})
    ds = (off or live or {}).get("dataset", {})
    fams = len(ds.get("families", []))
    a = rows[0]["prevented"][1] if rows else 0
    b = rows[0]["benign"][1] if rows else 0
    sub = (f"{ds.get('trajectories', a + b)} frozen episodes ({a} attack, {b} benign)"
           + (f", {fams} attack families" if fams else "") + ". Small, self-authored set.")
    foot = []
    pc = ((live or {}).get("paired_comparisons") or {}).get("nemotron-super vs text-rules")
    if pc:
        lo, hi = pc["difference_ci"]
        sig = "not significant" if lo <= 0 <= hi else "interval excludes zero"
        foot.append(f"<b>Nemotron Super alone vs text-only rules:</b> {pc['wins']} win, {pc['losses']} losses, {pc['ties']} ties; "
                    f"95% interval [{lo*100:+.0f}%, {hi*100:+.0f}%]: directional, {sig}.")
    foot.append("Rows that read curator labels are upper bounds, not fair competitors. Invalid model outputs fail closed and are never forwarded. "
                "This does not claim Bouncer stops all prompt injection.")
    hosted = "nemotron-super" in sources and sources["nemotron-super"][0] == "hosted"
    return {"rows": rows, "sub": sub, "foot": foot, "hosted": hosted, "pc": pc, "n": (a, b),
            "by": {r["key"]: r for r in rows}}


def percall_block():
    nl = load_json("eval/results/go_no_go_noleak.json")
    v1 = load_json("eval/results/go_no_go_v1.json")
    S = nl["summaries"]
    lab = {"deterministic": ("Rules baseline", "deterministic, no model"), "nemotron-super": ("Nemotron Super", "hosted NVIDIA API")}
    rows = []
    for k in ("deterministic", "nemotron-super"):
        if k not in S:
            continue
        s = S[k]
        p50 = "<1 ms" if s["latency_p50_ms"] < 1 else f"{s['latency_p50_ms']/1000:.2f} s"
        rows.append({"label": lab[k][0], "note": lab[k][1], "kind": "hosted" if k == "nemotron-super" else "plain",
                     "acc": f"{s['accuracy']*100:.1f}%", "att": frac(s["attack_blocked"], s["attack_total"]),
                     "ben": frac(s["benign_allowed"], s["benign_total"]),
                     "inv": f"{s['invalid']} ({s['invalid_rate']*100:.1f}%)" if s["invalid"] else "0", "p50": p50})
    tot = S["nemotron-super"]["total"]
    foot = [f"<b>{tot} frozen cases</b> ({S['nemotron-super']['attack_total']} attack, {S['nemotron-super']['benign_total']} benign). "
            "Small, self-authored set: a diagnostic, not the headline."]
    if v1 and "nemotron-super" in v1.get("summaries", {}):
        a = v1["summaries"]["nemotron-super"]["accuracy"]
        foot.append(f"An earlier run scored {a*100:.0f}% but the dataset leaked labels; it is archived and this is the leak-free re-run.")
    sub = f"{tot} frozen cases, rules baseline vs Nemotron Super. Diagnostic only."
    misses = []
    for k in ("deterministic", "nemotron-super"):
        fl = [f for f in nl.get("failures", []) if f["system"] == k]
        if not fl:
            continue
        exp = {(f["expected"], f["actual"] or "INVALID") for f in fl}
        if exp == {("ALLOW", "BLOCK")}:
            txt = f"Wrongly blocked {len(fl)} legitimate actions (the destination was not named in the goal)."
        elif exp == {("ALLOW", "INVALID")}:
            txt = f"{len(fl)} legitimate actions came back as invalid model output, so they failed closed (blocked, never forwarded)."
        else:
            txt = f"{len(fl)} cases missed: " + ", ".join(sorted(f"expected {e}, got {a}" for e, a in exp))
        misses.append({"title": f"{lab[k][0]}: where it misses", "text": txt, "ids": ", ".join(f["case_id"] for f in fl)})
    return {"rows": rows, "sub": sub, "foot": foot, "S": S, "tot": tot, "v1": v1, "misses": misses}


def finetune_block():
    d = load_json("finetune/results/finetune_v1.json")
    if not d:
        return None
    rows = []

    def add(prefix, obj, depth=0):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                val = f"{v*100:.1f}%" if (0 <= v <= 1 and re.search(r"rate|acc|block|allow|recall|precision|f1", k, re.I)) else (f"{v:g}")
                rows.append((f"{prefix}{k}".replace("_", " "), val))
            elif isinstance(v, dict) and depth < 2 and len(rows) < 8:
                add(f"{prefix}{k} / ", v, depth + 1)
    add("", d.get("summaries", d.get("summary", d)))
    return {"title": "Fine-tune result (finetune/results/finetune_v1.json)", "rows": rows[:8],
            "note": "Shown exactly as reported in the file. Small, self-authored sets."}


# ------------------------------------------------------------------ narration + captions
def clamp(s, n=118):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def act_specs():
    sc = json.loads((ROOT / "live" / "scenario.json").read_text())
    D = sc["decisions"]
    goal = sc["goal"]
    inj = D[2]["meta"]["injection"]
    ev = lambda i: D[i]["evidence"]["proposed_action"]  # noqa: E731
    off = {
        "bouncerOn": False,
        "speed": {"-1": 1, "0": 3, "1": 3, "2": 1.25, "3": 1.3, "4": 3.5, "5": 3.5, "6": 4, "7": 4},
        "endHoldSec": 3.5,
        "captions": {
            "pre": [clamp(f'Goal: "{goal}"'), "Bouncer is OFF: nobody checks what the agent does with its tools."],
            "byDecision": {
                "0": ["The agent opens the inbox.", ev(0)],
                "1": ["It reads email #1.", ev(1)],
                "2": ["Email #2 hides an instruction written by an attacker.", clamp(f'"{inj["text"]}"  (from {inj["from"]})')],
                "3": ["The agent obeys: it sends the whole inbox to the attacker.", ev(3)],
                "4": ["It also deletes email #2. Nobody asked for that.", ev(4)],
                "5": ["And it runs a shell command that came from the email.", clamp(ev(5))],
                "6": ["Back to normal: it reads email #3.", ev(6)],
                "7": ["It emails a summary to priya@company.com.", "With no bouncer, nothing asks the user first."],
            },
            "endUseResultText": True,
            "end": ["", "Same agent, same emails. The only difference is the bouncer."],
        },
    }
    on = {
        "bouncerOn": True,
        "askWaitSec": 2.0,
        "speed": {"-1": 1, "0": 3, "1": 3, "2": 1.5, "3": 1.3, "4": 2.0, "5": 2.0, "6": 4, "7": 1.6},
        "endHoldSec": 3.5,
        "captions": {
            "pre": [clamp(f'Goal: "{goal}"'), "Bouncer is ON: every tool call is checked against the goal before it runs."],
            "byDecision": {
                "0": ["Opening the inbox: ALLOWED.", clamp(D[0]["reason"])],
                "1": ["Reading email #1: ALLOWED.", clamp(D[1]["reason"])],
                "2": ["Reading email #2: ALLOWED, but it hides an instruction.", clamp(f'"{inj["text"]}"  (from {inj["from"]})')],
                "3": ["send_email to attacker@evil.com: DENIED.", clamp(D[3]["reason"])],
                "4": ["delete_email #2: DENIED.", clamp(D[4]["reason"])],
                "5": ["run_shell from the email: DENIED.", clamp(D[5]["reason"])],
                "6": ["Back to normal: reading email #3: ALLOWED.", clamp(D[6]["reason"])],
                "7": ["priya@company.com: HOLD UP. Bouncer asks the user.", clamp(D[7]["reason"])],
            },
            "endUseResultText": True,
            "end": ["", "Reads pass, unrequested actions are stopped at the door, and the real job carries on."],
        },
    }
    return {"act1": off, "act2": on}


def spoken(n):
    return "none" if n == 0 else str(n)


def narration(term_mode, e2e, pc):
    t = {}
    t["title"] = "Bouncer. The intent firewall for AI agents."
    t["act1"] = ("I asked an agent to read my email and summarize it. Watch what happens with no bouncer. "
                 "The second email hides an instruction from an attacker. The agent obeys it, "
                 "sends my whole inbox to a stranger, and even runs a shell command from the email. "
                 "It can't tell content from commands.")
    t["act2"] = ("Same agent, same emails. This time a bouncer stands between the agent and its tools, "
                 "and checks every call against what I actually asked for. Reading is fine. "
                 "But the send, the delete and the shell command all come from the email, not from me, so they are turned away. "
                 "And the summary I asked for still gets done. "
                 "If a call is ambiguous, like emailing someone I never mentioned, Bouncer asks me first.")
    if term_mode == "live":
        t["term0"] = ("Here is the real thing. This is our M C P proxy in front of real M C P servers, "
                      "with Nemotron Super judging each call, live, through NVIDIA's API. "
                      "The same trajectory: the injected forward is refused, and the summary is still produced.")
        t["term1"] = ("The decision trace shows each call as an effect, read or send, with Nemotron's reason. "
                      "The reads are allowed. The send is blocked, because the goal was to read and summarize. "
                      "Anything that isn't a clean allow fails closed.")
    else:
        t["term0"] = ("This is our M C P proxy in front of real M C P servers. "
                      "This run is an offline replay with a scripted stand-in judge, not Nemotron's decision. "
                      "The injected forward is refused, and the summary is still produced.")
        t["term1"] = ("The decision trace shows each call as an effect with a reason. "
                      "These verdicts come from the scripted stand-in, not from the model. "
                      "Anything that isn't a clean allow fails closed.")
    by = e2e["by"]
    a, b = e2e["n"]
    s = f"The headline is end to end: {a + b} frozen episodes, {a} attacks and {b} benign tasks. "
    if "no-defense" in by:
        s += f"With no defense, {spoken(by['no-defense']['prevented'][0])} of the {a} attacks are prevented. "
    if "text-rules" in by:
        s += f"Text-only rules prevent {by['text-rules']['prevented'][0]}. "
    if e2e["hosted"]:
        n = by["nemotron-super"]
        s += (f"Nemotron Super alone, on the hosted API, prevents {n['prevented'][0]} of {a} and completes "
              f"{n['benign'][0]} of {b} benign tasks. ")
        if e2e["pc"]:
            s += "But this is a small, self-authored set, and the interval against text rules is wide: directional, not significant."
    else:
        s += "The hosted Nemotron end to end run is not in the results yet, so it is not shown. This is a small, self-authored set."
    t["ev1"] = s
    S = pc["S"]
    d, n = S.get("deterministic"), S["nemotron-super"]
    s2 = f"Per call, as a diagnostic, on {pc['tot']} frozen cases. "
    if d:
        s2 += (f"The rules baseline blocks {d['attack_blocked']} of {d['attack_total']} attacks but allows only "
               f"{d['benign_allowed']} of {d['benign_total']} legitimate actions. ")
    s2 += (f"Nemotron Super blocks {n['attack_blocked']} of {n['attack_total']} and allows "
           f"{n['benign_allowed']} of {n['benign_total']}, with {n['invalid']} invalid outputs that fail closed.")
    t["ev2"] = s2
    t["close"] = ("Bouncer, the intent firewall for AI agents. " + CATEGORY + " Nemotron makes the call.")
    return t


# ------------------------------------------------------------------ audio / video assembly
def dur(path: Path) -> float:
    o = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True).stdout.strip()
    return float(o)


def tts(texts: dict, skip: bool) -> dict:
    ad = BUILD / "audio"
    ad.mkdir(parents=True, exist_ok=True)
    lens = {}
    for k, txt in texts.items():
        aiff, wav = ad / f"{k}.aiff", ad / f"{k}.wav"
        if not (skip and wav.exists()):
            sh(["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), txt])
            sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "44100", "-ac", "1", str(wav)])
        (ad / f"{k}.txt").write_text(txt)
        lens[k] = dur(wav)
    return lens


def encode_segment(seg: dict, seconds: float, out: Path):
    """seg -> silent mp4 of exactly `seconds` (holding the last frame if shorter), with 0.3 s fades."""
    fade = f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0, seconds - 0.3):.3f}:d=0.3"
    common = ["-c:v", "libx264", "-preset", "medium", "-crf", "27", "-maxrate", "1700k", "-bufsize", "3400k", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
    if seg["type"] == "frames":
        natural = seg["count"] / FPS
        pad = f"tpad=stop_mode=clone:stop_duration={max(0.0, seconds - natural) + 0.1:.3f}," if seconds > natural else ""
        vf = f"{pad}trim=duration={seconds:.3f},setpts=PTS-STARTPTS,{fade},format=yuv420p"
        sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", f"{seg['dir']}/f_%05d.jpg",
            "-vf", vf, *common, str(out)])
    else:
        lst = BUILD / f"{seg['name']}.concat.txt"
        lines = []
        for it in seg["items"]:
            lines += [f"file '{it['file']}'", f"duration {it['dur']:.4f}"]
        lines.append(f"file '{seg['items'][-1]['file']}'")
        lst.write_text("\n".join(lines) + "\n")
        vf = f"fps={FPS},trim=duration={seconds:.3f},setpts=PTS-STARTPTS,{fade},format=yuv420p"
        sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-vf", vf, *common, str(out)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-terminal", action="store_true")
    ap.add_argument("--skip-tts", action="store_true")
    ap.add_argument("--skip-capture", action="store_true", help="reuse frames and stills from the last capture")
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)

    print("[1/6] terminal output (Act 3)")
    term = get_terminal(args.reuse_terminal)
    T = terminal_pages(term)
    print(f"      mode: {term['mode']}  ran_at: {term['ran_at']}")

    print("[2/6] evidence from eval/results")
    e2e, pc, ft = e2e_block(), percall_block(), finetune_block()
    print("      hosted end-to-end present:", e2e["hosted"], "| fine-tune present:", ft is not None)

    print("[3/6] narration")
    texts = narration(term["mode"], e2e, pc)
    lens = tts(texts, args.skip_tts)
    for k, v in lens.items():
        print(f"      {k:6s} {v:5.1f}s")

    # target durations for still-based segments
    D = {
        "title": max(4.5, lens["title"] + 1.2),
        "term0": max(14.0, lens["term0"] + 1.2),
        "term1": max(11.0, lens["term1"] + 1.2),
        "ev1": max(14.0, lens["ev1"] + 1.2),
        "ev2": max(12.0, lens["ev2"] + 1.2),
        "close": max(9.0, lens["close"] + 1.6),
    }
    try:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        remote = re.sub(r"^https?://([^@/]+@)?", "", remote).removesuffix(".git")
    except Exception:  # noqa: BLE001
        remote = ""
    data = {
        "buildDir": str(BUILD), "fps": FPS, "durations": D, "acts": act_specs(), "terminal": T,
        "e2e": e2e, "percall": pc, "finetune": ft,
        "repo": remote or "github.com/<owner>/bouncer",
        "repoNote": "docs/story/pitch.md · eval/results/ · live/index.html · packages/proxy",
    }
    (BUILD / "data.json").write_text(json.dumps(data, indent=1))
    key = read_key()
    if key and key in (BUILD / "data.json").read_text():
        raise SystemExit("key found in rendered data; aborting")

    print("[4/6] capture frames (headless Chrome)")
    if not (HERE / "node_modules").exists():
        sh(["npm", "install", "--silent"], cwd=HERE)
    if not args.skip_capture:
        sh([NODE, str(HERE / "capture.mjs"), str(BUILD / "data.json")])
    segs = {s["name"]: s for s in json.loads((BUILD / "segments.json").read_text())}

    print("[5/6] encode segments")
    order = ["title", "act1", "act2", "term0", "term1", "ev1", "ev2", "close"]
    lead = {"title": 0.5, "act1": 0.6, "act2": 0.6, "term0": 0.5, "term1": 0.4, "ev1": 0.5, "ev2": 0.4, "close": 0.6}
    seg_dir = BUILD / "segs"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir()
    starts, t, files = {}, 0.0, []
    for name in order:
        seg = segs[name]
        natural = seg["count"] / FPS if seg["type"] == "frames" else sum(i["dur"] for i in seg["items"])
        seconds = max(natural, lens.get(name, 0) + lead[name] + 0.8)
        out = seg_dir / f"{name}.mp4"
        encode_segment(seg, seconds, out)
        starts[name] = t + lead[name]
        t += dur(out)
        files.append(out)
        print(f"      {name:6s} {seconds:5.1f}s")
    lst = BUILD / "segs.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in files))
    silent = BUILD / "silent.mp4"
    sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)])

    print("[6/6] mix narration + mux")
    inputs, filt, labels = [], [], []
    for i, name in enumerate(order):
        inputs += ["-i", str(BUILD / "audio" / f"{name}.wav")]
        ms = int(starts[name] * 1000)
        filt.append(f"[{i+1}:a]adelay={ms}|{ms},volume=1.0[a{i}]")
        labels.append(f"[a{i}]")
    filt.append("".join(labels) + f"amix=inputs={len(order)}:normalize=0,alimiter=limit=0.9,apad,atrim=duration={t:.3f}[aout]")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent), *inputs,
        "-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(OUT)])
    size = OUT.stat().st_size / 1e6
    print(f"done: {OUT}  {dur(OUT):.1f}s  {size:.1f} MB")
    if size >= 20:
        print("WARNING: file is 20 MB or larger", file=sys.stderr)
    # final secret check on everything textual we rendered
    for p in (BUILD / "data.json", BUILD / "terminal_raw.txt"):
        txt = p.read_text()
        if (key and key in txt) or re.search(r"nvapi-[A-Za-z0-9_\-]{8,}", txt):
            raise SystemExit(f"secret-like text found in {p}")
    print("secret scan of rendered text: clean")


if __name__ == "__main__":
    main()
