import { normalizeToolCall } from "./effects.js";
import type {
  AuditRecord,
  AuditSink,
  Decision,
  DecisionEvaluator,
  DownstreamToolClient,
  JsonObject,
  NormalizedAction,
  ToolCallResult,
  ToolDefinition,
  Verdict,
} from "./types.js";

export interface BouncerProxyOptions {
  downstream: DownstreamToolClient;
  evaluator: DecisionEvaluator;
  audit: AuditSink;
  now?: () => string;
  contextLimit?: number;
}

export class BouncerProxy {
  private readonly downstream: DownstreamToolClient;
  private readonly evaluator: DecisionEvaluator;
  private readonly audit: AuditSink;
  private readonly now: () => string;
  private readonly contextLimit: number;
  private goal: string | undefined;
  private tools: ToolDefinition[] | undefined;
  private context: string[] = [];

  constructor(options: BouncerProxyOptions) {
    this.downstream = options.downstream;
    this.evaluator = options.evaluator;
    this.audit = options.audit;
    this.now = options.now ?? (() => new Date().toISOString());
    this.contextLimit = options.contextLimit ?? 2;
  }

  setGoal(goal: string): void {
    const trimmed = goal.trim();
    if (trimmed.length === 0) throw new Error("Original user goal cannot be empty");
    this.goal = trimmed;
    this.context = [];
  }

  async listTools(): Promise<ToolDefinition[]> {
    this.tools = await this.downstream.listTools();
    return this.tools;
  }

  async callTool(name: string, args: JsonObject = {}): Promise<ToolCallResult> {
    const tool = await this.findTool(name);
    if (tool === undefined) {
      return this.blockedResult(name, "EXECUTE", `Unknown downstream tool: ${name}`);
    }
    const normalized = normalizeToolCall(tool, args);

    if (this.goal === undefined) {
      const decision: Decision = {
        verdict: "BLOCK",
        reason: "Bouncer has no original user goal; call bouncer_set_goal before using downstream tools.",
        latencyMs: 0,
      };
      await this.writeAudit(normalized, decision, false);
      return this.blockedResult(name, normalized.effect, decision.reason);
    }

    const decision = await this.evaluator.evaluate({
      ...normalized,
      goal: this.goal,
      context: [...this.context],
    });

    if (decision.verdict === null || decision.error !== undefined) {
      const failed: Decision = {
        verdict: "BLOCK",
        reason: "Bouncer evaluation failed; the action was not forwarded.",
        latencyMs: decision.latencyMs,
        ...(decision.error === undefined ? {} : { error: decision.error }),
      };
      await this.writeAudit(normalized, failed, false);
      return this.blockedResult(name, normalized.effect, failed.reason, failed.error);
    }

    if (decision.verdict === "BLOCK") {
      await this.writeAudit(normalized, decision, false);
      return this.blockedResult(name, normalized.effect, decision.reason);
    }

    const invariantReason = this.invariantBlockReason(normalized);
    if (invariantReason !== undefined) {
      const blocked: Decision = {
        verdict: "BLOCK",
        reason: invariantReason,
        latencyMs: decision.latencyMs,
      };
      await this.writeAudit(normalized, blocked, false);
      return this.blockedResult(name, normalized.effect, blocked.reason);
    }

    try {
      await this.writeAudit(normalized, decision, true);
    } catch (error) {
      return this.blockedResult(
        name,
        normalized.effect,
        "Bouncer could not persist the audit record; the action was not forwarded.",
        error instanceof Error ? error.message : String(error),
      );
    }

    const result = await this.downstream.callTool(name, args);
    this.remember(normalized, args, result);
    return result;
  }

  private async findTool(name: string): Promise<ToolDefinition | undefined> {
    const tools = this.tools ?? await this.listTools();
    return tools.find((tool) => tool.name === name);
  }

  private invariantBlockReason(action: NormalizedAction): string | undefined {
    if (
      action.effect === "SEND"
      && action.destination !== undefined
      && !this.goal?.toLocaleLowerCase().includes(action.destination.toLocaleLowerCase())
    ) {
      return `Destination ${action.destination} was not named in the original goal; ASK is treated as BLOCK in V1.`;
    }
    return undefined;
  }

  private async writeAudit(action: NormalizedAction, decision: Decision, forwarded: boolean): Promise<void> {
    const verdict: Verdict = decision.verdict ?? "BLOCK";
    const record: AuditRecord = {
      timestamp: this.now(),
      toolName: action.toolName,
      effect: action.effect,
      verdict,
      reason: decision.reason,
      forwarded,
      latencyMs: decision.latencyMs,
      ...(action.destination === undefined ? {} : { destination: action.destination }),
      ...(action.resource === undefined ? {} : { resource: action.resource }),
      ...(decision.error === undefined ? {} : { error: decision.error }),
    };
    await this.audit.write(record);
  }

  private blockedResult(
    tool: string,
    effect: NormalizedAction["effect"],
    reason: string,
    error?: string,
  ): ToolCallResult {
    const structuredContent: JsonObject = {
      blocked: true,
      verdict: "BLOCK",
      effect,
      tool,
      reason,
      ...(error === undefined ? {} : { error }),
    };
    return {
      isError: true,
      content: [{ type: "text", text: `BOUNCER BLOCKED ${effect} ${tool}: ${reason}` }],
      structuredContent,
    };
  }

  private remember(action: NormalizedAction, args: JsonObject, result: ToolCallResult): void {
    const resultText = result.content
      .map((block) => block.type === "text" && typeof block.text === "string" ? block.text : JSON.stringify(block))
      .join("\n")
      .slice(0, 2_000);
    const summary = [
      `Prior tool: ${action.toolName}`,
      `Arguments: ${JSON.stringify(args)}`,
      `Untrusted result: ${resultText}`,
    ].join("\n");
    this.context.push(summary);
    this.context = this.context.slice(-this.contextLimit);
  }
}
