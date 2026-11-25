import assert from "node:assert/strict";
import { test } from "node:test";
import {
  computeEtag,
  ifNoneMatchMatches,
  MAX_PHOTO_BYTES,
  photoErrorResponse,
  photoFailureToResult,
  photoProxyResponse,
  photoUrl,
  scaledSize,
  validatePhotoFile,
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

test("validatePhotoFile: jpeg, png and webp up to 5 MB", () => {
  for (const type of ["image/jpeg", "image/png", "image/webp"]) {
    assert.deepEqual(validatePhotoFile({ type, size: 1 }), { ok: true });
  }
  assert.equal(MAX_PHOTO_BYTES, 5 * 1024 * 1024);
  assert.deepEqual(validatePhotoFile({ type: "image/png", size: MAX_PHOTO_BYTES }), { ok: true });
});

test("validatePhotoFile: wrong type, empty, too big", () => {
  for (const type of ["image/heic", "image/gif", "image/svg+xml", ""]) {
    const r = validatePhotoFile({ type, size: 10 });
    assert.equal(r.ok, false);
    assert.match(!r.ok ? r.message : "", /JPEG, PNG or WebP/);
  }
  const empty = validatePhotoFile({ type: "image/jpeg", size: 0 });
  assert.match(!empty.ok ? empty.message : "", /empty/);
  const big = validatePhotoFile({ type: "image/jpeg", size: MAX_PHOTO_BYTES + 1 });
  assert.match(!big.ok ? big.message : "", /5 MB/);
});

test("scaledSize: long side to 2048, aspect kept, never upscaled", () => {
  assert.deepEqual(scaledSize(4000, 3000), { width: 2048, height: 1536 });
  assert.deepEqual(scaledSize(3000, 4000), { width: 1536, height: 2048 });
  assert.deepEqual(scaledSize(2048, 1000), { width: 2048, height: 1000 });
  assert.deepEqual(scaledSize(800, 600), { width: 800, height: 600 });
  assert.deepEqual(scaledSize(100000, 10), { width: 2048, height: 1 });
  assert.deepEqual(scaledSize(1000, 500, 100), { width: 100, height: 50 });
});

const fail = (kind: "http" | "network" | "timeout", status?: number, detail = "x") => ({
  kind,
  status,
  detail,
});

test("photoFailureToResult: 422 with and without a server detail", () => {
  assert.deepEqual(photoFailureToResult(fail("http", 422, "Photo is larger than 5 MB")), {
    ok: false,
    kind: "validation",
    message: "Use a JPEG, PNG or WebP photo up to 5 MB. (Photo is larger than 5 MB)",
  });
  for (const detail of ["422 Unprocessable Entity", ""]) {
    const r = photoFailureToResult(fail("http", 422, detail));
    assert.equal(!r.ok && r.message, "Use a JPEG, PNG or WebP photo up to 5 MB.");
  }
});

test("photoFailureToResult: 503 and network errors", () => {
  for (const f of [fail("http", 503), fail("network")]) {
    assert.deepEqual(photoFailureToResult(f), {
      ok: false,
      kind: "unavailable",
      message: "Photo storage unavailable. Nothing changed. Try again.",
    });
  }
});

test("photoFailureToResult: timeout", () => {
  assert.deepEqual(photoFailureToResult(fail("timeout")), {
    ok: false,
    kind: "timeout",
    message: "No answer in time. The photo may not have been saved. Try again.",
  });
});

test("photoFailureToResult: 404 means the plot is gone", () => {
  assert.deepEqual(photoFailureToResult(fail("http", 404)), {
    ok: false,
    kind: "rejected",
    message: "This plot no longer exists.",
    plotGone: true,
  });
});

test("photoFailureToResult: anything else is generic, never the detail", () => {
  for (const f of [fail("http", 500, "boto3 ClientError at s3://b/k"), fail("http", 400, "secret")]) {
    const r = photoFailureToResult(f);
    assert.equal(!r.ok && r.message, "The photo could not be saved. Try again.");
  }
});
