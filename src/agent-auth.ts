import { timingSafeEqual } from "node:crypto";

export function assertSecureSecret(
  name: string,
  value: string | undefined,
  options: { required?: boolean; minLength?: number } = {},
): void {
  const required = options.required ?? true;
  const minLength = options.minLength ?? 32;
  if (!value) {
    if (required) throw new Error(`${name} is required`);
    return;
  }
  if (
    value.length < minLength ||
    /^(?:replace-with|change-me|placeholder|development|secret)/i.test(value)
  ) {
    throw new Error(`${name} must be a long, non-placeholder secret`);
  }
}

export function isAuthorizedAgent(
  agentId: string,
  authorization: string | undefined,
  env: NodeJS.ProcessEnv,
  hasAgent: (id: string) => boolean,
): boolean {
  if (!hasAgent(agentId)) return false;
  const key = `AGENT_TOKEN_${agentId.toUpperCase().replace(/[^A-Z0-9]/g, "_")}`;
  const expected = env[key];
  const presented = authorization?.replace(/^Bearer\s+/i, "") ?? "";
  if (!expected || Buffer.byteLength(expected) !== Buffer.byteLength(presented)) return false;
  return timingSafeEqual(Buffer.from(expected), Buffer.from(presented));
}
