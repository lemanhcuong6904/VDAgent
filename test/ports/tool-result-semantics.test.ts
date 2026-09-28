import { describe, expect, it } from "vitest";
import type { EvidenceRef, ToolError, ToolResult } from "../../src/ports/tool-port.js";

describe("Tool Result Semantics", () => {
  describe("evidence types", () => {
    it("receipt evidence indicates verified execution", () => {
      const receipt: EvidenceRef = {
        type: "receipt",
        id: "exec-123",
        timestamp: "2024-01-01T00:00:00Z",
        verified: true,
      };

      expect(receipt.type).toBe("receipt");
      expect(receipt.verified).toBe(true);
    });

    it("claim evidence is unverified assertion", () => {
      const claim: EvidenceRef = {
        type: "claim",
        id: "claim-456",
        timestamp: "2024-01-01T00:00:00Z",
        verified: false,
      };

      expect(claim.type).toBe("claim");
      expect(claim.verified).toBe(false);
    });

    it("observer_hint provides context without verification", () => {
      const hint: EvidenceRef = {
        type: "observer_hint",
        id: "hint-789",
        timestamp: "2024-01-01T00:00:00Z",
        verified: false,
      };

      expect(hint.type).toBe("observer_hint");
      expect(hint.verified).toBe(false);
    });

    it("process_exit captures termination state", () => {
      const processExit: EvidenceRef = {
        type: "process_exit",
        id: "exit-101",
        timestamp: "2024-01-01T00:00:00Z",
        verified: true,
      };

      expect(processExit.type).toBe("process_exit");
      // Process exits can be verified if captured reliably
      expect(processExit.verified).toBe(true);
    });
  });

  describe("success status", () => {
    it("requires verified receipt evidence for definitive success", () => {
      const result: ToolResult<{ data: string }> = {
        status: "success",
        output: { data: "result" },
        evidence: [
          {
            type: "receipt",
            id: "exec-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: true,
          },
        ],
        usage: { durationMs: 100 },
      };

      expect(result.status).toBe("success");
      expect(result.evidence).toBeDefined();
      expect(result.evidence![0].type).toBe("receipt");
      expect(result.evidence![0].verified).toBe(true);
    });

    it("should include limitations when operation is partial", () => {
      const result: ToolResult<{ items: string[] }> = {
        status: "success",
        output: { items: ["a", "b"] },
        limitations: ["Only first 100 items returned", "Ordering not guaranteed"],
        evidence: [
          {
            type: "receipt",
            id: "exec-2",
            timestamp: "2024-01-01T00:00:00Z",
            verified: true,
          },
        ],
        usage: { durationMs: 200 },
      };

      expect(result.status).toBe("success");
      expect(result.limitations).toHaveLength(2);
      expect(result.limitations![0]).toContain("first 100");
    });
  });

  describe("unknown status", () => {
    it("preserves unknown when verification unavailable", () => {
      const result: ToolResult = {
        status: "unknown",
        evidence: [
          {
            type: "claim",
            id: "claim-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: false,
          },
        ],
        limitations: ["Provider did not confirm completion", "State cannot be verified"],
      };

      expect(result.status).toBe("unknown");
      expect(result.evidence![0].verified).toBe(false);
      expect(result.limitations).toContain("State cannot be verified");
    });

    it("unknown status when network effect unverifiable", () => {
      const result: ToolResult = {
        status: "unknown",
        evidence: [
          {
            type: "observer_hint",
            id: "hint-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: false,
          },
        ],
        limitations: ["Network partition during execution", "Final state not observable"],
      };

      expect(result.status).toBe("unknown");
      expect(result.limitations).toBeDefined();
    });
  });

  describe("error classification", () => {
    it("validation errors are permanent and not retryable", () => {
      const error: ToolError = {
        code: "invalid_input",
        message: "Input schema validation failed",
        class: "validation",
        retryable: false,
        safeMessage: "Invalid input",
      };

      expect(error.class).toBe("validation");
      expect(error.retryable).toBe(false);
    });

    it("permission errors are permanent", () => {
      const error: ToolError = {
        code: "permission_denied",
        message: "Tool not granted",
        class: "permission",
        retryable: false,
        safeMessage: "Permission denied",
      };

      expect(error.class).toBe("permission");
      expect(error.retryable).toBe(false);
    });

    it("transient errors are retryable", () => {
      const error: ToolError = {
        code: "network_error",
        message: "Connection timeout",
        class: "transient",
        retryable: true,
        safeMessage: "Network error",
      };

      expect(error.class).toBe("transient");
      expect(error.retryable).toBe(true);
    });

    it("permanent errors are not retryable", () => {
      const error: ToolError = {
        code: "not_found",
        message: "Resource does not exist",
        class: "permanent",
        retryable: false,
        safeMessage: "Resource not found",
      };

      expect(error.class).toBe("permanent");
      expect(error.retryable).toBe(false);
    });

    it("unknown errors default to not retryable", () => {
      const error: ToolError = {
        code: "execution_error",
        message: "Unexpected failure",
        class: "unknown",
        retryable: false,
        safeMessage: "Tool execution failed",
      };

      expect(error.class).toBe("unknown");
      expect(error.retryable).toBe(false);
    });
  });

  describe("timeout status", () => {
    it("timeout status with transient classification", () => {
      const result: ToolResult = {
        status: "timeout",
        error: {
          code: "timeout",
          message: "Execution exceeded deadline",
          class: "transient",
          retryable: true,
          safeMessage: "Request timed out",
        },
        usage: { durationMs: 5000 },
      };

      expect(result.status).toBe("timeout");
      expect(result.error?.class).toBe("transient");
      expect(result.error?.retryable).toBe(true);
    });
  });

  describe("usage tracking", () => {
    it("tracks duration for all results", () => {
      const result: ToolResult<string> = {
        status: "success",
        output: "data",
        evidence: [
          {
            type: "receipt",
            id: "exec-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: true,
          },
        ],
        usage: {
          durationMs: 250,
        },
      };

      expect(result.usage?.durationMs).toBe(250);
    });

    it("tracks bytes read and written for I/O operations", () => {
      const result: ToolResult<{ content: string }> = {
        status: "success",
        output: { content: "file data" },
        evidence: [
          {
            type: "receipt",
            id: "exec-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: true,
          },
        ],
        usage: {
          durationMs: 100,
          bytesRead: 1024,
          bytesWritten: 512,
        },
      };

      expect(result.usage?.bytesRead).toBe(1024);
      expect(result.usage?.bytesWritten).toBe(512);
    });
  });

  describe("safe messages", () => {
    it("provides safe message for user display", () => {
      const error: ToolError = {
        code: "database_error",
        message: "Connection failed: postgres://user:pass@host/db",
        class: "transient",
        retryable: true,
        safeMessage: "Database connection error",
      };

      // Internal message may contain sensitive data
      expect(error.message).toContain("user:pass");

      // Safe message is sanitized
      expect(error.safeMessage).toBe("Database connection error");
      expect(error.safeMessage).not.toContain("user:pass");
    });
  });

  describe("multiple evidence refs", () => {
    it("can combine multiple evidence sources", () => {
      const result: ToolResult<{ status: string }> = {
        status: "success",
        output: { status: "deployed" },
        evidence: [
          {
            type: "receipt",
            id: "exec-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: true,
          },
          {
            type: "observer_hint",
            id: "health-check",
            timestamp: "2024-01-01T00:00:01Z",
            verified: false,
          },
        ],
        usage: { durationMs: 1000 },
      };

      expect(result.evidence).toHaveLength(2);
      expect(result.evidence![0].type).toBe("receipt");
      expect(result.evidence![1].type).toBe("observer_hint");
    });
  });

  describe("result without output", () => {
    it("error result has no output", () => {
      const result: ToolResult = {
        status: "error",
        error: {
          code: "execution_failed",
          message: "Tool handler threw exception",
          class: "unknown",
          retryable: false,
          safeMessage: "Execution failed",
        },
      };

      expect(result.status).toBe("error");
      expect(result.output).toBeUndefined();
      expect(result.error).toBeDefined();
    });

    it("unknown result may have partial output", () => {
      const result: ToolResult<{ partial: string }> = {
        status: "unknown",
        output: { partial: "data" },
        evidence: [
          {
            type: "claim",
            id: "claim-1",
            timestamp: "2024-01-01T00:00:00Z",
            verified: false,
          },
        ],
        limitations: ["Connection lost during execution", "Output may be incomplete"],
      };

      expect(result.status).toBe("unknown");
      expect(result.output).toBeDefined();
      expect(result.limitations).toContain("Output may be incomplete");
    });
  });
});
