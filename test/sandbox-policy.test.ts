/**
 * Sandbox Policy Tests
 * M9.5: Resource/egress/filesystem/credential policy and lifecycle state tests
 */

import { describe, expect, it } from "vitest";
import {
  assertSandboxPolicy,
  canTransition,
  clampResources,
  DEFAULT_SANDBOX_POLICY,
  evaluateSandboxPolicy,
  isTerminalSandboxState,
  type SandboxExecutionAttempt,
  SandboxLifecycle,
  type SandboxLifecycleState,
  type SandboxPolicy,
  SandboxPolicyError,
  TERMINAL_SANDBOX_STATES,
  validateSandboxPolicy,
} from "../src/sandbox-policy.js";

describe("M9.5: Sandbox Lifecycle States", () => {
  it("should start in pending state", () => {
    const lifecycle = new SandboxLifecycle();
    expect(lifecycle.state).toBe("pending");
    expect(lifecycle.terminal).toBe(false);
  });

  it("should allow valid transitions", () => {
    const lifecycle = new SandboxLifecycle();
    expect(lifecycle.state).toBe("pending");

    lifecycle.transition("provisioning");
    expect(lifecycle.state).toBe("provisioning");

    lifecycle.transition("ready");
    expect(lifecycle.state).toBe("ready");

    lifecycle.transition("busy");
    expect(lifecycle.state).toBe("busy");

    lifecycle.transition("draining");
    expect(lifecycle.state).toBe("draining");

    lifecycle.transition("stopped");
    expect(lifecycle.state).toBe("stopped");
    expect(lifecycle.terminal).toBe(true);
  });

  it("should reject invalid transitions", () => {
    const lifecycle = new SandboxLifecycle();
    expect(() => lifecycle.transition("ready")).toThrow("Invalid sandbox transition");
    expect(() => lifecycle.transition("stopped")).toThrow("Invalid sandbox transition");
  });

  it("should allow transition to failed from any non-terminal state", () => {
    const states: SandboxLifecycleState[] = [
      "pending",
      "provisioning",
      "ready",
      "busy",
      "draining",
    ];
    for (const state of states) {
      expect(canTransition(state, "failed")).toBe(true);
    }
  });

  it("should not allow transitions from terminal states", () => {
    expect(canTransition("stopped", "ready")).toBe(false);
    expect(canTransition("failed", "ready")).toBe(false);
    expect(TERMINAL_SANDBOX_STATES).toContain("stopped");
    expect(TERMINAL_SANDBOX_STATES).toContain("failed");
  });

  it("should call onTransition callback", () => {
    const transitions: Array<[SandboxLifecycleState, SandboxLifecycleState]> = [];
    const lifecycle = new SandboxLifecycle((from, to) => transitions.push([from, to]));

    lifecycle.transition("provisioning");
    lifecycle.transition("ready");

    expect(transitions).toEqual([
      ["pending", "provisioning"],
      ["provisioning", "ready"],
    ]);
  });

  it("should identify terminal states correctly", () => {
    expect(isTerminalSandboxState("stopped")).toBe(true);
    expect(isTerminalSandboxState("failed")).toBe(true);
    expect(isTerminalSandboxState("ready")).toBe(false);
    expect(isTerminalSandboxState("busy")).toBe(false);
  });
});

describe("M9.5: Resource Policy", () => {
  it("should clamp requested resources to policy ceiling", () => {
    const policy = {
      memoryMb: 512,
      cpuShares: 256,
      diskMb: 1024,
      timeoutMs: 30_000,
      maxParallel: 2,
    };

    const clamped = clampResources(policy, {
      memoryMb: 1024, // exceeds ceiling
      cpuShares: 128, // within ceiling
      diskMb: 2048, // exceeds ceiling
    });

    expect(clamped.memoryMb).toBe(512);
    expect(clamped.cpuShares).toBe(128);
    expect(clamped.diskMb).toBe(1024);
    expect(clamped.timeoutMs).toBe(30_000);
  });

  it("should use policy defaults when not requested", () => {
    const policy = {
      memoryMb: 512,
      cpuShares: 256,
      diskMb: 1024,
      timeoutMs: 30_000,
      maxParallel: 2,
    };

    const clamped = clampResources(policy, {});

    expect(clamped).toEqual(policy);
  });

  it("should reject grossly excessive resource requests", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      resources: {
        memoryMb: 512,
        cpuShares: 256,
        diskMb: 1024,
        timeoutMs: 30_000,
        maxParallel: 2,
      },
    };

    const attempt: SandboxExecutionAttempt = {
      command: "test",
      resources: {
        memoryMb: 4096, // 8x ceiling
        diskMb: 8192, // 8x ceiling
      },
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(2);
    expect(violations[0].rule).toBe("resource");
    expect(violations[0].message).toContain("far exceeds");
    expect(violations[1].rule).toBe("resource");
  });

  it("should reject maxParallel exceeding ceiling", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      resources: {
        memoryMb: 512,
        cpuShares: 256,
        diskMb: 1024,
        timeoutMs: 30_000,
        maxParallel: 2,
      },
    };

    const attempt: SandboxExecutionAttempt = {
      command: "test",
      resources: { maxParallel: 5 },
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("resource");
    expect(violations[0].message).toContain("parallelism");
  });
});

describe("M9.5: Filesystem Policy", () => {
  it("should allow reads from read-only mounts", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/data", mode: "read-only" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "cat",
      paths: [{ path: "/data/file.txt", write: false }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });

  it("should allow writes to read-write mounts", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/workspace", mode: "read-write" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "write",
      paths: [{ path: "/workspace/output.txt", write: true }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });

  it("should reject writes to read-only mounts", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/data", mode: "read-only" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "write",
      paths: [{ path: "/data/output.txt", write: true }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("filesystem");
    expect(violations[0].message).toContain("read-only");
  });

  it("should reject access to unlisted paths", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/allowed", mode: "read-only" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "cat",
      paths: [{ path: "/etc/passwd", write: false }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("filesystem");
    expect(violations[0].message).toContain("not within any permitted mount");
  });

  it("should match subdirectories under mounts", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/data", mode: "read-write" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "write",
      paths: [
        { path: "/data/subdir/file1.txt", write: true },
        { path: "/data/deep/nested/file2.txt", write: true },
      ],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });

  it("should reject paths with mode none", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/blocked", mode: "none" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "cat",
      paths: [{ path: "/blocked/file.txt", write: false }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("filesystem");
  });
});

describe("M9.5: Egress Policy", () => {
  it("should allow egress to allow-listed hosts", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      egress: [{ host: "api.internal", ports: [443] }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "curl",
      egress: [{ host: "api.internal", port: 443 }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });

  it("should reject egress to unlisted hosts", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      egress: [{ host: "api.internal" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "curl",
      egress: [{ host: "evil.com" }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("egress");
    expect(violations[0].message).toContain("not on the egress allow-list");
  });

  it("should support wildcard host matching", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      egress: [{ host: "*.example.com" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "curl",
      egress: [
        { host: "api.example.com" },
        { host: "cdn.example.com" },
        { host: "auth.example.com" },
      ],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });

  it("should reject ports not in the allow-list", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      egress: [{ host: "api.internal", ports: [443, 8443] }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "curl",
      egress: [{ host: "api.internal", port: 80 }],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("egress");
    expect(violations[0].message).toContain("port");
  });

  it("should allow any port when ports list is undefined", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      egress: [{ host: "api.internal" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "curl",
      egress: [
        { host: "api.internal", port: 80 },
        { host: "api.internal", port: 443 },
        { host: "api.internal", port: 8080 },
      ],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });
});

describe("M9.5: Credential Policy", () => {
  it("should allow declared credentials", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      credentials: [
        {
          name: "DB_TOKEN",
          reference: "arn:aws:secretsmanager:us-east-1:123456789012:secret:prod/db",
          scopes: ["warehouse"],
        },
      ],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "query",
      credentials: ["DB_TOKEN"],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);
    expect(violations).toHaveLength(0);
  });

  it("should reject undeclared credentials", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      credentials: [],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "query",
      credentials: ["SECRET_KEY"],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("credential");
    expect(violations[0].message).toContain("not declared");
  });

  it("should reject credentials with empty references", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      credentials: [
        {
          name: "EMPTY_CRED",
          reference: "  ",
          scopes: ["test"],
        },
      ],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "test",
      credentials: ["EMPTY_CRED"],
    };

    const violations = evaluateSandboxPolicy(policy, attempt);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("credential");
    expect(violations[0].message).toContain("empty reference");
  });
});

describe("M9.5: Policy Validation", () => {
  it("should accept valid policies", () => {
    const policy: SandboxPolicy = {
      resources: {
        memoryMb: 512,
        cpuShares: 256,
        diskMb: 1024,
        timeoutMs: 30_000,
        maxParallel: 2,
      },
      filesystem: [
        { path: "/data", mode: "read-only" },
        { path: "/workspace", mode: "read-write" },
      ],
      egress: [{ host: "api.internal", ports: [443] }, { host: "*.cdn.example.com" }],
      credentials: [
        {
          name: "API_KEY",
          reference: "arn:secret:api-key",
          scopes: ["tools"],
        },
      ],
    };

    const violations = validateSandboxPolicy(policy);
    expect(violations).toHaveLength(0);
  });

  it("should reject negative resource values", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      resources: {
        memoryMb: -1,
        cpuShares: 0,
        diskMb: -512,
        timeoutMs: 0,
        maxParallel: -1,
      },
    };

    const violations = validateSandboxPolicy(policy);
    expect(violations.length).toBeGreaterThan(0);
    expect(violations.every((v) => v.rule === "resource")).toBe(true);
  });

  it("should reject relative filesystem paths", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "relative/path", mode: "read-only" }],
    };

    const violations = validateSandboxPolicy(policy);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("filesystem");
    expect(violations[0].message).toContain("must be absolute");
  });

  it("should reject read-write root mount", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/", mode: "read-write" }],
    };

    const violations = validateSandboxPolicy(policy);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("filesystem");
    expect(violations[0].message).toContain("root");
  });

  it("should reject overly permissive egress rules", () => {
    const badHosts = ["*", "0.0.0.0", ""];

    for (const host of badHosts) {
      const policy: SandboxPolicy = {
        ...DEFAULT_SANDBOX_POLICY,
        egress: [{ host }],
      };

      const violations = validateSandboxPolicy(policy);
      expect(violations).toHaveLength(1);
      expect(violations[0].rule).toBe("egress");
      expect(violations[0].message).toContain("allow all hosts");
    }
  });

  it("should reject credentials without scopes", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      credentials: [
        {
          name: "NO_SCOPES",
          reference: "arn:secret:test",
          scopes: [],
        },
      ],
    };

    const violations = validateSandboxPolicy(policy);

    expect(violations).toHaveLength(1);
    expect(violations[0].rule).toBe("credential");
    expect(violations[0].message).toContain("at least one scope");
  });

  it("should reject credentials with inline secrets", () => {
    const inlineSecrets = [
      "sk-abc123",
      "ghp_tokenhere",
      "xoxb-slacktoken",
      ["AKIA", "IOSFODNN7EXAMPLE"].join(""),
    ];

    for (const secret of inlineSecrets) {
      const policy: SandboxPolicy = {
        ...DEFAULT_SANDBOX_POLICY,
        credentials: [
          {
            name: "BAD_CRED",
            reference: secret,
            scopes: ["test"],
          },
        ],
      };

      const violations = validateSandboxPolicy(policy);
      expect(violations.length).toBeGreaterThan(0);
      expect(violations.some((v) => v.message.includes("inline secret"))).toBe(true);
    }
  });
});

describe("M9.5: Policy Enforcement", () => {
  it("should throw SandboxPolicyError on violations", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/allowed", mode: "read-only" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "rm",
      paths: [{ path: "/etc/passwd", write: true }],
    };

    expect(() => assertSandboxPolicy(policy, attempt)).toThrow(SandboxPolicyError);

    try {
      assertSandboxPolicy(policy, attempt);
    } catch (error) {
      expect(error).toBeInstanceOf(SandboxPolicyError);
      const policyError = error as SandboxPolicyError;
      expect(policyError.violations).toHaveLength(1);
      expect(policyError.violations[0].rule).toBe("filesystem");
    }
  });

  it("should not throw when policy is satisfied", () => {
    const policy: SandboxPolicy = {
      ...DEFAULT_SANDBOX_POLICY,
      filesystem: [{ path: "/workspace", mode: "read-write" }],
    };

    const attempt: SandboxExecutionAttempt = {
      command: "write",
      paths: [{ path: "/workspace/output.txt", write: true }],
    };

    expect(() => assertSandboxPolicy(policy, attempt)).not.toThrow();
  });
});
