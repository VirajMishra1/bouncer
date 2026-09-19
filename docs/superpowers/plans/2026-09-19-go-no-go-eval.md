# Bouncer Go/No-Go Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible 48-case benchmark comparing deterministic rules with Nemotron Lightning and Super.

**Architecture:** A small dependency-free Python package loads frozen JSONL cases, evaluates them through interchangeable decision providers, computes metrics, and writes stable JSON/Markdown reports. NVIDIA access uses the hosted OpenAI-compatible endpoint and an injected HTTP transport for testability.

**Tech Stack:** Python 3.10+ standard library, `unittest`, NVIDIA hosted NIM API.

## Global Constraints

- Do not create or start a Brev GPU instance.
- Never print, persist in results, or commit `NVIDIA_API_KEY`.
- Use exactly 48 frozen cases with 24 benign and 24 attack cases across six families.
- Use deterministic settings and record all invalid outputs and API failures.

---

### Task 1: Dataset and domain models

**Files:**
- Create: `bouncer_eval/__init__.py`
- Create: `bouncer_eval/models.py`
- Create: `bouncer_eval/dataset.py`
- Create: `eval/datasets/go_no_go_v1.jsonl`
- Test: `tests/test_dataset.py`

**Interfaces:**
- Produces: `Case`, `Decision`, `load_cases(path)`, and `validate_cases(cases)`.

- [ ] Write tests that require 48 unique cases, 24 attacks, 24 benign cases, six balanced families, and valid effects/verdicts.
- [ ] Run `python3 -m unittest tests.test_dataset -v` and confirm failure because modules are missing.
- [ ] Implement immutable dataclasses, strict parsing, validation, and the frozen JSONL records.
- [ ] Re-run the dataset tests and confirm they pass.

### Task 2: Deterministic baseline

**Files:**
- Create: `bouncer_eval/deterministic.py`
- Test: `tests/test_deterministic.py`

**Interfaces:**
- Consumes: `Case`.
- Produces: `DeterministicEvaluator.evaluate(case) -> Decision`.

- [ ] Write focused tests for external SEND, secret-bearing SEND, untrusted EXECUTE, authorized SEND, and authorized EXECUTE.
- [ ] Run `python3 -m unittest tests.test_deterministic -v` and confirm failure because the evaluator is missing.
- [ ] Implement effect-based rules without dataset-id or family-specific logic.
- [ ] Re-run deterministic tests and confirm they pass.

### Task 3: Nemotron client and strict parsing

**Files:**
- Create: `bouncer_eval/nemotron.py`
- Test: `tests/test_nemotron.py`

**Interfaces:**
- Produces: `NemotronEvaluator(model, api_key, transport=None)` and `parse_decision(content)`.

- [ ] Write tests for valid JSON, fenced JSON, contradictory verdict/reason text, invalid verdicts, retries, and secret-free errors.
- [ ] Run `python3 -m unittest tests.test_nemotron -v` and confirm failure because the client is missing.
- [ ] Implement the strict prompt, JSON schema request, response validation, bounded retry, and latency capture.
- [ ] Re-run Nemotron tests and confirm they pass.

### Task 4: Metrics, report, and gate

**Files:**
- Create: `bouncer_eval/metrics.py`
- Create: `bouncer_eval/report.py`
- Test: `tests/test_metrics.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `summarize(cases, decisions)`, `classify_gate(summaries)`, and `write_reports(...)`.

- [ ] Write tests for accuracy, attack block rate, benign allow rate, invalid rate, latency percentiles, and GO/NO-GO/NARROW-SCOPE outcomes.
- [ ] Run the metric/report tests and confirm missing-module failures.
- [ ] Implement calculations and stable JSON/Markdown output with per-case failures.
- [ ] Re-run metric/report tests and confirm they pass.

### Task 5: CLI and live evaluation

**Files:**
- Create: `bouncer_eval/cli.py`
- Create: `tests/test_cli.py`
- Create: `eval/results/go_no_go_v1.json`
- Create: `eval/results/go_no_go_v1.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `python3 -m bouncer_eval.cli [--dry-run] [--systems ...]`.

- [ ] Write CLI tests for dry-run, missing key, system selection, and report paths.
- [ ] Run `python3 -m unittest tests.test_cli -v` and confirm failure because the CLI is missing.
- [ ] Implement CLI orchestration and concise README instructions.
- [ ] Run all unit tests, then dry-run validation.
- [ ] Run the live 48-case evaluation against Lightning and Super using the free NVIDIA endpoint.
- [ ] Inspect failures, rerun only operational failures if needed, and freeze the reports.
- [ ] Run final tests and repository-secret scan.
- [ ] Commit and push the verified branch.
