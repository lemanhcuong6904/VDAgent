import { beforeEach, describe, expect, it } from "vitest";
import { ContextBudget } from "../../src/session/context-budget.js";

describe("ContextBudget", () => {
  let budget: ContextBudget;

  beforeEach(() => {
    budget = new ContextBudget(100000, 1000);
  });

  describe("Initialization", () => {
    it("rejects invalid arithmetic and protects snapshots from mutation", () => {
      for (const amount of [-1, NaN, Infinity, 0.5]) {
        expect(() => new ContextBudget(amount)).toThrow();
        expect(budget.allocate("history", amount).ok).toBe(false);
        expect(budget.consume("history", amount, "invalid").ok).toBe(false);
        expect(budget.release("history", amount).ok).toBe(false);
        expect(budget.canConsume("history", amount)).toBe(false);
      }
      expect(budget.allocate("history", 98000).ok).toBe(true);
      expect(budget.allocate("tools", 2000).ok).toBe(false);
      budget.getAllocation("history")!.allocated = 1000000;
      budget.getStatus().allocations.get("history")!.allocated = 1000000;
      expect(budget.getAllocation("history")!.allocated).toBe(98000);
      expect(budget.getAvailable()).toBe(1000);
    });
    it("should initialize with total budget and margin", () => {
      const status = budget.getStatus();

      expect(status.total).toBe(100000);
      expect(status.remaining).toBe(100000);
      expect(status.overBudget).toBe(false);
    });

    it("should reserve margin", () => {
      const marginAlloc = budget.getAllocation("margin");

      expect(marginAlloc).toBeDefined();
      expect(marginAlloc!.reserved).toBe(1000);
    });

    it("should have available budget excluding margin", () => {
      const available = budget.getAvailable();

      expect(available).toBe(99000); // 100000 - 1000
    });
  });

  describe("Budget Allocation", () => {
    it("should allocate budget to category", () => {
      const result = budget.allocate("history", 10000);

      expect(result.ok).toBe(true);

      const allocation = budget.getAllocation("history");
      expect(allocation!.allocated).toBe(10000);
    });

    it("should fail to allocate more than available", () => {
      const result = budget.allocate("history", 100000);

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Insufficient budget");
    });

    it("should not allow direct allocation to margin", () => {
      const result = budget.allocate("margin", 500);

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Cannot directly allocate to margin");
    });

    it("should allocate to multiple categories", () => {
      budget.allocate("history", 20000);
      budget.allocate("tools", 15000);
      budget.allocate("results", 10000);

      expect(budget.getAllocation("history")!.allocated).toBe(20000);
      expect(budget.getAllocation("tools")!.allocated).toBe(15000);
      expect(budget.getAllocation("results")!.allocated).toBe(10000);
    });
  });

  describe("Budget Consumption", () => {
    beforeEach(() => {
      budget.allocate("history", 20000);
      budget.allocate("tools", 15000);
    });

    it("should consume budget from category", () => {
      const result = budget.consume("history", 5000, "Added messages");

      expect(result.ok).toBe(true);

      const allocation = budget.getAllocation("history");
      expect(allocation!.consumed).toBe(5000);
    });

    it("should fail to consume more than allocated", () => {
      const result = budget.consume("history", 25000, "Too much");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Would exceed history allocation");
    });

    it("should track consumption events", () => {
      budget.consume("history", 5000, "Added messages");
      budget.consume("tools", 3000, "Loaded tools");

      const events = budget.getEvents();

      expect(events).toHaveLength(2);
      expect(events[0].category).toBe("history");
      expect(events[0].delta).toBe(5000);
      expect(events[1].category).toBe("tools");
      expect(events[1].delta).toBe(3000);
    });

    it("should update remaining budget", () => {
      budget.consume("history", 5000, "Test");

      const remaining = budget.getRemaining();
      expect(remaining).toBe(95000);
    });

    it("should check if can consume", () => {
      const can1 = budget.canConsume("history", 10000);
      expect(can1).toBe(true);

      const can2 = budget.canConsume("history", 30000);
      expect(can2).toBe(false);
    });

    it("should prevent consuming beyond margin", () => {
      budget.allocate("output", 99000);

      const result = budget.consume("output", 99000, "Large output");

      expect(result.ok).toBe(false);
    });
  });

  describe("Budget Release", () => {
    beforeEach(() => {
      budget.allocate("results", 10000);
      budget.consume("results", 5000, "Tool results");
    });

    it("should release consumed budget", () => {
      const result = budget.release("results", 3000);

      expect(result.ok).toBe(true);

      const allocation = budget.getAllocation("results");
      expect(allocation!.consumed).toBe(2000);
    });

    it("should fail to release more than consumed", () => {
      const result = budget.release("results", 8000);

      expect(result.ok).toBe(false);
    });
  });

  describe("Budget Status", () => {
    it("should report budget status", () => {
      budget.allocate("history", 20000);
      budget.allocate("tools", 15000);
      budget.consume("history", 10000, "Messages");
      budget.consume("tools", 5000, "Tool defs");

      const status = budget.getStatus();

      expect(status.total).toBe(100000);
      expect(status.remaining).toBe(85000);
      expect(status.overBudget).toBe(false);
      expect(status.allocations.size).toBeGreaterThan(0);
    });

    it("should reject excess without changing consumed budget", () => {
      expect(budget.allocate("history", 99500).ok).toBe(false);
      expect(budget.consume("history", 99500, "Too much history").ok).toBe(false);

      const status = budget.getStatus();

      expect(status.overBudget).toBe(false);
      expect(status.remaining).toBe(100000);
    });

    it("should get category events", () => {
      budget.allocate("history", 10000);
      budget.consume("history", 3000, "Event 1");
      budget.consume("history", 2000, "Event 2");
      budget.allocate("tools", 5000);
      budget.consume("tools", 1000, "Event 3");

      const historyEvents = budget.getCategoryEvents("history");

      expect(historyEvents).toHaveLength(2);
      expect(historyEvents.every((e) => e.category === "history")).toBe(true);
    });
  });

  describe("Budget Recommendations", () => {
    it("should recommend compaction for large history", () => {
      budget.allocate("history", 6000);
      budget.consume("history", 6000, "Many messages");

      budget.allocate("output", 93000);
      budget.consume("output", 92999, "Force near budget");

      // Remaining = 100000 - 98999 = 1001, triggers recommendations
      expect(budget.getRemaining()).toBe(1001);

      const status = budget.getStatus();

      expect(status.recommendations.length).toBeGreaterThan(0);

      const historyRec = status.recommendations.find((r) => r.category === "history");
      expect(historyRec).toBeDefined();
      expect(historyRec!.action).toBe("compact");
    });

    it("should recommend externalization for large results", () => {
      budget.allocate("results", 4000);
      budget.consume("results", 4000, "Large results");

      budget.allocate("output", 95000);
      budget.consume("output", 94999, "Force near budget");

      // Remaining = 100000 - 98999 = 1001
      expect(budget.getRemaining()).toBe(1001);

      const status = budget.getStatus();

      const resultsRec = status.recommendations.find((r) => r.category === "results");
      expect(resultsRec).toBeDefined();
      expect(resultsRec!.action).toBe("externalize");
    });

    it("should recommend summarization for large memory", () => {
      budget.allocate("memory", 3000);
      budget.consume("memory", 2500, "Memory files");

      budget.allocate("output", 96000);
      budget.consume("output", 95999, "Force near budget");

      // Remaining = 100000 - 98499 = 1501
      expect(budget.getRemaining()).toBe(1501);

      const status = budget.getStatus();

      const memoryRec = status.recommendations.find((r) => r.category === "memory");
      expect(memoryRec).toBeDefined();
      expect(memoryRec!.action).toBe("summarize");
    });

    it("should prioritize recommendations", () => {
      budget.allocate("history", 6000);
      budget.consume("history", 6000, "History");
      budget.allocate("results", 4000);
      budget.consume("results", 4000, "Results");

      budget.allocate("output", 89000);
      budget.consume("output", 88999, "Force near budget");

      // Total consumed = 98999, remaining = 1001
      expect(budget.getRemaining()).toBe(1001);

      const status = budget.getStatus();

      expect(status.recommendations.length).toBeGreaterThan(0);

      // High priority should come first
      const priorities = status.recommendations.map((r) => r.priority);
      const highIndex = priorities.indexOf("high");
      const lowIndex = priorities.indexOf("low");

      if (highIndex >= 0 && lowIndex >= 0) {
        expect(highIndex).toBeLessThan(lowIndex);
      }
    });
  });

  describe("Budget Prediction", () => {
    beforeEach(() => {
      budget.allocate("history", 20000);
      budget.consume("history", 10000, "Current");
    });

    it("should predict if would exceed budget", () => {
      const would1 = budget.wouldExceedBudget("history", 5000);
      expect(would1).toBe(false);

      const would2 = budget.wouldExceedBudget("history", 15000);
      expect(would2).toBe(true);
    });

    it("should consider margin in prediction", () => {
      expect(budget.allocate("output", 79000).ok).toBe(true);
      expect(budget.consume("output", 79000, "Large").ok).toBe(true);

      const would = budget.wouldExceedBudget("history", 11000);
      expect(would).toBe(true);
    });
  });

  describe("Category Reset", () => {
    it("should reset category allocation and consumption", () => {
      budget.allocate("history", 10000);
      budget.consume("history", 5000, "Test");

      budget.reset("history");

      const allocation = budget.getAllocation("history");
      expect(allocation!.allocated).toBe(0);
      expect(allocation!.consumed).toBe(0);
    });

    it("should not reset margin", () => {
      const beforeMargin = budget.getAllocation("margin");

      budget.reset("margin");

      const afterMargin = budget.getAllocation("margin");
      expect(afterMargin!.reserved).toBe(beforeMargin!.reserved);
    });
  });

  describe("Summary Statistics", () => {
    it("should provide summary statistics", () => {
      budget.allocate("history", 20000);
      budget.consume("history", 15000, "History");
      budget.allocate("tools", 10000);
      budget.consume("tools", 8000, "Tools");

      const summary = budget.getSummary();

      expect(summary.total).toBe(100000);
      expect(summary.consumed).toBe(23000);
      expect(summary.remaining).toBe(77000);
      expect(summary.margin).toBe(1000);
      expect(summary.utilizationPercent).toBe(23);
      expect(summary.categories.length).toBeGreaterThanOrEqual(2); // At least history and tools
    });

    it("should sort categories by consumption", () => {
      budget.allocate("history", 20000);
      budget.consume("history", 15000, "History");
      budget.allocate("tools", 10000);
      budget.consume("tools", 5000, "Tools");

      const summary = budget.getSummary();

      expect(summary.categories[0].consumed).toBeGreaterThanOrEqual(summary.categories[1].consumed);
    });
  });

  describe("Over Budget Scenarios", () => {
    it("should handle approaching margin", () => {
      budget.allocate("output", 99000);
      budget.consume("output", 98000, "Large output");

      expect(budget.isOverBudget()).toBe(false);

      // Can consume 999 more (leaving 1001)
      budget.consume("output", 999, "More output");

      expect(budget.isOverBudget()).toBe(false);
      expect(budget.getRemaining()).toBe(1001);
      expect(budget.consume("output", 1, "Would hit margin").ok).toBe(false);
    });

    it("should track consumption near limit", () => {
      budget.allocate("history", 50000);
      budget.allocate("tools", 30000);
      budget.allocate("results", 19000);

      budget.consume("history", 50000, "Max history");
      budget.consume("tools", 30000, "Max tools");
      budget.consume("results", 17999, "Near max results");

      const remaining = budget.getRemaining();
      expect(remaining).toBe(2001);
      expect(budget.isOverBudget()).toBe(false);

      const canConsume = budget.canConsume("results", 1000);
      expect(canConsume).toBe(true); // Would leave 1001
    });
  });

  describe("Event Tracking", () => {
    it("should record timestamps in events", () => {
      budget.allocate("history", 10000);
      budget.consume("history", 5000, "Test event");

      const events = budget.getEvents();

      expect(events[0].timestamp).toBeDefined();
      expect(new Date(events[0].timestamp).getTime()).toBeLessThanOrEqual(Date.now());
    });

    it("should track remaining in events", () => {
      budget.allocate("history", 10000);
      budget.consume("history", 3000, "Event 1");
      budget.consume("history", 2000, "Event 2");

      const events = budget.getEvents();

      expect(events[0].remaining).toBe(97000);
      expect(events[1].remaining).toBe(95000);
    });
  });
});
