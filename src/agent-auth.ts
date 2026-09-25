import { timingSafeEqual } from "node:crypto";

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
