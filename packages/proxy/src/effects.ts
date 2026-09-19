import type { JsonObject, JsonValue, NormalizedAction, ToolDefinition } from "./types.js";

const SEND_NAME = /(?:^|_)(?:send|forward|post|notify|publish|upload)(?:_|$)/i;
const READ_NAME = /(?:^|_)(?:list|get|read|search|fetch|open|inspect|show|lookup|download)(?:_|$)/i;
const EXECUTE_NAME = /(?:^|_)(?:execute|exec|run|shell|delete|remove|write|create|update|install|deploy|commit|merge)(?:_|$)/i;

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
  firstString(args, ["command", "script", "code", "source"]);

export const normalizeToolCall = (
  tool: ToolDefinition,
  args: JsonObject,
): NormalizedAction => {
  const action = `Call ${tool.name} with ${JSON.stringify(args)}`;

  if (tool.annotations?.readOnlyHint === true) {
    return { toolName: tool.name, action, effect: "READ", resource: resourceFor(tool.name, args) };
  }

  if (SEND_NAME.test(tool.name)) {
    const destination = destinationFor(tool.name, args);
    return {
      toolName: tool.name,
      action,
      effect: "SEND",
      ...(destination === undefined ? {} : { destination }),
    };
  }

  if (READ_NAME.test(tool.name) && !EXECUTE_NAME.test(tool.name)) {
    return { toolName: tool.name, action, effect: "READ", resource: resourceFor(tool.name, args) };
  }

  const source = sourceFor(args);
  return {
    toolName: tool.name,
    action,
    effect: "EXECUTE",
    ...(source === undefined ? {} : { source }),
  };
};
