import { describe, expect, it } from "vitest";
import { clientAddress, RateLimiter, requestKey } from "../src/rate-limit.js";

describe("rate limiter", () => {
  it("bounds requests per key and resets the window", () => {
    const limiter = new RateLimiter({ maxRequests: 2, windowMs: 1000 });
    const key = requestKey({ ip: "127.0.0.1", route: "/api/tasks" });
    expect(limiter.allow(key, 100)).toBe(true);
    expect(limiter.allow(key, 200)).toBe(true);
    expect(limiter.allow(key, 300)).toBe(false);
    expect(limiter.allow(key, 1100)).toBe(true);
  });

  it("does not trust a spoofed forwarding header unless a proxy is explicitly trusted", () => {
    expect(
      clientAddress({ remoteAddress: "10.0.0.8", forwardedFor: "attacker", trustProxy: false }),
    ).toBe("10.0.0.8");
    expect(
      clientAddress({ remoteAddress: "10.0.0.8", forwardedFor: "client, proxy", trustProxy: true }),
    ).toBe("client");
  });
});
