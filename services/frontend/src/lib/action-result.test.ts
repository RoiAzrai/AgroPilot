import assert from "node:assert/strict";
import { test } from "node:test";
import {
  deleteFailureToResult,
  failureToResult,
  parseValidationDetail,
  plotFailureToResult,
  suggestionFailureToResult,
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

test("plotFailureToResult: 409 -> name field", () => {
  const r = plotFailureToResult(http(409, "Record already exists"));
  assert.ok(!r.ok);
  assert.equal(r.kind, "validation");
  assert.deepEqual(r.fieldErrors, {
    name: "A plot with this name already exists in this farm",
  });
});

test("plotFailureToResult: Unknown crop/soil/emitter -> that select", () => {
  for (const [detail, field] of [
    ["Unknown crop", "crop_id"],
    ["Unknown soil", "soil_id"],
    ["Unknown emitter", "emitter_id"],
  ]) {
    const r = plotFailureToResult(http(422, detail));
    assert.ok(!r.ok);
    assert.deepEqual(r.fieldErrors, { [field]: detail });
  }
});

test("plotFailureToResult: Unknown farm -> form message", () => {
  const r = plotFailureToResult(http(422, "Unknown farm"));
  assert.ok(!r.ok);
  assert.equal(r.message, "This farm no longer exists.");
  assert.equal(r.fieldErrors, undefined);
});

test("plotFailureToResult: other 422 falls back to body.<field> parsing", () => {
  const r = plotFailureToResult(http(422, "body.area_m2: Input should be > 0"));
  assert.ok(!r.ok);
  assert.deepEqual(r.fieldErrors, { area_m2: "Input should be > 0" });
});

test("plotFailureToResult: 503, 500, network and timeout fall back", () => {
  for (const f of [
    http(503),
    http(500),
    { kind: "network" as const, detail: "x" },
  ]) {
    const r = plotFailureToResult(f);
    assert.ok(!r.ok);
    assert.equal(r.kind, "unavailable");
  }
  const t = plotFailureToResult({ kind: "timeout", detail: "x" });
  assert.ok(!t.ok);
  assert.equal(t.kind, "timeout");
});

const network = { kind: "network" as const, detail: "Could not reach the service" };
const timeout = { kind: "timeout" as const, detail: "No answer within 5000 ms" };

test("suggestion: 404 -> plot gone, with a link flag", () => {
  const r = suggestionFailureToResult(http(404, "Plot not found"));
  assert.deepEqual(r, {
    ok: false,
    kind: "rejected",
    message: "This plot no longer exists.",
    plotGone: true,
  });
});

test("suggestion: 422 maps by content, never shows the raw text", () => {
  const cases: [string, string][] = [
    ["last_irrigation cannot be in the future", "That date is in the future."],
    ["last_irrigation is in the future", "That date is in the future."],
    [
      "last_irrigation is before the planting date",
      "That date is before the planting date (2026-10-21).",
    ],
    [
      "last_irrigation is more than 92 days ago",
      "That date is too far back. Pick a date within the last 92 days.",
    ],
    ["last_irrigation must be a date, YYYY-MM-DD", "Enter a valid date."],
    [
      "The plot's crop has no irrigation coefficients in the planner. This is a data problem, not a request problem.",
      "Can't estimate for this plot's crop.",
    ],
    ["query.last_irrigation: Field required", "Can't use that date. Try another one."],
  ];
  for (const [detail, message] of cases) {
    const r = suggestionFailureToResult(http(422, detail), "2026-10-21");
    assert.ok(!r.ok);
    assert.equal(r.kind, "validation");
    assert.equal(r.message, message);
    assert.ok(!r.message.includes("last_irrigation"));
  }
});

test("suggestion: 500", () => {
  const r = suggestionFailureToResult(http(500));
  assert.ok(!r.ok);
  assert.equal(r.message, "Something went wrong on our side. Try again.");
});

test("suggestion: 503 and network", () => {
  const msg = "The planner can't reach its data right now. Try again in a moment.";
  const a = suggestionFailureToResult(http(503));
  const b = suggestionFailureToResult(network);
  assert.ok(!a.ok && !b.ok);
  assert.equal(a.message, msg);
  assert.equal(b.message, msg);
  assert.equal(a.kind, "unavailable");
  assert.equal(b.kind, "unavailable");
});

test("suggestion: timeout", () => {
  const r = suggestionFailureToResult(timeout);
  assert.ok(!r.ok);
  assert.equal(r.kind, "timeout");
  assert.equal(r.message, "No answer in time. Try again.");
});

test("suggestion: no registry wording, and every failure is a failure", () => {
  for (const f of [http(404), http(422), http(500), http(503), http(400), network, timeout]) {
    const r = suggestionFailureToResult(f);
    assert.equal(r.ok, false);
    assert.ok(!/registry|saved/i.test(r.ok ? "" : r.message));
  }
});
