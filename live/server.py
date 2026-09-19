#!/usr/bin/env python3
"""Bouncer live server (stdlib only).

  POST /hook     Claude Code hook payload in, decision out
  GET  /events   Server-Sent Events stream for the animation page
  GET  /health   liveness probe
  GET  /         the animation page (index.html)

Run:  python3 server.py            (port 7777, override with BOUNCER_PORT)
Popup: on the first prompt with no page open, opens a small app-style window.
       BOUNCER_NO_POPUP=1 turns that off.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import judge as judge_mod

ROOT = Path(__file__).parent
PORT = int(os.environ.get("BOUNCER_PORT", "7777"))
URL = f"http://127.0.0.1:{PORT}/?live=1"
LOG = Path(os.environ.get("BOUNCER_LOG", Path.home() / ".bouncer-pub" / "log.jsonl"))
LOG.parent.mkdir(parents=True, exist_ok=True)

lock = threading.Lock()
clients = set()            # queue.Queue per connected page
events = []                # (id, json_str) since the last prompt
next_id = 1
state = {"goal": "", "session": None, "seq": 0, "recent": [], "last_popup": 0.0}


def broadcast(evt):
    """Store and push one event to every page."""
    global next_id
    with lock:
        evt["id"] = next_id
        next_id += 1
        s = json.dumps(evt)
        if evt["type"] == "prompt":
            events.clear()
        events.append((evt["id"], s))
        del events[:-400]
        for q in list(clients):
            q.put((evt["id"], s))
    try:
        with LOG.open("a") as f:
            f.write(s + "\n")
    except OSError:
        pass


def popup():
    """Open the animation as a small app-style window (falls back to the default browser)."""
    if os.environ.get("BOUNCER_NO_POPUP") == "1":
        return
    if time.time() - state["last_popup"] < 8:
        return
    state["last_popup"] = time.time()
    chrome = "/Applications/Google Chrome.app"
    try:
        if os.path.exists(chrome):
            subprocess.Popen(["open", "-na", "Google Chrome", "--args", f"--app={URL}", "--window-size=1320,900"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["open", URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def last_assistant_text(path):
    """Final assistant message from a Claude Code transcript (best effort)."""
    try:
        text = ""
        with open(path, "r") as f:
            for line in f.readlines()[-200:]:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                msg = o.get("message") or {}
                if o.get("type") == "assistant" and isinstance(msg.get("content"), list):
                    parts = [c.get("text", "") for c in msg["content"] if c.get("type") == "text"]
                    if any(parts):
                        text = "\n".join(p for p in parts if p)
        return text.strip()[:1600]
    except OSError:
        return ""


def handle_hook(p):
    ev = p.get("hook_event_name") or p.get("event")
    sid = p.get("session_id")
    out = {"ok": True}
    if ev == "UserPromptSubmit":
        goal = (p.get("prompt") or "").strip()
        state.update(goal=goal, session=sid, seq=0, recent=[])
        had_page = bool(clients)
        broadcast({"type": "prompt", "goal": goal, "session": sid, "ts": time.time()})
        if not had_page:
            popup()
    elif ev == "PreToolUse":
        tool = p.get("tool_name", "tool")
        inp = p.get("tool_input") or {}
        state["seq"] += 1
        d = judge_mod.judge(state["goal"], tool, inp, state["recent"])
        d.update(seq=state["seq"], tool=tool, summary=judge_mod.summarize(tool, inp),
                 table=judge_mod.table_for(tool, inp), args=inp if len(json.dumps(inp)) < 600 else {"note": "large input"},
                 tool_use_id=p.get("tool_use_id"), ts=time.time(), enforce=bool(p.get("bouncer_enforce")))
        state["recent"] = (state["recent"] + [f"{tool}:{d['summary']}"])[-2:]
        if not clients:
            popup()
        broadcast({"type": "call", "decision": d})
        out["decision"] = d
    elif ev == "PostToolUse":
        broadcast({"type": "result", "tool_use_id": p.get("tool_use_id"), "tool": p.get("tool_name")})
    elif ev in ("Stop", "SubagentStop"):
        if ev == "Stop":
            text = last_assistant_text(p.get("transcript_path", ""))
            broadcast({"type": "report", "text": text, "ts": time.time()})
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, json.dumps({"ok": True, "clients": len(clients)}))
        if path in ("/", "/index.html"):
            return self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/scenario.json":
            return self._send(200, (ROOT / "scenario.json").read_bytes())
        if path == "/events":
            return self.sse()
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path.split("?")[0] != "/hook":
            return self._send(404, '{"error":"not found"}')
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
            out = handle_hook(payload)
        except Exception as e:  # never let a bad payload take the server down
            out = {"ok": False, "error": str(e)}
        self._send(200, json.dumps(out))

    def sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = queue.Queue()
        last = self.headers.get("Last-Event-ID")
        with lock:
            backlog = [s for (i, s) in events if (last is None or i > int(last))]
            clients.add(q)
        try:
            self.wfile.write(b"retry: 1500\n\n")
            for s in backlog:
                eid = json.loads(s)["id"]
                self.wfile.write(f"id: {eid}\ndata: {s}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    eid, s = q.get(timeout=3)
                    self.wfile.write(f"id: {eid}\ndata: {s}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with lock:
                clients.discard(q)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    print(f"Bouncer live server on http://127.0.0.1:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
