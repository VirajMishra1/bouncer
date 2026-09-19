import assert from "node:assert/strict";
import { Client } from "@modelcontextprotocol/client";
import { InMemoryTransport } from "@modelcontextprotocol/server";
import { afterEach, describe, it } from "node:test";

import { MemoryAuditSink } from "../src/audit.js";
import { BouncerProxy } from "../src/bouncer.js";
import { buildProxyServer } from "../src/server.js";
import type {
  DecisionEvaluator,
  DownstreamToolClient,
  JsonObject,
  ToolCallResult,
  ToolDefinition,
} from "../src/types.js";

class Downstream implements DownstreamToolClient {
  calls: Array<{ name: string; args: JsonObject }> = [];

  async listTools(): Promise<ToolDefinition[]> {
    return [{
      name: "email_read_message",
      description: "Read an email by id",
      inputSchema: {
        type: "object",
        properties: { message_id: { type: "string" } },
        required: ["message_id"],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    }];
  }

  async callTool(name: string, args: JsonObject): Promise<ToolCallResult> {
    this.calls.push({ name, args });
    return { content: [{ type: "text", text: "Quarterly report due Friday." }] };
  }
}

describe("buildProxyServer", () => {
  const clients: Client[] = [];

  afterEach(async () => {
    await Promise.all(clients.splice(0).map(async (client) => client.close()));
  });

  it("exposes control + downstream tools and enforces calls over MCP", async () => {
    const downstream = new Downstream();
    let allow = true;
    const evaluator: DecisionEvaluator = {
      evaluate: async () => allow
        ? { verdict: "ALLOW", reason: "Directly requested.", latencyMs: 1 }
        : { verdict: "BLOCK", reason: "Not authorized.", latencyMs: 1 },
    };
    const proxy = new BouncerProxy({ downstream, evaluator, audit: new MemoryAuditSink() });
    const server = buildProxyServer({ proxy });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client({ name: "bouncer-test-client", version: "1.0.0" });
    clients.push(client);
    await client.connect(clientTransport);

    const listing = await client.listTools();
    assert.deepEqual(listing.tools.map((tool) => tool.name), [
      "bouncer_set_goal",
      "email_read_message",
    ]);

    const beforeGoal = await client.callTool({
      name: "email_read_message",
      arguments: { message_id: "mail-1" },
    });
    assert.equal(beforeGoal.isError, true);

    const goal = await client.callTool({
      name: "bouncer_set_goal",
      arguments: { goal: "Read message mail-1" },
    });
    assert.notEqual(goal.isError, true);

    const allowed = await client.callTool({
      name: "email_read_message",
      arguments: { message_id: "mail-1" },
    });
    assert.equal(allowed.content[0]?.type, "text");
    assert.equal(allowed.content[0]?.type === "text" ? allowed.content[0].text : "", "Quarterly report due Friday.");
    assert.equal(downstream.calls.length, 1);

    allow = false;
    const blocked = await client.callTool({
      name: "email_read_message",
      arguments: { message_id: "mail-1" },
    });
    assert.equal(blocked.isError, true);
    assert.equal((blocked.structuredContent as Record<string, unknown> | undefined)?.blocked, true);
    assert.equal(downstream.calls.length, 1);
  });

  it("validates the goal control tool input", async () => {
    const proxy = new BouncerProxy({
      downstream: new Downstream(),
      evaluator: { evaluate: async () => ({ verdict: "ALLOW", reason: "ok", latencyMs: 0 }) },
      audit: new MemoryAuditSink(),
    });
    const server = buildProxyServer({ proxy });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client({ name: "bouncer-test-client", version: "1.0.0" });
    clients.push(client);
    await client.connect(clientTransport);

    const result = await client.callTool({ name: "bouncer_set_goal", arguments: { goal: "" } });

    assert.equal(result.isError, true);
    assert.equal(result.content[0]?.type, "text");
    assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /non-empty/);
  });
});
