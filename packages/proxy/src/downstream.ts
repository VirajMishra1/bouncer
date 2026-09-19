import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import type { CallToolResult as McpCallToolResult, Tool as McpTool } from "@modelcontextprotocol/client";

import type {
  DownstreamToolClient,
  JsonObject,
  ToolCallResult,
  ToolDefinition,
} from "./types.js";

export interface StdioDownstreamConfig {
  name: string;
  command: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
}

const toToolDefinition = (tool: McpTool): ToolDefinition => tool as unknown as ToolDefinition;
const toToolCallResult = (result: McpCallToolResult): ToolCallResult => result as unknown as ToolCallResult;

export class StdioDownstream implements DownstreamToolClient {
  private constructor(
    readonly name: string,
    private readonly client: Client,
  ) {}

  static async connect(config: StdioDownstreamConfig): Promise<StdioDownstream> {
    const client = new Client({ name: `bouncer-downstream-${config.name}`, version: "0.1.0" });
    const transport = new StdioClientTransport({
      command: config.command,
      ...(config.args === undefined ? {} : { args: config.args }),
      ...(config.cwd === undefined ? {} : { cwd: config.cwd }),
      ...(config.env === undefined ? {} : { env: config.env }),
      stderr: "inherit",
    });
    await client.connect(transport);
    return new StdioDownstream(config.name, client);
  }

  async listTools(): Promise<ToolDefinition[]> {
    const { tools } = await this.client.listTools();
    return tools.map(toToolDefinition);
  }

  async callTool(name: string, args: JsonObject): Promise<ToolCallResult> {
    return toToolCallResult(await this.client.callTool({ name, arguments: args }));
  }

  async close(): Promise<void> {
    await this.client.close();
  }
}

interface Route {
  client: DownstreamToolClient;
  downstreamName: string;
}

export class CompositeDownstream implements DownstreamToolClient {
  private readonly routes = new Map<string, Route>();
  private tools: ToolDefinition[] | undefined;

  constructor(private readonly clients: Array<{ name: string; client: DownstreamToolClient }>) {
    if (clients.length === 0) throw new Error("At least one downstream MCP server is required");
  }

  async listTools(): Promise<ToolDefinition[]> {
    if (this.tools !== undefined) return this.tools;

    const listed = await Promise.all(this.clients.map(async ({ name, client }) => ({
      name,
      client,
      tools: await client.listTools(),
    })));
    const prefix = listed.length > 1;
    const exposed: ToolDefinition[] = [];
    for (const entry of listed) {
      for (const tool of entry.tools) {
        const exposedName = prefix ? `${entry.name}__${tool.name}` : tool.name;
        if (this.routes.has(exposedName)) throw new Error(`Duplicate downstream tool: ${exposedName}`);
        this.routes.set(exposedName, { client: entry.client, downstreamName: tool.name });
        exposed.push({ ...tool, name: exposedName });
      }
    }
    this.tools = exposed;
    return exposed;
  }

  async callTool(name: string, args: JsonObject): Promise<ToolCallResult> {
    if (this.tools === undefined) await this.listTools();
    const route = this.routes.get(name);
    if (route === undefined) throw new Error(`Unknown downstream tool: ${name}`);
    return route.client.callTool(route.downstreamName, args);
  }

  async close(): Promise<void> {
    await Promise.all(this.clients.map(async ({ client }) => client.close?.()));
  }
}

export const connectDownstreams = async (
  configs: StdioDownstreamConfig[],
): Promise<CompositeDownstream> => {
  const clients: Array<{ name: string; client: DownstreamToolClient }> = [];
  try {
    for (const config of configs) {
      clients.push({ name: config.name, client: await StdioDownstream.connect(config) });
    }
    return new CompositeDownstream(clients);
  } catch (error) {
    await Promise.all(clients.map(async ({ client }) => client.close?.()));
    throw error;
  }
};
