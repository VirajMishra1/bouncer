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

// Named credentials (bare, quoted JSON, or inside a URL query) plus well-known token shapes.
const SECRET_VALUE = /(?:^|[\s,{"'?&;(])(?:[A-Z0-9_-]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE[_-]?KEY|CREDENTIAL)[A-Z0-9_-]*)["']?\s*[:=]\s*["']?[^\s,;}"']+|-----BEGIN [^-]*PRIVATE KEY-----|(?:postgres|mysql|mongodb(?:\+srv)?):\/\/[^\s:@]+:[^\s@]+@|\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_-]{10,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})/i;
const SECRET_FIELD = /(?:^|[._-])(?:api[_-]?key|token|secret|password|passwd|private[_-]?key|credential)(?:$|[._-])/i;

export interface BouncerProxyOptions {
  downstream: DownstreamToolClient;
  evaluator: DecisionEvaluator;
  audit: AuditSink;
  now?: () => string;
  contextLimit?: number;
  /** Let the goal be replaced after it is first set. Off by default: a hijacked agent must not rewrite it. */
  allowGoalChange?: boolean;
}

export class BouncerProxy {
  private readonly downstream: DownstreamToolClient;
  private readonly evaluator: DecisionEvaluator;
  private readonly audit: AuditSink;
  private readonly now: () => string;
  private readonly contextLimit: number;
  private readonly allowGoalChange: boolean;
  private goal: string | undefined;
  private tools: ToolDefinition[] | undefined;
  private context: string[] = [];

  constructor(options: BouncerProxyOptions) {
    this.downstream = options.downstream;
    this.evaluator = options.evaluator;
    this.audit = options.audit;
    this.now = options.now ?? (() => new Date().toISOString());
    this.contextLimit = options.contextLimit ?? 2;
    this.allowGoalChange = options.allowGoalChange ?? false;
  }

  setGoal(goal: string): void {
    const trimmed = goal.trim();
    if (trimmed.length === 0) throw new Error("Original user goal cannot be empty");
    if (this.goal !== undefined && trimmed !== this.goal && !this.allowGoalChange) {
      throw new Error("The original user goal is already set for this session and cannot be replaced.");
    }
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
      const unknown: Decision = { verdict: "BLOCK", reason: `Unknown downstream tool: ${name}`, latencyMs: 0 };
      try {
        await this.writeAudit({ toolName: name, action: `Call ${name}`, effect: "EXECUTE" }, unknown, false);
      } catch {
        // Blocking does not depend on the log; the caller still gets a refusal.
      }
      return this.blockedResult(name, "EXECUTE", unknown.reason);
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

    const runtimeBlock = this.invariantBlockReason(normalized);
    if (runtimeBlock !== undefined) {
      const blocked: Decision = {
        verdict: "BLOCK",
        reason: runtimeBlock,
        latencyMs: 0,
      };
      await this.writeAudit(normalized, blocked, false);
      return this.blockedResult(name, normalized.effect, blocked.reason);
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

    const needsApproval = this.unmentionedSendDestination(normalized);
    if (needsApproval !== undefined) {
      const approval: Decision = {
        verdict: "ASK",
        reason: needsApproval,
        latencyMs: decision.latencyMs,
      };
      await this.writeAudit(normalized, approval, false);
      return this.approvalResult(normalized, approval.reason);
    }

    if (decision.verdict === "ASK") {
      const blocked: Decision = {
        verdict: "BLOCK",
        reason: "ASK is only valid for SEND to a destination not named in the original goal; the action was not forwarded.",
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
    if (action.runtime?.destructiveOperation === true) {
      return "Bouncer blocked a destructive operation; irreversible actions fail closed.";
    }
    if (
      action.effect === "SEND"
      && (
        action.runtime?.outboundText.some((value) => SECRET_VALUE.test(value)) === true
        || Object.entries(action.runtime?.outboundFields ?? {}).some(
          ([path, value]) => SECRET_FIELD.test(path) && value.trim().length > 0,
        )
      )
    ) {
      return "Bouncer blocked a secret-bearing outbound action.";
    }
    const executableText = action.runtime?.executableText;
    if (action.effect === "EXECUTE" && executableText !== undefined) {
      const collapse = (text: string): string => text.replace(/\s+/g, " ").trim().toLocaleLowerCase();
      const normalizedExecutable = collapse(executableText);
      if (
        normalizedExecutable.length >= 4
        && this.context.some((entry) => collapse(entry).includes(normalizedExecutable))
      ) return "Bouncer blocked executable text derived from prior untrusted tool output.";
    }
    if (action.effect === "SEND" && action.destination === undefined) {
      return "Bouncer could not determine the SEND destination; the action was not forwarded.";
    }
    return undefined;
  }

  private unmentionedSendDestination(action: NormalizedAction): string | undefined {
    if (
      action.effect === "SEND"
      && action.destination !== undefined
      && !this.goal?.toLocaleLowerCase().includes(action.destination.toLocaleLowerCase())
    ) return `Destination ${action.destination} was not named in the original goal.`;
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

  private approvalResult(action: NormalizedAction, reason: string): ToolCallResult {
    const approval: JsonObject = {
      effect: action.effect,
      tool: action.toolName,
      ...(action.destination === undefined ? {} : { destination: action.destination }),
      reason,
    };
    return {
      isError: true,
      content: [{
        type: "text",
        text: `BOUNCER APPROVAL REQUIRED ${action.effect} ${action.toolName}: ${reason}`,
      }],
      structuredContent: {
        approvalRequired: true,
        verdict: "ASK",
        effect: action.effect,
        tool: action.toolName,
        reason,
        approval,
      },
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
