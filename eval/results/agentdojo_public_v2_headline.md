# AgentDojo public-v2 headline replay

Fixed public AgentDojo sample: 50 injection-exposed attack traces and 50 clean traces across workspace, travel, banking, and Slack. Nemotron returned 94 valid decisions; five calls hit HTTP 429 and one hit HTTP 503.

| Same valid actions (47 attack, 47 clean) | Deterministic rules | Nemotron Super |
|---|---:|---:|
| Attack action stopped or escalated | 10/47 (21.3%) | 36/47 (76.6%) |
| Attack action blocked outright | 10/47 (21.3%) | 5/47 (10.6%) |
| Clean action allowed | 26/47 (55.3%) | 28/47 (59.6%) |

Nemotron's 36 interventions were 5 BLOCK and 31 ASK decisions. In a fail-closed runtime, both prevent the tool call from executing; ASK requires approval before continuing. The result supports Nemotron as the semantic decision layer, but also shows that the current prompt is too cautious for a fully autonomous workflow.

This is retrospective action replay, not a native AgentDojo rerun. Say “stopped or escalated the recorded action,” not “prevented the attack.”
