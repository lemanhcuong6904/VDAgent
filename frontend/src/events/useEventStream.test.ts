import { afterEach, describe, expect, it, vi } from "vitest";
import { buildEventStreamRequest, consumeEventStream, parseSseBlock } from "./useEventStream";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("authenticated browser event stream", () => {
  it("uses Authorization for sessions and keeps identity out of request headers", () => {
    vi.stubGlobal("window", {
      __VDAGENT_AUTH__: { webSessionToken: "signed-web-session" },
    });

    const request = buildEventStreamRequest("user with spaces", 42);

    expect(request.url).toBe("/api/events?user_id=user+with+spaces&after=42");
    expect(request.init.headers).toEqual({
      Accept: "text/event-stream",
      Authorization: "Bearer signed-web-session",
      "Last-Event-ID": "42",
    });
  });

  it("uses the demo user header only when there is no bearer session", () => {
    vi.stubGlobal("window", { __VDAGENT_AUTH__: {} });

    expect(buildEventStreamRequest("demo-user", 0).init.headers).toEqual({
      Accept: "text/event-stream",
      "X-User-Id": "demo-user",
      "Last-Event-ID": "0",
    });
  });

  it("parses multi-line frames and ignores comments and unknown fields", () => {
    expect(
      parseSseBlock(
        ': keepalive\nid: 7\nevent: task.updated\ndata: {\ndata: "status":"completed"}\nretry: 3000',
      ),
    ).toEqual({
      id: "7",
      event: "task.updated",
      data: '{\n"status":"completed"}',
    });
  });

  it("preserves UTF-8 and event boundaries across network chunks", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('id: 1\nevent: task.updated\ndata: {"label":'));
        controller.enqueue(encoder.encode('"café"}\n\n'));
        controller.close();
      },
    });
    const messages: { id?: string; event: string; data: string }[] = [];

    await consumeEventStream(body, (message) => messages.push(message));

    expect(messages).toEqual([{ id: "1", event: "task.updated", data: '{"label":"café"}' }]);
  });
});
