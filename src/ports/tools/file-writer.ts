/**
 * File Writer Tool
 * Write tool implementation using ToolPort interface
 */

import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ToolHandler } from "../tool-pool.js";
import type { ToolManifest } from "../tool-port.js";

export const fileWriterManifest: ToolManifest = {
  id: "file-writer",
  version: "1.0.0",
  displayName: "File Writer",
  description: "Write content to a file on the filesystem",
  inputSchema: {
    type: "object",
    properties: {
      path: {
        type: "string",
        description: "File path to write",
      },
      content: {
        type: "string",
        description: "Content to write",
      },
      encoding: {
        type: "string",
        enum: ["utf8", "base64"],
        description: "Content encoding (default: utf8)",
      },
      createDirs: {
        type: "boolean",
        description: "Create parent directories if needed (default: false)",
      },
    },
    required: ["path", "content"],
  },
  outputSchema: {
    type: "object",
    properties: {
      path: {
        type: "string",
        description: "Written file path",
      },
      bytesWritten: {
        type: "number",
        description: "Number of bytes written",
      },
    },
    required: ["path", "bytesWritten"],
  },
  effectClass: "write",
  idempotent: true, // Writing same content to same path is idempotent
  limits: {
    maxInputBytes: 1100000, // ~1MB + overhead
    maxOutputBytes: 1000,
    timeoutMs: 10000,
  },
  sensitivity: "internal",
  tags: ["filesystem", "io"],
};

export interface FileWriterInput {
  path: string;
  content: string;
  encoding?: "utf8" | "base64";
  createDirs?: boolean;
}

export interface FileWriterOutput {
  path: string;
  bytesWritten: number;
}

export const fileWriterHandler: ToolHandler<FileWriterInput, FileWriterOutput> = async (
  input,
  _context,
) => {
  const { path: filePath, content, encoding = "utf8", createDirs = false } = input;

  // Validate path (basic security check)
  if (!filePath || filePath.includes("..")) {
    throw new Error("Invalid file path");
  }

  // Resolve absolute path
  const absolutePath = path.resolve(filePath);

  try {
    // Create parent directories if requested
    if (createDirs) {
      const dirPath = path.dirname(absolutePath);
      await fs.mkdir(dirPath, { recursive: true });
    }

    // Decode content if base64
    const buffer =
      encoding === "base64" ? Buffer.from(content, "base64") : Buffer.from(content, "utf8");

    // Write file
    await fs.writeFile(absolutePath, buffer);

    return {
      path: absolutePath,
      bytesWritten: buffer.length,
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(`Directory does not exist: ${path.dirname(filePath)}`);
    }
    if ((error as NodeJS.ErrnoException).code === "EACCES") {
      throw new Error(`Permission denied: ${filePath}`);
    }
    if ((error as NodeJS.ErrnoException).code === "ENOSPC") {
      throw new Error("No space left on device");
    }
    throw error;
  }
};
