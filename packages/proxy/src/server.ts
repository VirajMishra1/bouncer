import { Server } from "@modelcontextprotocol/server";
import type { CallToolResult, ListToolsResult, Tool } from "@modelcontextprotocol/server";

import type { BouncerProxy } from "./bouncer.js";
import type { JsonObject, ToolCallResult, ToolDefinition } from "./types.js";

const GOAL_TOOL: Tool = {
  name: "bouncer_set_goal",
  title: "Set Bouncer session goal",
  description: "Set the original user instruction for this session before calling downstream tools.",
  inputSchema: {
    type: "object",
    properties: {
      goal: { type: "string", minLength: 1, description: "The user's original instruction, verbatim." },
    },
    required: ["goal"],
    additionalProperties: false,
  },
  annotations: {
    readOnlyHint: false,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const toMcpTool = (tool: ToolDefinition): Tool => tool as unknown as Tool;
const toMcpResult = (result: ToolCallResult): CallToolResult => result as unknown as CallToolResult;

export interface ProxyServerOptions {
  proxy: BouncerProxy;
}

export const buildProxyServer = ({ proxy }: ProxyServerOptions): Server => {
  const server = new Server(
    { name: "bouncer-mcp-server", version: "0.1.0" },
    {
      capabilities: { tools: {} },
      instructions: "Call bouncer_set_goal with the user's original instruction before using any downstream tool.",
    },
  );

  server.setRequestHandler("tools/list", async (): Promise<ListToolsResult> => {
    const downstreamTools = await proxy.listTools();
    return { tools: [GOAL_TOOL, ...downstreamTools.map(toMcpTool)] };
  });

  server.setRequestHandler("tools/call", async (request): Promise<CallToolResult> => {
    const { name } = request.params;
    const rawArguments = request.params.arguments;
    const args = (
      typeof rawArguments === "object"
      && rawArguments !== null
      && !Array.isArray(rawArguments)
    ) ? rawArguments as JsonObject : {};

    if (name === GOAL_TOOL.name) {
      const goal = args.goal;
      if (typeof goal !== "string" || goal.trim().length === 0) {
        return {
          isError: true,
          content: [{ type: "text", text: "bouncer_set_goal requires a non-empty goal string." }],
        };
      }
      proxy.setGoal(goal);
      return {
        content: [{ type: "text", text: "Bouncer captured the original user goal." }],
        structuredContent: { captured: true },
      };
    }

    const result = toMcpResult(await proxy.callTool(name, args));
    return server.projectCallToolResult(result, undefined);
  });

  return server;
};
