# Bouncer MCP Proxy + Demo Implementation Plan

**Goal:** Build a runnable TypeScript MCP proxy that authorizes downstream tool calls with Nemotron Super, records a safe audit trail, and demonstrates the same injected email/GitHub trajectories with Bouncer OFF and ON.

**Architecture:** A low-level stdio MCP relay discovers tools from one or more downstream MCP servers, exposes them unchanged, and routes each `tools/call` through a testable `BouncerProxy` core. The core derives a three-value effect, sends only neutral metadata plus the original goal and two-call context to the canonical Nemotron prompt/schema, fails closed on evaluator errors, and forwards only ALLOW decisions. Demo servers are ordinary MCP servers; the counterfactual runner drives them through real MCP clients.

**Tech stack:** Node.js 23+, TypeScript, MCP TypeScript SDK v2, Vitest, native `fetch`, JSONL audit records.

## Global constraints

- Only modify `packages/proxy/` and `demo/`; never touch `bouncer_eval/` or `eval/`.
- Match `bouncer_eval/nemotron.py`: model `nvidia/nemotron-3-super-120b-a12b`, endpoint `https://integrate.api.nvidia.com/v1/chat/completions`, temperature 0, strict JSON schema, thinking disabled.
- V1 decisions are ALLOW or BLOCK. ASK is represented as BLOCK with an audit reason.
- Preserve the prior two tool-call/result summaries and treat downstream content as untrusted.
- Never write API keys, raw email bodies, or tool arguments to the audit log.
- Fail closed if goal capture, model evaluation, response validation, or downstream routing fails.

---

### Task 1: Core contracts and effect normalization

**Files:**
- Create: `packages/proxy/package.json`
- Create: `packages/proxy/tsconfig.json`
- Create: `packages/proxy/src/types.ts`
- Create: `packages/proxy/src/effects.ts`
- Test: `packages/proxy/test/effects.test.ts`

**Interfaces:**
- `normalizeToolCall(tool, args): NormalizedAction`
- `NormalizedAction.effect` is exactly `READ | SEND | EXECUTE`.

- [ ] Write table-driven tests for email/GitHub read, send, delete, shell, and unknown tools.
- [ ] Run the focused test and observe a missing-module failure.
- [ ] Implement the typed contracts and the smallest name/schema/annotation-based normalizer.
- [ ] Run the focused test and confirm green.

### Task 2: Canonical Nemotron evaluator and audit sink

**Files:**
- Create: `packages/proxy/src/nemotron.ts`
- Create: `packages/proxy/src/audit.ts`
- Test: `packages/proxy/test/nemotron.test.ts`
- Test: `packages/proxy/test/audit.test.ts`

**Interfaces:**
- `NemotronEvaluator.evaluate(input): Promise<Decision>`
- `AuditSink.write(record): Promise<void>`

- [ ] Write tests that inspect the outgoing NIM request, parse valid decisions, reject malformed decisions, redact secrets, and serialize one JSON object per line.
- [ ] Run the focused tests and observe missing-module failures.
- [ ] Implement the exact Python prompt/schema request using injected `fetch` and strict response parsing.
- [ ] Implement memory and JSONL audit sinks that store normalized action/decision metadata only.
- [ ] Run focused tests and confirm green.

### Task 3: Enforcement core

**Files:**
- Create: `packages/proxy/src/bouncer.ts`
- Test: `packages/proxy/test/bouncer.test.ts`

**Interfaces:**
- `BouncerProxy.setGoal(goal): void`
- `BouncerProxy.listTools(): Promise<ToolDefinition[]>`
- `BouncerProxy.callTool(name, args): Promise<ToolCallResult>`

- [ ] Write tests proving ALLOW forwards, BLOCK does not forward, evaluator errors fail closed, missing goals fail closed, audit records are emitted, and only the last two call/result summaries enter context.
- [ ] Run the test and observe a missing-module failure.
- [ ] Implement dependency-injected enforcement and bounded untrusted context.
- [ ] Run the test and confirm green.

### Task 4: Real MCP relay and downstream clients

**Files:**
- Create: `packages/proxy/src/downstream.ts`
- Create: `packages/proxy/src/server.ts`
- Create: `packages/proxy/src/cli.ts`
- Create: `packages/proxy/src/index.ts`
- Test: `packages/proxy/test/server.test.ts`

**Interfaces:**
- `StdioDownstream.connect(config): Promise<StdioDownstream>`
- `buildProxyServer(options): Server`
- Control tool: `bouncer_set_goal({ goal })`.

- [ ] Write an in-memory MCP integration test for dynamic `tools/list`, goal capture, allowed forwarding, and blocked structured tool errors.
- [ ] Run the test and observe a missing-module failure.
- [ ] Implement stdio downstream discovery, collision-safe names, low-level relay handlers, environment configuration, and graceful shutdown.
- [ ] Run the integration test and confirm green.

### Task 5: Mock email/GitHub MCP servers and counterfactual runner

**Files:**
- Create: `demo/email-server.ts`
- Create: `demo/github-server.ts`
- Create: `demo/run-counterfactual.ts`
- Create: `demo/README.md`
- Test: `packages/proxy/test/demo.test.ts`

**Interfaces:**
- Email tools: `email_list_messages`, `email_read_message`, `email_send_message`, `email_delete_message`, `email_summarize_inbox`.
- GitHub tools: `github_read_issue`, `github_read_file`, `github_post_comment`.
- Runner flags: `--offline` for deterministic fixture decisions; live mode requires `NVIDIA_API_KEY`.

- [ ] Write an end-to-end child-process test asserting OFF exfiltrates, ON blocks exfiltration, and ON still returns the legitimate summary.
- [ ] Run the test and observe a missing-script failure.
- [ ] Implement the two MCP mock servers and a runner that replays identical trajectories through direct and proxied clients.
- [ ] Run the end-to-end test and confirm green.
- [ ] Run the live Nemotron-backed counterfactual with the existing `.env` key and save sanitized output.

### Task 6: Clip, docs, verification, and handoff

**Files:**
- Create: `demo/record-demo.sh`
- Create: `demo/artifacts/bouncer-demo.mp4`
- Create: `packages/proxy/README.md`

- [ ] Add a deterministic terminal-clip generator from the offline counterfactual so recording is reproducible and secret-free.
- [ ] Run formatting/typecheck/unit/integration tests and the offline/live demos.
- [ ] Inspect the git diff to confirm no Claude-owned paths changed and no secrets were added.
- [ ] Commit, push `codex/proxy-demo`, open a PR, publish a Loadout progress update, release ownership, and mark handoff `329581f4` done.
