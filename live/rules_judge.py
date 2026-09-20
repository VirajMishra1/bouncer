"""Local rules judge: decides ALLOW / ASK / BLOCK for one tool call with no network access.

This is the default for the live view (nothing leaves the machine). The Nemotron judge in judge.py is an explicit opt-in. It returns the same decision shape as
MASTERPLAN 4.5 (verdict, effect, intent_relationship, intent_match, reason, evidence)
so the real judge can replace `judge()` without touching the server or the page.
"""
import os
import re
from urllib.parse import urlparse

SECRET_PATH = re.compile(r"(\.env\b|\.ssh|id_rsa|id_ed25519|\.aws|credentials|\.npmrc|\.netrc|\.pypirc|keychain|\.gnupg|secret|token|\.pem\b)", re.I)
SENSITIVE_WRITE = re.compile(r"(\.zshrc|\.bashrc|\.bash_profile|\.profile|\.ssh/|\.git/hooks|LaunchAgents|crontab|\.claude/settings|/etc/)", re.I)
DEV_VERBS = re.compile(r"\b(fix|add|write|create|update|implement|refactor|build|make|change|edit|modify|rename|debug|test|run|install|set ?up|configure|migrate|generate|patch|remove|delete|clean|deploy|commit|push)\b", re.I)
LOOK_VERBS = re.compile(r"\b(read|summari[sz]e|explain|review|what|why|how|find|list|show|check|look|tell|describe|analy[sz]e|search|understand|audit|inspect)\b", re.I)
DESTRUCTIVE = re.compile(r"(\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)|\bgit\s+push\s+.*--force|\bgit\s+push\s+.*-f\b|\bgit\s+reset\s+--hard|\bgit\s+clean\s+-[a-z]*f|\bdrop\s+(table|database)\b|\bmkfs\b|\bdd\s+.*of=|\bchmod\s+-R\s+777|>\s*/dev/sd|\bshred\b|\btruncate\b)", re.I)
NET_SEND = re.compile(r"(\bcurl\b.*(\s-d\b|\s--data|\s-F\b|\s--form|\s-T\b|--upload-file|\s-X\s*(POST|PUT|PATCH))|\bwget\b.*--post|\bnc\b\s|\bncat\b|\bscp\b|\brsync\b.*:|\bsftp\b|\bftp\b)", re.I)
PIPE_SHELL = re.compile(r"(curl|wget)[^|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", re.I)
READ_ONLY_CMD = re.compile(r"^\s*(ls|sed\s+-n|nl|printf|readlink|realpath|basename|dirname|git\s+ls-files|cat|head|tail|pwd|wc|echo|which|whoami|date|env\s*$|git\s+(status|diff|log|show|branch|remote|rev-parse)|grep|rg|find|file|stat|tree|node\s+(-v|--version)|python3?\s+(-V|--version)|du|df|sort|uniq|jq)\b", re.I)
TEST_CMD = re.compile(r"\b(npm\s+(test|run|ci|install|i)\b|pnpm|yarn|pytest|python3?\s+-m\s+(pytest|unittest)|make\b|cargo\s+(build|test|check)|go\s+(build|test)|tsc\b|vitest|jest|eslint|ruff|mypy)\b", re.I)
INSTALL_CMD = re.compile(r"\b(npm\s+(i|install)|pip3?\s+install|brew\s+install|apt(-get)?\s+install|cargo\s+install|gem\s+install)\b", re.I)
GIT_SHIP = re.compile(r"\bgit\s+(commit|push|tag|merge|rebase)\b|\bgh\s+(pr|release)\s+(create|merge)", re.I)
SECRET_RE = re.compile(r"(nvapi-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._\-]{16,}|(?i:(?:api[_-]?key|token|secret|password|passwd)\s*[=:]\s*)[^\s'\"]+)")


def redact(v):
    """Scrub anything that looks like a credential before it is shown or logged."""
    if isinstance(v, str):
        return SECRET_RE.sub("[redacted]", v)
    if isinstance(v, dict):
        return {k: redact(x) for k, x in v.items()}
    if isinstance(v, list):
        return [redact(x) for x in v]
    return v


URL = re.compile(r"https?://([^/\s:'\"]+)", re.I)
SAFE_HOSTS = ("localhost", "127.0.0.1", "github.com", "githubusercontent.com", "npmjs.org", "npmjs.com", "pypi.org", "anthropic.com")
DEFAULT_HOST_OK = lambda h: any(h == s or h.endswith("." + s) for s in SAFE_HOSTS)


def _base(p):
    return os.path.basename(str(p).rstrip("/")) or str(p)


def _trim(s, n=44):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize(tool, inp):
    inp = inp or {}
    if tool == "Bash":
        return _trim(inp.get("command", ""))
    if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead"):
        return _base(inp.get("file_path") or inp.get("notebook_path") or "")
    if tool in ("Grep",):
        return _trim(inp.get("pattern", ""))
    if tool in ("Glob",):
        return _trim(inp.get("pattern", ""))
    if tool == "WebFetch":
        m = URL.search(inp.get("url", ""))
        return m.group(1) if m else _trim(inp.get("url", ""))
    if tool == "WebSearch":
        return _trim(inp.get("query", ""))
    for k in ("description", "prompt", "command", "path", "url", "to", "id"):
        if isinstance(inp.get(k), str):
            return _trim(inp[k])
    return ""


def table_for(tool, inp):
    t = tool.lower()
    if tool == "Bash":
        return "SHELL"
    if tool in ("WebFetch", "WebSearch") or re.search(r"send|post|http|upload|mail|slack|message", t):
        return "OUTBOX"
    if re.search(r"mail|inbox|calendar", t):
        return "MAIL"
    return "FILES"


def _mentioned(goal, text):
    text = str(text).lower()
    return bool(text) and text in goal.lower()


def _decision(verdict, effect, rel, match, reason, goal, action, mismatch=None):
    return {
        "verdict": verdict,
        "effect": effect,
        "intent_relationship": rel,
        "intent_match": match,
        "reason": reason,
        "evidence": {"user_goal": goal, "proposed_action": action, "mismatch": mismatch},
    }


def judge(goal, tool, inp, recent=None):
    """Return a decision dict. `goal` is the user's latest prompt."""
    inp = inp or {}
    goal = goal or ""
    action = f"{tool}({summarize(tool, inp)})"
    wants_change = bool(DEV_VERBS.search(goal))
    look_only = bool(LOOK_VERBS.search(goal)) and not wants_change
    D = lambda *a, **k: _decision(*a, goal=goal, action=action, **k)

    # --- file reads / search ---
    if tool in ("Read", "Glob", "Grep", "NotebookRead", "LS"):
        path = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
        if SECRET_PATH.search(str(path)) and not SECRET_PATH.search(goal):
            return D("ASK", "READ", "ambiguous", 0.3, "That file looks like it holds secrets, and you didn't ask for it.", mismatch="Secret-looking path not mentioned in the goal.")
        return D("ALLOW", "READ", "necessary_substep", 0.92, "Looking at files is how the agent understands your request.")

    # --- web ---
    if tool in ("WebFetch", "WebSearch"):
        url = inp.get("url", "")
        m = URL.search(url)
        if m and not DEFAULT_HOST_OK(m.group(1)) and len(url) > 220:
            return D("ASK", "SEND", "ambiguous", 0.35, "A very long link to a site you didn't mention could be smuggling data out.", mismatch="Long URL to unlisted host.")
        return D("ALLOW", "READ", "necessary_substep", 0.85, "Looking something up on the web is just reading.")

    # --- edits ---
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if SENSITIVE_WRITE.search(str(path)):
            return D("BLOCK", "WRITE", "unrelated", 0.05, "That file controls your machine or credentials. Nobody asked to change it.", mismatch="Write to a sensitive system file.")
        if wants_change:
            return D("ALLOW", "WRITE", "entailed", 0.9, "You asked for a change, and this edit is part of making it.")
        if look_only:
            return D("BLOCK", "WRITE", "contradictory", 0.08, "You asked to look, not change. This edits a file.", mismatch="Write during a read-only request.")
        return D("ASK", "WRITE", "ambiguous", 0.45, "This edits a file and your request didn't clearly ask for that.")

    # --- shell ---
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        hosts = URL.findall(cmd)
        outside = [h for h in hosts if not DEFAULT_HOST_OK(h) and not _mentioned(goal, h)]
        touches_secret = bool(SECRET_PATH.search(cmd)) and not SECRET_PATH.search(goal)
        if PIPE_SHELL.search(cmd):
            return D("BLOCK", "EXECUTE", "contradictory", 0.02, "This downloads code and runs it blind. That's how attackers take over.", mismatch="Remote script piped into a shell.")
        if NET_SEND.search(cmd) or (outside and re.search(r"\|\s*(curl|nc)|<\s*\S+|@\S+", cmd)):
            if touches_secret or outside:
                return D("BLOCK", "SEND", "unrelated", 0.03, "This sends data to a place you never mentioned.", mismatch="Outbound data transfer to an unlisted destination.")
            return D("ASK", "SEND", "ambiguous", 0.35, "This sends data out over the network. Is that what you wanted?")
        if DESTRUCTIVE.search(cmd):
            if re.search(r"\b(delete|remove|clean|reset|force|wipe|drop)\b", goal, re.I):
                return D("ASK", "WRITE", "ambiguous", 0.5, "This can't be undone. You mentioned deleting, but please confirm this exact command.")
            return D("BLOCK", "WRITE", "unrelated", 0.04, "This permanently deletes or overwrites things, and you didn't ask for that.", mismatch="Irreversible operation not requested.")
        if touches_secret:
            return D("ASK", "READ", "ambiguous", 0.3, "This command touches a file that looks like secrets.", mismatch="Secret-looking path not in the goal.")
        if GIT_SHIP.search(cmd):
            if re.search(r"\b(commit|push|ship|pr|pull request|release|merge|tag|deploy)\b", goal, re.I):
                return D("ALLOW", "SEND", "entailed", 0.8, "You asked to ship this, and this is the git step for it.")
            return D("ASK", "SEND", "ambiguous", 0.4, "This commits or publishes your work, and you didn't ask for that yet.")
        if INSTALL_CMD.search(cmd) and not re.search(r"\b(install|set ?up|add|dependenc|package)\b", goal, re.I):
            return D("ASK", "EXECUTE", "ambiguous", 0.4, "This installs software on your machine and you didn't ask for it.")
        if READ_ONLY_CMD.search(cmd):
            return D("ALLOW", "READ", "necessary_substep", 0.9, "A read-only command that just looks around.")
        if TEST_CMD.search(cmd) or wants_change:
            return D("ALLOW", "EXECUTE", "necessary_substep", 0.75, "Running this fits the work you asked for.")
        if outside:
            return D("ASK", "SEND", "ambiguous", 0.35, "This talks to a site you didn't mention.")
        return D("ASK", "EXECUTE", "ambiguous", 0.45, "The agent wants to run a command that isn't clearly part of your request.")

    # --- MCP / other tools ---
    if tool.startswith("mcp__"):
        name = tool.lower()
        if re.search(r"send|post|delete|remove|create|write|update|publish|transfer|pay|forward", name):
            eff = "SEND" if re.search(r"send|post|publish|forward|transfer|pay", name) else "WRITE"
            verb = re.search(r"send|post|delete|remove|create|write|update|publish|transfer|pay|forward", name).group(0)
            if re.search(verb, goal, re.I):
                return D("ALLOW", eff, "entailed", 0.7, "You asked for this kind of action.")
            return D("ASK", eff, "ambiguous", 0.25, "This changes something outside your machine, and you didn't ask for that.")
        return D("ALLOW", "READ", "necessary_substep", 0.8, "A read-only lookup through a connected tool.")

    # bookkeeping / planning tools
    return D("ALLOW", "READ", "necessary_substep", 0.85, "Internal step: the agent is planning or organizing.")
