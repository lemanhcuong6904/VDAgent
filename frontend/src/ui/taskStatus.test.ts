import { describe, expect, it } from "vitest";
import type { TaskDTO } from "../api/types";
import { taskStatusLabel } from "./taskStatus";

const task = (status: TaskDTO["status"], outcome: TaskDTO["outcome"]): TaskDTO => ({
  id: "t_1", root_agent: "orchestrator", status, outcome, created_at: "", finished_at: null,
});

describe("taskStatusLabel (WS7 F-03/F-04)", () => {
  it("never shows a partial or interrupted run as plainly completed", () => {
    expect(taskStatusLabel(task("completed", "partial"))).toBe("completed · partial");
    expect(taskStatusLabel(task("failed", "interrupted"))).toBe("failed · interrupted");
  });
  it("keeps plain statuses when the outcome adds nothing", () => {
    expect(taskStatusLabel(task("completed", "completed"))).toBe("completed");
    expect(taskStatusLabel(task("failed", "failed"))).toBe("failed");
    expect(taskStatusLabel(task("running", null))).toBe("running");
  });
});
