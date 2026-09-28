/** Strict bounded JSON encoding for local test doubles, without invoking getters/toJSON. */
export function encodeBoundedJson(value: unknown, maxBytes: number, maxDepth = 64): string {
  if (
    !Number.isSafeInteger(maxBytes) ||
    maxBytes < 1 ||
    !Number.isSafeInteger(maxDepth) ||
    maxDepth < 0
  )
    throw new Error("invalid_json_limits");
  const ancestors = new Set<object>();
  const parts: string[] = [];
  let size = 0;
  const encoder = new TextEncoder();
  const append = (text: string) => {
    size += encoder.encode(text).byteLength;
    if (size > maxBytes) throw new Error("json_byte_limit");
    parts.push(text);
  };
  function visit(item: unknown, depth: number): void {
    if (depth > maxDepth) throw new Error("json_depth_limit");
    if (item === null || typeof item === "boolean") {
      append(String(item));
      return;
    }
    if (typeof item === "string") {
      if (item.length > maxBytes) throw new Error("json_byte_limit");
      append(JSON.stringify(item));
      return;
    }
    if (typeof item === "number" && Number.isFinite(item)) {
      append(JSON.stringify(item));
      return;
    }
    if (typeof item !== "object" || item === null) throw new Error("invalid_json_value");
    if (ancestors.has(item)) throw new Error("cyclic_json");
    const array = Array.isArray(item);
    if (
      !array &&
      Object.getPrototypeOf(item) !== Object.prototype &&
      Object.getPrototypeOf(item) !== null
    )
      throw new Error("non_plain_json_object");
    if (Object.getOwnPropertySymbols(item).length) throw new Error("symbol_json_key");
    ancestors.add(item);
    try {
      const descriptors = Object.getOwnPropertyDescriptors(item);
      if (array) {
        const length = (item as unknown[]).length;
        if (length > maxBytes) throw new Error("json_byte_limit");
        if (Object.keys(descriptors).length !== length + 1)
          throw new Error("non_json_array_properties");
        append("[");
        for (let index = 0; index < length; index++) {
          const descriptor = descriptors[String(index)];
          if (!descriptor || !("value" in descriptor)) throw new Error("sparse_or_accessor_array");
          if (index) append(",");
          visit(descriptor.value, depth + 1);
        }
        append("]");
      } else {
        append("{");
        let count = 0;
        for (const [key, descriptor] of Object.entries(descriptors)) {
          if (!("value" in descriptor) || !descriptor.enumerable)
            throw new Error("non_json_property");
          if (count++) append(",");
          if (key.length > maxBytes) throw new Error("json_byte_limit");
          append(JSON.stringify(key));
          append(":");
          visit(descriptor.value, depth + 1);
        }
        append("}");
      }
    } finally {
      ancestors.delete(item);
    }
  }
  visit(value, 0);
  return parts.join("");
}
