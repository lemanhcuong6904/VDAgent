import type { Pool } from "pg";

export interface OutboxEvent {
  id: number;
  run_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  attempts: number;
}

export interface OutboxPublisherOptions {
  publisherId: string;
  leaseMs?: number;
  batchSize?: number;
  pollMs?: number;
}

export type OutboxDispatcher = (event: OutboxEvent) => Promise<void>;

/** Delivers committed outbox rows without holding a database transaction during I/O. */
export class OutboxPublisher {
  private stopped = true;
  private timer: NodeJS.Timeout | undefined;

  constructor(
    private readonly pool: Pool,
    private readonly dispatch: OutboxDispatcher,
    private readonly options: OutboxPublisherOptions,
  ) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.loop();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
  }

  async publishOnce(): Promise<number> {
    const events = await this.claim();
    let published = 0;
    for (const event of events) {
      try {
        await this.dispatch(event);
        await this.pool.query(
          `UPDATE platform_outbox_events
           SET published_at = now(), claimed_by = NULL, claimed_until = NULL
           WHERE id = $1 AND claimed_by = $2 AND published_at IS NULL`,
          [event.id, this.options.publisherId],
        );
        published += 1;
      } catch (error) {
        await this.pool.query(
          `UPDATE platform_outbox_events
           SET attempts = attempts + 1, last_error = $3, claimed_by = NULL, claimed_until = NULL
           WHERE id = $1 AND claimed_by = $2 AND published_at IS NULL`,
          [
            event.id,
            this.options.publisherId,
            error instanceof Error ? error.message : String(error),
          ],
        );
      }
    }
    return published;
  }

  private async claim(): Promise<OutboxEvent[]> {
    const leaseMs = Math.max(1_000, this.options.leaseMs ?? 30_000);
    const batchSize = Math.min(100, Math.max(1, this.options.batchSize ?? 25));
    const result = await this.pool.query<OutboxEvent>(
      `WITH picked AS (
         SELECT id FROM platform_outbox_events
         WHERE published_at IS NULL
           AND (claimed_until IS NULL OR claimed_until < now())
         ORDER BY id
         FOR UPDATE SKIP LOCKED LIMIT $1
       )
       UPDATE platform_outbox_events AS event
       SET claimed_by = $2, claimed_until = now() + ($3 * interval '1 millisecond')
       FROM picked
       WHERE event.id = picked.id
       RETURNING event.id, event.run_id, event.event_type, event.payload, event.attempts`,
      [batchSize, this.options.publisherId, leaseMs],
    );
    return result.rows;
  }

  private async loop(): Promise<void> {
    while (!this.stopped) {
      const count = await this.publishOnce().catch(() => 0);
      if (!count) {
        await new Promise<void>((resolve) => {
          this.timer = setTimeout(resolve, this.options.pollMs ?? 250);
        });
      }
    }
  }
}
