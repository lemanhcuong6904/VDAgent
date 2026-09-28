import { Ajv2020 } from "ajv/dist/2020.js";
import type { JsonSchema, JsonValue, PortOutcome, WarehousePort } from "../contracts/index.js";
import { runFakeCall, type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";

export interface WarehouseFixture {
  sourceId: string;
  displayName: string;
  datasetId: string;
  columns: Array<{ name: string; type: string }>;
  queryId: string;
  rows: JsonValue[];
}
export interface WarehouseQueryHandler {
  parameterSchema: JsonSchema;
  execute(parameters: Record<string, JsonValue>, signal: AbortSignal): Promise<JsonValue[]>;
}
/** Each instance is an isolated, host-selected catalog; no provider or SQL access. */
export function createFakeWarehousePort(config: {
  fixtures: WarehouseFixture[];
  handlers?: ReadonlyMap<string, WarehouseQueryHandler>;
  clock: TestClock;
  maxRows: number;
  maxBytes: number;
  maxInputBytes: number;
}): WarehousePort {
  for (const value of [config.maxRows, config.maxBytes, config.maxInputBytes])
    if (!Number.isSafeInteger(value) || value < 1)
      throw new Error("Invalid warehouse fixture limits");
  const fixtures = JSON.parse(
    encodeBoundedJson(config.fixtures, config.maxBytes),
  ) as WarehouseFixture[];
  if (new Set(fixtures.map((fixture) => fixture.queryId)).size !== fixtures.length)
    throw new Error("Duplicate query fixture");
  const handlers = new Map(
    [...(config.handlers ?? [])].map(([id, handler]) => {
      if (!fixtures.some((fixture) => fixture.queryId === id))
        throw new Error("Handler query not registered");
      const schema = JSON.parse(encodeBoundedJson(handler.parameterSchema, config.maxInputBytes));
      const validate = new Ajv2020({ strict: true }).compile(schema);
      return [id, { validate, execute: handler.execute }] as const;
    }),
  );
  const denied = <T>(code: string): PortOutcome<T> => ({
    status: "denied",
    error: {
      code,
      class: "policy",
      retryable: false,
      safeMessage: code,
      correlationId: "fake-warehouse",
    },
    evidence: [],
  });
  const limits = {
    maxOutputBytes: config.maxBytes,
    correlationId: "fake-warehouse",
    effect: "read" as const,
  };
  return {
    catalog(options) {
      const sources = [
        ...new Map(
          fixtures.map(({ sourceId, displayName }) => [sourceId, { id: sourceId, displayName }]),
        ).values(),
      ];
      return runFakeCall(async () => sources, options, limits, config.clock);
    },
    describe(input, options) {
      if (Object.keys(input).some((key) => !["sourceId", "datasetId"].includes(key)))
        return Promise.resolve(denied("unknown_request_field"));
      const fixture = fixtures.find(
        (entry) => entry.sourceId === input.sourceId && entry.datasetId === input.datasetId,
      );
      if (!fixture) return Promise.resolve(denied("dataset_unavailable"));
      return runFakeCall(async () => ({ columns: fixture.columns }), options, limits, config.clock);
    },
    query(input, options) {
      if (
        Object.keys(input).some(
          (key) =>
            !["queryId", "parameters", "maxRows", "maxBytes", "idempotencyKey"].includes(key),
        )
      )
        return Promise.resolve(denied("unknown_request_field"));
      if (
        !Number.isSafeInteger(input.maxRows) ||
        input.maxRows < 1 ||
        input.maxRows > config.maxRows ||
        !Number.isSafeInteger(input.maxBytes) ||
        input.maxBytes < 1 ||
        input.maxBytes > config.maxBytes
      )
        return Promise.resolve(denied("query_limit"));
      if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(input.idempotencyKey))
        return Promise.resolve(denied("invalid_idempotency_key"));
      let snapshot: typeof input;
      try {
        snapshot = JSON.parse(encodeBoundedJson(input, config.maxInputBytes)) as typeof input;
      } catch {
        return Promise.resolve(denied("invalid_query_input"));
      }
      const fixture = fixtures.find((entry) => entry.queryId === snapshot.queryId);
      if (!fixture) return Promise.resolve(denied("query_not_registered"));
      const handler = handlers.get(snapshot.queryId);
      if (
        !snapshot.parameters ||
        Array.isArray(snapshot.parameters) ||
        typeof snapshot.parameters !== "object"
      )
        return Promise.resolve(denied("invalid_parameters"));
      if (
        handler
          ? !handler.validate(snapshot.parameters)
          : Object.keys(snapshot.parameters).length > 0
      )
        return Promise.resolve(denied("invalid_parameters"));
      return runFakeCall(
        async (signal) => {
          const rows = handler ? await handler.execute(snapshot.parameters, signal) : fixture.rows;
          if (!Array.isArray(rows)) throw new Error("Invalid fixture rows");
          // Bound the provider result too, before truncating the consumer projection.
          encodeBoundedJson(rows, config.maxBytes);
          return {
            rows: rows.slice(0, snapshot.maxRows),
            truncated: rows.length > snapshot.maxRows,
          };
        },
        options,
        { ...limits, maxOutputBytes: snapshot.maxBytes },
        config.clock,
      );
    },
  };
}
