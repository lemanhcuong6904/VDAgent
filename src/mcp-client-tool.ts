import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { McpPoolTool, ToolScope } from "./tool-pool.js";

export function defineRemoteMcpTool(
  input: Omit<McpPoolTool, "execute"> & {
    remoteName: string;
    connection(scope: ToolScope): Promise<{ endpoint: string; headers?: Record<string, string> }>;
  },
): McpPoolTool {
  const { remoteName, connection, ...tool } = input;
  return {
    ...tool,
    async execute(args, scope) {
      const resolved = await connection(scope);
      const endpoint = new URL(resolved.endpoint);
      if (
        endpoint.protocol !== "https:" &&
        endpoint.hostname !== "localhost" &&
        endpoint.hostname !== "127.0.0.1"
      ) {
        throw new Error("MCP endpoint must use HTTPS unless it is local development");
      }
      scope.signal.throwIfAborted();
      const client = new Client({ name: "team-6-cai", version: "0.1.0" });
      const transport = new StreamableHTTPClientTransport(endpoint, {
        requestInit: { headers: resolved.headers },
      });
      try {
        await client.connect(transport);
        const result = await client.callTool({
          name: remoteName,
          arguments: args as Record<string, unknown>,
        });
        if (result.isError) throw new Error(`Remote MCP tool '${remoteName}' failed`);
        scope.signal.throwIfAborted();
        return result;
      } finally {
        await client.close();
      }
    },
  };
}
