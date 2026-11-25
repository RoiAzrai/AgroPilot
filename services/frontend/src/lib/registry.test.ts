import assert from "node:assert/strict";
import { mock, test } from "node:test";

// registry.ts imports server-only modules; replace them so tsx can load it.
type Call = { service: string; path: string; timeoutMs: number; baseUrl: string };
const serviceFetch = mock.fn(async (opts: Call) => ({ opts }));
mock.module("server-only", { namedExports: {} });
mock.module("./config", {
  namedExports: {
    config: { registryUrl: "http://registry.test", registryTimeoutMs: 1234 },
  },
});
mock.module("./http", { namedExports: { serviceFetch } });

const lastCall = () => serviceFetch.mock.calls.at(-1)!.arguments[0];

test("getFarm: GET /v1/farms/{id} on the registry", async () => {
  const { getFarm } = await import("./registry");
  await getFarm("123e4567-e89b-42d3-a456-426614174000");
  const call = lastCall();
  assert.equal(call.service, "registry");
  assert.equal(call.baseUrl, "http://registry.test");
  assert.equal(call.path, "/v1/farms/123e4567-e89b-42d3-a456-426614174000");
  assert.equal(call.timeoutMs, 1234);
});

test("getFarm: the id is URL-encoded", async () => {
  const { getFarm } = await import("./registry");
  await getFarm("../v1/plots?x=1");
  assert.equal(lastCall().path, "/v1/farms/..%2Fv1%2Fplots%3Fx%3D1");
});
