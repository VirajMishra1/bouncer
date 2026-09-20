# Bouncer MCP proxy

Bouncer is a local stdio MCP relay that checks every downstream `tools/call` against the user's original goal before forwarding it. NVIDIA Nemotron Super acts as a strict, non-chat authorization judge.

## Security behavior

- Captures the original goal through `bouncer_set_goal` (or `BOUNCER_GOAL`).
- Normalizes each tool call to `READ`, `SEND`, or `EXECUTE`.
- Sends the goal, concrete action with typed arguments, neutral destination/resource identifiers, and the previous two untrusted tool results to Nemotron.
- Forwards only a valid `ALLOW`; `BLOCK`, invalid model output, network failure, missing goal, and audit failure all fail closed.
- Treats a `SEND` to a destination absent from the goal as `ASK`: it is never forwarded, the reason is logged, and structured approval details are returned to the host (`structuredContent.approvalRequired`). There is no approval-resume step yet.
- The goal is set once and locked. A later `bouncer_set_goal` with different text is refused unless the proxy is built with `allowGoalChange`.
- Deterministic invariants run before the model and cannot be overruled by it: destructive operations, secret-bearing sends (any field, JSON-quoted or prefixed tokens), execution of text copied from earlier untrusted output, and sends with no determinable destination.
- Writes JSONL audit records without raw arguments, goals, tool-result bodies, or API keys.

The prompt, JSON schema, endpoint, model, and reasoning settings match `bouncer_eval/nemotron.py`:

- Model: `nvidia/nemotron-3-super-120b-a12b`
- Endpoint: `https://integrate.api.nvidia.com/v1/chat/completions`
- Temperature: `0`
- Structured output: strict `{ verdict: "ALLOW" | "BLOCK", reason: string }`
- `enable_thinking: false`

## Install and verify

```bash
cd packages/proxy
npm install
npm test
npm run typecheck
npm run build
```

## Run the counterfactual demo

```bash
# Deterministic rehearsal
npm run demo:offline -- --no-color

# Live Nemotron Super run; loads ../../.env if needed
npm run demo -- --no-color
```

See [`../../demo/README.md`](../../demo/README.md) for the email/GitHub mock servers and clip generator.

## Run as an MCP proxy

`BOUNCER_DOWNSTREAMS` is a JSON array of stdio server definitions. Multiple downstreams are exposed with a `<server>__<tool>` prefix; a single downstream preserves its original tool names.

```bash
export NVIDIA_API_KEY="..."
export BOUNCER_AUDIT_LOG="./bouncer-audit.jsonl"
export BOUNCER_DOWNSTREAMS='[
  {
    "name": "email",
    "command": "node",
    "args": ["--import", "tsx", "../../demo/email-server.ts"],
    "cwd": "/absolute/path/to/bouncer/packages/proxy"
  }
]'
npm run build
node dist/cli.js
```

Optional settings: `BOUNCER_GOAL` (set by the host, so a hijacked agent never chooses the goal; recommended when you can), `BOUNCER_NEMOTRON_ENDPOINT` and `BOUNCER_NEMOTRON_MODEL` (a self-hosted NIM or another OpenAI-compatible judge, so tool calls never leave your network).

Otherwise the MCP client must first call:

```json
{
  "name": "bouncer_set_goal",
  "arguments": { "goal": "Read my emails and summarize what's important." }
}
```

The proxy then discovers and exposes the downstream tools dynamically. Stdio protocol traffic uses stdout; diagnostics use stderr.

## Use it with a real agent (Claude Code, Codex, Cursor)

Point the agent at Bouncer instead of at the tool server. [`../../examples/claude-code.mcp.json`](../../examples/claude-code.mcp.json) is a ready-to-edit config: replace the `/ABSOLUTE/PATH/TO` placeholders, build once (`npm run build`), export `NVIDIA_API_KEY`, and drop it in as `.mcp.json` (Claude Code) or add the same `command`/`args`/`env` to your agent's MCP settings. Remove the agent's direct connection to the same tool server, otherwise it can bypass the proxy.

What is tested: `test/cli.test.ts` launches the real CLI over stdio in front of the demo email server with a stand-in judge that allows everything, and checks that nothing runs before a goal exists, an allowed read is forwarded, a send to an unnamed address is never forwarded, the goal cannot be rewritten, and the audit log holds no raw arguments or key. What is not tested: a real hosted Nemotron call through this path (needs your key) and any agent other than the MCP test client.
