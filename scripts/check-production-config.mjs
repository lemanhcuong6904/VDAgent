import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(resolve(root, path), "utf8");
const failures = [];
const requireText = (text, pattern, description) => {
  if (!pattern.test(text)) failures.push(description);
};

const dockerfile = read("Dockerfile");
requireText(
  dockerfile,
  /FROM node@sha256:[^\s]+ AS runtime/,
  "runtime image must pin node by digest",
);
requireText(
  dockerfile,
  /(?:FROM|--from=)ghcr\.io\/astral-sh\/uv@sha256:/,
  "uv source must be digest pinned",
);
requireText(dockerfile, /USER node\b/, "runtime image must run as the node user");
requireText(dockerfile, /ENV NODE_ENV=production\b/, "runtime image must set NODE_ENV=production");
requireText(
  dockerfile,
  /apt-get install[^\n]*bubblewrap/,
  "runtime image must include the isolated agent launcher",
);
requireText(
  dockerfile,
  /COPY --from=build --chown=node:node \/app\/agent-seccomp\.bpf \.\/agent-seccomp\.bpf/,
  "runtime image must include the agent child seccomp filter",
);
requireText(
  dockerfile,
  /CMD \["node", "dist\/server\.js"\]/,
  "api image must run compiled JavaScript",
);
requireText(
  dockerfile,
  /CMD \["node", "dist\/worker\.js"\]/,
  "worker image must run compiled JavaScript",
);
if (/CMD \["pnpm", "(?:start|worker)"\]/.test(dockerfile)) {
  failures.push("runtime image must not use the TypeScript pnpm launcher");
}

const compose = read("docker-compose.yml");
for (const service of ["api", "worker"]) {
  const block =
    new RegExp(`\\n  ${service}:([\\s\\S]*?)(?=\\n  [a-z-]+:|$)`).exec(compose)?.[1] ?? "";
  requireText(block, /target: (?:api|worker)/, `${service} must use the compiled runtime target`);
  requireText(block, /user: ["']?1000:1000/, `${service} must not run as root`);
  requireText(block, /read_only: true/, `${service} root filesystem must be read-only`);
  requireText(block, /no-new-privileges:true/, `${service} must disable privilege escalation`);
  requireText(
    block,
    /seccomp=\.\/docker\/seccomp-bubblewrap\.json/,
    `${service} must use the restricted bubblewrap seccomp profile`,
  );
  requireText(block, /cap_drop:[\s\S]*?- ALL/, `${service} must drop Linux capabilities`);
  requireText(block, /NODE_ENV: production/, `${service} must set NODE_ENV=production`);
  requireText(block, /AGENT_ISOLATION_MODE:/, `${service} must configure external agent isolation`);
}
const apiBlock = /\n {2}api:([\s\S]*?)(?=\n {2}worker:)/.exec(compose)?.[1] ?? "";
if (apiBlock.includes("/var/run/docker.sock"))
  failures.push("api must not mount the Docker socket");
const workerBlock = /\n {2}worker:([\s\S]*?)(?=\n {2}otel-collector:)/.exec(compose)?.[1] ?? "";
// A Docker socket is equivalent to host-level control. Only deployments that
// explicitly mount it may configure the supplementary group; the default
// production Compose profile disables the Docker sandbox entirely.
if (/\/var\/run\/docker\.sock/.test(workerBlock)) {
  requireText(
    workerBlock,
    /DOCKER_GID/,
    "worker Docker socket access must use an explicit group id",
  );
} else {
  requireText(
    workerBlock,
    /SANDBOX_PROVIDER:\s*none/,
    "worker must disable the Docker sandbox when no socket is mounted",
  );
}
for (const service of ["api", "worker"]) {
  const block =
    new RegExp(`\\n  ${service}:([\\s\\S]*?)(?=\\n  [a-z-]+:|$)`).exec(compose)?.[1] ?? "";
  requireText(
    block,
    /AGENT_TOOL_MODULES:\s*\$\{AGENT_TOOL_MODULES:-dist\/tools\/warehouse\.js\}/,
    `${service} must default AGENT_TOOL_MODULES to emitted JavaScript`,
  );
}
const envExample = read(".env.example");
if (/^AGENT_TOOL_MODULES=src\/tools\/warehouse\.ts$/m.test(envExample)) {
  failures.push(".env.example must not point the production default at TypeScript source");
}

const seccomp = JSON.parse(read("docker/seccomp-bubblewrap.json"));
const hasRule = (name, test) =>
  seccomp.syscalls.some((rule) => rule.names.includes(name) && test(rule));
if (seccomp.defaultAction !== "SCMP_ACT_ERRNO") {
  failures.push("bubblewrap seccomp profile must fail closed by default");
}
if (
  !hasRule("clone", (rule) =>
    rule.args?.some(
      (arg) =>
        arg.index === 0 &&
        arg.value === 4_294_967_295 &&
        arg.valueTwo === 2_114_060_305 &&
        arg.op === "SCMP_CMP_MASKED_EQ",
    ),
  )
) {
  failures.push("bubblewrap seccomp profile must allow only the namespace clone used for setup");
}
if (
  !hasRule("unshare", (rule) =>
    rule.args?.some(
      (arg) =>
        arg.index === 0 &&
        arg.value === 4_294_967_295 &&
        arg.valueTwo === 268_435_456 &&
        arg.op === "SCMP_CMP_MASKED_EQ",
    ),
  )
) {
  failures.push("bubblewrap seccomp profile must limit unshare to a user namespace");
}
for (const syscall of ["mount", "umount2", "pivot_root"]) {
  if (!hasRule(syscall, (rule) => rule.action === "SCMP_ACT_ALLOW" && !rule.args)) {
    failures.push(`bubblewrap seccomp profile must allow ${syscall} for sandbox setup`);
  }
}

const packageJson = JSON.parse(read("package.json"));
for (const dependency of ["ajv", "ajv-formats"]) {
  if (!packageJson.dependencies?.[dependency] || packageJson.devDependencies?.[dependency]) {
    failures.push(`${dependency} must be a production dependency`);
  }
}
if (packageJson.scripts?.["build:server"] !== "tsc -p tsconfig.build.json") {
  failures.push("build:server must emit the compiled server");
}

if (failures.length) {
  process.stderr.write(`Production config check failed:\n- ${failures.join("\n- ")}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write("Production config: OK\n");
}
