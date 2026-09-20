# Masterplan Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Bouncer's trajectory evidence, runtime ASK/invariant contract, static results dashboard, and submission-ready documentation without making live NVIDIA calls.

**Architecture:** Add a Python trajectory layer above the existing per-call evaluator, align the TypeScript proxy with the same fail-closed decisions, and generate all judge-facing evidence from one result bundle. Keep the diagnostic benchmark and historical model output, but label their limits explicitly.

**Tech Stack:** Python 3 standard library and `unittest`; TypeScript 7, Node 20, MCP SDK; dependency-free HTML/CSS/SVG.

## Global Constraints

- Do not call NVIDIA or allocate GPU compute during automated verification.
- Preserve the existing per-call CLI and archived result files.
- `ASK` is valid only for an unmentioned `SEND` destination and never forwards automatically.
- Every generated report records the exact dataset SHA-256.
- No `.env`, API key, raw secret, or Loadout coordination file may be committed.
- Keep work on `codex/masterplan-complete`; never merge into `master` automatically.

---

### Task 1: Complete trajectory evaluation

**Files:**
- Create: `bouncer_eval/trajectories.py`
- Create: `bouncer_eval/trajectory_cli.py`
- Create: `eval/datasets/trajectory_v1.jsonl`
- Create: `eval/datasets/trajectory_v1.freeze.json`
- Create: `tests/test_trajectories.py`
- Create: `tests/test_trajectory_cli.py`
- Modify: `bouncer_eval/models.py`
- Modify: `bouncer_eval/report.py`

**Interfaces:**
- Consumes: existing evaluator objects exposing `evaluate(Case) -> Decision`
- Produces: `load_trajectories`, `run_trajectories`, `summarize_trajectories`, and a one-command CLI that emits raw outcomes and headline metrics

- [ ] Write tests for ordered replay, retries, harmful-sink success, benign completion, dataset validation, paired win/loss counts, paired seeded bootstrap differences, and artifact generation.
- [ ] Run `python3 -m unittest tests.test_trajectories tests.test_trajectory_cli -v` and confirm failures are caused by missing trajectory modules.
- [ ] Implement immutable trajectory/step/outcome models, strict JSONL validation, fail-closed replay, headline metrics, and the CLI.
- [ ] Add at least 12 complete episodes across the six frozen families, including reformulation-after-block and legitimate high-impact actions.
- [ ] Generate the freeze manifest from the exact dataset bytes.
- [ ] Run focused and full Python tests.
- [ ] Commit as `feat: add end-to-end trajectory benchmark` and push the checkpoint.

### Task 2: Align runtime enforcement with the hybrid contract

**Files:**
- Modify: `packages/proxy/src/types.ts`
- Modify: `packages/proxy/src/nemotron.ts`
- Modify: `packages/proxy/src/effects.ts`
- Modify: `packages/proxy/src/bouncer.ts`
- Modify: `packages/proxy/test/bouncer.test.ts`
- Modify: `packages/proxy/test/nemotron.test.ts`
- Modify: `packages/proxy/test/effects.test.ts`

**Interfaces:**
- Consumes: normalized `READ | SEND | EXECUTE` actions
- Produces: fail-closed `ALLOW | BLOCK | ASK`, with `ASK` returned as a structured non-forwarded approval request

- [ ] Write tests proving ASK never forwards, secret-bearing SEND and untrusted EXECUTE are blocked, destructive actions fail closed, and ordinary allowed calls still forward.
- [ ] Run focused proxy tests and observe the expected failures.
- [ ] Extend strict model parsing and runtime decision types for ASK.
- [ ] Add neutral runtime signals derived from tool arguments without trusting attacker-supplied risk labels.
- [ ] Apply invariants before forwarding and return normalized approval details for ASK.
- [ ] Run proxy test, typecheck, build, and offline demo.
- [ ] Commit as `feat: align proxy with hybrid enforcement` and push the checkpoint.

### Task 3: Generate judge-facing results and dashboard

**Files:**
- Create: `eval/run_eval.py`
- Create: `eval/build_dashboard.py`
- Create: `dashboard/index.html`
- Create: `eval/results/trajectory_deterministic.json`
- Create: `eval/results/trajectory_deterministic.md`
- Create: `eval/results/failures.md`
- Modify: `eval/plot_pareto.py`
- Create: `tests/test_dashboard.py`
- Modify: `tests/test_plot.py`

**Interfaces:**
- Consumes: the trajectory result JSON plus the archived per-call model result
- Produces: reproducible result bundle, Pareto SVG, failures report, and self-contained dashboard

- [ ] Write failing tests for the one-command wrapper, dashboard result embedding, truthful evidence labels, responsive/accessibility hooks, and plot input compatibility.
- [ ] Implement deterministic trajectory generation and static dashboard build without network dependencies.
- [ ] Generate and inspect all committed artifacts; label archived per-call numbers as diagnostic, never end-to-end.
- [ ] Run dashboard and plot tests plus a local HTTP smoke test.
- [ ] Commit as `feat: add reproducible results dashboard` and push the checkpoint.

### Task 4: Finish status, story, and release verification

**Files:**
- Modify: `MASTERPLAN.md`
- Modify: `README.md`
- Create: `docs/story/pitch.md`
- Create: `docs/story/architecture.md`

**Interfaces:**
- Consumes: verified code, tests, demo video, and generated results
- Produces: accurate public onboarding, status markers, architecture diagram, and timed pitch

- [ ] Integrate Claude's separately owned story commit and verify every command and quantitative claim against tracked artifacts.
- [ ] Update MASTERPLAN phase/checklist status, leaving live model rerun and external submission explicitly pending.
- [ ] Run Python tests, proxy tests, typecheck, build, offline demo, dashboard generation, diff checks, and tracked secret scan.
- [ ] Request a whole-branch code review and resolve all critical/important findings.
- [ ] Commit remaining documentation, push `codex/masterplan-complete`, and report only genuine external blockers.
