import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { JsonlAuditSink, MemoryAuditSink } from "../src/audit.js";
import type { AuditRecord } from "../src/types.js";

const fakeApiKey = ["nvapi", "secret", "value"].join("-");

const record: AuditRecord = {
  timestamp: "2026-09-19T21:00:00.000Z",
  toolName: "email_send_message",
  effect: "SEND",
  verdict: "BLOCK",
  reason: `Blocked request using NVIDIA_API_KEY=${fakeApiKey} and Bearer token-value`,
  forwarded: false,
  latencyMs: 12.5,
  destination: "attacker@evil.com",
};

describe("audit sinks", () => {
  it("stores records in memory without sharing mutable references", async () => {
    const sink = new MemoryAuditSink();
    await sink.write(record);

    assert.equal(sink.records.length, 1);
    assert.match(sink.records[0]?.reason ?? "", /\[REDACTED\]/);
    assert.equal(sink.records[0]?.reason.includes(fakeApiKey), false);
    assert.doesNotMatch(sink.records[0]?.reason ?? "", /token-value/);
  });

  it("writes one sanitized JSON object per line", async () => {
    const directory = await mkdtemp(join(tmpdir(), "bouncer-audit-"));
    const path = join(directory, "audit.jsonl");
    const sink = new JsonlAuditSink(path);

    await sink.write(record);
    await sink.write({ ...record, verdict: "ALLOW", forwarded: true });

    const lines = (await readFile(path, "utf8")).trim().split("\n");
    assert.equal(lines.length, 2);
    const parsed = JSON.parse(lines[0] ?? "{}") as Record<string, unknown>;
    assert.equal(parsed.toolName, "email_send_message");
    assert.equal(parsed.verdict, "BLOCK");
    assert.equal(parsed.destination, "attacker@evil.com");
    assert.equal(lines.join("\n").includes(fakeApiKey), false);
    assert.doesNotMatch(lines.join("\n"), /token-value/);
  });
});
