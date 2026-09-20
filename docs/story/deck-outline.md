# Bouncer: slide outline

Ten slides for a 3-minute talk. Each one names the committed artifact to screenshot, so nothing on a slide is unsupported. Items marked **[pending]** must be filled from `eval/results/trajectory_live.*` once the hosted run exists; until then say the sentence in the "until then" column, not a number.

| # | Slide | On screen | Say | Source |
|---|---|---|---|---|
| 1 | **The hijack** | Bouncer Live, switch **OFF**: the attacker walks away with the inbox | "I asked an agent to summarize my email. One email hid an instruction, and the agent sent my inbox to a stranger." | `live/index.html` (scripted replay) |
| 2 | **Why it happens** | One line: "Agents can't tell content from commands." | "An attack does nothing until the agent takes a real action: send, delete, run, pay. That boundary is where we sit." | README, *The problem* |
| 3 | **Bouncer** | Switch **ON**: the send is turned away, the summary still completes | "Same trajectory. The send is stopped, the legitimate work finishes." | `live/index.html`, `demo/artifacts/bouncer-demo.mp4` |
| 4 | **How it decides** | Diagram: goal + action + last two results → deterministic invariants → Nemotron Super → ALLOW / ASK / BLOCK | "Crisp dangers are rules. Judgment about intent is Nemotron, and its verdict changes what executes. Not a chatbot." | `docs/story/architecture.md` |
| 5 | **Same action, opposite verdicts** | "Fetch the weather" vs "Fix this bug", same outbound request | "Prompt filters ask whether content looks malicious. We ask whether this effect is authorized by the goal." | category line |
| 6 | **Evidence, per call** | Table: rules 91.7 / 100 / 83.3, Nemotron Super 93.8 / 100 / 87.5 (accuracy / attacks blocked / benign allowed) | "48 frozen cases. Our first run scored 100% and we didn't trust it, because labels leaked the answer. We removed them; 93.8% is what we report." | `eval/results/go_no_go_noleak.md` |
| 7 | **Evidence, end to end** | Chart: no defense 0/6, text-only rules 5/6, Bouncer **[pending]** | "Whole attack episodes with retries. Doing nothing stops zero of six. A keyword firewall misses a paraphrased shell command." Until then: "Our Nemotron end-to-end run is next, and we'll show it whichever way it lands." | `dashboard/index.html`, `eval/results/trajectory_offline.md` |
| 8 | **What we don't claim** | Three lines: small self-authored sets · no AgentDojo yet · no NeMo comparison run | "We'd rather you trust the number than be impressed by it." | `docs/status/masterplan-audit.md` |
| 9 | **Use it** | `.mcp.json` snippet and the popup window | "It's an MCP proxy: point your agent at Bouncer. And there's a live view that opens while your agent works." | `examples/claude-code.mcp.json`, `live/` |
| 10 | **Why now** | Market line | "Agents are getting real tools, and every team shipping one needs an authorization layer at the tool boundary." (Most Fundable) | `MASTERPLAN.md` §1, §8 |

## Do not put on a slide
- "Beats NeMo Guardrails", "beats AgentDojo defenses", the "~96% false-block" figure, or anything called fine-tuned. None of these has been run or done.
- The label-reading `deterministic` score (6/6) as a competitor. It is an upper bound for rules and the dashboard says so.
- The offline demo as "Nemotron's decision". It uses a scripted stand-in for the judge.
