/**
 * MCP Tool Adapter
 * Bridges MCP protocol to ToolPort interface
 */

import type { EffectClass, ToolError, ToolManifest } from "./tool-port.js";

export interface McpToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
}

export interface McpCapability {
  name: string;
  version: string;
}

export interface McpServerConnection {
  id: string;
  capabilities: McpCapability[];
  tools: McpToolDefinition[];
  allowedResourcePatterns?: string[];
  authenticate?: boolean;
}

export interface McpToolConfig {
  mcpTool: McpToolDefinition;
  serverId: string;
  version: string;
  effectClass: EffectClass;
  idempotent: boolean;
  sensitivity: "public" | "internal" | "confidential" | "restricted";
  limits?: {
    maxInputBytes?: number;
    maxOutputBytes?: number;
    timeoutMs?: number;
  };
}

export class McpToolAdapter {
  private connections = new Map<string, McpServerConnection>();
  private allowlist = new Map<string, string[]>(); // serverId -> allowed tool names

  /**
   * Register an MCP server connection
   */
  registerServer(connection: McpServerConnection): void {
    this.connections.set(connection.id, connection);
  }

  /**
   * Set tool allowlist for a server
   */
  setAllowlist(serverId: string, toolNames: string[]): void {
    this.allowlist.set(serverId, toolNames);
  }

  /**
   * Check if tool is allowed
   */
  isAllowed(serverId: string, toolName: string): boolean {
    const allowed = this.allowlist.get(serverId);
    if (!allowed) {
      return false; // Default deny if no allowlist configured
    }
    return allowed.includes(toolName);
  }

  /**
   * Convert MCP tool to ToolManifest
   */
  convertToManifest(config: McpToolConfig): ToolManifest {
    const { mcpTool, serverId, version, effectClass, idempotent, sensitivity, limits } = config;

    // Validate tool is allowed
    if (!this.isAllowed(serverId, mcpTool.name)) {
      throw new Error(`Tool ${mcpTool.name} not in allowlist for server ${serverId}`);
    }

    const defaultLimits = {
      maxInputBytes: 100000,
      maxOutputBytes: 100000,
      timeoutMs: 30000,
    };

    return {
      id: `mcp:${serverId}:${mcpTool.name}`,
      version,
      displayName: mcpTool.name,
      description: mcpTool.description,
      inputSchema: mcpTool.inputSchema,
      outputSchema: undefined, // MCP tools don't declare output schema
      effectClass,
      idempotent,
      limits: { ...defaultLimits, ...limits },
      sensitivity,
      tags: ["mcp", serverId],
    };
  }

  /**
   * Validate resource URI against allowlist
   */
  validateResourceUri(serverId: string, uri: string): { valid: boolean; error?: string } {
    const connection = this.connections.get(serverId);
    if (!connection) {
      return { valid: false, error: "Server not found" };
    }

    if (!connection.allowedResourcePatterns || connection.allowedResourcePatterns.length === 0) {
      return { valid: false, error: "No resource patterns allowed" };
    }

    // Check against patterns
    const isAllowed = connection.allowedResourcePatterns.some((pattern) => {
      // Simple pattern matching - in production use a proper URI pattern matcher
      if (pattern.endsWith("*")) {
        const prefix = pattern.slice(0, -1);
        return uri.startsWith(prefix);
      }
      return uri === pattern;
    });

    if (!isAllowed) {
      return { valid: false, error: `URI ${uri} not in allowed patterns` };
    }

    return { valid: true };
  }

  /**
   * Check output bounds
   */
  validateOutputSize(output: unknown, maxBytes: number): { valid: boolean; error?: string } {
    const outputJson = JSON.stringify(output);
    const outputBytes = Buffer.byteLength(outputJson, "utf8");

    if (outputBytes > maxBytes) {
      return {
        valid: false,
        error: `Output size ${outputBytes} exceeds limit ${maxBytes}`,
      };
    }

    return { valid: true };
  }

  /**
   * Classify MCP error into ToolError
   */
  classifyMcpError(error: unknown): ToolError {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const lowerMessage = errorMessage.toLowerCase();

    // Classify based on error patterns
    if (lowerMessage.includes("timeout") || lowerMessage.includes("deadline")) {
      return {
        code: "timeout",
        message: errorMessage,
        class: "transient",
        retryable: true,
        safeMessage: "Request timed out",
      };
    }

    if (lowerMessage.includes("permission") || lowerMessage.includes("unauthorized")) {
      return {
        code: "permission_denied",
        message: errorMessage,
        class: "permission",
        retryable: false,
        safeMessage: "Permission denied",
      };
    }

    if (
      lowerMessage.includes("invalid") ||
      lowerMessage.includes("validation") ||
      lowerMessage.includes("bad request")
    ) {
      return {
        code: "validation_error",
        message: errorMessage,
        class: "validation",
        retryable: false,
        safeMessage: "Invalid input",
      };
    }

    if (
      lowerMessage.includes("not found") ||
      lowerMessage.includes("does not exist") ||
      lowerMessage.includes("no such")
    ) {
      return {
        code: "not_found",
        message: errorMessage,
        class: "permanent",
        retryable: false,
        safeMessage: "Resource not found",
      };
    }

    if (
      lowerMessage.includes("network") ||
      lowerMessage.includes("connection") ||
      lowerMessage.includes("unavailable")
    ) {
      return {
        code: "connection_error",
        message: errorMessage,
        class: "transient",
        retryable: true,
        safeMessage: "Connection error",
      };
    }

    // Unknown error
    return {
      code: "execution_error",
      message: errorMessage,
      class: "unknown",
      retryable: false,
      safeMessage: "Tool execution failed",
    };
  }

  /**
   * List all available MCP tools
   */
  listMcpTools(): Array<{
    serverId: string;
    toolName: string;
    allowed: boolean;
  }> {
    const result: Array<{ serverId: string; toolName: string; allowed: boolean }> = [];

    for (const [serverId, connection] of this.connections.entries()) {
      for (const tool of connection.tools) {
        result.push({
          serverId,
          toolName: tool.name,
          allowed: this.isAllowed(serverId, tool.name),
        });
      }
    }

    return result;
  }

  /**
   * Get server connection
   */
  getConnection(serverId: string): McpServerConnection | undefined {
    return this.connections.get(serverId);
  }

  /**
   * Check if server requires authentication
   */
  requiresAuth(serverId: string): boolean {
    const connection = this.connections.get(serverId);
    return connection?.authenticate === true;
  }
}
