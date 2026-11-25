import assert from "node:assert/strict";
import { mock, test } from "node:test";

// registry.ts imports server-only modules; replace them so tsx can load it.
type Call = {
  service: string;
  path: string;
  timeoutMs: number;
  baseUrl: string;
  query?: Record<string, string>;
  method?: string;
  body?: unknown;
};
const serviceFetch = mock.fn(async (opts: Call) => ({ opts, plot_ids: ["p1", "p2"] }));
const serviceFetchBinary = mock.fn(async (opts: Call) => ({
  opts,
  bytes: new Uint8Array([1]),
  contentType: "image/png",
}));
mock.module("server-only", { namedExports: {} });
mock.module("./config", {
  namedExports: {
    config: {
      registryUrl: "http://registry.test",
      registryTimeoutMs: 1234,
      photoTimeoutMs: 45000,
    },
  },
});
mock.module("./http", { namedExports: { serviceFetch, serviceFetchBinary } });

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

test("getPlotPhotoIds: GET /v1/plot-photos?farm_id= with the registry timeout", async () => {
  const { getPlotPhotoIds } = await import("./registry");
  const ids = await getPlotPhotoIds("farm/1");
  assert.deepEqual(ids, ["p1", "p2"]);
  const call = lastCall();
  assert.equal(call.service, "registry");
  assert.equal(call.path, "/v1/plot-photos");
  // serviceFetch puts query values through URLSearchParams, which encodes them.
  assert.deepEqual(call.query, { farm_id: "farm/1" });
  assert.equal(call.timeoutMs, 1234);
});

test("getPlotPhoto: binary GET /v1/plots/{id}/photo with the photo timeout", async () => {
  const { getPlotPhoto } = await import("./registry");
  const out = await getPlotPhoto("a b/c");
  assert.equal(out.contentType, "image/png");
  const call = serviceFetchBinary.mock.calls.at(-1)!.arguments[0];
  assert.equal(call.service, "registry");
  assert.equal(call.baseUrl, "http://registry.test");
  assert.equal(call.path, "/v1/plots/a%20b%2Fc/photo");
  assert.equal(call.timeoutMs, 45000);
});

test("uploadPlotPhoto: multipart POST with field \"file\" and the photo timeout", async () => {
  const { uploadPlotPhoto } = await import("./registry");
  const blob = new Blob([new Uint8Array([1, 2])], { type: "image/jpeg" });
  await uploadPlotPhoto("a/b", blob);
  const call = lastCall();
  assert.equal(call.service, "registry");
  assert.equal(call.method, "POST");
  assert.equal(call.path, "/v1/plots/a%2Fb/photo");
  assert.equal(call.timeoutMs, 45000);
  assert.ok(call.body instanceof FormData);
  const file = call.body.get("file");
  assert.ok(file instanceof File);
  assert.equal(file.name, "photo.jpg");
  assert.equal(file.type, "image/jpeg");
  assert.equal(file.size, 2);
});

test("uploadPlotPhoto: a File keeps its own name", async () => {
  const { uploadPlotPhoto } = await import("./registry");
  await uploadPlotPhoto("p", new File(["x"], "field.png", { type: "image/png" }));
  const file = (lastCall().body as FormData).get("file") as File;
  assert.equal(file.name, "field.png");
  assert.equal(file.type, "image/png");
});
