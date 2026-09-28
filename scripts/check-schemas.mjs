import { createValidator, isMain, loadSchemas, schemaConventions } from "./lib/schema.mjs";

export function checkSchemas() {
  const schemas = loadSchemas();
  if (schemas.length === 0) throw new Error("No schemas found");
  const ajv = createValidator();
  for (const { name, schema } of schemas) {
    const errors = schemaConventions(schema);
    if (errors.length) throw new Error(`${name}: ${errors.join("; ")}`);
    ajv.addSchema(schema);
  }
  for (const { schema } of schemas) ajv.getSchema(schema.$id);
  return schemas.length;
}

if (isMain(import.meta.url)) {
  try {
    console.log(`Validated ${checkSchemas()} versioned schemas`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
