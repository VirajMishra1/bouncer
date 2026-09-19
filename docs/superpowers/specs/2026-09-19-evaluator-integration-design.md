# Evaluator Integration Design

## Goal

Finish Claude's interrupted evaluation work without changing the MCP proxy's
published V1 `ALLOW|BLOCK` contract.

## Design

The Python evaluation harness will expose four explicit model systems:
`lightning`, `lightning-thinking`, `super`, and `super-thinking`, plus a
`bouncer` hybrid. The hybrid applies deterministic invariants for secret-bearing
`SEND` and untrusted-content `EXECUTE` actions, then delegates ambiguous cases
to Nemotron Super. Evaluation-only decisions may include `ASK` so reports can
measure interruption rate; the proxy continues to fail closed and treats any
non-`ALLOW` result as blocked.

Every report records the SHA-256 of the exact JSONL dataset bytes. Existing
confidence intervals, per-family metrics, and reasoning token limits remain.
The CLI wiring is covered with injected evaluators so tests do not call NVIDIA.

## Compatibility and failure behavior

- Existing system names continue to work unchanged.
- `--dry-run` remains deterministic-only and requires no API key.
- `bouncer` requires `NVIDIA_API_KEY` because ambiguous cases invoke Super.
- Invalid model output, transport errors, and missing credentials continue to
  fail safely through existing error paths.
- No raw goals, tool arguments, or secrets are added to reports or audit logs.

## Verification

Run the complete Python unit suite, deterministic CLI smoke test, proxy tests,
TypeScript typecheck/build, diff checks, and a tracked-file secret scan before
committing and pushing the integrated branch.
