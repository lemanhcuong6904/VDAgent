import { beforeEach, describe, expect, it } from "vitest";
import { ContextBudget } from "../../src/session/context-budget.js";

describe("ContextBudget - Edge Cases and Boundary Tests", () => {
  let budget: ContextBudget;

  beforeEach(() => {
    budget = new ContextBudget(100000, 1000);
  });

  describe("Margin Boundary Precision", () => {
    it("should block consumption leaving exactly margin (1000)", () => {
      budget.allocate("history", 99000);

      // Try to consume leaving exactly 1000
      // newRemaining = 100000 - 99000 = 1000
      // Check: 1000 <= 1000 -> true, so BLOCKED
      const result = budget.consume("history", 99000, "To margin boundary");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("margin");
      expect(budget.getRemaining()).toBe(100000); // Nothing consumed
    });

    it("should block consumption leaving less than margin", () => {
      budget.allocate("history", 99000);

      // Consume 97999, leaving 2001
      budget.consume("history", 97999, "Safe consumption");
      expect(budget.getRemaining()).toBe(2001);

      // Try to consume 1001 more (would leave 1000 exactly = margin)
      const result = budget.consume("history", 1001, "Would leave 1000");

      // Should fail: newRemaining = 1000 <= 1000 (at margin boundary)
      expect(result.ok).toBe(false);
      expect(result.reason).toContain("margin");
      expect(budget.getRemaining()).toBe(2001); // Unchanged
    });

    it("should allow consumption leaving margin + 1 (1001)", () => {
      budget.allocate("history", 98999);

      // Consume leaving 1001
      // newRemaining = 100000 - 98999 = 1001
      // Check: 1001 <= 1000 -> false, so ALLOWED
      const result = budget.consume("history", 98999, "Leave 1001");

      expect(result.ok).toBe(true);
      expect(budget.getRemaining()).toBe(1001);
      expect(budget.isOverBudget()).toBe(false); // 1001 <= 1000 is false
    });

    it("should correctly report isOverBudget at boundary", () => {
      budget.allocate("history", 98999);
      budget.consume("history", 98999, "Leave 1001");

      // At 1001 remaining
      expect(budget.getRemaining()).toBe(1001);
      expect(budget.isOverBudget()).toBe(false); // 1001 <= 1000 is false

      // Release 2, now at 1003
      budget.release("history", 2);
      expect(budget.getRemaining()).toBe(1003);
      expect(budget.isOverBudget()).toBe(false);
    });
  });

  describe("canConsume vs wouldExceedBudget vs consume Consistency", () => {
    it("should all agree when blocking at margin boundary", () => {
      budget.allocate("history", 99000);

      // Try amount that would leave exactly 1000
      const testAmount = 99000;

      const can = budget.canConsume("history", testAmount);
      const would = budget.wouldExceedBudget("history", testAmount);
      const result = budget.consume("history", testAmount, "Test");

      // All should agree: BLOCKED
      expect(can).toBe(false); // newRemaining > margin? 1000 > 1000 -> false
      expect(would).toBe(true); // !canConsume
      expect(result.ok).toBe(false); // newRemaining <= margin? 1000 <= 1000 -> true (blocked)
    });

    it("should all agree when blocking below margin", () => {
      budget.allocate("history", 99000);

      // Consume some first
      budget.consume("history", 97000, "Partial");

      // Try amount that would leave 500
      const testAmount = 2500;

      const can = budget.canConsume("history", testAmount);
      const would = budget.wouldExceedBudget("history", testAmount);
      const result = budget.consume("history", testAmount, "Test");

      // All should agree: BLOCKED
      expect(can).toBe(false);
      expect(would).toBe(true);
      expect(result.ok).toBe(false);
    });

    it("should all agree when allowing above margin", () => {
      budget.allocate("history", 98999);

      // Amount that would leave 1001
      const testAmount = 98999;

      const can = budget.canConsume("history", testAmount);
      const would = budget.wouldExceedBudget("history", testAmount);
      const result = budget.consume("history", testAmount, "Test");

      // All should agree: ALLOWED
      expect(can).toBe(true); // newRemaining > margin? 1001 > 1000 -> true
      expect(would).toBe(false); // !canConsume
      expect(result.ok).toBe(true); // newRemaining <= margin? 1001 <= 1000 -> false (allowed)
      expect(budget.getRemaining()).toBe(1001);
    });
  });

  describe("Arithmetic Edge Cases", () => {
    it("should handle zero consumption", () => {
      budget.allocate("history", 1000);

      const result = budget.consume("history", 0, "Zero");

      expect(result.ok).toBe(true);
      expect(budget.getRemaining()).toBe(100000);
    });

    it("should reject negative consumption", () => {
      budget.allocate("history", 1000);

      const result = budget.consume("history", -100, "Negative");

      expect(result.ok).toBe(false);
    });

    it("should reject non-integer consumption", () => {
      budget.allocate("history", 1000);

      const result = budget.consume("history", 100.5, "Decimal");

      expect(result.ok).toBe(false);
    });

    it("should reject NaN consumption", () => {
      budget.allocate("history", 1000);

      const result = budget.consume("history", NaN, "NaN");

      expect(result.ok).toBe(false);
    });

    it("should reject Infinity consumption", () => {
      budget.allocate("history", 1000);

      const result = budget.consume("history", Infinity, "Infinity");

      expect(result.ok).toBe(false);
    });

    it("should reject negative release", () => {
      budget.allocate("history", 1000);
      budget.consume("history", 500, "Test");

      const result = budget.release("history", -100);
      expect(result.ok).toBe(false);
    });
  });

  describe("Multiple Category Interactions", () => {
    it("should track remaining correctly across categories", () => {
      budget.allocate("history", 40000);
      budget.allocate("tools", 30000);
      budget.allocate("results", 29000);

      budget.consume("history", 40000, "Max history");
      expect(budget.getRemaining()).toBe(60000);

      budget.consume("tools", 30000, "Max tools");
      expect(budget.getRemaining()).toBe(30000);

      // Can consume up to 28999 from results (leaving 1001)
      budget.consume("results", 28999, "Near max results");
      expect(budget.getRemaining()).toBe(1001);
      expect(budget.isOverBudget()).toBe(false);

      // Try to consume 2 more - should fail (would leave 999)
      const result = budget.consume("results", 2, "Would violate");
      expect(result.ok).toBe(false);
    });

    it("should enforce global margin across categories", () => {
      // Available = 99000, allocate within that
      budget.allocate("history", 49500);
      budget.allocate("tools", 49500);

      // Consume all history
      budget.consume("history", 49500, "Consume all history");
      expect(budget.getRemaining()).toBe(50500);

      // From tools, can consume at most 49499 (leaving 1001)
      const result1 = budget.consume("tools", 49499, "Max safe tools");
      expect(result1.ok).toBe(true);
      expect(budget.getRemaining()).toBe(1001);

      // Try to consume 1 more - should fail (would leave 1000 = margin)
      const result2 = budget.consume("tools", 1, "Would hit margin");
      expect(result2.ok).toBe(false);
    });
  });

  describe("Release and Re-consumption", () => {
    it("should allow re-consumption after release", () => {
      budget.allocate("history", 98999);
      budget.consume("history", 98999, "Almost full");

      expect(budget.getRemaining()).toBe(1001);

      // Release some
      budget.release("history", 1000);
      expect(budget.getRemaining()).toBe(2001);

      // Now can consume more
      const result = budget.consume("history", 1000, "Re-consume");
      expect(result.ok).toBe(true);
      expect(budget.getRemaining()).toBe(1001);
    });

    it("should not allow release of more than consumed", () => {
      budget.allocate("history", 10000);
      budget.consume("history", 5000, "Partial");

      const result = budget.release("history", 6000);
      expect(result.ok).toBe(false);

      // Consumption should be unchanged
      const allocation = budget.getAllocation("history");
      expect(allocation!.consumed).toBe(5000);
    });
  });

  describe("Recommendation Generation", () => {
    it("should generate recommendations when approaching margin", () => {
      // Total available = 99000, need remaining = 2000
      // So total consumption = 98000
      // Allocations must sum to <= 99000

      budget.allocate("history", 25000);
      budget.consume("history", 25000, "History");

      budget.allocate("results", 15000);
      budget.consume("results", 15000, "Results");

      budget.allocate("output", 59000);
      budget.consume("output", 58000, "Large output");

      // Total allocated = 99000, consumed = 98000
      // Remaining = 100000 - 98000 = 2000 (exactly margin * 2)
      expect(budget.getRemaining()).toBe(2000);

      const status = budget.getStatus();

      // Recommendations should exist for history and results
      expect(status.recommendations.length).toBeGreaterThan(0);

      const historyRec = status.recommendations.find((r) => r.category === "history");
      expect(historyRec).toBeDefined();
      expect(historyRec!.action).toBe("compact");

      const resultsRec = status.recommendations.find((r) => r.category === "results");
      expect(resultsRec).toBeDefined();
      expect(resultsRec!.action).toBe("externalize");
    });

    it("should not generate recommendations when budget is healthy", () => {
      budget.allocate("history", 10000);
      budget.consume("history", 5000, "Moderate usage");

      // Remaining = 95000, which is > margin * 2 (2000)
      const status = budget.getStatus();

      expect(status.recommendations).toHaveLength(0);
    });
  });

  describe("Allocation Limits", () => {
    it("should not allow allocation exceeding available", () => {
      // Available = 100000 - 1000 = 99000
      const result = budget.allocate("history", 99001);

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Insufficient budget");
    });

    it("should allow allocation up to available", () => {
      const result = budget.allocate("history", 99000);

      expect(result.ok).toBe(true);
      expect(budget.getAvailable()).toBe(0);
    });

    it("should track available after multiple allocations", () => {
      budget.allocate("history", 30000);
      budget.allocate("tools", 20000);
      budget.allocate("results", 10000);

      // Available = 100000 - 1000 - 60000 = 39000
      expect(budget.getAvailable()).toBe(39000);
    });
  });

  describe("Over Budget Detection", () => {
    it("should detect when at or below margin", () => {
      budget.allocate("output", 98999);
      budget.consume("output", 98999, "Leave 1001");

      expect(budget.isOverBudget()).toBe(false); // 1001 <= 1000 is false

      // Now release 2 and try to consume 3
      budget.release("output", 2);
      expect(budget.getRemaining()).toBe(1003);

      const result = budget.consume("output", 3, "Would leave 1000");
      expect(result.ok).toBe(false); // Would leave exactly 1000
    });
  });
});
