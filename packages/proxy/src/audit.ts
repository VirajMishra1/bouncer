import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";

import type { AuditRecord, AuditSink } from "./types.js";

type Replacer = (match: string, ...groups: string[]) => string;

const keepName: Replacer = (match) => {
  const separator = match.includes("=") ? match.slice(0, match.indexOf("=") + 1) : match.split(/\s+/)[0] + " ";
  return `${separator}[REDACTED]`;
};
const keepPrefix: Replacer = (_match, prefix) => `${prefix}[REDACTED]`;
const wholly: Replacer = () => "[REDACTED]";

const SECRET_PATTERNS: Array<[RegExp, Replacer]> = [
  [/\b(?:NVIDIA_API_KEY|API_KEY|TOKEN|SECRET|PASSWORD)=\S+/gi, keepName],
  [/\bBearer\s+\S+/gi, keepName],
  [/\b(?:nvapi|sk)-[A-Za-z0-9_-]{8,}\b/g, wholly],
  [/\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b/g, wholly],
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, wholly],
  // named credentials in JSON, query strings or key: value form
  [/(["']?[A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password|passwd)["']?\s*[:=]\s*)["']?[^\s,;}"'&]+["']?/gi, keepPrefix],
];

export const redactAuditText = (value: string): string => {
  let redacted = value;
  for (const [pattern, replacer] of SECRET_PATTERNS) redacted = redacted.replace(pattern, replacer);
  return redacted;
};

const sanitizeRecord = (record: AuditRecord): AuditRecord => ({
  ...record,
  reason: redactAuditText(record.reason),
  ...(record.error === undefined ? {} : { error: redactAuditText(record.error) }),
  ...(record.destination === undefined ? {} : { destination: redactAuditText(record.destination) }),
  ...(record.resource === undefined ? {} : { resource: redactAuditText(record.resource) }),
});

export class MemoryAuditSink implements AuditSink {
  readonly records: AuditRecord[] = [];

  async write(record: AuditRecord): Promise<void> {
    this.records.push(sanitizeRecord(record));
  }
}

export class JsonlAuditSink implements AuditSink {
  constructor(private readonly path: string) {}

  async write(record: AuditRecord): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await appendFile(this.path, `${JSON.stringify(sanitizeRecord(record))}\n`, { encoding: "utf8", mode: 0o600 });
  }
}
