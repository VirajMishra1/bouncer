import type { JsonObject, JsonValue, NormalizedAction, RuntimeSignals, ToolDefinition } from "./types.js";

const SEND_NAME = /(?:^|_)(?:send|forward|post|notify|publish|upload)(?:_|$)/i;
const READ_NAME = /(?:^|_)(?:list|get|read|search|fetch|open|inspect|show|lookup|download)(?:_|$)/i;
const EXECUTE_NAME = /(?:^|_)(?:execute|exec|run|shell|delete|remove|write|create|update|install|deploy|commit|merge)(?:_|$)/i;
const DESTRUCTIVE_NAME = /(?:^|_)(?:delete|remove|destroy|drop|truncate|purge|erase|wipe|revoke)(?:_|$)/i;
const DESTRUCTIVE_VALUE = /^(?:delete|remove|destroy|drop|truncate|purge|erase|wipe|revoke)$/i;
// Caller-supplied risk labels are never evidence: they are hidden from the judge.
// `source` is only treated as a label when its value is a known provenance word;
// any other value (a path, URL or script) is real payload and stays visible.
const RISK_LABEL_KEYS = new Set([
  "data_class",
  "sensitivity",
  "risk",
  "risk_level",
  "destructive",
  "destination_in_goal",
  "operation_in_goal",
]);
const SOURCE_LABEL_VALUE = /^(?:trusted|untrusted(?:_content)?|user|system|tool_output|internal|external)$/i;

const isLabelEntry = (key: string, value: JsonValue): boolean => {
  const normalizedKey = key.toLocaleLowerCase();
  if (RISK_LABEL_KEYS.has(normalizedKey)) return true;
  return normalizedKey === "source" && typeof value === "string" && SOURCE_LABEL_VALUE.test(value.trim());
};

// Define own properties so an argument literally named "__proto__" cannot hit the prototype setter.
const setOwn = <T>(target: Record<string, T>, key: string, value: T): void => {
  Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true });
};

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

const sourceFor = (args: JsonObject): string | undefined => {
  const direct = firstString(args, ["command", "script", "code"]);
  if (direct !== undefined) return direct;
  const source = asString(args.source);
  return source !== undefined && !SOURCE_LABEL_VALUE.test(source.trim()) ? source : undefined;
};

const outboundFor = (args: JsonObject): Pick<RuntimeSignals, "outboundText" | "outboundFields"> => {
  const values: string[] = [];
  const fields: Record<string, string> = {};
  // Every string is scanned, including destination-named keys and label keys: a secret can hide
  // in `url`, `to` or a nested `destination`. Destination inference is a separate step.
  const visit = (value: JsonValue, key?: string, path = ""): void => {
    if (typeof value === "string") {
      if (value.length > 0) {
        values.push(value);
        if (path.length > 0) setOwn(fields, path, value);
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
      if (!isLabelEntry(key, nestedValue)) setOwn(sanitized, key, visit(nestedValue));
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

  // The downstream server's readOnlyHint is untrusted: a name that says send or execute wins.
  if (
    tool.annotations?.readOnlyHint === true
    && !destructiveOperation
    && !SEND_NAME.test(tool.name)
    && !EXECUTE_NAME.test(tool.name)
  ) {
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
