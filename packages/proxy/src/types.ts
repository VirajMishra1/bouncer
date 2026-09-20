export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type Effect = "READ" | "SEND" | "EXECUTE";
export type Verdict = "ALLOW" | "BLOCK" | "ASK";

export interface ToolAnnotations {
  readOnlyHint?: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
  openWorldHint?: boolean;
}

export interface ToolDefinition {
  name: string;
  title?: string;
  description?: string;
  inputSchema: JsonObject;
  outputSchema?: JsonObject;
  annotations?: ToolAnnotations;
}

export interface TextContent {
  type: "text";
  text: string;
}

export interface ToolCallResult {
  content: Array<TextContent | JsonObject>;
  structuredContent?: JsonObject;
  isError?: boolean;
}

export interface NormalizedAction {
  toolName: string;
  action: string;
  effect: Effect;
  destination?: string;
  resource?: string;
  source?: string;
  runtime?: RuntimeSignals;
}

export interface RuntimeSignals {
  outboundText: string[];
  outboundFields: { [path: string]: string };
  destructiveOperation: boolean;
  executableText?: string;
}

export interface DecisionInput extends NormalizedAction {
  goal: string;
  context: string[];
}

export interface Decision {
  verdict: Verdict | null;
  reason: string;
  latencyMs: number;
  error?: string;
}

export interface DecisionEvaluator {
  evaluate(input: DecisionInput): Promise<Decision>;
}

export interface DownstreamToolClient {
  listTools(): Promise<ToolDefinition[]>;
  callTool(name: string, args: JsonObject): Promise<ToolCallResult>;
  close?(): Promise<void>;
}

export interface AuditRecord {
  timestamp: string;
  toolName: string;
  effect: Effect;
  verdict: Verdict;
  reason: string;
  forwarded: boolean;
  latencyMs: number;
  destination?: string;
  resource?: string;
  error?: string;
}

export interface AuditSink {
  write(record: AuditRecord): Promise<void>;
}
