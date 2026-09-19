# Evaluator Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and verify Claude's interrupted evaluator integration on the existing proxy PR.

**Architecture:** Keep the Python evaluation harness as an offline measurement surface while preserving the MCP proxy's V1 fail-closed contract. Add only CLI composition and reproducibility wiring around Claude's existing evaluator, metrics, and reporting changes.

**Tech Stack:** Python 3 standard library `unittest`; TypeScript/Node proxy workspace; GitHub CLI.

## Global Constraints

- Preserve existing CLI system names and dry-run behavior.
- Do not make live NVIDIA calls in unit tests.
- Keep the proxy contract `ALLOW|BLOCK`; `ASK` is evaluation-only.
- Record the SHA-256 of the exact dataset bytes in generated reports.

---

### Task 1: Define CLI composition behavior

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `bouncer_eval/cli.py`

**Interfaces:**
- Consumes: `NemotronEvaluator(model, api_key, reasoning=bool)` and `BouncerEvaluator(model)`
- Produces: CLI composition for each named system while `main` retains interval control

- [ ] Add tests proving reasoning variants set `reasoning=True`, `bouncer` wraps Super, and the parser accepts every system.
- [ ] Run `python3 -m unittest tests.test_cli -v` and confirm the new tests fail because the factory and choices do not exist.
- [ ] Implement the minimal evaluator factory and route `main` through it.
- [ ] Rerun `python3 -m unittest tests.test_cli -v` and confirm it passes.

### Task 2: Record dataset identity

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `bouncer_eval/cli.py`

**Interfaces:**
- Consumes: raw bytes from `args.dataset`
- Produces: `dataset_sha256` passed to `write_reports(..., dataset_hash=...)`

- [ ] Add a dry-run assertion that the JSON report contains the SHA-256 of the selected dataset.
- [ ] Run the focused test and confirm it fails with a missing/null hash.
- [ ] Compute `hashlib.sha256(args.dataset.read_bytes()).hexdigest()` and pass it to the report writer.
- [ ] Rerun the focused test and confirm it passes.

### Task 3: Verify and publish the integrated branch

**Files:**
- Include: Claude's evaluator/report changes, new evaluator module, tests, and these design/plan records.
- Exclude: Loadout-generated `AGENTS.md`.

- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run the proxy test, typecheck, build, audit, and demo verification commands defined by `packages/proxy/package.json` and `demo/package.json`.
- [ ] Run `git diff --check` and scan tracked staged content for credential patterns.
- [ ] Commit the evaluator integration separately from the existing proxy commit.
- [ ] Push `codex/proxy-demo`, inspect PR #2 checks and mergeability, and report the safe merge order.
