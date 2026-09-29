import { describe, expect, it, vi } from "vitest";
import { OutboxPublisher } from "../src/outbox.js";

describe("outbox publisher", () => {
  it("claims and marks committed events after dispatch", async () => {
    const queries: string[] = [];
    const pool = {
      async query(sql: string) {
        queries.push(sql);
        if (sql.includes("WITH picked")) {
          return {
            rows: [{ id: 1, run_id: "run-1", event_type: "run.status", payload: {}, attempts: 0 }],
          };
        }
        return { rows: [] };
      },
    } as never;
    const dispatch = vi.fn(async () => undefined);
    const publisher = new OutboxPublisher(pool, dispatch, { publisherId: "publisher-1" });

    await expect(publisher.publishOnce()).resolves.toBe(1);
    expect(dispatch).toHaveBeenCalledOnce();
    expect(queries.some((query) => query.includes("published_at = now()"))).toBe(true);
  });

  it("releases a failed claim for a later retry", async () => {
    const pool = {
      async query(sql: string) {
        if (sql.includes("WITH picked")) {
          return {
            rows: [{ id: 1, run_id: "run-1", event_type: "run.status", payload: {}, attempts: 0 }],
          };
        }
        return { rows: [] };
      },
    } as never;
    const publisher = new OutboxPublisher(
      pool,
      async () => {
        throw new Error("temporary sink failure");
      },
      { publisherId: "publisher-1" },
    );

    await expect(publisher.publishOnce()).resolves.toBe(0);
  });
});
