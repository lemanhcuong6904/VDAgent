/**
 * Agent Protocol v2 Tests
 * M9.1: Versioned JSONL/bidi protocol tests
 */

import { describe, expect, it } from "vitest";
import {
  AGENT_PROTOCOL,
  type CheckpointMessage,
  type EventMessage,
  type InvokeMessage,
  isProtocolMessage,
  type PortCallMessage,
  type PortResultMessage,
  parseMessage,
  type ResultMessage,
  serializeMessage,
} from "../../src/agent-protocol.js";

describe("M9.1: Protocol Message Parsing", () => {
  it("should parse valid invoke message", () => {
    const message: InvokeMessage = {
      protocol: AGENT_PROTOCOL,
      type: "invoke",
      request_id: "req-123",
      agent_id: "test-agent",
      input: { query: "test" },
      scope: {
        user_id: "user-1",
        space_id: "space-1",
      },
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
    expect(isProtocolMessage(parsed)).toBe(true);
  });

  it("should parse port call message", () => {
    const message: PortCallMessage = {
      protocol: AGENT_PROTOCOL,
      type: "port_call",
      request_id: "req-123",
      call_id: "call-456",
      port: "tools",
      operation: "search",
      input: { query: "test" },
      sequence: 1,
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
  });

  it("should parse result message with usage", () => {
    const message: ResultMessage = {
      protocol: AGENT_PROTOCOL,
      type: "result",
      request_id: "req-123",
      ok: true,
      output: { answer: "done" },
      usage: {
        input_tokens: 100,
        output_tokens: 50,
        total_tokens: 150,
      },
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
  });

  it("should reject invalid protocol version", () => {
    const line = JSON.stringify({
      protocol: "agent-runner.v1",
      type: "invoke",
      request_id: "req-123",
    });

    expect(() => parseMessage(line)).toThrow("Invalid protocol v2 message");
  });

  it("should reject malformed JSON", () => {
    expect(() => parseMessage("not json")).toThrow();
  });

  it("should preserve unknown fields for forward compatibility", () => {
    const line = JSON.stringify({
      protocol: AGENT_PROTOCOL,
      type: "invoke",
      request_id: "req-123",
      agent_id: "test",
      input: {},
      scope: { user_id: "u1", space_id: "s1" },
      future_field: "preserved",
      nested: { unknown: "value" },
    });

    const parsed = parseMessage(line) as InvokeMessage & {
      future_field?: string;
      nested?: unknown;
    };

    expect(parsed.future_field).toBe("preserved");
    expect(parsed.nested).toEqual({ unknown: "value" });
  });
});

describe("M9.1: Event Messages", () => {
  it("should parse event message", () => {
    const message: EventMessage = {
      protocol: AGENT_PROTOCOL,
      type: "event",
      request_id: "req-123",
      event: "progress",
      data: { completed: 5, total: 10 },
      timestamp: new Date().toISOString(),
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
  });

  it("should handle event without data", () => {
    const message: EventMessage = {
      protocol: AGENT_PROTOCOL,
      type: "event",
      request_id: "req-123",
      event: "started",
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed.type).toBe("event");
    if (parsed.type !== "event") throw new Error("Expected event frame");
    expect(parsed.event).toBe("started");
    expect(parsed.data).toBeUndefined();
  });
});

describe("M9.1: Checkpoint Messages", () => {
  it("should parse checkpoint message with manifest", () => {
    const message: CheckpointMessage = {
      protocol: AGENT_PROTOCOL,
      type: "checkpoint",
      request_id: "req-123",
      checkpoint_id: "ckpt-789",
      manifest: {
        id: "ckpt-789",
        created_at: new Date().toISOString(),
        parent_id: "ckpt-456",
        content_hash: "sha256:abc123",
        size_bytes: 1024,
      },
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
  });

  it("should handle checkpoint without manifest", () => {
    const message: CheckpointMessage = {
      protocol: AGENT_PROTOCOL,
      type: "checkpoint",
      request_id: "req-123",
      checkpoint_id: "ckpt-789",
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed.type).toBe("checkpoint");
    if (parsed.type !== "checkpoint") throw new Error("Expected checkpoint frame");
    expect(parsed.checkpoint_id).toBe("ckpt-789");
    expect(parsed.manifest).toBeUndefined();
  });
});

describe("M9.1: Structured Errors", () => {
  it("should parse result with structured error", () => {
    const message: ResultMessage = {
      protocol: AGENT_PROTOCOL,
      type: "result",
      request_id: "req-123",
      ok: false,
      error: {
        code: "validation_error",
        message: "Invalid input format",
        details: { field: "query", reason: "required" },
        retriable: false,
      },
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
    expect((parsed as ResultMessage).error?.code).toBe("validation_error");
    expect((parsed as ResultMessage).error?.retriable).toBe(false);
  });

  it("should parse port result with structured error", () => {
    const message: PortResultMessage = {
      protocol: AGENT_PROTOCOL,
      type: "port_result",
      request_id: "req-123",
      call_id: "call-456",
      ok: false,
      error: {
        code: "unauthorized",
        message: "Port access denied",
        retriable: false,
      },
      sequence: 5,
    };

    const serialized = serializeMessage(message);
    const parsed = parseMessage(serialized);

    expect(parsed).toEqual(message);
  });
});

describe("M9.1: Sequence and Idempotency", () => {
  it("should include sequence numbers in port calls", () => {
    const message: PortCallMessage = {
      protocol: AGENT_PROTOCOL,
      type: "port_call",
      request_id: "req-123",
      call_id: "call-1",
      port: "tools",
      operation: "list",
      sequence: 1,
    };

    const parsed = parseMessage(serializeMessage(message));
    expect((parsed as PortCallMessage).sequence).toBe(1);
  });

  it("should include idempotency key in invoke", () => {
    const message: InvokeMessage = {
      protocol: AGENT_PROTOCOL,
      type: "invoke",
      request_id: "req-123",
      agent_id: "test",
      input: {},
      scope: { user_id: "u1", space_id: "s1" },
      idempotency_key: "idempotent-invoke-abc",
    };

    const parsed = parseMessage(serializeMessage(message));
    expect((parsed as InvokeMessage).idempotency_key).toBe("idempotent-invoke-abc");
  });

  it("should include idempotency key in port call", () => {
    const message: PortCallMessage = {
      protocol: AGENT_PROTOCOL,
      type: "port_call",
      request_id: "req-123",
      call_id: "call-1",
      port: "agents",
      operation: "send",
      input: { message: "test" },
      idempotency_key: "send-once-xyz",
    };

    const parsed = parseMessage(serializeMessage(message));
    expect((parsed as PortCallMessage).idempotency_key).toBe("send-once-xyz");
  });
});
