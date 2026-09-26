import type { Pool } from "pg";

export interface AuditEventInput {
  spaceId?: string;
  userId?: string;
  actor: string;
  action: string;
  resourceType?: string;
  resourceId?: string;
  outcome: "allowed" | "denied" | "success" | "failure";
  metadata?: Record<string, unknown>;
}

export async function recordAudit(pool: Pool, input: AuditEventInput): Promise<void> {
  await pool.query(
    `INSERT INTO platform_audit_events
     (space_id, user_id, actor, action, resource_type, resource_id, outcome, metadata)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)`,
    [
      input.spaceId ?? null,
      input.userId ?? null,
      input.actor.slice(0, 128),
      input.action.slice(0, 128),
      input.resourceType?.slice(0, 128) ?? null,
      input.resourceId?.slice(0, 256) ?? null,
      input.outcome,
      JSON.stringify(redactMetadata(input.metadata ?? {})),
    ],
  );
}

function redactMetadata(metadata: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(metadata).map(([key, value]) => [
      key,
      /(prompt|content|memory|secret|token|password|query|row)/i.test(key)
        ? "[redacted]"
        : typeof value === "string"
          ? value.slice(0, 256)
          : value,
    ]),
  );
}
