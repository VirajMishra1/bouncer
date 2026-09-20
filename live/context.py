"""Session context for the overseer: what the agent knows, so Nemotron can tell WHY an action happens.

The overseer (see bouncer_eval/overseer.py) judges a proposed tool call with the same context the agent
has. This module builds that context from what Claude Code and Codex already write to disk:

    session = {
        "user_messages": [...],   # what the user actually typed: the ONLY authority
        "agent_notes":   [...],   # the agent's own words this turn: claims, never authority
        "content_seen":  [...],   # recent tool results: untrusted data
        "prior_actions": [...],   # earlier calls this turn, with the monitor's decision when known
    }

Rules for everything here:
  * never raise: any failure yields an empty or partial context;
  * everything is passed through `rules_judge.redact` and capped to ~600 chars BEFORE it is stored or sent;
  * bounded memory and bounded work: Claude transcripts are read from the tail only (they can be many MB).

Claude Code transcript format (one JSON object per line), as observed:
  type "user"      message.content is a string or a list of blocks. Real prompts are text (origin.kind == "human");
                   tool results arrive as user entries whose blocks are `tool_result` (content: string or list of
                   text blocks) and carry a top-level `toolUseResult`. `isMeta` marks injected text (skills, caveats).
                   Prompts can embed <system-reminder> blocks, <command-name> slash-command wrappers, and
                   <task-notification> / <local-command-*> system messages.
  type "assistant" one content block per line: text, thinking or tool_use {id, name, input}.
  everything else  (attachment, system, queue-operation, mode, ...) is ignored.
Codex rollout format: see CodexContext.
"""
import json
import os
import re
import sys
import threading
from collections import OrderedDict, deque
from collections.abc import Mapping

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules_judge import redact  # noqa: E402

ITEM_CAP = 600                 # chars per string
DEFAULT_MAX_CHARS = 6000       # total budget for one context
TAIL_WINDOWS = (400_000, 2_000_000, 8_000_000)   # read this much of the end; widen only if no user message is found
LIMITS = {"user_messages": 6, "agent_notes": 6, "content_seen": 4, "prior_actions": 12}
SECTIONS = tuple(LIMITS)
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead"}

_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S | re.I)
_LOCAL_CMD = re.compile(r"<(local-command-[a-z]+|bash-[a-z]+)>.*?</\1>", re.S | re.I)
_CMD_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
_CMD_ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)
_SYSTEM_PREFIXES = ("<task-notification>", "[Request interrupted", "Caveat:", "<local-command", "<bash-")


def empty_context():
    return {name: [] for name in SECTIONS}


def _clean(value, cap=ITEM_CAP, keep_newlines=False):
    """Redact, normalise whitespace, cap. Redaction happens first so a cut never leaves half a secret."""
    try:
        text = redact(str(value))
    except Exception:
        return ""
    if keep_newlines:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text if len(text) <= cap else text[: cap - 1] + "…"


def describe_call(tool, inp):
    """One-line description of a tool call, e.g. `Bash: git status`."""
    inp = inp if isinstance(inp, Mapping) else {}
    tool = str(tool or "tool")
    if tool == "Bash":
        detail = inp.get("command", "")
    elif tool in FILE_TOOLS:
        detail = inp.get("file_path") or inp.get("notebook_path") or ""
    else:
        detail = ""
        for key in ("to", "url", "query", "pattern", "description", "prompt", "path", "id", "command"):
            if isinstance(inp.get(key), str) and inp[key]:
                detail = inp[key]
                break
    return _clean(f"{tool}: {detail}" if detail else tool, 160)


def _total(session):
    return sum(len(s) for name in SECTIONS for s in session.get(name, []))


def _fit(session, max_chars):
    """Drop the least useful old items until the whole context fits. Keeps the newest of everything."""
    floors = [("content_seen", 1), ("prior_actions", 4), ("agent_notes", 2), ("user_messages", 1),
              ("content_seen", 0), ("prior_actions", 1), ("agent_notes", 1)]
    while _total(session) > max_chars:
        for name, floor in floors:
            if len(session[name]) > floor:
                session[name].pop(0)
                break
        else:
            break
    return session


def sanitize_session(raw, max_chars=DEFAULT_MAX_CHARS):
    """Coerce anything into the four-section schema: strings only, redacted, capped, bounded. Never raises."""
    session = empty_context()
    try:
        if not isinstance(raw, Mapping):
            return session
        for name in SECTIONS:
            items = raw.get(name)
            if isinstance(items, (list, tuple)):
                cleaned = [_clean(i, keep_newlines=(name == "user_messages")) for i in list(items)[-LIMITS[name]:]]
                session[name] = [c for c in cleaned if c]
        return _fit(session, max_chars)
    except Exception:
        return empty_context()


def context_summary(session):
    """Counts per section, e.g. {"user_messages": 1, "agent_notes": 3, ...}, for the UI and logs."""
    session = session if isinstance(session, Mapping) else {}
    return {name: len(session.get(name) or []) for name in SECTIONS}


def annotate_prior(session, decisions):
    """Append the monitor's earlier verdict to matching prior actions (`... -> BLOCK`) using `prior_action_ids`."""
    try:
        ids, acts = session.get("prior_action_ids"), session.get("prior_actions")
        if decisions and isinstance(ids, list) and isinstance(acts, list) and len(ids) == len(acts):
            session["prior_actions"] = [f"{a} -> {decisions[i]}" if i in decisions else a for i, a in zip(ids, acts)]
    except Exception:
        pass
    return session


# ---------------------------------------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------------------------------------

def _human_text(text):
    """The part of a user text block that the person actually typed, or '' for system/boilerplate text."""
    text = _SYSTEM_REMINDER.sub("", text or "")
    text = _LOCAL_CMD.sub("", text).strip()
    if not text:
        return ""
    if text.startswith(_SYSTEM_PREFIXES):
        return ""
    if "<command-name>" in text:                 # slash command / skill invocation typed by the user
        name = _CMD_NAME.search(text)
        args = _CMD_ARGS.search(text)
        if not name:
            return ""
        return (name.group(1) + (" " + args.group(1) if args and args.group(1) else "")).strip()
    return text


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _read_tail(path, nbytes):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - nbytes)
        f.seek(start)
        data = f.read()
    if start > 0:                                # drop the partial first line
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else b""
    return data.decode("utf-8", "replace"), start > 0


def _events(text):
    """Ordered events from transcript lines: user / note / call / result."""
    seq = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict) or o.get("isSidechain") or not isinstance(o.get("message"), dict):
            continue
        msg = o["message"]
        content = msg.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else \
                 [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        kind = o.get("type")
        if kind == "user":
            if o.get("isMeta"):
                continue
            carrier = "toolUseResult" in o or any(b.get("type") == "tool_result" for b in blocks)
            for b in blocks:
                if b.get("type") == "tool_result":
                    seq.append(("result", b.get("tool_use_id"), _result_text(b.get("content")), bool(b.get("is_error"))))
                elif b.get("type") == "text" and not carrier:
                    origin = o.get("origin")
                    if isinstance(origin, Mapping) and origin.get("kind") not in (None, "human"):
                        continue             # task notifications and other system-originated messages
                    human = _human_text(b.get("text", ""))
                    if human:
                        seq.append(("user", human))
        elif kind == "assistant":
            if msg.get("model") == "<synthetic>":
                continue
            for b in blocks:
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    seq.append(("note", b["text"]))
                elif b.get("type") == "tool_use":
                    seq.append(("call", b.get("id"), b.get("name"), b.get("input")))
    return seq


def _build_claude(seq, current_tool_use_id, max_chars, decisions):
    labels = {}
    for ev in seq:
        if ev[0] == "call":
            labels[ev[1]] = describe_call(ev[2], ev[3])
    last_user = max((i for i, ev in enumerate(seq) if ev[0] == "user"), default=-1)
    after = seq[last_user + 1:]
    user_messages = [_clean(ev[1], keep_newlines=True) for ev in seq if ev[0] == "user"][-LIMITS["user_messages"]:]
    notes = [_clean(ev[1]) for ev in after if ev[0] == "note"][-LIMITS["agent_notes"]:]
    ids, actions = [], []
    for ev in after:
        if ev[0] == "call" and not (current_tool_use_id and ev[1] == current_tool_use_id):
            ids.append(ev[1])
            actions.append(labels[ev[1]])
    ids, actions = ids[-LIMITS["prior_actions"]:], actions[-LIMITS["prior_actions"]:]
    seen = []
    for ev in seq:
        if ev[0] == "result" and not (current_tool_use_id and ev[1] == current_tool_use_id):
            text = _clean(ev[2], 420)
            if text:
                seen.append(_clean(f"{labels.get(ev[1], 'tool')}{' [error]' if ev[3] else ''} -> {text}"))
    session = {"user_messages": [m for m in user_messages if m], "agent_notes": [n for n in notes if n],
               "content_seen": seen[-LIMITS["content_seen"]:], "prior_actions": actions, "prior_action_ids": ids}
    annotate_prior(session, decisions)
    session.pop("prior_action_ids", None)
    return _fit(session, max_chars)


_cache = OrderedDict()
_cache_lock = threading.Lock()


def claude_session_context(transcript_path, current_tool_use_id=None, max_chars=DEFAULT_MAX_CHARS, decisions=None):
    """Context for a Claude Code PreToolUse hook, from its transcript JSONL. Never raises.

    `decisions` optionally maps tool_use_id -> verdict so prior actions read like `Bash: ... -> BLOCK`.
    """
    try:
        path = os.fspath(transcript_path)
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns, current_tool_use_id, max_chars,
               tuple(sorted((decisions or {}).items()))[-40:])
        with _cache_lock:
            hit = _cache.get(key)
        if hit is not None:
            return json.loads(json.dumps(hit))
        seq = []
        for window in TAIL_WINDOWS:
            text, truncated = _read_tail(path, window)
            seq = _events(text)
            if not truncated or any(ev[0] == "user" for ev in seq):
                break
        session = _build_claude(seq, current_tool_use_id, max_chars, decisions or {})
        with _cache_lock:
            _cache[key] = session
            while len(_cache) > 16:
                _cache.popitem(last=False)
        return json.loads(json.dumps(session))
    except Exception:
        return empty_context()


# ---------------------------------------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------------------------------------

def _output_text(output):
    """Text of a Codex tool output: a string, or a list of {type: input_text|output_text, text}."""
    if isinstance(output, str):
        return output
    if isinstance(output, Mapping):
        return str(output.get("text") or output.get("content") or "")
    if isinstance(output, list):
        return "\n".join(str(b.get("text", "")) for b in output if isinstance(b, Mapping))
    return ""


class CodexContext:
    """Per-session accumulator fed by codex_watch while it tails a rollout. Bounded memory.

    Rollout lines it understands (each line is {"type", "payload"}):
      event_msg / item_completed / item.type UserMessage      -> user prompt (authority)
      response_item / message / role assistant (commentary)   -> agent note
      response_item / custom_tool_call_output | function_call_output, output text in output[].text  -> content seen
    Tool calls are registered by the watcher with `add_action` right after it sends the PreToolUse, so a call is
    never part of its own context.
    """

    def __init__(self):
        self.users = deque(maxlen=LIMITS["user_messages"])
        self.notes = deque(maxlen=LIMITS["agent_notes"])
        self.outputs = deque(maxlen=LIMITS["content_seen"])
        self.actions = deque(maxlen=LIMITS["prior_actions"])      # (call_id, text)
        self.labels = OrderedDict()                                # call_id -> description, bounded

    def add_user(self, text):
        text = _clean(text, keep_newlines=True)
        if text:
            self.users.append(text)
            self.notes.clear()          # notes and prior actions are scoped to the current turn
            self.actions.clear()

    def add_note(self, text):
        text = _clean(text)
        if text:
            self.notes.append(text)

    def add_action(self, tool, inp, call_id=None):
        text = describe_call(tool, inp)
        self.actions.append((call_id, text))
        if call_id is not None:
            self.labels[call_id] = text
            while len(self.labels) > 64:
                self.labels.popitem(last=False)

    def add_output(self, call_id, output):
        text = _clean(_output_text(output), 420)
        if text:
            self.outputs.append(_clean(f"{self.labels.get(call_id, 'tool')} -> {text}"))

    def observe(self, o):
        """Feed one parsed rollout line. Never raises."""
        try:
            p = o.get("payload") if isinstance(o, Mapping) and isinstance(o.get("payload"), Mapping) else {}
            if o.get("type") == "event_msg" and p.get("type") == "item_completed":
                item = p.get("item") if isinstance(p.get("item"), Mapping) else {}
                if item.get("type") == "UserMessage":
                    parts = [c.get("text", "") for c in item.get("content", []) if isinstance(c, Mapping) and c.get("type") == "text"]
                    self.add_user("\n".join(x for x in parts if x))
            elif o.get("type") == "response_item":
                kind = p.get("type")
                if kind == "message" and p.get("role") == "assistant" and p.get("phase") in (None, "commentary"):
                    parts = [c.get("text", "") for c in p.get("content", []) if isinstance(c, Mapping) and c.get("type") == "output_text"]
                    self.add_note("\n".join(x for x in parts if x))
                elif kind in ("custom_tool_call_output", "function_call_output"):
                    self.add_output(p.get("call_id"), p.get("output"))
        except Exception:
            pass

    def snapshot(self):
        """The session dict to attach to a PreToolUse payload. `prior_action_ids` lets the server add verdicts."""
        return {"user_messages": list(self.users), "agent_notes": list(self.notes), "content_seen": list(self.outputs),
                "prior_actions": [t for _, t in self.actions], "prior_action_ids": [i for i, _ in self.actions]}
