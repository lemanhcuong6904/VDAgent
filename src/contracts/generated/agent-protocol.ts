// Generated from schemas/agent-protocol.schema.json. Do not edit.
// Runtime validation is required for bounds, patterns and cross-field semantics.
type AgentProtocolId = string;
type AgentProtocolTimestamp = string;
type AgentProtocolJson =
  | null
  | boolean
  | number
  | string
  | Array<AgentProtocolJson>
  | { [key: string]: AgentProtocolJson };
type AgentProtocolJsonMap = { [key: string]: AgentProtocolJson };
type AgentProtocolScope = {
  user_id: AgentProtocolId;
  space_id: AgentProtocolId;
  task_id?: AgentProtocolId;
  run_id?: AgentProtocolId;
  parent_run_id?: AgentProtocolId;
  trace_id?: AgentProtocolId;
};
type AgentProtocolError = {
  code: string;
  message: string;
  details?: AgentProtocolJsonMap;
  retriable?: boolean;
};
type AgentProtocolUsage = { input_tokens?: number; output_tokens?: number; total_tokens?: number };
type AgentProtocolArtifact = {
  id: AgentProtocolId;
  type: string;
  url?: string;
  metadata?: AgentProtocolJsonMap;
};
type AgentProtocolCheckpointManifest = {
  id: AgentProtocolId;
  created_at: AgentProtocolTimestamp;
  parent_id?: AgentProtocolId;
  base_id?: AgentProtocolId;
  source?: string;
  content_hash?: string;
  size_bytes?: number;
  metadata?: AgentProtocolJsonMap;
};
type AgentProtocolHello = {
  protocol: "agent-runner.v2";
  type: "hello";
  version: string;
  capabilities: Array<string>;
  metadata?: AgentProtocolJsonMap;
};
type AgentProtocolInvoke = {
  protocol: "agent-runner.v2";
  type: "invoke";
  request_id: AgentProtocolId;
  agent_id: AgentProtocolId;
  agent_version?: string;
  input: AgentProtocolJson;
  scope: AgentProtocolScope;
  tools?: Array<string>;
  deadline_at?: AgentProtocolTimestamp;
  checkpoint_id?: AgentProtocolId;
  idempotency_key?: AgentProtocolId;
};
type AgentProtocolPortCall = {
  protocol: "agent-runner.v2";
  type: "port_call";
  request_id: AgentProtocolId;
  call_id: AgentProtocolId;
  port: string;
  operation: string;
  input?: AgentProtocolJson;
  sequence?: number;
  idempotency_key?: AgentProtocolId;
};
type AgentProtocolPortResult = {
  protocol: "agent-runner.v2";
  type: "port_result";
  request_id: AgentProtocolId;
  call_id: AgentProtocolId;
  ok: boolean;
  output?: AgentProtocolJson;
  error?: AgentProtocolError;
  sequence?: number;
};
type AgentProtocolEvent = {
  protocol: "agent-runner.v2";
  type: "event";
  request_id: AgentProtocolId;
  event: string;
  data?: AgentProtocolJson;
  timestamp?: AgentProtocolTimestamp;
};
type AgentProtocolCheckpoint = {
  protocol: "agent-runner.v2";
  type: "checkpoint";
  request_id: AgentProtocolId;
  checkpoint_id: AgentProtocolId;
  manifest?: AgentProtocolCheckpointManifest;
  parent_id?: AgentProtocolId;
};
type AgentProtocolWait = {
  protocol: "agent-runner.v2";
  type: "wait";
  request_id: AgentProtocolId;
  wait_for: string;
  timeout_ms?: number;
  poll_interval_ms?: number;
};
type AgentProtocolCancel = {
  protocol: "agent-runner.v2";
  type: "cancel";
  request_id: AgentProtocolId;
  reason?: string;
};
type AgentProtocolResult = {
  protocol: "agent-runner.v2";
  type: "result";
  request_id: AgentProtocolId;
  ok: boolean;
  output?: AgentProtocolJson;
  error?: AgentProtocolError;
  usage?: AgentProtocolUsage;
  artifacts?: Array<AgentProtocolArtifact>;
};
export type AgentProtocol =
  | AgentProtocolHello
  | AgentProtocolInvoke
  | AgentProtocolPortCall
  | AgentProtocolPortResult
  | AgentProtocolEvent
  | AgentProtocolCheckpoint
  | AgentProtocolWait
  | AgentProtocolCancel
  | AgentProtocolResult;
export const AgentProtocolSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "urn:team6:schema:agent-protocol:v2",
  title: "AgentProtocol",
  description:
    "agent-runner.v2 JSONL frames. Known fields are closed here; the runtime parser forwards unknown fields for forward compatibility and must not treat schema validity as authorization.",
  $defs: {
    Id: {
      type: "string",
      minLength: 1,
      maxLength: 256,
    },
    Timestamp: {
      type: "string",
      minLength: 1,
      maxLength: 64,
      format: "date-time",
    },
    Json: {
      anyOf: [
        {
          type: "null",
        },
        {
          type: "boolean",
        },
        {
          type: "number",
          minimum: -1.7976931348623157e308,
          maximum: 1.7976931348623157e308,
        },
        {
          type: "string",
          maxLength: 1048576,
        },
        {
          type: "array",
          maxItems: 10000,
          items: {
            $ref: "#/$defs/Json",
          },
        },
        {
          type: "object",
          maxProperties: 10000,
          propertyNames: {
            type: "string",
            maxLength: 256,
          },
          additionalProperties: {
            $ref: "#/$defs/Json",
          },
        },
      ],
    },
    JsonMap: {
      type: "object",
      maxProperties: 256,
      propertyNames: {
        type: "string",
        maxLength: 256,
      },
      additionalProperties: {
        $ref: "#/$defs/Json",
      },
    },
    Scope: {
      type: "object",
      additionalProperties: false,
      properties: {
        user_id: {
          $ref: "#/$defs/Id",
        },
        space_id: {
          $ref: "#/$defs/Id",
        },
        task_id: {
          $ref: "#/$defs/Id",
        },
        run_id: {
          $ref: "#/$defs/Id",
        },
        parent_run_id: {
          $ref: "#/$defs/Id",
        },
        trace_id: {
          $ref: "#/$defs/Id",
        },
      },
      required: ["user_id", "space_id"],
    },
    Error: {
      type: "object",
      additionalProperties: false,
      properties: {
        code: {
          type: "string",
          minLength: 1,
          maxLength: 128,
        },
        message: {
          type: "string",
          maxLength: 4096,
        },
        details: {
          $ref: "#/$defs/JsonMap",
        },
        retriable: {
          type: "boolean",
        },
      },
      required: ["code", "message"],
    },
    Usage: {
      type: "object",
      additionalProperties: false,
      properties: {
        input_tokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        output_tokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        total_tokens: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
      },
    },
    Artifact: {
      type: "object",
      additionalProperties: false,
      properties: {
        id: {
          $ref: "#/$defs/Id",
        },
        type: {
          type: "string",
          minLength: 1,
          maxLength: 128,
        },
        url: {
          type: "string",
          minLength: 1,
          maxLength: 2048,
          format: "uri",
        },
        metadata: {
          $ref: "#/$defs/JsonMap",
        },
      },
      required: ["id", "type"],
    },
    CheckpointManifest: {
      type: "object",
      additionalProperties: false,
      properties: {
        id: {
          $ref: "#/$defs/Id",
        },
        created_at: {
          $ref: "#/$defs/Timestamp",
        },
        parent_id: {
          $ref: "#/$defs/Id",
        },
        base_id: {
          $ref: "#/$defs/Id",
        },
        source: {
          type: "string",
          minLength: 1,
          maxLength: 256,
        },
        content_hash: {
          type: "string",
          minLength: 1,
          maxLength: 128,
        },
        size_bytes: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        metadata: {
          $ref: "#/$defs/JsonMap",
        },
      },
      required: ["id", "created_at"],
    },
    Hello: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "hello",
          maxLength: 32,
        },
        version: {
          type: "string",
          minLength: 1,
          maxLength: 32,
          pattern: "^[0-9]+\\.[0-9]+\\.[0-9]+$",
        },
        capabilities: {
          type: "array",
          maxItems: 64,
          items: {
            type: "string",
            minLength: 1,
            maxLength: 128,
          },
        },
        metadata: {
          $ref: "#/$defs/JsonMap",
        },
      },
      required: ["protocol", "type", "version", "capabilities"],
    },
    Invoke: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "invoke",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        agent_id: {
          $ref: "#/$defs/Id",
        },
        agent_version: {
          type: "string",
          minLength: 1,
          maxLength: 64,
        },
        input: {
          $ref: "#/$defs/Json",
        },
        scope: {
          $ref: "#/$defs/Scope",
        },
        tools: {
          type: "array",
          maxItems: 256,
          items: {
            type: "string",
            minLength: 1,
            maxLength: 128,
          },
        },
        deadline_at: {
          $ref: "#/$defs/Timestamp",
        },
        checkpoint_id: {
          $ref: "#/$defs/Id",
        },
        idempotency_key: {
          $ref: "#/$defs/Id",
        },
      },
      required: ["protocol", "type", "request_id", "agent_id", "input", "scope"],
    },
    PortCall: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "port_call",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        call_id: {
          $ref: "#/$defs/Id",
        },
        port: {
          type: "string",
          minLength: 1,
          maxLength: 64,
        },
        operation: {
          type: "string",
          minLength: 1,
          maxLength: 128,
        },
        input: {
          $ref: "#/$defs/Json",
        },
        sequence: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        idempotency_key: {
          $ref: "#/$defs/Id",
        },
      },
      required: ["protocol", "type", "request_id", "call_id", "port", "operation"],
    },
    PortResult: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "port_result",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        call_id: {
          $ref: "#/$defs/Id",
        },
        ok: {
          type: "boolean",
        },
        output: {
          $ref: "#/$defs/Json",
        },
        error: {
          $ref: "#/$defs/Error",
        },
        sequence: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
      },
      required: ["protocol", "type", "request_id", "call_id", "ok"],
    },
    Event: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "event",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        event: {
          type: "string",
          minLength: 1,
          maxLength: 128,
        },
        data: {
          $ref: "#/$defs/Json",
        },
        timestamp: {
          $ref: "#/$defs/Timestamp",
        },
      },
      required: ["protocol", "type", "request_id", "event"],
    },
    Checkpoint: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "checkpoint",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        checkpoint_id: {
          $ref: "#/$defs/Id",
        },
        manifest: {
          $ref: "#/$defs/CheckpointManifest",
        },
        parent_id: {
          $ref: "#/$defs/Id",
        },
      },
      required: ["protocol", "type", "request_id", "checkpoint_id"],
    },
    Wait: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "wait",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        wait_for: {
          type: "string",
          minLength: 1,
          maxLength: 256,
        },
        timeout_ms: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
        poll_interval_ms: {
          type: "integer",
          minimum: 0,
          maximum: 9007199254740991,
        },
      },
      required: ["protocol", "type", "request_id", "wait_for"],
    },
    Cancel: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "cancel",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        reason: {
          type: "string",
          maxLength: 1024,
        },
      },
      required: ["protocol", "type", "request_id"],
    },
    Result: {
      type: "object",
      additionalProperties: false,
      properties: {
        protocol: {
          type: "string",
          const: "agent-runner.v2",
          maxLength: 32,
        },
        type: {
          type: "string",
          const: "result",
          maxLength: 32,
        },
        request_id: {
          $ref: "#/$defs/Id",
        },
        ok: {
          type: "boolean",
        },
        output: {
          $ref: "#/$defs/Json",
        },
        error: {
          $ref: "#/$defs/Error",
        },
        usage: {
          $ref: "#/$defs/Usage",
        },
        artifacts: {
          type: "array",
          maxItems: 256,
          items: {
            $ref: "#/$defs/Artifact",
          },
        },
      },
      required: ["protocol", "type", "request_id", "ok"],
    },
  },
  oneOf: [
    {
      $ref: "#/$defs/Hello",
    },
    {
      $ref: "#/$defs/Invoke",
    },
    {
      $ref: "#/$defs/PortCall",
    },
    {
      $ref: "#/$defs/PortResult",
    },
    {
      $ref: "#/$defs/Event",
    },
    {
      $ref: "#/$defs/Checkpoint",
    },
    {
      $ref: "#/$defs/Wait",
    },
    {
      $ref: "#/$defs/Cancel",
    },
    {
      $ref: "#/$defs/Result",
    },
  ],
} as const;
