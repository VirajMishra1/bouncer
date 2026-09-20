#!/usr/bin/env node
import process from "node:process";

import { serveStdio } from "@modelcontextprotocol/server/stdio";

import { JsonlAuditSink } from "./audit.js";
import { BouncerProxy } from "./bouncer.js";
import { connectDownstreams } from "./downstream.js";
import type { StdioDownstreamConfig } from "./downstream.js";
import { NemotronEvaluator } from "./nemotron.js";
import { buildProxyServer } from "./server.js";

const parseDownstreams = (raw: string | undefined): StdioDownstreamConfig[] => {
  if (raw === undefined) throw new Error("BOUNCER_DOWNSTREAMS must be a JSON array of stdio server configs");
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("BOUNCER_DOWNSTREAMS must contain at least one server config");
  }
  return value.map((entry, index) => {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      throw new Error(`BOUNCER_DOWNSTREAMS[${index}] must be an object`);
    }
    const rawEntry = entry as Record<string, unknown>;
    if (typeof rawEntry.name !== "string" || typeof rawEntry.command !== "string") {
      throw new Error(`BOUNCER_DOWNSTREAMS[${index}] requires string name and command`);
    }
    if (rawEntry.args !== undefined && (!Array.isArray(rawEntry.args) || !rawEntry.args.every((arg) => typeof arg === "string"))) {
      throw new Error(`BOUNCER_DOWNSTREAMS[${index}].args must be a string array`);
    }
    return {
      name: rawEntry.name,
      command: rawEntry.command,
      ...(rawEntry.args === undefined ? {} : { args: rawEntry.args as string[] }),
      ...(typeof rawEntry.cwd === "string" ? { cwd: rawEntry.cwd } : {}),
    };
  });
};

const main = async (): Promise<void> => {
  const apiKey = process.env.NVIDIA_API_KEY;
  if (apiKey === undefined || apiKey.trim().length === 0) throw new Error("NVIDIA_API_KEY is required");

  const downstream = await connectDownstreams(parseDownstreams(process.env.BOUNCER_DOWNSTREAMS));
  // Point at a self-hosted NIM (data never leaves your network) or any OpenAI-compatible judge.
  const endpoint = process.env.BOUNCER_NEMOTRON_ENDPOINT?.trim();
  const model = process.env.BOUNCER_NEMOTRON_MODEL?.trim();
  const evaluator = new NemotronEvaluator({
    apiKey,
    ...(endpoint ? { endpoint } : {}),
    ...(model ? { model } : {}),
  });
  const audit = new JsonlAuditSink(process.env.BOUNCER_AUDIT_LOG ?? "./bouncer-audit.jsonl");
  const proxy = new BouncerProxy({ downstream, evaluator, audit });
  if (process.env.BOUNCER_GOAL?.trim()) proxy.setGoal(process.env.BOUNCER_GOAL);

  const handle = serveStdio(() => buildProxyServer({ proxy }), {
    onerror: (error) => console.error(`[bouncer] MCP error: ${error.message}`),
  });

  const close = async (): Promise<void> => {
    await handle.close();
    await downstream.close();
  };
  process.once("SIGINT", () => void close());
  process.once("SIGTERM", () => void close());
};

main().catch((error: unknown) => {
  console.error(`[bouncer] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
