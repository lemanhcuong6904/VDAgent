/**
 * MCP run reader - M12.4
 * An agent sees a run over MCP only when it ran a step in that run and the run is
 * inside the request's user/space scope. Membership in the space is not enough:
 * otherwise any agent token could read every run its tenant ever made.
 */

import type { Pool } from "pg";
import type { McpRunReader } from "./mcp-server.js";
import { ObservatoryProjector } from "./observatory.js";

export class ParticipatingRunReader implements McpRunReader {
  private readonly projector: ObservatoryProjector;

  constructor(private readonly database: Pool) {
    this.projector = new ObservatoryProjector(database);
  }

  async read(
    runId: string,
    scope: { userId: string; spaceId: string; agentId: string },
  ): Promise<unknown | null> {
    const participation = await this.database.query(
      `SELECT 1 FROM platform_run_steps s
       JOIN platform_runs r ON r.id = s.run_id
       WHERE s.run_id = $1 AND s.agent_id = $2 AND r.space_id = $3 AND r.user_id = $4
       LIMIT 1`,
      [runId, scope.agentId, scope.spaceId, scope.userId],
    );
    if (!participation.rowCount) return null;
    return this.projector.get(runId, { spaceId: scope.spaceId, userId: scope.userId });
  }
}
