import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";

import type { AuditRecord, AuditSink } from "./types.js";

const SECRET_PATTERNS = [
  /\b(?:NVIDIA_API_KEY|API_KEY|TOKEN|SECRET|PASSWORD)=\S+/gi,
  /\bBearer\s+\S+/gi,
  /\b(?:nvapi|sk)-[A-Za-z0-9_-]{8,}\b/g,
];

export const redactAuditText = (value: string): string => {
  let redacted = value;
  for (const pattern of SECRET_PATTERNS) {
    redacted = redacted.replace(pattern, (match) => {
      const separator = match.includes("=") ? match.slice(0, match.indexOf("=") + 1) : match.split(/\s+/)[0] + " ";
      return `${separator}[REDACTED]`;
    });
  }
  return redacted;
};

const sanitizeRecord = (record: AuditRecord): AuditRecord => ({
  ...record,
  reason: redactAuditText(record.reason),
  ...(record.error === undefined ? {} : { error: redactAuditText(record.error) }),
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
