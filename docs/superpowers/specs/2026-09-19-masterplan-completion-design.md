# Masterplan Completion Design

## Scope

Finish the software and evidence artifacts that remain after the proxy/demo merge. External hackathon submission and live NVIDIA reruns remain human-triggered because they consume credentials or require uploading to third-party forms.

## Architecture

The existing per-call benchmark remains clearly labelled as diagnostic evidence. A new trajectory layer groups ordered tool calls into complete episodes, records whether harmful sinks execute after retries, and records whether every required benign step completes. It reuses the existing evaluator interface so deterministic, Nemotron, and hybrid systems receive equivalent goal/action/context.

The runtime proxy adopts the same three-outcome contract. `ASK` never forwards a call; it returns structured approval details for the host. Deterministic runtime invariants cover secret-bearing sends, untrusted-content execution, unmentioned send destinations, and destructive actions before forwarding.

The results surface is dependency-free: one command produces JSON, Markdown, a standalone failures file, a Pareto SVG, and a static dashboard. Historical model results remain archived and explicitly labelled; no new NVIDIA request is made automatically.

## Data and metrics

- A frozen trajectory dataset contains complete benign and attacked episodes, ordered steps, retry attempts, required benign steps, and harmful-sink markers.
- Headline security is the fraction of attack episodes where no harmful sink executes.
- Headline utility is the fraction of benign episodes where all required steps execute.
- Reports include raw episode outcomes, per-family results, ASK rate, paired win/loss tables, and deterministic seeded bootstrap confidence intervals for paired system differences.
- Dataset SHA-256 and a frozen manifest make the evaluated bytes identifiable.

## Dashboard direction

The static page is a security checkpoint ledger, not a generic analytics template. Its signature is an action stream that visibly crosses an authorization gate, paired with the safety/utility plot and plain-language failures. It embeds generated results, works from a local file, is responsive, keyboard-readable, and respects reduced motion.

## Failure behavior

Invalid model output, missing credentials, audit failures, and unknown tools fail closed. Dataset validation rejects duplicate identifiers, malformed trajectories, inconsistent attack markers, and missing held-out families. Generated artifacts never include API keys or raw secrets.

## Verification

Python unit tests cover trajectory loading, replay, headline metrics, paired statistics, report generation, and CLI behavior without network access. TypeScript tests cover runtime invariants and ASK no-forward behavior. End-to-end verification also runs typecheck, build, the offline counterfactual demo, static dashboard generation, diff checks, and a staged-secret scan.
