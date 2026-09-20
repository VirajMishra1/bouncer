"""Codex -> Bouncer Live bridge (read-only).

Codex Desktop has no hooks, and its single `notify` slot is used by another app, so we do
not touch its config. Instead this tails the session files Codex already writes
(~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl) and turns them into the same events the
Claude Code hook sends: a new prompt, each tool call, and the final message.

Privacy: only sessions whose working folder is this repo (or inside an allowed folder) are
read, so unrelated Codex chats never reach the animation or the log. Add more folders with
BOUNCER_CODEX_CWD (colon-separated) or one path per line in ~/.bouncer-live/codex_cwds.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SESSIONS = Path(os.environ.get("BOUNCER_CODEX_SESSIONS", CODEX_HOME / "sessions"))
CONFIG_FILE = Path(os.environ.get("BOUNCER_HOME", Path.home() / ".bouncer-live")) / "codex_cwds"
CMD_RE = re.compile(r'"cmd"\s*:\s*"((?:[^"\\]|\\.)*)"')
PATCH_FILE_RE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: ([^\\\n\"]+)")
TOOL_RE = re.compile(r"tools\.(\w+)\(")


def prefixes():
    """Folders whose Codex sessions may be shown: this repo, BOUNCER_CODEX_CWD, and ~/.bouncer-live/codex_cwds."""
    out = [p for p in os.environ.get("BOUNCER_CODEX_CWD", "").split(":") if p]
    try:
        out += [ln.strip() for ln in CONFIG_FILE.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    except OSError:
        pass
    out.append(REPO_ROOT)
    return [p.rstrip("/") for p in out]


def in_scope(cwd, allowed):
    """A session is in scope only when its folder IS an allowed folder or is inside one."""
    cwd = cwd.rstrip("/")
    return any(cwd == p or cwd.startswith(p + "/") for p in allowed)


def recent_files(max_age_s=1800):
    """Rollout files touched recently (today + yesterday folders only)."""
    out = []
    now = datetime.now()
    for d in (now, now - timedelta(days=1)):
        folder = SESSIONS / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"
        if folder.is_dir():
            for f in folder.glob("rollout-*.jsonl"):
                try:
                    if time.time() - f.stat().st_mtime < max_age_s:
                        out.append(f)
                except OSError:
                    pass
    return out


def user_text(payload):
    item = payload.get("item") or {}
    parts = [c.get("text", "") for c in item.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip()


def to_tool_calls(payload):
    """Map one Codex tool call to zero or more (tool_name, tool_input, call_id) tuples."""
    kind, name, cid = payload.get("type"), payload.get("name", ""), payload.get("call_id")
    if kind == "custom_tool_call" and name == "exec":
        src = payload.get("input", "")
        calls = []
        if "tools.apply_patch(" in src:
            m = PATCH_FILE_RE.search(src)
            calls.append(("Edit", {"file_path": m.group(1).strip() if m else "patch"}, cid))
        for m in CMD_RE.finditer(src):
            try:
                cmd = json.loads('"' + m.group(1) + '"')
            except ValueError:
                cmd = m.group(1)
            calls.append(("Bash", {"command": cmd}, cid))
        if not calls:
            used = [t for t in TOOL_RE.findall(src) if t not in ("text", "exec_command", "apply_patch")]
            if used:
                calls.append((used[0], {"description": used[0]}, cid))
        return calls
    if kind == "function_call" and name in ("spawn_agent", "followup_task", "send_message"):
        try:
            args = json.loads(payload.get("arguments", "{}"))
        except ValueError:
            args = {}
        return [("Task", {"description": f"{name}: {args.get('task_name', '')}".strip(": ")}, cid)]
    return []


class Tail:
    def __init__(self, path, sid, offset):
        self.path, self.sid, self.offset, self.buf = path, sid, offset, b""


def run(handle, poll=1.0, log=print):
    """Poll forever. `handle(payload_dict)` is server.handle_hook."""
    tails = {}          # path -> Tail (or None when the session is out of scope)
    started = time.time()
    allowed = prefixes()
    log(f"[codex] watching {SESSIONS} for cwd prefixes {allowed}")
    while True:
        try:
            for f in recent_files():
                if f in tails:
                    continue
                try:
                    with open(f, "rb") as fh:
                        first = json.loads(fh.readline() or b"{}")
                except (OSError, ValueError):
                    continue
                meta = first.get("payload", {}) if isinstance(first.get("payload"), dict) else {}
                cwd, sid = meta.get("cwd", ""), meta.get("session_id") or meta.get("id") or f.name
                if not in_scope(cwd, allowed):
                    tails[f] = None
                    continue
                st = f.stat()
                born = getattr(st, "st_birthtime", st.st_mtime)        # ctime moves on every write; birth time does not
                new_file = born >= started - 2 and st.st_size < 2_000_000  # never replay a big old history
                tails[f] = Tail(f, "codex:" + sid, 0 if new_file else st.st_size)
                log(f"[codex] tailing {f.name} ({'new' if new_file else 'from end'}) cwd={cwd}")
            for t in [t for t in tails.values() if t]:
                try:
                    size = t.path.stat().st_size
                    if size <= t.offset:
                        continue
                    with open(t.path, "rb") as fh:
                        fh.seek(t.offset)
                        chunk = fh.read()
                    t.offset += len(chunk)
                except OSError:
                    continue
                t.buf += chunk
                *lines, t.buf = t.buf.split(b"\n")
                for line in lines:
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                    base = {"session_id": t.sid, "agent": "codex"}
                    if o.get("type") == "event_msg" and p.get("type") == "item_completed" and (p.get("item") or {}).get("type") == "UserMessage":
                        text = user_text(p)
                        if text:
                            handle({**base, "hook_event_name": "UserPromptSubmit", "prompt": text})
                    elif o.get("type") == "response_item":
                        for tool, inp, cid in to_tool_calls(p):
                            handle({**base, "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "tool_use_id": cid})
                    elif o.get("type") == "event_msg" and p.get("type") == "task_complete":
                        handle({**base, "hook_event_name": "Stop", "last_message": p.get("last_agent_message") or ""})
        except Exception as e:      # never die: this runs inside the server
            log(f"[codex] error: {e}")
        time.sleep(poll)
