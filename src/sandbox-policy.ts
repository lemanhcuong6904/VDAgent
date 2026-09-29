/**
 * Sandbox Policy
 * M9.5: Resource/egress/filesystem/credential-reference policy and lifecycle states
 *
 * A sandbox session is created from a policy, moves through explicit lifecycle
 * states, and is torn down deterministically. Every request is checked against
 * the policy before it reaches the runner.
 */

/** Lifecycle states for a sandbox session (M9.5) */
export type SandboxLifecycleState =
  | "pending"
  | "provisioning"
  | "ready"
  | "busy"
  | "draining"
  | "stopped"
  | "failed";

const LIFECYCLE_TRANSITIONS: Record<SandboxLifecycleState, readonly SandboxLifecycleState[]> = {
  pending: ["provisioning", "failed"],
  provisioning: ["ready", "failed"],
  ready: ["busy", "draining", "failed"],
  busy: ["ready", "draining", "failed"],
  draining: ["stopped", "failed"],
  stopped: [],
  failed: [],
};

export const TERMINAL_SANDBOX_STATES: readonly SandboxLifecycleState[] = ["stopped", "failed"];

/** Filesystem access mode for a mounted path */
export type FilesystemMode = "read-only" | "read-write" | "none";

export interface FilesystemMount {
  /** Absolute container path */
  path: string;
  mode: FilesystemMode;
  /** If true the host may seed content here before the session starts */
  seedable?: boolean;
}

export interface EgressRule {
  /** Hostname or glob-ish suffix, e.g. "api.internal" or "*.example.com" */
  host: string;
  ports?: readonly number[];
  protocol?: "http" | "https" | "tcp";
}

/** Pointer to a credential held by the platform; never the secret itself */
export interface CredentialReference {
  /** Logical name the sandbox sees, e.g. "WAREHOUSE_TOKEN" */
  name: string;
  /** Opaque id resolved host-side at call time */
  reference: string;
  /** Ports the credential may be injected into */
  scopes: readonly string[];
  /** If true the host will not expose the value to the process env, only via broker */
  brokered?: boolean;
}

export interface ResourcePolicy {
  memoryMb: number;
  cpuShares: number;
  diskMb: number;
  /** Wall-clock limit for a single execution */
  timeoutMs: number;
  /** Max concurrent executions inside one session */
  maxParallel: number;
}

export interface SandboxPolicy {
  resources: ResourcePolicy;
  /** Absolute paths the sandbox may see. Anything else is inaccessible. */
  filesystem: readonly FilesystemMount[];
  /** Egress allow-list. Empty means no network egress at all. */
  egress: readonly EgressRule[];
  credentials: readonly CredentialReference[];
  /** Whether the process may write anywhere outside the listed mounts */
  allowUnlistedWrites?: boolean;
}

export const DEFAULT_SANDBOX_POLICY: SandboxPolicy = {
  resources: {
    memoryMb: 512,
    cpuShares: 512,
    diskMb: 1024,
    timeoutMs: 60_000,
    maxParallel: 1,
  },
  filesystem: [],
  egress: [],
  credentials: [],
  allowUnlistedWrites: false,
};

export interface PolicyViolation {
  rule: "resource" | "egress" | "filesystem" | "credential";
  message: string;
  detail?: Record<string, unknown>;
}

export class SandboxPolicyError extends Error {
  constructor(public readonly violations: readonly PolicyViolation[]) {
    super(
      `Sandbox policy violation: ${violations.map((v) => `${v.rule}: ${v.message}`).join("; ")}`,
    );
    this.name = "SandboxPolicyError";
  }
}

export interface SandboxExecutionAttempt {
  command: string;
  args?: readonly string[];
  /** Requests larger than the policy ceiling are clamped, not rejected */
  resources?: Partial<ResourcePolicy>;
  /** Paths the process intends to read or write */
  paths?: readonly { path: string; write?: boolean }[];
  /** Hosts the process intends to contact */
  egress?: readonly { host: string; port?: number }[];
  /** Credential names the process intends to resolve */
  credentials?: readonly string[];
}

/** Match a host against an egress rule, supporting a leading "*." wildcard */
function hostMatches(rule: string, host: string): boolean {
  if (rule === host) return true;
  if (rule.startsWith("*.")) {
    const suffix = rule.slice(1); // ".example.com"
    return host.endsWith(suffix);
  }
  return false;
}

/** Match a path against a mount, honouring trailing-slash directory prefixes */
function pathMatches(mount: string, path: string): boolean {
  if (path === mount) return true;
  const prefix = mount.endsWith("/") ? mount : `${mount}/`;
  return path.startsWith(prefix);
}

/** Clamp requested resources to the policy ceiling */
export function clampResources(
  policy: ResourcePolicy,
  requested: Partial<ResourcePolicy> | undefined,
): ResourcePolicy {
  return {
    memoryMb: Math.min(requested?.memoryMb ?? policy.memoryMb, policy.memoryMb),
    cpuShares: Math.min(requested?.cpuShares ?? policy.cpuShares, policy.cpuShares),
    diskMb: Math.min(requested?.diskMb ?? policy.diskMb, policy.diskMb),
    timeoutMs: Math.min(requested?.timeoutMs ?? policy.timeoutMs, policy.timeoutMs),
    maxParallel: Math.min(requested?.maxParallel ?? policy.maxParallel, policy.maxParallel),
  };
}

/**
 * Evaluate an execution attempt against a policy.
 * Returns the violations found; an empty array means the attempt is allowed.
 */
export function evaluateSandboxPolicy(
  policy: SandboxPolicy,
  attempt: SandboxExecutionAttempt,
): PolicyViolation[] {
  const violations: PolicyViolation[] = [];

  // Resources are clamped rather than rejected, but a request that exceeds the
  // ceiling by more than 4x is a signal the caller is misconfigured.
  if (attempt.resources) {
    const ceiling = policy.resources;
    const overMemory =
      attempt.resources.memoryMb !== undefined && attempt.resources.memoryMb > ceiling.memoryMb * 4;
    const overDisk =
      attempt.resources.diskMb !== undefined && attempt.resources.diskMb > ceiling.diskMb * 4;
    if (overMemory) {
      violations.push({
        rule: "resource",
        message: `requested memory ${attempt.resources.memoryMb}Mb far exceeds policy ceiling ${ceiling.memoryMb}Mb`,
        detail: { requested: attempt.resources.memoryMb, ceiling: ceiling.memoryMb },
      });
    }
    if (overDisk) {
      violations.push({
        rule: "resource",
        message: `requested disk ${attempt.resources.diskMb}Mb far exceeds policy ceiling ${ceiling.diskMb}Mb`,
        detail: { requested: attempt.resources.diskMb, ceiling: ceiling.diskMb },
      });
    }
    if (
      attempt.resources.maxParallel !== undefined &&
      attempt.resources.maxParallel > ceiling.maxParallel
    ) {
      violations.push({
        rule: "resource",
        message: `requested parallelism ${attempt.resources.maxParallel} exceeds policy maximum ${ceiling.maxParallel}`,
        detail: { requested: attempt.resources.maxParallel, ceiling: ceiling.maxParallel },
      });
    }
  }

  // Filesystem: every path must fall under a matching mount with a usable mode.
  for (const access of attempt.paths ?? []) {
    const mount = policy.filesystem.find((m) => pathMatches(m.path, access.path));
    if (!mount || mount.mode === "none") {
      violations.push({
        rule: "filesystem",
        message: `path ${access.path} is not within any permitted mount`,
        detail: { path: access.path },
      });
      continue;
    }
    if (access.write && mount.mode !== "read-write") {
      violations.push({
        rule: "filesystem",
        message: `path ${access.path} is mounted ${mount.mode} and cannot be written`,
        detail: { path: access.path, mode: mount.mode },
      });
    }
  }

  // Egress: host must match an allow-list rule, and the port if specified.
  for (const request of attempt.egress ?? []) {
    const rule = policy.egress.find((r) => hostMatches(r.host, request.host));
    if (!rule) {
      violations.push({
        rule: "egress",
        message: `host ${request.host} is not on the egress allow-list`,
        detail: { host: request.host },
      });
      continue;
    }
    if (rule.ports && request.port !== undefined && !rule.ports.includes(request.port)) {
      violations.push({
        rule: "egress",
        message: `port ${request.port} is not permitted for host ${request.host}`,
        detail: { host: request.host, port: request.port, allowed: rule.ports },
      });
    }
  }

  // Credentials: must be declared by the policy and used within its scopes.
  for (const name of attempt.credentials ?? []) {
    const reference = policy.credentials.find((c) => c.name === name);
    if (!reference) {
      violations.push({
        rule: "credential",
        message: `credential ${name} is not declared by the policy`,
        detail: { name },
      });
    } else if (reference.reference.trim() === "") {
      violations.push({
        rule: "credential",
        message: `credential ${name} has an empty reference`,
        detail: { name },
      });
    }
  }

  return violations;
}

/** Throw a SandboxPolicyError when the attempt is not permitted */
export function assertSandboxPolicy(policy: SandboxPolicy, attempt: SandboxExecutionAttempt): void {
  const violations = evaluateSandboxPolicy(policy, attempt);
  if (violations.length > 0) {
    throw new SandboxPolicyError(violations);
  }
}

/** Validate a policy itself; catches mistakes before a session is created */
export function validateSandboxPolicy(policy: SandboxPolicy): PolicyViolation[] {
  const violations: PolicyViolation[] = [];

  if (policy.resources.memoryMb <= 0) {
    violations.push({ rule: "resource", message: "memoryMb must be positive" });
  }
  if (policy.resources.cpuShares <= 0) {
    violations.push({ rule: "resource", message: "cpuShares must be positive" });
  }
  if (policy.resources.diskMb <= 0) {
    violations.push({ rule: "resource", message: "diskMb must be positive" });
  }
  if (policy.resources.timeoutMs <= 0) {
    violations.push({ rule: "resource", message: "timeoutMs must be positive" });
  }
  if (policy.resources.maxParallel <= 0) {
    violations.push({ rule: "resource", message: "maxParallel must be positive" });
  }

  for (const mount of policy.filesystem) {
    if (!mount.path.startsWith("/")) {
      violations.push({
        rule: "filesystem",
        message: `mount path ${mount.path} must be absolute`,
        detail: { path: mount.path },
      });
    }
    if (mount.path === "/" && mount.mode === "read-write") {
      violations.push({
        rule: "filesystem",
        message: "read-write mount of the container root is not permitted",
        detail: { path: mount.path },
      });
    }
  }

  for (const rule of policy.egress) {
    if (rule.host === "*" || rule.host === "0.0.0.0" || rule.host === "") {
      violations.push({
        rule: "egress",
        message: `egress rule ${JSON.stringify(rule.host)} would allow all hosts`,
        detail: { host: rule.host },
      });
    }
  }

  for (const credential of policy.credentials) {
    if (credential.reference.trim() === "") {
      violations.push({
        rule: "credential",
        message: `credential ${credential.name} must carry a non-empty reference`,
        detail: { name: credential.name },
      });
    }
    if (credential.scopes.length === 0) {
      violations.push({
        rule: "credential",
        message: `credential ${credential.name} must declare at least one scope`,
        detail: { name: credential.name },
      });
    }
    // A reference that looks like an inline secret is a policy design error.
    if (/^(sk-|ghp_|xox[baprs]-|AKIA)/.test(credential.reference)) {
      violations.push({
        rule: "credential",
        message: `credential ${credential.name} carries an inline secret; store a reference instead`,
        detail: { name: credential.name },
      });
    }
  }

  return violations;
}

/** True when the lifecycle state may move to `next` */
export function canTransition(from: SandboxLifecycleState, to: SandboxLifecycleState): boolean {
  return LIFECYCLE_TRANSITIONS[from].includes(to);
}

export function isTerminalSandboxState(state: SandboxLifecycleState): boolean {
  return TERMINAL_SANDBOX_STATES.includes(state);
}

/** Small state machine wrapper so callers cannot skip lifecycle steps */
export class SandboxLifecycle {
  private current: SandboxLifecycleState = "pending";

  constructor(
    private readonly onTransition?: (
      from: SandboxLifecycleState,
      to: SandboxLifecycleState,
    ) => void,
  ) {}

  get state(): SandboxLifecycleState {
    return this.current;
  }

  get terminal(): boolean {
    return isTerminalSandboxState(this.current);
  }

  transition(to: SandboxLifecycleState): SandboxLifecycleState {
    if (!canTransition(this.current, to)) {
      throw new Error(`Invalid sandbox transition ${this.current} -> ${to}`);
    }
    const from = this.current;
    this.current = to;
    this.onTransition?.(from, to);
    return this.current;
  }
}
