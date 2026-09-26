import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { McpToolPool } from "./tool-pool.js";

export async function handleMcpRequest(
  request: Request,
  input: {
    agentId: string;
    userId: string;
    spaceId: string;
    allowedTools: readonly string[];
    pool: McpToolPool;
  },
): Promise<Response> {
  const server = new Server(
    { name: "team-6-cai", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );
  const scope = { userId: input.userId, spaceId: input.spaceId, signal: request.signal };
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: input.pool
      .forAgent(input.agentId)
      .filter(({ name }) => input.allowedTools.includes(name))
      .map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.schema as Record<string, unknown>,
        annotations: { readOnlyHint: !tool.mutates },
      })),
  }));
  server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
    try {
      const result = await input.pool.call(
        params.name,
        params.arguments ?? {},
        scope,
        input.agentId,
        input.allowedTools,
      );
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    } catch (error) {
      return {
        isError: true,
        content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }],
      };
    }
  });
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });
  await server.connect(transport);
  return transport.handleRequest(request);
}
