import { describe, expect, it } from "vitest";
import { composerPlaceholder } from "./composerHint";

describe("composerPlaceholder", () => {
  it("invites questions about the fetched data in the Data chat", () => {
    const text = composerPlaceholder("data");
    expect(text).toContain("Hỏi thêm về dữ liệu vừa lấy");
    expect(text).toContain("Vì sao lấy căn này?");
    expect(text).toContain("Enter");
  });

  it("keeps the generic prompt for every other agent", () => {
    expect(composerPlaceholder("orchestrator")).toBe("Message orchestrator…  (Enter to send, Shift+Enter for a new line)");
    expect(composerPlaceholder("insight")).toContain("Message insight");
  });
});
