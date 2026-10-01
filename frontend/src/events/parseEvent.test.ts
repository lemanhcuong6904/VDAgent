import { QueryClient } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { queryKeys } from "../api/keys";
import type { TaskDTO } from "../api/types";
import { MarkdownText } from "../components/Markdown";
import { applyEvent } from "./applyEvent";
import { parseServerEvent } from "./parseEvent";

const task: TaskDTO = {
  id: "t_1",
  root_agent: "data",
  status: "running",
  created_at: "2026-09-27T12:00:00Z",
  finished_at: null,
};

describe("event unknown-field compatibility", () => {
  it("accepts an event carrying fields this UI does not know", () => {
    const parsed = parseServerEvent("task.updated", {
      task: { ...task, priority: 3, labels: ["x"] },
      emitted_by: "server-v2",
    });
    expect(parsed).toBeDefined();
    if (!parsed) throw new Error("Expected the event parser to accept the event");

    const client = new QueryClient();
    client.setQueryData<TaskDTO[]>(queryKeys.tasks, []);
    applyEvent(client, parsed);
    expect(client.getQueryData<TaskDTO[]>(queryKeys.tasks)?.[0]?.id).toBe("t_1");
  });

  it("drops an event missing a field the reducer reads, instead of throwing", () => {
    expect(parseServerEvent("task.updated", { task: { status: "running" } })).toBeUndefined();
    expect(
      parseServerEvent("message.appended", {
        agent: "data",
        message: { id: "1", seq: 1, content: "x" },
      }),
    ).toBeUndefined();
    expect(parseServerEvent("invocation.updated", { invocation: null })).toBeUndefined();
    expect(parseServerEvent("agent.status", [])).toBeUndefined();
    expect(parseServerEvent("task.updated", "not an object")).toBeUndefined();
  });

  it("rejects an event name outside the protocol", () => {
    expect(parseServerEvent("run.migrated" as never, { task })).toBeUndefined();
  });

  it("does not let a crafted status value reach the cache as another type", () => {
    expect(
      parseServerEvent("task.updated", { task: { ...task, status: { $gt: "" } } }),
    ).toBeUndefined();
  });
});

describe("markdown rendering is inert", () => {
  const render = (text: string) => renderToStaticMarkup(createElement(MarkdownText, { text }));

  it("escapes raw HTML in agent output", () => {
    const html = render('<img src=x onerror="alert(1)"><script>alert(2)</script>');
    expect(html).not.toMatch(/<img|<script/i);
  });

  it("neutralises javascript: and data: links", () => {
    const html = render("[a](javascript:alert(1)) [b](data:text/html,<script>alert(1)</script>)");
    expect(html).not.toMatch(/href="(javascript|data):/i);
  });

  it("opens external links without an opener reference", () => {
    const html = render("[docs](https://example.com)");
    expect(html).toContain('rel="noreferrer"');
    expect(html).toContain('target="_blank"');
  });
});
