import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";
import { readBoundedFile, sha256 } from "./receipt.mjs";

export function repositoryFiles(root) {
  const paths = execFileSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    {
      cwd: root,
      encoding: "utf8",
      maxBuffer: 8 * 1024 * 1024,
    },
  )
    .split("\0")
    .filter(Boolean);
  return [...new Set(paths)].filter((path) => existsSync(resolve(root, path))).sort();
}

export function sourceFile(path, source) {
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
  if (file.parseDiagnostics.length) throw new Error(`${path}: cannot parse source`);
  return file;
}

export function analyzeModule(path, source) {
  const file = sourceFile(path, source);
  const result = { path, exports: [], imports: [], registrations: [], tests: [], conditions: [] };
  const line = (node) => file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
  const literal = (node) =>
    node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))
      ? node.text
      : null;
  function dependency(node, expression, kind) {
    result.imports.push({
      line: line(node),
      kind,
      specifier: literal(expression),
      fingerprint: sha256(node.getText(file)),
    });
  }
  for (const node of file.statements) {
    if (ts.isExportDeclaration(node)) {
      if (node.exportClause && ts.isNamedExports(node.exportClause)) {
        result.exports.push(
          ...node.exportClause.elements.map((element) => ({
            name: element.name.text,
            line: line(element),
            kind: "reexport",
          })),
        );
      } else
        result.exports.push({
          name: node.exportClause?.name?.text ?? "*",
          line: line(node),
          kind: "reexport",
        });
    } else if (ts.isExportAssignment(node)) {
      result.exports.push({ name: "default", line: line(node), kind: "assignment" });
    } else if (
      ts.getModifiers(node)?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)
    ) {
      if (ts.isVariableStatement(node)) {
        for (const declaration of node.declarationList.declarations) {
          result.exports.push({
            name: declaration.name.getText(file),
            line: line(declaration),
            kind: "variable",
          });
        }
      } else
        result.exports.push({
          name: node.name?.text ?? "default",
          line: line(node),
          kind: ts.SyntaxKind[node.kind],
        });
    }
  }
  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      if (node.moduleSpecifier)
        dependency(
          node,
          node.moduleSpecifier,
          ts.isImportDeclaration(node) ? "import" : "reexport",
        );
    } else if (
      ts.isImportEqualsDeclaration(node) &&
      ts.isExternalModuleReference(node.moduleReference)
    ) {
      dependency(node, node.moduleReference.expression, "require");
    } else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)) {
      dependency(node, node.argument.literal, "import-type");
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(file);
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword || callee === "require") {
        dependency(node, node.arguments[0], callee === "require" ? "require" : "dynamic-import");
      }
      if (
        /\.(register|registerAgentManifest)$/.test(callee) ||
        /^(defineAgent|createAnalyticsAgent)$/.test(callee)
      ) {
        result.registrations.push({
          line: line(node),
          callee,
          literalId: literal(node.arguments[0]),
        });
      }
      if (/^(it|test|describe)(\.|$)/.test(callee) && literal(node.arguments[0]) !== null) {
        result.tests.push({ line: line(node), callee, title: literal(node.arguments[0]) });
      }
      if (/\.(skipIf|runIf|skip|todo)$/.test(callee)) {
        result.conditions.push({
          line: line(node),
          callee,
          condition: node.arguments[0]?.getText(file) ?? null,
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return result;
}

export function readSource(root, path) {
  return readBoundedFile(root, path).toString("utf8");
}
