/**
 * Pool tools over ArtifactStorage (PostgreSQL, SHA-256 + length verified). The canonical
 * ArtifactPort (src/ports/host-artifacts.ts) reaches storage only through these tools, so the
 * same grant, scope and timeout rules apply as for every other effect.
 */
import { Type } from "typebox";
import type { ArtifactStorage } from "../artifact-storage.js";
import type { McpPoolTool } from "../tool-pool.js";

/** Pool results are capped at 1 MB JSON; base64 inflates by 4/3, so stay well below. */
export const MAX_ARTIFACT_BYTES = 512 * 1024;

export function createArtifactTools(storage: ArtifactStorage): McpPoolTool[] {
  return [
    {
      name: "artifacts.store",
      description: "Store a verified artifact (bytes as base64) owned by the current run.",
      schema: Type.Object({
        kind: Type.String({ minLength: 1, maxLength: 64 }),
        version: Type.String({ minLength: 1, maxLength: 32 }),
        mediaType: Type.String({ minLength: 1, maxLength: 128 }),
        bytesBase64: Type.String({ maxLength: Math.ceil((MAX_ARTIFACT_BYTES * 4) / 3) + 4 }),
      }),
      mutates: true,
      agents: ["*"],
      authorize: () => true,
      async execute(raw, scope) {
        const input = raw as {
          kind: string;
          version: string;
          mediaType: string;
          bytesBase64: string;
        };
        const content = Buffer.from(input.bytesBase64, "base64");
        if (content.byteLength > MAX_ARTIFACT_BYTES) throw new Error("Artifact is too large");
        return storage.store({
          workspaceId: scope.spaceId,
          ownerUserId: scope.userId,
          ownerRunId: scope.runId ?? "unknown",
          kind: input.kind,
          version: input.version,
          content,
          metadata: { mediaType: input.mediaType, agentId: scope.agentId ?? null },
        });
      },
    },
    {
      name: "artifacts.read",
      description: "Read a ready artifact in this workspace by id.",
      schema: Type.Object({ artifactId: Type.String({ minLength: 1, maxLength: 128 }) }),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute(raw, scope) {
        const { artifactId } = raw as { artifactId: string };
        const metadata = await storage.getMetadata(artifactId, scope.spaceId, scope.userId);
        if (metadata?.status !== "ready") return { found: false };
        const content = await storage.getContent(artifactId, scope.spaceId, scope.userId);
        if (!content || content.byteLength > MAX_ARTIFACT_BYTES) return { found: false };
        return {
          found: true,
          artifact: {
            id: metadata.id,
            workspaceId: metadata.workspaceId,
            ownerRunId: metadata.ownerRunId,
            kind: metadata.kind,
            version: metadata.version,
            status: "ready",
            sha256: metadata.sha256,
            bytes: metadata.bytes,
          },
          bytesBase64: content.toString("base64"),
        };
      },
    },
  ];
}
