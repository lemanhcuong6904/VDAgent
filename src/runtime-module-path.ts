/** Resolve source-style module settings to emitted JavaScript in the production image. */
export function runtimeModuleSpecifier(
  specifier: string,
  production = process.env.NODE_ENV === "production",
) {
  if (!production || specifier.startsWith("file:")) return specifier;

  const normalized = specifier.replaceAll("\\", "/");
  const match = /(^|\/)src\/(.+)\.(?:ts|tsx)$/.exec(normalized);
  if (!match) return specifier;

  const replacement = `${match[1]}dist/${match[2]}.js`;
  return normalized.slice(0, match.index) + replacement;
}
