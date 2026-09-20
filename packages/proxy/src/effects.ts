import type { JsonObject, JsonValue, NormalizedAction, RuntimeSignals, ToolDefinition } from "./types.js";

const SEND_NAME = /(?:^|_)(?:send|forward|post|notify|publish|upload)(?:_|$)/i;
const READ_NAME = /(?:^|_)(?:list|get|read|search|fetch|open|inspect|show|lookup|download)(?:_|$)/i;
const EXECUTE_NAME = /(?:^|_)(?:execute|exec|run|shell|delete|remove|write|create|update|install|deploy|commit|merge)(?:_|$)/i;
const DESTRUCTIVE_NAME = /(?:^|_)(?:delete|remove|destroy|drop|truncate|purge|erase|wipe|revoke)(?:_|$)/i;
const DESTRUCTIVE_VALUE = /^(?:delete|remove|destroy|drop|truncate|purge|erase|wipe|revoke)$/i;
const DESTINATION_KEYS = new Set(["destination", "to", "recipient", "url", "endpoint"]);
const RISK_LABEL_KEYS = new Set([
  "data_class",
  "sensitivity",
  "risk",
  "risk_level",
  "source",
  "destructive",
  "destination_in_goal",
  "operation_in_goal",
]);

const asString = (value: JsonValue | undefined): string | undefined => {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number") return String(value);
  return undefined;
};

const firstString = (args: JsonObject, keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = asString(args[key]);
    if (value !== undefined) return value;
  }
  return undefined;
};

const destinationFor = (toolName: string, args: JsonObject): string | undefined => {
  const direct = firstString(args, ["destination", "to", "recipient", "url", "endpoint"]);
  if (direct !== undefined) return direct;

  if (/github_(?:post|create)_comment/i.test(toolName)) {
    const repo = firstString(args, ["repo", "repository"]);
    const issue = firstString(args, ["issue", "issue_number"]);
    if (repo !== undefined && issue !== undefined) return `${repo}#${issue}`;
  }
  return undefined;
};

const resourceFor = (toolName: string, args: JsonObject): string =>
  firstString(args, ["resource", "path", "message_id", "issue", "issue_number", "id", "query", "folder"])
  ?? toolName;

const sourceFor = (args: JsonObject): string | undefined =>
  firstString(args, ["command", "script", "code"]);

const outboundFor = (args: JsonObject): Pick<RuntimeSignals, "outboundText" | "outboundFields"> => {
  const values: string[] = [];
  const fields: Record<string, string> = {};
  const visit = (value: JsonValue, key?: string, path = ""): void => {
    const normalizedKey = key?.toLocaleLowerCase();
    if (
      normalizedKey !== undefined
      && (DESTINATION_KEYS.has(normalizedKey) || RISK_LABEL_KEYS.has(normalizedKey))
    ) return;
    if (typeof value === "string") {
      if (value.length > 0) {
        values.push(value);
        if (path.length > 0) fields[path] = value;
      }
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((entry, index) => visit(entry, undefined, `${path}[${index}]`));
      return;
    }
    if (typeof value === "object" && value !== null) {
      for (const [nestedKey, nestedValue] of Object.entries(value)) {
        visit(nestedValue, nestedKey, path.length === 0 ? nestedKey : `${path}.${nestedKey}`);
      }
    }
  };
  for (const [key, value] of Object.entries(args)) visit(value, key, key);
  return { outboundText: values, outboundFields: fields };
};

const isDestructiveOperation = (toolName: string, args: JsonObject): boolean => {
  if (DESTRUCTIVE_NAME.test(toolName)) return true;
  const operation = firstString(args, ["operation", "action", "mode"]);
  return operation !== undefined && DESTRUCTIVE_VALUE.test(operation.trim());
};

const neutralArgsForModel = (args: JsonObject): JsonObject => {
  const visit = (value: JsonValue): JsonValue => {
    if (Array.isArray(value)) return value.map(visit);
    if (typeof value !== "object" || value === null) return value;
    const sanitized: JsonObject = {};
    for (const [key, nestedValue] of Object.entries(value)) {
      if (!RISK_LABEL_KEYS.has(key.toLocaleLowerCase())) sanitized[key] = visit(nestedValue);
    }
    return sanitized;
  };
  return visit(args) as JsonObject;
};

export const normalizeToolCall = (
  tool: ToolDefinition,
  args: JsonObject,
): NormalizedAction => {
  const action = `Call ${tool.name} with ${JSON.stringify(neutralArgsForModel(args))}`;
  const destructiveOperation = isDestructiveOperation(tool.name, args);
  const executableText = sourceFor(args);
  const outbound = SEND_NAME.test(tool.name)
    ? outboundFor(args)
    : { outboundText: [], outboundFields: {} };
  const runtime = {
    ...outbound,
    destructiveOperation,
    ...(executableText === undefined ? {} : { executableText }),
  };

  if (tool.annotations?.readOnlyHint === true && !destructiveOperation) {
    return { toolName: tool.name, action, effect: "READ", resource: resourceFor(tool.name, args), runtime };
  }

  if (SEND_NAME.test(tool.name)) {
    const destination = destinationFor(tool.name, args);
    return {
      toolName: tool.name,
      action,
      effect: "SEND",
      ...(destination === undefined ? {} : { destination }),
      runtime,
    };
  }

  if (READ_NAME.test(tool.name) && !EXECUTE_NAME.test(tool.name)) {
    return { toolName: tool.name, action, effect: "READ", resource: resourceFor(tool.name, args), runtime };
  }

  const source = sourceFor(args);
  return {
    toolName: tool.name,
    action,
    effect: "EXECUTE",
    ...(source === undefined ? {} : { source }),
    runtime,
  };
};
