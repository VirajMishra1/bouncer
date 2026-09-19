# Bouncer MCP proxy

Bouncer is a local stdio MCP relay that checks every downstream `tools/call` against the user's original goal before forwarding it. NVIDIA Nemotron Super acts as a strict, non-chat authorization judge.

## Security behavior

- Captures the original goal through `bouncer_set_goal` (or `BOUNCER_GOAL`).
- Normalizes each tool call to `READ`, `SEND`, or `EXECUTE`.
- Sends the goal, concrete action with typed arguments, neutral destination/resource identifiers, and the previous two untrusted tool results to Nemotron.
- Forwards only a valid `ALLOW`; `BLOCK`, invalid model output, network failure, missing goal, and audit failure all fail closed.
- Treats V1 `ASK` situations—especially a `SEND` destination absent from the goal—as blocked and logs the reason.
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

The MCP client must first call:

```json
{
  "name": "bouncer_set_goal",
  "arguments": { "goal": "Read my emails and summarize what's important." }
}
```

The proxy then discovers and exposes the downstream tools dynamically. Stdio protocol traffic uses stdout; diagnostics use stderr.
