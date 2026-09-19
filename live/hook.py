#!/usr/bin/env python3
"""Claude Code hook -> Bouncer live server.

Wire this to UserPromptSubmit, PreToolUse, PostToolUse and Stop. It never breaks the
agent: on any error it exits 0 silently. By default it only WATCHES (the animation
shows what Bouncer would decide). Set BOUNCER_ENFORCE=1 to make BLOCK/ASK real.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("BOUNCER_PORT", "7777"))
BASE = f"http://127.0.0.1:{PORT}"
HERE = os.path.dirname(os.path.abspath(__file__))


def post(raw):
    req = urllib.request.Request(BASE + "/hook", data=raw, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2.5) as r:
        return json.loads(r.read() or b"{}")


def alive():
    try:
        urllib.request.urlopen(BASE + "/health", timeout=0.4).read()
        return True
    except Exception:
        return False


def ensure_server():
    if alive():
        return True
    subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")], cwd=HERE, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.1)
        if alive():
            return True
    return False


def main():
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return
    if not ensure_server():
        return
    payload["bouncer_enforce"] = os.environ.get("BOUNCER_ENFORCE") == "1"
    try:
        out = post(json.dumps(payload).encode())
    except Exception:
        return
    d = out.get("decision")
    if payload.get("hook_event_name") == "PreToolUse" and d and os.environ.get("BOUNCER_ENFORCE") == "1":
        if d["verdict"] in ("BLOCK", "ASK"):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny" if d["verdict"] == "BLOCK" else "ask",
                "permissionDecisionReason": "Bouncer: " + d["reason"],
            }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
