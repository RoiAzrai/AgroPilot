import assert from "node:assert/strict";
import { test } from "node:test";
import {
  computeEtag,
  ifNoneMatchMatches,
  photoErrorResponse,
  photoProxyResponse,
  photoUrl,
} from "./photo";

const bytes = new Uint8Array([137, 80, 78, 71, 1, 2, 3]);
const ok = (contentType = "image/png") => ({ ok: true as const, bytes, contentType });
const failed = (kind: "http" | "network" | "timeout", status?: number) => ({
  ok: false as const,
  error: { kind, status, detail: "internal: s3://bucket/key" },
});

test("photoUrl: proxy path, id encoded, optional version", () => {
  assert.equal(photoUrl("abc"), "/api/plots/abc/photo");
  assert.equal(photoUrl("abc", 17), "/api/plots/abc/photo?v=17");
  assert.equal(photoUrl("a/b"), "/api/plots/a%2Fb/photo");
});

test("computeEtag: quoted, stable, base64url, differs per content", async () => {
  const a = await computeEtag(bytes);
  assert.equal(a, await computeEtag(new Uint8Array(bytes)));
  assert.match(a, /^"[A-Za-z0-9_-]{43}"$/);
  assert.notEqual(a, await computeEtag(new Uint8Array([1])));
});

test("ifNoneMatchMatches: quotes, W/, lists and *", () => {
  const tag = '"abc"';
  assert.equal(ifNoneMatchMatches('"abc"', tag), true);
  assert.equal(ifNoneMatchMatches('W/"abc"', tag), true);
  assert.equal(ifNoneMatchMatches('"x", W/"abc" ,"y"', tag), true);
  assert.equal(ifNoneMatchMatches("*", tag), true);
  assert.equal(ifNoneMatchMatches("abc", tag), true);
  assert.equal(ifNoneMatchMatches('"abd"', tag), false);
  assert.equal(ifNoneMatchMatches("", tag), false);
  assert.equal(ifNoneMatchMatches(null, tag), false);
  assert.equal(ifNoneMatchMatches(" , ", tag), false);
});

test("photoProxyResponse: 200 with bytes, type, ETag and cache headers", async () => {
  const r = await photoProxyResponse(ok("image/png"), null);
  assert.equal(r.status, 200);
  assert.equal(r.body, bytes);
  assert.equal(r.headers["Content-Type"], "image/png");
  assert.equal(r.headers["Cache-Control"], "private, no-cache");
  assert.equal(r.headers["X-Content-Type-Options"], "nosniff");
  assert.equal(r.headers.ETag, await computeEtag(bytes));
});

test("photoProxyResponse: a content-type with parameters is normalised", async () => {
  const r = await photoProxyResponse(ok("Image/JPEG; charset=binary"), null);
  assert.equal(r.status, 200);
  assert.equal(r.headers["Content-Type"], "image/jpeg");
});

test("photoProxyResponse: 304 with the same ETag and no body when If-None-Match matches", async () => {
  const etag = await computeEtag(bytes);
  const r = await photoProxyResponse(ok(), `W/${etag}`);
  assert.equal(r.status, 304);
  assert.equal(r.body, null);
  assert.equal(r.headers.ETag, etag);
  assert.equal(r.headers["Content-Type"], undefined);
});

test("photoProxyResponse: a content-type outside jpeg/png/webp is 502", async () => {
  for (const type of ["image/svg+xml", "text/html", ""]) {
    const r = await photoProxyResponse(ok(type), null);
    assert.equal(r.status, 502);
    assert.equal(r.headers["Cache-Control"], "no-store");
  }
});

test("photoProxyResponse: registry 404 is 404", async () => {
  const r = await photoProxyResponse(failed("http", 404), null);
  assert.equal(r.status, 404);
  assert.equal(r.headers["Cache-Control"], "no-store");
});

test("photoProxyResponse: registry 503 and network errors are 503 with Retry-After", async () => {
  for (const f of [failed("http", 503), failed("network")]) {
    const r = await photoProxyResponse(f, null);
    assert.equal(r.status, 503);
    assert.equal(r.headers["Retry-After"], "5");
    assert.equal(r.headers["Cache-Control"], "no-store");
  }
});

test("photoProxyResponse: timeout is 504", async () => {
  const r = await photoProxyResponse(failed("timeout"), null);
  assert.equal(r.status, 504);
});

test("photoProxyResponse: other registry errors are 502, never the internal detail", async () => {
  for (const f of [failed("http", 500), failed("http", 422)]) {
    const r = await photoProxyResponse(f, null);
    assert.equal(r.status, 502);
    assert.doesNotMatch(String(r.body), /s3|internal|bucket/i);
  }
});

test("photoErrorResponse: plain text, no-store, nosniff", () => {
  const r = photoErrorResponse(404);
  assert.equal(r.headers["Content-Type"], "text/plain; charset=utf-8");
  assert.equal(r.headers["X-Content-Type-Options"], "nosniff");
  assert.equal(r.headers["Retry-After"], undefined);
});
