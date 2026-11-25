import assert from "node:assert/strict";
import { mock, test } from "node:test";

// http.ts imports server-only; replace it so tsx can load the module.
mock.module("server-only", { namedExports: {} });

type Seen = { url: string; init: RequestInit };
let seen: Seen[] = [];

function stubFetch(response: () => Response | Promise<Response>) {
  seen = [];
  mock.method(globalThis, "fetch", async (url: URL, init: RequestInit) => {
    seen.push({ url: String(url), init });
    return response();
  });
}

const base = { service: "registry" as const, baseUrl: "http://registry.test", timeoutMs: 1000 };
const headersOf = (s: Seen) => s.init.headers as Record<string, string>;

test("serviceFetch: a JSON body still gets a JSON content-type", async () => {
  const { serviceFetch } = await import("./http");
  stubFetch(() => Response.json({ id: "1" }, { status: 201 }));
  const out = await serviceFetch({ ...base, path: "/v1/farms", method: "POST", body: { name: "A" } });
  assert.deepEqual(out, { id: "1" });
  assert.equal(seen[0].init.body, '{"name":"A"}');
  assert.equal(headersOf(seen[0])["content-type"], "application/json");
  assert.equal(headersOf(seen[0]).accept, "application/json, application/problem+json");
});

test("serviceFetch: a FormData body is passed as is, without a manual content-type", async () => {
  const { serviceFetch } = await import("./http");
  stubFetch(() => Response.json({ ok: true }, { status: 201 }));
  const form = new FormData();
  form.append("file", new Blob(["x"], { type: "image/png" }), "photo.png");
  await serviceFetch({ ...base, path: "/v1/plots/1/photo", method: "POST", body: form });
  assert.equal(seen[0].init.body, form);
  assert.equal("content-type" in headersOf(seen[0]), false);
});

test("serviceFetch: 204 gives undefined", async () => {
  const { serviceFetch } = await import("./http");
  stubFetch(() => new Response(null, { status: 204 }));
  assert.equal(await serviceFetch({ ...base, path: "/x", method: "DELETE" }), undefined);
});

test("serviceFetchBinary: raw bytes and the content-type", async () => {
  const { serviceFetchBinary } = await import("./http");
  stubFetch(() => new Response(new Uint8Array([1, 2, 3]), { headers: { "content-type": "image/png" } }));
  const out = await serviceFetchBinary({ ...base, path: "/v1/plots/1/photo" });
  assert.deepEqual([...out.bytes], [1, 2, 3]);
  assert.equal(out.contentType, "image/png");
  assert.match(headersOf(seen[0]).accept, /image\/\*/);
});

test("serviceFetchBinary: an HTTP error is an ApiError with the problem detail", async () => {
  const { serviceFetchBinary } = await import("./http");
  stubFetch(
    () =>
      new Response(JSON.stringify({ detail: "Plot has no photo", code: "NOT_FOUND" }), {
        status: 404,
        headers: { "content-type": "application/problem+json" },
      }),
  );
  await assert.rejects(serviceFetchBinary({ ...base, path: "/v1/plots/1/photo" }), (e: unknown) => {
    const err = e as { name: string; kind: string; status: number; detail: string };
    return err.name === "ApiError" && err.kind === "http" && err.status === 404 && err.detail === "Plot has no photo";
  });
});

test("serviceFetchBinary: a timeout is an ApiError of kind timeout", async () => {
  const { serviceFetchBinary } = await import("./http");
  stubFetch(() => {
    throw new DOMException("timed out", "TimeoutError");
  });
  await assert.rejects(serviceFetchBinary({ ...base, path: "/x" }), (e: unknown) => {
    return (e as { kind: string }).kind === "timeout";
  });
});

test("serviceFetchBinary: a failed connection is an ApiError of kind network", async () => {
  const { serviceFetchBinary } = await import("./http");
  stubFetch(() => {
    throw new TypeError("fetch failed");
  });
  await assert.rejects(serviceFetchBinary({ ...base, path: "/x" }), (e: unknown) => {
    return (e as { kind: string }).kind === "network";
  });
});
