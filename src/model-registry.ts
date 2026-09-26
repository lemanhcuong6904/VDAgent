export interface ModelProfile {
  id: string;
  provider: string;
  model: string;
  capabilities: readonly string[];
  contextLimit?: number;
  maxOutputTokens?: number;
  timeoutMs?: number;
  retryable?: boolean;
  costInputPerMillion?: number;
  costOutputPerMillion?: number;
}

export class ModelRegistry {
  private readonly profiles = new Map<string, ModelProfile>();

  constructor(private readonly configuredDefault?: string) {}

  register(profile: ModelProfile): void {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(profile.id)) {
      throw new Error(`Invalid model profile id '${profile.id}'`);
    }
    if (!profile.provider.trim() || !profile.model.trim()) {
      throw new Error(`Model profile '${profile.id}' needs a provider and model`);
    }
    if (this.profiles.has(profile.id)) {
      throw new Error(`Model profile '${profile.id}' is already registered`);
    }
    this.profiles.set(profile.id, {
      ...profile,
      capabilities: [...profile.capabilities],
    });
  }

  get(id: string): ModelProfile | undefined {
    return this.profiles.get(id);
  }

  require(id: string): ModelProfile {
    const profile = this.get(id);
    if (!profile) throw new Error(`Unknown model profile '${id}'`);
    return profile;
  }

  list(): ModelProfile[] {
    return [...this.profiles.values()].map((profile) => ({
      ...profile,
      capabilities: [...profile.capabilities],
    }));
  }

  findByCapability(capability: string): ModelProfile[] {
    const normalized = capability.trim().toLowerCase();
    return this.list().filter((profile) =>
      profile.capabilities.some((value) => value.toLowerCase() === normalized),
    );
  }

  defaultProfile(): ModelProfile | undefined {
    const configured =
      this.configuredDefault?.trim() || process.env.PI_DEFAULT_MODEL_PROFILE?.trim();
    if (configured) return this.get(configured);
    const first = this.profiles.values().next();
    return first.done ? undefined : first.value;
  }
}

export function createDefaultModelRegistry(env: NodeJS.ProcessEnv = process.env): ModelRegistry {
  const registry = new ModelRegistry(env.PI_DEFAULT_MODEL_PROFILE);
  const configuredProfiles = env.MODEL_PROFILES_JSON?.trim();
  if (configuredProfiles) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(configuredProfiles);
    } catch (error) {
      throw new Error(
        `MODEL_PROFILES_JSON is invalid: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (!Array.isArray(parsed)) throw new Error("MODEL_PROFILES_JSON must be a JSON array");
    for (const profile of parsed) {
      if (!isModelProfile(profile))
        throw new Error("MODEL_PROFILES_JSON contains an invalid profile");
      registry.register(profile);
    }
  }
  const provider = env.PI_DEFAULT_PROVIDER ?? "openai";
  const model = env.PI_DEFAULT_MODEL ?? "gpt-4o-mini";
  if (!registry.get("default")) {
    registry.register({
      id: "default",
      provider,
      model,
      capabilities: ["general", "tool-calling", "structured-output"],
    });
  }
  return registry;
}

function isModelProfile(value: unknown): value is ModelProfile {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const profile = value as Partial<ModelProfile>;
  return (
    typeof profile.id === "string" &&
    typeof profile.provider === "string" &&
    typeof profile.model === "string" &&
    Array.isArray(profile.capabilities) &&
    profile.capabilities.every((capability) => typeof capability === "string")
  );
}
