import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApiClient browser authentication", () => {
  it("sends the runtime web session and does not rely on a user header", async () => {
    vi.stubGlobal("window", {
      __VDAGENT_AUTH__: { webSessionToken: "signed-web-session" },
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient("owner").listTasks();

    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: "Bearer signed-web-session",
    });
  });

  it("keeps X-User-Id as a fallback only when no session token is configured", async () => {
    vi.stubGlobal("window", { __VDAGENT_AUTH__: {} });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient("demo-user").listTasks();

    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({
      Accept: "application/json",
      "X-User-Id": "demo-user",
    });
  });

  it("reads a rotated session token on the next API call", async () => {
    const runtimeConfig = { webSessionToken: "session-one" };
    vi.stubGlobal("window", { __VDAGENT_AUTH__: runtimeConfig });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = new ApiClient("owner");

    await api.listTasks();
    runtimeConfig.webSessionToken = "session-two";
    await api.listTasks();

    expect(
      fetchMock.mock.calls.map(
        ([, init]) => ((init?.headers ?? {}) as Record<string, string>).Authorization,
      ),
    ).toEqual(["Bearer session-one", "Bearer session-two"]);
  });
});
