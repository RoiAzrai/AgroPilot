import assert from "node:assert/strict";
import { test } from "node:test";
import {
  deleteFailureToResult,
  failureToResult,
  parseValidationDetail,
} from "./action-result";

const http = (status: number, detail = "x") => ({
  kind: "http" as const,
  status,
  detail,
});

test("parseValidationDetail: several fields", () => {
  assert.deepEqual(
    parseValidationDetail("body.name: Field required; body.area_m2: must be > 0"),
    { name: "Field required", area_m2: "must be > 0" },
  );
});

test("parseValidationDetail: no body.<field> parts", () => {
  assert.deepEqual(parseValidationDetail("something odd"), {});
});

test("422 with fields -> fieldErrors", () => {
  const r = failureToResult(http(422, "body.name: too short"));
  assert.ok(!r.ok);
  assert.equal(r.kind, "validation");
  assert.deepEqual(r.fieldErrors, { name: "too short" });
});

test("422 without fields -> form message", () => {
  const r = failureToResult(http(422, "bad input"));
  assert.ok(!r.ok);
  assert.equal(r.fieldErrors, undefined);
  assert.equal(r.message, "bad input");
});

test("503 and 500 -> unavailable", () => {
  for (const s of [503, 500]) {
    const r = failureToResult(http(s));
    assert.ok(!r.ok);
    assert.equal(r.kind, "unavailable");
    assert.equal(r.message, "Registry unavailable. Nothing was saved. Try again.");
  }
});

test("network -> unavailable", () => {
  const r = failureToResult({ kind: "network", detail: "x" });
  assert.ok(!r.ok);
  assert.equal(r.kind, "unavailable");
});

test("timeout -> may have been saved", () => {
  const r = failureToResult({ kind: "timeout", detail: "x" });
  assert.ok(!r.ok);
  assert.equal(r.kind, "timeout");
  assert.equal(
    r.message,
    "The registry did not answer. It may have been saved. Check before retrying.",
  );
});

test("farm 409 is not special (farms.name is not UNIQUE)", () => {
  const r = failureToResult(http(409, "conflict"));
  assert.ok(!r.ok);
  assert.equal(r.kind, "rejected");
  assert.equal(r.fieldErrors, undefined);
});

test("delete 404 -> ok alreadyDeleted", () => {
  assert.deepEqual(deleteFailureToResult(http(404)), {
    ok: true,
    data: undefined,
    alreadyDeleted: true,
  });
});

test("delete 503 / timeout stay errors", () => {
  const a = deleteFailureToResult(http(503));
  const b = deleteFailureToResult({ kind: "timeout", detail: "x" });
  assert.ok(!a.ok && a.kind === "unavailable");
  assert.ok(!b.ok && b.kind === "timeout");
});
