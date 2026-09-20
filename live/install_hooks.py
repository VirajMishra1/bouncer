#!/usr/bin/env python3
"""Wire Bouncer Live into Claude Code for ALL your sessions (reversible).

Cloning this repo already enables it for sessions opened in the repo (see .claude/settings.json).
Use this only if you want the animation for every project on your machine.

  python3 install_hooks.py             show exactly what would change (dry run)
  python3 install_hooks.py --apply     back up settings.json, then add the hooks
  python3 install_hooks.py --uninstall remove only the hooks this script added

Scope: user-level ~/.claude/settings.json by default (every Claude Code session).
       --project <dir> writes <dir>/.claude/settings.local.json instead (that folder only).
Mode:  watch-only by default (the animation shows what Bouncer WOULD decide; nothing is blocked).
       --enforce makes the hook return deny/ask for real. Try watch-only first.
"""
import argparse
import difflib
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MARKS = (os.path.join("live", "hook.py"), "bouncer-pub/hook.py")   # how we recognise our own entries (current + legacy)
EVENTS = ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]


def entry(enforce):
    cmd = ("BOUNCER_ENFORCE=1 " if enforce else "") + f"{sys.executable} {os.path.join(HERE, 'hook.py')}"
    e = {"hooks": [{"type": "command", "command": cmd, "timeout": 5}]}
    return e


def ours(group):
    return any(m in h.get("command", "") for m in MARKS for h in group.get("hooks", []))


def merge(settings, enforce):
    out = json.loads(json.dumps(settings))
    hooks = out.setdefault("hooks", {})
    for ev in EVENTS:
        groups = [g for g in hooks.get(ev, []) if not ours(g)]
        g = entry(enforce)
        if ev in ("PreToolUse", "PostToolUse"):
            g["matcher"] = "*"
        groups.append(g)
        hooks[ev] = groups
    return out


def strip(settings):
    out = json.loads(json.dumps(settings))
    hooks = out.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [g for g in hooks[ev] if not ours(g)]
        if not hooks[ev]:
            del hooks[ev]
    if not hooks:
        out.pop("hooks", None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--enforce", action="store_true")
    ap.add_argument("--project", help="install into <dir>/.claude/settings.local.json instead of user settings")
    a = ap.parse_args()

    path = (os.path.join(os.path.abspath(a.project), ".claude", "settings.local.json") if a.project
            else os.path.expanduser("~/.claude/settings.json"))
    cur = {}
    if os.path.exists(path):
        with open(path) as f:
            cur = json.load(f)
    new = strip(cur) if a.uninstall else merge(cur, a.enforce)

    before = json.dumps(cur, indent=2, sort_keys=False).splitlines()
    after = json.dumps(new, indent=2, sort_keys=False).splitlines()
    diff = list(difflib.unified_diff(before, after, "current", "proposed", lineterm=""))
    if not diff:
        print("Nothing to change.")
        return
    print(f"Target: {path}\n")
    print("\n".join(diff))
    if not a.apply:
        print("\nDry run only. Re-run with --apply to write this (a backup is saved first).")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        bak = f"{path}.bouncer-backup-{int(time.time())}"
        shutil.copy2(path, bak)
        print(f"\nBackup: {bak}")
    with open(path, "w") as f:
        json.dump(new, f, indent=2)
        f.write("\n")
    print("Written. Start a NEW Claude Code session for hooks to take effect.")


if __name__ == "__main__":
    sys.exit(main())
