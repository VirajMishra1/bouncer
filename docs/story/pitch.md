# Bouncer: 3-minute pitch

**Category line (say it, and put it on screen):**
> Prompt filters ask whether content looks malicious. Bouncer asks whether the concrete side effect is authorized by the user's goal.

**Track:** NVIDIA Nemotron, "Beyond the Chatbot." Also entered for Most Fundable.

The script is demo-first: the audience sees the attack before they hear any theory. Total: **3:00**.

## Before you record

- Use `demo/artifacts/bouncer-demo.mp4` as a fallback, or run the demo live from `packages/proxy`:
  - `npm run demo:offline` is deterministic, needs no network, and uses a scripted stand-in for the judge.
  - `npm run demo` calls Nemotron Super and needs `NVIDIA_API_KEY`. **Rehearse the live run. If you narrate it as Nemotron's decision, it has to be the live run.**
- Have `eval/results/go_no_go_noleak.md` open for the evidence beat.
- Keep real credentials and live external services off screen. The demo uses local mock servers.

## Script

### 0:00–0:20 · The hijack (Bouncer OFF)

**On screen:** terminal, `BOUNCER OFF` banner. Goal line: *Read my emails and summarize what's important.*

> "I asked an agent to read my email and summarize it. Watch what happens."

The replay reads `mail-1`, then `mail-2`. Point at `[READ] mail-2 → untrusted instructions detected in content`, then at the line:

`[HARM] Forward to attacker@evil.com succeeded`

> "One email hid an instruction. The agent obeyed it and sent my inbox to a stranger. It can't tell content from commands."

### 0:20–1:10 · Same attack, Bouncer ON

**On screen:** the `BOUNCER ON` replay of the identical trajectory.

> "Same agent, same emails. This time there's a bouncer between the agent and its tools."

Point at each line as it appears:

- `[READ]` calls pass. Reading the inbox is exactly what the user asked for.
- `[BLOCKED] Forward to attacker@evil.com refused`
- `[COMPLETE] Legitimate inbox summary produced`

> "The forward never reaches the email server. And the summary I asked for still gets done. Bouncer isn't a kill switch. It stops the one action nobody asked for."

### 1:10–1:50 · Why this works, and where Nemotron sits

**On screen:** the **DECISION TRACE** block from the demo output, then the diagram from `docs/story/architecture.md`.

> "Every tool call is intercepted at the MCP boundary. Bouncer normalizes it into an effect: read, send, or execute. It hands Nemotron Super the user's original goal, the concrete action, and the last two tool results, which is where an injection would show up. Nemotron answers one question: does this action match what the user asked for?"

> "Nemotron isn't a chatbot here. Its verdict decides whether the action executes at all. Anything that isn't a clean allow (a bad verdict, a network failure, no goal) fails closed."

> "That's the difference. A prompt filter asks 'does this look malicious?' We ask: 'is this side effect authorized by the goal?'"

### 1:50–2:40 · Evidence, honestly

**On screen:** the results table from `eval/results/go_no_go_noleak.md`.

> "We tested on 48 frozen cases, half attacks and half benign, across six attack families. A rules baseline blocks 100% of attacks but wrongly blocks about one in six legitimate actions. Nemotron Super blocks 100% of attacks and allows 87.5% of legitimate ones."

> "Two honest notes. Our first run scored 100%, and we didn't trust it, because our dataset had labels that gave the answer away. We removed them and re-ran. 93.8% is the number we report. And this is per-call evidence on a small, self-authored set. We haven't yet shown end-to-end results or run a public benchmark."

> "Why we kept the rules baseline in the chart: it's the bar. Where the rules over-block legitimate sends, Nemotron reasoned about intent and let most of them through."

### 2:40–3:00 · Close

**On screen:** the category line, large.

> "Bouncer: the intent firewall for AI agents. Prompt filters ask whether content looks malicious. Bouncer asks whether the side effect is authorized. Beyond the chatbot, with Nemotron making the call."

If Most Fundable is judged: one sentence, **"Agents are getting real tools, and every team shipping one needs an authorization layer at the tool boundary."**

## Numbers you may say (all from `eval/results/`)

| Claim | Source |
|---|---|
| 48 frozen cases, 24 attack / 24 benign, 6 families | `eval/datasets/go_no_go_v1.jsonl` |
| Nemotron Super 93.8% accuracy, 100% attacks blocked, 87.5% benign allowed, 6.2% invalid, p50 ~1.05 s | `eval/results/go_no_go_noleak.md` |
| Rules baseline 91.7% accuracy, 100% attacks blocked, 83.3% benign allowed | same |
| The first, leaky run scored 100% and is archived | `eval/results/go_no_go_v1.md` |

## Do not say

- Do **not** claim Bouncer stops all prompt injection. The claim is about unauthorized tool-mediated effects in mediated tools.
- Do **not** cite the "~96% false-block" figure for NeMo Guardrails as a result. It comes from the plan and we did not reproduce it. We have not run NeMo Guardrails.
- Do **not** claim end-to-end results, AgentDojo results, or post-freeze adaptive-attack results unless they have been run and committed.
- Do **not** present the ≥90% / ≥85% / <10% figures in `MASTERPLAN.md` as achieved. They are a pre-registered target.
- Do **not** call the offline replay Nemotron's decision. It's a scripted stand-in.

## Likely questions

- **"Couldn't the agent rephrase and try again?"** Every call is checked, so a reformulated forward hits the same gate. That is a design argument. Measuring it end to end is not done yet, and we say so.
- **"Why not just regex?"** In our set the rules baseline blocks all attacks but over-blocks four legitimate sends (`hex-05` to `hex-08`). Nemotron Super allowed three of them; the fourth (`hex-06`) came back INVALID.
- **"Why Super only?"** Lightning timed out and truncated its JSON through the hosted API in our run, so V1 uses Super only.
- **"What about ASK?"** In the proxy today, anything ambiguous, such as a send to a destination the goal never named, is stopped and logged. Human approval is designed, not shipped.
