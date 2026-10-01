export interface RateLimitOptions {
  maxRequests: number;
  windowMs: number;
  maxKeys?: number;
}

interface Bucket {
  count: number;
  resetAt: number;
}

/** Bounded per-process guard; use a gateway/distributed limiter for multi-replica deployments. */
export class RateLimiter {
  private readonly buckets = new Map<string, Bucket>();

  constructor(private readonly options: RateLimitOptions) {}

  allow(key: string, now = Date.now()): boolean {
    this.prune(now);
    const current = this.buckets.get(key);
    if (!current || current.resetAt <= now) {
      this.buckets.set(key, { count: 1, resetAt: now + this.options.windowMs });
      return true;
    }
    if (current.count >= this.options.maxRequests) return false;
    current.count += 1;
    return true;
  }

  private prune(now: number): void {
    for (const [key, bucket] of this.buckets) {
      if (bucket.resetAt <= now) this.buckets.delete(key);
    }
    const maxKeys = this.options.maxKeys ?? 10_000;
    while (this.buckets.size > maxKeys) {
      const oldest = this.buckets.keys().next().value as string | undefined;
      if (!oldest) break;
      this.buckets.delete(oldest);
    }
  }
}

export function requestKey(input: { ip?: string; tenant?: string; route: string }): string {
  return `${input.tenant ?? "anonymous"}:${input.ip ?? "unknown"}:${input.route}`;
}

/**
 * Resolve a client address without trusting user supplied forwarding headers by default.
 * A proxy may opt in only after it has been configured as trusted at the deployment boundary.
 */
export function clientAddress(input: {
  remoteAddress?: string;
  forwardedFor?: string;
  trustProxy?: boolean;
}): string {
  if (input.trustProxy && input.forwardedFor) {
    const forwarded = input.forwardedFor
      .split(",")
      .map((value) => value.trim())
      .find(Boolean);
    if (forwarded) return forwarded;
  }
  return input.remoteAddress?.trim() || "unknown";
}
