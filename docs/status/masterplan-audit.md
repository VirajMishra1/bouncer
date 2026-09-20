# MASTERPLAN audit (2026-09-20)

Every row was checked against code, tests or generated artifacts on branch `codex/masterplan-complete`. Legend: ✅ done and verified · 🟡 partial · ⬜ not started · ✂️ cut on purpose · 🔑 needs your NVIDIA key or a decision only a human can make.

## Product

| Plan item | Status | Evidence / gap |
|---|---|---|
| MCP proxy that intercepts `tools/call` | ✅ | `packages/proxy/` (TypeScript). 59 tests, typecheck, build. Used by the offline counterfactual demo and tests only; not yet pointed at a real agent's tool config. |
| Effect normalization (READ / SEND / EXECUTE) | ✅ | `effects.ts`, name heuristics, hardened after review (untrusted read-only hints, `__proto__` args, label handling). |
| Deterministic invariants (fail-closed) | ✅ | Destructive ops, secret-bearing sends (all fields, quoted and prefixed tokens), execution derived from prior untrusted output, SEND with unknown destination. |
| Nemotron Super judge with strict JSON | ✅ | `nemotron.ts`, `bouncer_eval/nemotron.py`. Timeout added (hung call now fails closed). |
| Nano triage tier | ✂️ | Lightning was unreliable through the hosted API (35% invalid). V1 is Super-only, as the plan allows. |
| ASK rule (unmentioned SEND destination) | ✅ | Never forwarded; returns structured approval details. There is no approval-resume step (documented limit). |
| Stateless plus previous 2 tool results | ✅ | `contextLimit` = 2. |
| Audit log | ✅ | JSONL, secrets redacted incl. destination/resource; write failure blocks the call. |
| Audit replay | 🟡 | The Bouncer Live page can replay a decision log, but the proxy's audit format is not wired to it. |
| Email counterfactual demo + recorded clip | ✅ | `demo/`, `demo/artifacts/bouncer-demo.mp4`. GitHub is a second mocked server. |
| Animated door-checking view ("Bouncer Live") | ✅ | `live/`. Works for Claude Code (hooks) and Codex (session-file watcher). 22 tests. Local rules by default, Nemotron opt-in. |

## Evidence

| Plan item | Status | Evidence / gap |
|---|---|---|
| Per-call diagnostic on 48 frozen cases | ✅ | Leak-fixed: Super 93.8% acc, 100% attacks blocked, 87.5% benign allowed vs rules 91.7 / 100 / 83.3. Labelled diagnostic. |
| End-to-end trajectory scoring | 🟡 | Implemented and frozen (12 episodes, 6 families). Only the rules baseline was run; it scores 6/6 and 6/6, so the set cannot separate systems. |
| Baseline fairness | 🟡 | The rules baseline reads curator labels (`data_class`, `source`, `destructive`, `operation_in_goal`) that the model never sees. Its perfect score is label-driven. A text-only baseline is planned. |
| Hybrid / Nemotron trajectory run | 🔑 | Needs `NVIDIA_API_KEY` and your OK to spend hosted-API quota. |
| No-defense baseline in the results | ⬜ | Trivial to add offline. |
| Post-freeze adaptive red-team set | ⬜ | Required by the plan; must be written and labelled as post-freeze. |
| Ablations (reasoning on/off, structured vs freeform) | ⬜ | Need model runs. |
| NeMo Guardrails baseline | ⬜ 🔑 | The "~96% false block" is a reported figure and has never been reproduced here. No comparison has been run, so no claim can be made. |
| AgentDojo | ⬜ | Plan allows deferral. Needs their harness plus agent-model runs. |
| Freeze manifest, paired bootstrap CIs | 🟡 | Code and manifest exist; CIs are only meaningful with 2+ systems on trajectories. |
| Pareto chart, published failures | ✅ | `eval/results/pareto*.svg`, `failures.md`. |
| Results dashboard | ✅ | `dashboard/index.html` (never blends the three evidence tiers). |
| One-command reproduction | ✅ | `python3 -m eval.run_eval`. |
| Cost per completed safe task | ⬜ | Needs model runs. |
| Fine-tuned Nemotron | ⬜ 🔑 | Optional stretch in the plan (LoRA of Nano on a rented GPU). Not started. No fine-tuning claim is made anywhere. |

## Story and submission

| Plan item | Status | Notes |
|---|---|---|
| README, architecture diagram, 3-minute pitch script | ✅ | Kept honest; updated tonight. |
| Slide deck | ⬜ | |
| Final recorded video, Devpost write-up | ⬜ | |
| Public repo | ⬜ 🔑 | The GitHub repo is currently **private**. |
| Submit to Nemotron + Most Fundable | ⬜ 🔑 | Human-only. |

## Whole-branch code review (2026-09-19)
A read-only review found 4 critical and 7 important issues. Fixed in `59b4fc6` with 19 new tests: secret scan blind spots (destination-named keys, JSON-quoted values, bare tokens), the `source` argument hidden from both layers, downstream `readOnlyHint` overriding send-named tools, `__proto__` args, unaudited unknown tools, goal overwrite, model timeout, and audit redaction. Not fixed: the provenance check is still an exact-substring heuristic over the last 2 results; the benchmark baseline still reads labels (see above); CI index off-by-one in the bootstrap code; `retry_of` is validated but unused; `_ratio` returns 0.0 for an empty denominator.
