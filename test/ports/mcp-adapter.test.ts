import { beforeEach, describe, expect, it } from "vitest";
import type { McpServerConnection, McpToolConfig } from "../../src/ports/mcp-adapter.js";
import { McpToolAdapter } from "../../src/ports/mcp-adapter.js";

describe("McpToolAdapter", () => {
  let adapter: McpToolAdapter;

  const sampleServer: McpServerConnection = {
    id: "test-server",
    capabilities: [{ name: "tools", version: "1.0.0" }],
    tools: [
      {
        name: "read_file",
        description: "Read a file",
        inputSchema: {
          type: "object",
          properties: {
            path: { type: "string" },
          },
          required: ["path"],
        },
      },
      {
        name: "write_file",
        description: "Write a file",
        inputSchema: {
          type: "object",
          properties: {
            path: { type: "string" },
            content: { type: "string" },
          },
          required: ["path", "content"],
        },
      },
    ],
    allowedResourcePatterns: ["file:///workspace/*", "file:///tmp/*"],
  };

  beforeEach(() => {
    adapter = new McpToolAdapter();
  });

  describe("server registration", () => {
    it("should register a server", () => {
      adapter.registerServer(sampleServer);
      const connection = adapter.getConnection("test-server");
      expect(connection).toBeDefined();
      expect(connection?.id).toBe("test-server");
    });

    it("should get registered server", () => {
      adapter.registerServer(sampleServer);
      const connection = adapter.getConnection("test-server");
      expect(connection?.tools).toHaveLength(2);
    });
  });

  describe("allowlist", () => {
    beforeEach(() => {
      adapter.registerServer(sampleServer);
    });

    it("should set tool allowlist", () => {
      adapter.setAllowlist("test-server", ["read_file"]);
      expect(adapter.isAllowed("test-server", "read_file")).toBe(true);
      expect(adapter.isAllowed("test-server", "write_file")).toBe(false);
    });

    it("should deny by default when no allowlist", () => {
      expect(adapter.isAllowed("test-server", "read_file")).toBe(false);
    });

    it("should deny unknown server", () => {
      adapter.setAllowlist("test-server", ["read_file"]);
      expect(adapter.isAllowed("unknown-server", "read_file")).toBe(false);
    });
  });

  describe("manifest conversion", () => {
    beforeEach(() => {
      adapter.registerServer(sampleServer);
      adapter.setAllowlist("test-server", ["read_file", "write_file"]);
    });

    it("should convert MCP tool to manifest", () => {
      const config: McpToolConfig = {
        mcpTool: sampleServer.tools[0],
        serverId: "test-server",
        version: "1.0.0",
        effectClass: "read",
        idempotent: true,
        sensitivity: "public",
      };

      const manifest = adapter.convertToManifest(config);

      expect(manifest.id).toBe("mcp:test-server:read_file");
      expect(manifest.version).toBe("1.0.0");
      expect(manifest.displayName).toBe("read_file");
      expect(manifest.effectClass).toBe("read");
      expect(manifest.idempotent).toBe(true);
      expect(manifest.sensitivity).toBe("public");
      expect(manifest.tags).toContain("mcp");
      expect(manifest.tags).toContain("test-server");
    });

    it("should use default limits", () => {
      const config: McpToolConfig = {
        mcpTool: sampleServer.tools[0],
        serverId: "test-server",
        version: "1.0.0",
        effectClass: "read",
        idempotent: true,
        sensitivity: "public",
      };

      const manifest = adapter.convertToManifest(config);

      expect(manifest.limits.maxInputBytes).toBe(100000);
      expect(manifest.limits.maxOutputBytes).toBe(100000);
      expect(manifest.limits.timeoutMs).toBe(30000);
    });

    it("should override default limits", () => {
      const config: McpToolConfig = {
        mcpTool: sampleServer.tools[0],
        serverId: "test-server",
        version: "1.0.0",
        effectClass: "read",
        idempotent: true,
        sensitivity: "public",
        limits: {
          maxInputBytes: 50000,
          timeoutMs: 10000,
        },
      };

      const manifest = adapter.convertToManifest(config);

      expect(manifest.limits.maxInputBytes).toBe(50000);
      expect(manifest.limits.maxOutputBytes).toBe(100000);
      expect(manifest.limits.timeoutMs).toBe(10000);
    });

    it("should reject tool not in allowlist", () => {
      adapter.setAllowlist("test-server", ["read_file"]);

      const config: McpToolConfig = {
        mcpTool: sampleServer.tools[1], // write_file
        serverId: "test-server",
        version: "1.0.0",
        effectClass: "write",
        idempotent: false,
        sensitivity: "internal",
      };

      expect(() => adapter.convertToManifest(config)).toThrow("not in allowlist");
    });
  });

  describe("resource URI validation", () => {
    beforeEach(() => {
      adapter.registerServer(sampleServer);
    });

    it("should validate allowed URI patterns", () => {
      const result1 = adapter.validateResourceUri("test-server", "file:///workspace/test.txt");
      expect(result1.valid).toBe(true);

      const result2 = adapter.validateResourceUri("test-server", "file:///tmp/cache.json");
      expect(result2.valid).toBe(true);
    });

    it("should reject disallowed URI patterns", () => {
      const result = adapter.validateResourceUri("test-server", "file:///etc/passwd");
      expect(result.valid).toBe(false);
      expect(result.error).toContain("not in allowed patterns");
    });

    it("should reject when server not found", () => {
      const result = adapter.validateResourceUri("unknown-server", "file:///workspace/test.txt");
      expect(result.valid).toBe(false);
      expect(result.error).toBe("Server not found");
    });

    it("should reject when no patterns configured", () => {
      const serverNoPatterns: McpServerConnection = {
        id: "no-patterns",
        capabilities: [],
        tools: [],
      };

      adapter.registerServer(serverNoPatterns);

      const result = adapter.validateResourceUri("no-patterns", "file:///any/path");
      expect(result.valid).toBe(false);
      expect(result.error).toBe("No resource patterns allowed");
    });
  });

  describe("output size validation", () => {
    it("should validate output size within limit", () => {
      const output = { message: "Hello" };
      const result = adapter.validateOutputSize(output, 1000);
      expect(result.valid).toBe(true);
    });

    it("should reject output exceeding limit", () => {
      const output = { message: "x".repeat(10000) };
      const result = adapter.validateOutputSize(output, 1000);
      expect(result.valid).toBe(false);
      expect(result.error).toContain("exceeds limit");
    });
  });

  describe("error classification", () => {
    it("should classify timeout errors", () => {
      const error = new Error("Request timeout");
      const toolError = adapter.classifyMcpError(error);

      expect(toolError.code).toBe("timeout");
      expect(toolError.class).toBe("transient");
      expect(toolError.retryable).toBe(true);
    });

    it("should classify permission errors", () => {
      const error = new Error("Permission denied");
      const toolError = adapter.classifyMcpError(error);

      expect(toolError.code).toBe("permission_denied");
      expect(toolError.class).toBe("permission");
      expect(toolError.retryable).toBe(false);
    });

    it("should classify validation errors", () => {
      const error = new Error("Invalid input schema");
      const toolError = adapter.classifyMcpError(error);

      expect(toolError.code).toBe("validation_error");
      expect(toolError.class).toBe("validation");
      expect(toolError.retryable).toBe(false);
    });

    it("should classify not found errors", () => {
      const error = new Error("File not found");
      const toolError = adapter.classifyMcpError(error);

      expect(toolError.code).toBe("not_found");
      expect(toolError.class).toBe("permanent");
      expect(toolError.retryable).toBe(false);
    });

    it("should classify network errors", () => {
      const error = new Error("Connection refused");
      const toolError = adapter.classifyMcpError(error);

      expect(toolError.code).toBe("connection_error");
      expect(toolError.class).toBe("transient");
      expect(toolError.retryable).toBe(true);
    });

    it("should classify unknown errors", () => {
      const error = new Error("Something went wrong");
      const toolError = adapter.classifyMcpError(error);

      expect(toolError.code).toBe("execution_error");
      expect(toolError.class).toBe("unknown");
      expect(toolError.retryable).toBe(false);
    });
  });

  describe("list operations", () => {
    beforeEach(() => {
      adapter.registerServer(sampleServer);
      adapter.setAllowlist("test-server", ["read_file"]);
    });

    it("should list all MCP tools", () => {
      const tools = adapter.listMcpTools();
      expect(tools).toHaveLength(2);
      expect(tools[0].serverId).toBe("test-server");
      expect(tools[0].toolName).toBe("read_file");
      expect(tools[0].allowed).toBe(true);
      expect(tools[1].toolName).toBe("write_file");
      expect(tools[1].allowed).toBe(false);
    });

    it("should handle multiple servers", () => {
      const server2: McpServerConnection = {
        id: "server-2",
        capabilities: [],
        tools: [
          {
            name: "echo",
            description: "Echo input",
            inputSchema: { type: "object", properties: {} },
          },
        ],
      };

      adapter.registerServer(server2);
      adapter.setAllowlist("server-2", ["echo"]);

      const tools = adapter.listMcpTools();
      expect(tools).toHaveLength(3);
    });
  });

  describe("authentication", () => {
    it("should check if server requires auth", () => {
      const authServer: McpServerConnection = {
        id: "auth-server",
        capabilities: [],
        tools: [],
        authenticate: true,
      };

      adapter.registerServer(authServer);
      expect(adapter.requiresAuth("auth-server")).toBe(true);
    });

    it("should return false for server without auth", () => {
      adapter.registerServer(sampleServer);
      expect(adapter.requiresAuth("test-server")).toBe(false);
    });

    it("should return false for unknown server", () => {
      expect(adapter.requiresAuth("unknown")).toBe(false);
    });
  });
});
