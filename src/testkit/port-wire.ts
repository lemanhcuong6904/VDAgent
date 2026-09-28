import { Ajv2020 } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import { type PortCallWire, PortCallWireSchema } from "../contracts/generated/port-call.js";
import { type PortResultWire, PortResultWireSchema } from "../contracts/generated/port-result.js";
import { encodeBoundedJson } from "./json.js";

const hardMaxBytes = 16 * 1024 * 1024;
export class PortWireError extends Error {
  constructor(
    readonly code:
      | "invalid_frame"
      | "invalid_contract"
      | "invalid_base64"
      | "correlation_mismatch"
      | "payload_limit",
  ) {
    super(code);
    this.name = "PortWireError";
  }
}
/** Offline testkit codec only: validation never authenticates or dispatches a port call. */
export function createPortWireCodec(limits: { maxBytes?: number; maxDepth?: number } = {}) {
  const maxBytes = limits.maxBytes ?? hardMaxBytes;
  const maxDepth = limits.maxDepth ?? 64;
  if (
    !Number.isSafeInteger(maxBytes) ||
    maxBytes < 1 ||
    maxBytes > hardMaxBytes ||
    !Number.isSafeInteger(maxDepth) ||
    maxDepth < 1 ||
    maxDepth > 64
  )
    throw new Error("Invalid wire limits");
  const ajv = new Ajv2020({ strict: true, allErrors: false });
  ajv.addFormat("date-time", fullFormats["date-time"]);
  const callValidator = ajv.compile<PortCallWire>(PortCallWireSchema);
  const resultValidator = ajv.compile<PortResultWire>(PortResultWireSchema);
  function json(value: unknown): string {
    try {
      return encodeBoundedJson(value, maxBytes, maxDepth);
    } catch (error) {
      throw new PortWireError(
        error instanceof Error && ["json_byte_limit", "json_depth_limit"].includes(error.message)
          ? "payload_limit"
          : "invalid_frame",
      );
    }
  }
  function frame(value: string | Uint8Array): unknown {
    let decoded: string;
    try {
      if (typeof value === "string") {
        if (value.length > maxBytes || new TextEncoder().encode(value).byteLength > maxBytes)
          throw new PortWireError("payload_limit");
        decoded = value;
      } else {
        if (!(value instanceof Uint8Array)) throw new PortWireError("invalid_frame");
        if (value.byteLength > maxBytes) throw new PortWireError("payload_limit");
        decoded = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(value);
      }
      return JSON.parse(decoded);
    } catch (error) {
      if (error instanceof PortWireError) throw error;
      throw new PortWireError("invalid_frame");
    }
  }
  function bytes(value: string): Uint8Array {
    if (typeof value !== "string" || value.length > maxBytes)
      throw new PortWireError("payload_limit");
    if (value.length % 4 !== 0) throw new PortWireError("invalid_base64");
    const decoded = Buffer.from(value, "base64");
    if (decoded.toString("base64") !== value) throw new PortWireError("invalid_base64");
    return new Uint8Array(decoded);
  }
  function checkCall(value: unknown): PortCallWire {
    // Bound nesting and copy plain JSON before recursive schema validation.
    const copy = JSON.parse(json(value));
    if (!callValidator(copy)) throw new PortWireError("invalid_contract");
    if (copy.method === "artifacts.write") bytes(copy.input.bytesBase64);
    return copy;
  }
  function checkResult(
    value: unknown,
    expected: Pick<PortCallWire, "callId" | "method">,
  ): PortResultWire {
    const copy = JSON.parse(json(value));
    if (!resultValidator(copy)) throw new PortWireError("invalid_contract");
    if (copy.callId !== expected.callId || copy.method !== expected.method)
      throw new PortWireError("correlation_mismatch");
    if (copy.method === "artifacts.read" && copy.outcome.status === "ok")
      bytes(copy.outcome.output.bytesBase64);
    return copy;
  }
  return {
    encodeCall: (value: unknown): string => json(checkCall(value)),
    decodeCall: (value: string | Uint8Array): PortCallWire => checkCall(frame(value)),
    encodeResult: (value: unknown, expected: Pick<PortCallWire, "callId" | "method">): string =>
      json(checkResult(value, expected)),
    decodeResult: (
      value: string | Uint8Array,
      expected: Pick<PortCallWire, "callId" | "method">,
    ): PortResultWire => checkResult(frame(value), expected),
    encodeBytes(value: Uint8Array): string {
      if (!(value instanceof Uint8Array)) throw new PortWireError("invalid_frame");
      if (4 * Math.ceil(value.byteLength / 3) > maxBytes) throw new PortWireError("payload_limit");
      return Buffer.from(value).toString("base64");
    },
    decodeBytes: bytes,
  };
}
