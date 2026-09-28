/**
 * MCP server - M12.4
 * Tools and resources for one authenticated agent. The contract is published as a
 * resource so a client can read its limits instead of discovering them by failing.
 * Nothing here grants more than the tool pool already allows the agent.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListResourcesRequestSchema,
  ListResourceTemplatesRequestSchema,
  ListToolsRequestSchema,
  McpError,
  ReadResourceRequestSchema,
  SUPPORTED_PROTOCOL_VERSIONS,
} from "@modelcontextprotocol/sdk/types.js";
import type { McpToolPool } from "./tool-pool.js";

export const MCP_SERVER_VERSION = "0.2.0";
/** Bumped on any breaking change to tool/resource shapes or error codes. */
export const MCP_CONTRACT_VERSION = "mcp-contract.v1";
export const DEFAULT_MCP_MAX_RESULT_BYTES = 256_000;
export const MCP_MAX_REQUEST_BYTES = 1_000_000;

export const CONTRACT_URI = "platform://contract";
export const SELF_URI = "platform://agent/self";
export const RUN_URI_TEMPLATE = "platform://runs/{runId}";
const RUN_URI = /^platform:\/\/runs\/([a-zA-Z0-9._:-]{1,128})$/;

/** Stable error codes a client may branch on; exception text is never forwarded. */
export type McpToolErrorCode =
  | "not_authorized"
  | "invalid_input"
  | "timeout"
  | "cancelled"
  | "result_too_large"
  | "tool_failed";

export interface McpRunReader {
  /** Returns the run only when this agent took part in it, inside the caller's scope. */
  read(
    runId: string,
    scope: { userId: string; spaceId: string; agentId: string },
  ): Promise<unknown | null>;
}

export interface McpRequestInput {
  agentId: string;
  userId: string;
  spaceId: string;
  allowedTools: readonly string[];
  pool: McpToolPool;
  /** The agent's own public descriptor, exposed at `platform://agent/self`. */
  descriptor?: Record<string, unknown>;
  runs?: McpRunReader;
  maxResultBytes?: number;
  /** Browser origins allowed to call; requests with any other `Origin` are refused. */
  allowedOrigins?: readonly string[];
}

export function classifyToolError(error: unknown): McpToolErrorCode {
  const message = error instanceof Error ? error.message : String(error);
  if (/is not authorized for agent/.test(message)) return "not_authorized";
  if (/^Invalid input for tool/.test(message)) return "invalid_input";
  if (/timed out/i.test(message)) return "timeout";
  if (error instanceof Error && error.name === "AbortError") return "cancelled";
  if (/at most 1 MB/.test(message)) return "result_too_large";
  return "tool_failed";
}

const ERROR_MESSAGES: Record<McpToolErrorCode, string> = {
  not_authorized: "This tool is not available to the calling agent",
  invalid_input: "Arguments do not match the tool's input schema",
  timeout: "The tool did not finish within its time limit",
  cancelled: "The call was cancelled",
  result_too_large: "The tool result exceeds the contract size limit",
  tool_failed: "The tool failed",
};

/** Encode once, measure once: the size check is on the exact bytes that are sent. */
export function encodeBounded(
  value: unknown,
  maxBytes: number,
): { text: string } | { tooLarge: number } {
  const text = JSON.stringify(value ?? null);
  const bytes = Buffer.byteLength(text);
  return bytes > maxBytes ? { tooLarge: bytes } : { text };
}

function toolError(code: McpToolErrorCode, tool: string) {
  return {
    isError: true,
    content: [
      {
        type: "text" as const,
        text: JSON.stringify({ error: { code, message: ERROR_MESSAGES[code] } }),
      },
    ],
    structuredContent: { error: { code, message: ERROR_MESSAGES[code], tool } },
  };
}

export async function handleMcpRequest(
  request: Request,
  input: McpRequestInput,
): Promise<Response> {
  // Agents call server-to-server and send no Origin; a browser always does. Refusing an
  // unlisted origin stops a page in the user's browser from driving an agent's tools
  // (DNS rebinding / CSRF against a token the browser might hold).
  const origin = request.headers.get("origin");
  if (origin !== null && !(input.allowedOrigins ?? []).includes(origin)) {
    return Response.json(
      { jsonrpc: "2.0", error: { code: -32000, message: "Origin not allowed" }, id: null },
      { status: 403 },
    );
  }
  const maxResultBytes = input.maxResultBytes ?? DEFAULT_MCP_MAX_RESULT_BYTES;
  const server = new Server(
    { name: "team-6-cai", version: MCP_SERVER_VERSION },
    {
      capabilities: { tools: {}, resources: {} },
      instructions: `Contract ${MCP_CONTRACT_VERSION}; read ${CONTRACT_URI} for limits and error codes.`,
    },
  );
  const scope = { userId: input.userId, spaceId: input.spaceId, signal: request.signal };
  const visibleTools = () =>
    input.pool.forAgent(input.agentId).filter(({ name }) => input.allowedTools.includes(name));

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: visibleTools().map((tool) => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.schema as Record<string, unknown>,
      annotations: { readOnlyHint: !tool.mutates, destructiveHint: tool.mutates },
    })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
    let result: unknown;
    try {
      result = await input.pool.call(
        params.name,
        params.arguments ?? {},
        scope,
        input.agentId,
        input.allowedTools,
      );
    } catch (error) {
      return toolError(classifyToolError(error), params.name);
    }
    const encoded = encodeBounded(result, maxResultBytes);
    if ("tooLarge" in encoded) return toolError("result_too_large", params.name);
    return {
      content: [{ type: "text" as const, text: encoded.text }],
      ...(isRecord(result) && { structuredContent: result }),
    };
  });

  server.setRequestHandler(ListResourcesRequestSchema, async () => ({
    resources: [
      {
        uri: CONTRACT_URI,
        name: "contract",
        title: "MCP contract",
        mimeType: "application/json",
        annotations: { audience: ["assistant"] },
      },
      {
        uri: SELF_URI,
        name: "agent-self",
        title: "Calling agent descriptor",
        mimeType: "application/json",
        annotations: { audience: ["assistant"] },
      },
    ],
  }));

  server.setRequestHandler(ListResourceTemplatesRequestSchema, async () => ({
    resourceTemplates: input.runs
      ? [
          {
            uriTemplate: RUN_URI_TEMPLATE,
            name: "run",
            title: "Run this agent took part in",
            mimeType: "application/json",
            annotations: { audience: ["assistant"] },
          },
        ]
      : [],
  }));

  server.setRequestHandler(ReadResourceRequestSchema, async ({ params }) => {
    const body = await readResource(
      params.uri,
      input,
      visibleTools().map(({ name }) => name),
      maxResultBytes,
    );
    // An unknown URI and an out-of-scope run are indistinguishable to the caller.
    if (body === undefined) throw new McpError(ErrorCode.InvalidParams, "Resource not found");
    const encoded = encodeBounded(body, maxResultBytes);
    if ("tooLarge" in encoded) {
      throw new McpError(ErrorCode.InvalidRequest, ERROR_MESSAGES.result_too_large);
    }
    return { contents: [{ uri: params.uri, mimeType: "application/json", text: encoded.text }] };
  });

  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });
  await server.connect(transport);
  return transport.handleRequest(request);
}

async function readResource(
  uri: string,
  input: McpRequestInput,
  toolNames: string[],
  maxResultBytes: number,
): Promise<unknown | undefined> {
  if (uri === CONTRACT_URI) {
    return {
      contract_version: MCP_CONTRACT_VERSION,
      server_version: MCP_SERVER_VERSION,
      protocol_versions: SUPPORTED_PROTOCOL_VERSIONS,
      auth: {
        scheme: "bearer",
        audience: "per-agent token bound to X-Agent-Id; valid only for that agent on this server",
      },
      scope: { user_id: input.userId, space_id: input.spaceId, agent_id: input.agentId },
      limits: { max_result_bytes: maxResultBytes, max_request_bytes: MCP_MAX_REQUEST_BYTES },
      tools: toolNames,
      error_codes: Object.keys(ERROR_MESSAGES),
    };
  }
  if (uri === SELF_URI) {
    return input.descriptor ?? { id: input.agentId };
  }
  const match = RUN_URI.exec(uri);
  if (match && input.runs) {
    const run = await input.runs.read(match[1], {
      userId: input.userId,
      spaceId: input.spaceId,
      agentId: input.agentId,
    });
    return run ?? undefined;
  }
  return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
