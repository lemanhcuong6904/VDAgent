/**
 * File Reader Tool
 * Read tool implementation using ToolPort interface
 */

import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ToolHandler } from "../tool-pool.js";
import type { ToolManifest } from "../tool-port.js";

export const fileReaderManifest: ToolManifest = {
  id: "file-reader",
  version: "1.0.0",
  displayName: "File Reader",
  description: "Read file contents from the filesystem",
  inputSchema: {
    type: "object",
    properties: {
      path: {
        type: "string",
        description: "File path to read",
      },
      encoding: {
        type: "string",
        enum: ["utf8", "base64"],
        description: "File encoding (default: utf8)",
      },
    },
    required: ["path"],
  },
  outputSchema: {
    type: "object",
    properties: {
      content: {
        type: "string",
        description: "File contents",
      },
      path: {
        type: "string",
        description: "Resolved file path",
      },
      size: {
        type: "number",
        description: "File size in bytes",
      },
    },
    required: ["content", "path", "size"],
  },
  effectClass: "read",
  idempotent: true,
  limits: {
    maxInputBytes: 1000,
    maxOutputBytes: 1000000, // 1MB
    timeoutMs: 5000,
  },
  sensitivity: "internal",
  tags: ["filesystem", "io"],
};

export interface FileReaderInput {
  path: string;
  encoding?: "utf8" | "base64";
}

export interface FileReaderOutput {
  content: string;
  path: string;
  size: number;
}

export const fileReaderHandler: ToolHandler<FileReaderInput, FileReaderOutput> = async (
  input,
  _context,
) => {
  const { path: filePath, encoding = "utf8" } = input;

  // Validate path (basic security check)
  if (!filePath || filePath.includes("..")) {
    throw new Error("Invalid file path");
  }

  // Resolve absolute path
  const absolutePath = path.resolve(filePath);

  try {
    // Check file exists and get stats
    const stats = await fs.stat(absolutePath);

    if (!stats.isFile()) {
      throw new Error("Path is not a file");
    }

    // Read file content
    const content =
      encoding === "base64"
        ? (await fs.readFile(absolutePath)).toString("base64")
        : await fs.readFile(absolutePath, "utf8");

    return {
      content,
      path: absolutePath,
      size: stats.size,
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(`File not found: ${filePath}`);
    }
    if ((error as NodeJS.ErrnoException).code === "EACCES") {
      throw new Error(`Permission denied: ${filePath}`);
    }
    throw error;
  }
};
