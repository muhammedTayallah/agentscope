import { afterEach, expect, it, vi } from "vitest";

import { fetchHealth } from "./api";

afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

it("returns the body for 200 and for 503", async () => {
  reply(503, { status: "unhealthy", database: "ok", redis: "error" });
  expect(await fetchHealth()).toEqual({ status: "unhealthy", database: "ok", redis: "error" });
});

it("throws on other errors", async () => {
  reply(502, {});
  await expect(fetchHealth()).rejects.toThrow("HTTP 502");
});
