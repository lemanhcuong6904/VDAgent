/**
 * Context Budget System
 * Tracks token usage across tools/history/memory/results/output with margin
 * No silent mandatory drops - explicit decisions when budget exceeded
 */

/**
 * Budget category for tracking consumption
 */
export type BudgetCategory =
  | "tools" // Tool definitions and schemas
  | "history" // Conversation history
  | "memory" // Memory/context files
  | "results" // Tool execution results
  | "output" // Assistant output
  | "system" // System prompts and instructions
  | "margin"; // Safety margin for response

/**
 * Budget allocation entry
 */
export interface BudgetAllocation {
  category: BudgetCategory;
  allocated: number;
  consumed: number;
  reserved: number;
}

/**
 * Budget status
 */
export interface BudgetStatus {
  total: number;
  allocations: Map<BudgetCategory, BudgetAllocation>;
  remaining: number;
  overBudget: boolean;
  recommendations: BudgetRecommendation[];
}

/**
 * Recommendation when budget exceeded
 */
export interface BudgetRecommendation {
  category: BudgetCategory;
  action: "compact" | "drop_oldest" | "summarize" | "externalize";
  reason: string;
  estimatedSavings: number;
  priority: "low" | "medium" | "high";
}

/**
 * Budget event for tracking changes
 */
export interface BudgetEvent {
  timestamp: string;
  category: BudgetCategory;
  delta: number;
  consumed: number;
  remaining: number;
  reason: string;
}

/**
 * Context budget tracker
 */
export class ContextBudget {
  private totalBudget: number;
  private allocations: Map<BudgetCategory, BudgetAllocation> = new Map();
  private events: BudgetEvent[] = [];
  private minMargin: number;

  constructor(totalBudget: number, minMargin: number = 1000) {
    if (
      !Number.isSafeInteger(totalBudget) ||
      totalBudget < 1 ||
      !Number.isSafeInteger(minMargin) ||
      minMargin < 0 ||
      minMargin > totalBudget
    )
      throw new Error("Invalid context budget");
    this.totalBudget = totalBudget;
    this.minMargin = minMargin;

    // Initialize allocations
    this.initializeAllocations();
  }

  /**
   * Initialize budget allocations
   */
  private initializeAllocations(): void {
    const categories: BudgetCategory[] = [
      "tools",
      "history",
      "memory",
      "results",
      "output",
      "system",
      "margin",
    ];

    for (const category of categories) {
      this.allocations.set(category, {
        category,
        allocated: 0,
        consumed: 0,
        reserved: 0,
      });
    }

    // Reserve margin
    const marginAlloc = this.requireAllocation("margin");
    marginAlloc.reserved = this.minMargin;
  }

  /**
   * Allocate budget to a category
   */
  allocate(category: BudgetCategory, amount: number): { ok: boolean; reason?: string } {
    if (!Number.isSafeInteger(amount) || amount < 0)
      return { ok: false, reason: "Invalid budget amount" };
    if (category === "margin") {
      return { ok: false, reason: "Cannot directly allocate to margin" };
    }

    const available = this.getAvailable();
    if (amount > available) {
      return {
        ok: false,
        reason: `Insufficient budget: requested ${amount}, available ${available}`,
      };
    }

    const allocation = this.requireAllocation(category);
    allocation.allocated += amount;

    return { ok: true };
  }

  /**
   * Consume budget from a category
   */
  consume(
    category: BudgetCategory,
    amount: number,
    reason: string,
  ): { ok: boolean; reason?: string } {
    if (!Number.isSafeInteger(amount) || amount < 0)
      return { ok: false, reason: "Invalid budget amount" };
    if (category === "margin") {
      return { ok: false, reason: "Cannot consume from margin directly" };
    }

    const allocation = this.requireAllocation(category);
    const newConsumed = allocation.consumed + amount;

    // Check if exceeds allocated
    if (newConsumed > allocation.allocated) {
      return {
        ok: false,
        reason: `Would exceed ${category} allocation: ${newConsumed} > ${allocation.allocated}`,
      };
    }

    // Must leave MORE than the margin - margin itself cannot be touched
    const newRemaining = this.getRemaining() - amount;
    if (newRemaining <= this.minMargin) {
      return {
        ok: false,
        reason: `Would violate margin: remaining ${newRemaining} <= required ${this.minMargin}`,
      };
    }

    // Update consumption
    allocation.consumed = newConsumed;

    // Record event
    this.events.push({
      timestamp: new Date().toISOString(),
      category,
      delta: amount,
      consumed: newConsumed,
      remaining: this.getRemaining(),
      reason,
    });

    return { ok: true };
  }

  /**
   * Release consumed budget from a category
   */
  release(category: BudgetCategory, amount: number): { ok: boolean } {
    if (!Number.isSafeInteger(amount) || amount < 0) return { ok: false };
    const allocation = this.requireAllocation(category);

    if (amount > allocation.consumed) {
      return { ok: false };
    }

    allocation.consumed -= amount;

    return { ok: true };
  }

  /**
   * Get current budget status
   */
  getStatus(): BudgetStatus {
    const remaining = this.getRemaining();
    const overBudget = remaining < this.minMargin;

    // Generate recommendations if close to budget or over budget
    const recommendations = remaining <= this.minMargin * 2 ? this.generateRecommendations() : [];

    return {
      total: this.totalBudget,
      allocations: new Map([...this.allocations].map(([key, value]) => [key, { ...value }])),
      remaining,
      overBudget,
      recommendations,
    };
  }

  /**
   * Get total consumed across all categories
   */
  private getTotalConsumed(): number {
    let total = 0;
    for (const allocation of this.allocations.values()) {
      if (allocation.category !== "margin") {
        total += allocation.consumed;
      }
    }
    return total;
  }

  /**
   * Get remaining budget (including margin)
   */
  getRemaining(): number {
    const consumed = this.getTotalConsumed();
    return this.totalBudget - consumed;
  }

  /**
   * Get available budget (excluding margin)
   */
  getAvailable(): number {
    let allocated = 0;
    for (const entry of this.allocations.values()) allocated += entry.allocated;
    return this.totalBudget - this.minMargin - allocated;
  }

  /**
   * Check if budget allows consumption
   */
  canConsume(category: BudgetCategory, amount: number): boolean {
    if (category === "margin" || !Number.isSafeInteger(amount) || amount < 0) return false;
    const allocation = this.requireAllocation(category);
    const newConsumed = allocation.consumed + amount;

    if (newConsumed > allocation.allocated) {
      return false;
    }

    const newRemaining = this.getRemaining() - amount;
    return newRemaining > this.minMargin; // Must leave MORE than margin
  }

  /**
   * Generate recommendations when over budget
   */
  private generateRecommendations(): BudgetRecommendation[] {
    const recommendations: BudgetRecommendation[] = [];

    // Check each category for optimization opportunities
    const history = this.requireAllocation("history");
    if (history.consumed > 5000) {
      recommendations.push({
        category: "history",
        action: "compact",
        reason: "History consuming significant budget",
        estimatedSavings: Math.floor(history.consumed * 0.3),
        priority: "high",
      });
    }

    const results = this.requireAllocation("results");
    if (results.consumed > 3000) {
      recommendations.push({
        category: "results",
        action: "externalize",
        reason: "Large tool results should be externalized",
        estimatedSavings: Math.floor(results.consumed * 0.5),
        priority: "high",
      });
    }

    const memory = this.requireAllocation("memory");
    if (memory.consumed > 2000) {
      recommendations.push({
        category: "memory",
        action: "summarize",
        reason: "Memory files can be summarized",
        estimatedSavings: Math.floor(memory.consumed * 0.4),
        priority: "medium",
      });
    }

    const tools = this.requireAllocation("tools");
    if (tools.consumed > 4000) {
      recommendations.push({
        category: "tools",
        action: "drop_oldest",
        reason: "Too many tool definitions loaded",
        estimatedSavings: Math.floor(tools.consumed * 0.2),
        priority: "low",
      });
    }

    // Sort by priority
    recommendations.sort((a, b) => {
      const priorityOrder = { high: 0, medium: 1, low: 2 };
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    });

    return recommendations;
  }

  /**
   * Get consumption events
   */
  getEvents(): BudgetEvent[] {
    return this.events.map((event) => ({ ...event }));
  }

  /**
   * Get events for a specific category
   */
  getCategoryEvents(category: BudgetCategory): BudgetEvent[] {
    return this.getEvents().filter((e) => e.category === category);
  }

  /**
   * Reset allocation for a category
   */
  reset(category: BudgetCategory): void {
    if (category === "margin") {
      return;
    }

    const allocation = this.requireAllocation(category);
    allocation.allocated = 0;
    allocation.consumed = 0;
  }

  /**
   * Get allocation for category
   */
  getAllocation(category: BudgetCategory): BudgetAllocation | undefined {
    const value = this.allocations.get(category);
    return value ? { ...value } : undefined;
  }

  private requireAllocation(category: BudgetCategory): BudgetAllocation {
    const allocation = this.allocations.get(category);
    if (!allocation) throw new Error(`Unknown budget category: ${category}`);
    return allocation;
  }

  /**
   * Check if over budget with margin
   */
  isOverBudget(): boolean {
    return this.getRemaining() <= this.minMargin;
  }

  /**
   * Predict if consuming would exceed budget
   */
  wouldExceedBudget(category: BudgetCategory, amount: number): boolean {
    return !this.canConsume(category, amount);
  }

  /**
   * Get summary statistics
   */
  getSummary(): {
    total: number;
    consumed: number;
    remaining: number;
    margin: number;
    utilizationPercent: number;
    categories: Array<{ category: BudgetCategory; consumed: number; percent: number }>;
  } {
    const consumed = this.getTotalConsumed();
    const remaining = this.getRemaining();
    const utilizationPercent = (consumed / this.totalBudget) * 100;

    const categories = Array.from(this.allocations.values())
      .filter((a) => a.category !== "margin" && a.category !== "system")
      .map((a) => ({
        category: a.category,
        consumed: a.consumed,
        percent: (a.consumed / this.totalBudget) * 100,
      }))
      .sort((a, b) => b.consumed - a.consumed);

    return {
      total: this.totalBudget,
      consumed,
      remaining,
      margin: this.minMargin,
      utilizationPercent,
      categories,
    };
  }
}
