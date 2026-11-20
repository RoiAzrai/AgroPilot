import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addDays,
  bucketUrl,
  dateBounds,
  describeSuggestion,
  formatBucketPercent,
  friendlyValidationMessage,
  isRealIsoDate,
  isUuid,
  parsePercentInput,
  suggestionText,
  validateLastIrrigation,
} from "./bucket";
import type { SuggestionOut } from "./types";

const out = (over: Partial<SuggestionOut> = {}): SuggestionOut => ({
  plot_id: "p",
  last_irrigation: "2026-10-21",
  suggestion: 0.7416,
  exact: true,
  reason: null,
  past_days_requested: 29,
  past_days_returned: 29,
  stale: false,
  ...over,
});

test("isRealIsoDate", () => {
  assert.equal(isRealIsoDate("2026-11-20"), true);
  assert.equal(isRealIsoDate("2024-02-29"), true); // leap year
  assert.equal(isRealIsoDate("2026-02-29"), false);
  assert.equal(isRealIsoDate("2026-02-30"), false);
  assert.equal(isRealIsoDate("2026-13-01"), false);
  assert.equal(isRealIsoDate("2026-00-10"), false);
  assert.equal(isRealIsoDate("20261101"), false);
  assert.equal(isRealIsoDate("2026-1-1"), false);
  assert.equal(isRealIsoDate(""), false);
  assert.equal(isRealIsoDate("garbage"), false);
  assert.equal(isRealIsoDate("2026-11-20 "), false);
});

test("addDays: month, year and leap boundaries", () => {
  assert.equal(addDays("2026-11-20", -92), "2026-08-20");
  assert.equal(addDays("2026-03-01", -1), "2026-02-28");
  assert.equal(addDays("2024-03-01", -1), "2024-02-29");
  assert.equal(addDays("2026-01-01", -1), "2025-12-31");
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(addDays("2026-11-20", 0), "2026-11-20");
  assert.throws(() => addDays("2026-02-30", 1), RangeError);
});

test("dateBounds: min is the later of planting and today - 92", () => {
  // planted recently: planting date wins
  assert.deepEqual(dateBounds("2026-11-20", "2026-10-21"), {
    min: "2026-10-21",
    max: "2026-11-20",
  });
  // planted long ago: 92 days back wins
  assert.deepEqual(dateBounds("2026-11-20", "2026-01-01"), {
    min: "2026-08-20",
    max: "2026-11-20",
  });
  // planted exactly 92 days ago: same date either way
  assert.deepEqual(dateBounds("2026-11-20", "2026-08-20"), {
    min: "2026-08-20",
    max: "2026-11-20",
  });
});

test("validateLastIrrigation", () => {
  const ctx = { today: "2026-11-20", plantingDate: "2026-10-21" };
  assert.equal(validateLastIrrigation("2026-11-20", ctx), null);
  assert.equal(validateLastIrrigation("2026-10-21", ctx), null);
  assert.equal(validateLastIrrigation("", ctx), "Enter a valid date.");
  assert.equal(validateLastIrrigation("2026-02-30", ctx), "Enter a valid date.");
  assert.equal(validateLastIrrigation("2026-11-21", ctx), "That date is in the future.");
  assert.equal(
    validateLastIrrigation("2026-10-20", ctx),
    "That date is before the planting date (2026-10-21).",
  );
  const old = { today: "2026-11-20", plantingDate: "2026-01-01" };
  assert.equal(validateLastIrrigation("2026-08-20", old), null);
  assert.equal(
    validateLastIrrigation("2026-08-19", old),
    "That date is too far back. Pick a date within the last 92 days.",
  );
  // before planting wins over too old, as in the planner
  assert.match(validateLastIrrigation("2025-01-01", old)!, /before the planting date/);
});

test("friendlyValidationMessage: by content, never the raw text", () => {
  assert.equal(
    friendlyValidationMessage("last_irrigation cannot be in the future"),
    "That date is in the future.",
  );
  assert.equal(
    friendlyValidationMessage("last_irrigation is in the future"),
    "That date is in the future.",
  );
  assert.equal(
    friendlyValidationMessage("last_irrigation is before the planting date", "2026-10-21"),
    "That date is before the planting date (2026-10-21).",
  );
  assert.equal(
    friendlyValidationMessage("last_irrigation is before the planting date"),
    "That date is before the planting date.",
  );
  assert.equal(
    friendlyValidationMessage("last_irrigation is more than 92 days ago"),
    "That date is too far back. Pick a date within the last 92 days.",
  );
  assert.equal(
    friendlyValidationMessage("last_irrigation must be a date, YYYY-MM-DD"),
    "Enter a valid date.",
  );
  assert.equal(
    friendlyValidationMessage(
      "The plot's crop has no irrigation coefficients in the planner. This is a data problem, not a request problem.",
    ),
    "Can't estimate for this plot's crop.",
  );
  const other = friendlyValidationMessage("query.last_irrigation: Field required");
  assert.equal(other, "Can't use that date. Try another one.");
  assert.ok(!other.includes("query."));
});

test("describeSuggestion: a clean value", () => {
  const v = describeSuggestion(out());
  assert.deepEqual(v, {
    kind: "value",
    percent: 74,
    apply: 0.74,
    since: "2026-10-21",
    days: 29,
    stale: false,
  });
});

test("describeSuggestion: 0 is valid when exact, 1 is valid", () => {
  const zero = describeSuggestion(out({ suggestion: 0 }));
  assert.equal(zero.kind, "value");
  assert.equal(zero.kind === "value" && zero.percent, 0);
  assert.equal(zero.kind === "value" && zero.apply, 0);
  const full = describeSuggestion(out({ suggestion: 1, past_days_returned: 0 }));
  assert.equal(full.kind === "value" && full.percent, 100);
});

test("describeSuggestion: rounds to a whole percent, half up", () => {
  const v = describeSuggestion(out({ suggestion: 0.145 }));
  assert.equal(v.kind === "value" && v.percent, 15);
  const w = describeSuggestion(out({ suggestion: 0.875 }));
  assert.equal(w.kind === "value" && w.percent, 88);
});

test("describeSuggestion: stale flag", () => {
  const v = describeSuggestion(out({ stale: true }));
  assert.equal(v.kind === "value" && v.stale, true);
  const m = describeSuggestion(
    out({ suggestion: null, exact: false, reason: "insufficient_past_weather", stale: true }),
  );
  assert.deepEqual(m, { kind: "manual", stale: true });
});

test("describeSuggestion: season_ended", () => {
  const v = describeSuggestion(
    out({ suggestion: null, exact: false, reason: "season_ended" }),
  );
  assert.deepEqual(v, { kind: "season_ended" });
});

test("describeSuggestion: insufficient, unknown or missing reason -> manual", () => {
  const base = { suggestion: null, exact: false };
  assert.equal(
    describeSuggestion(out({ ...base, reason: "insufficient_past_weather" })).kind,
    "manual",
  );
  assert.equal(describeSuggestion(out({ ...base, reason: "something_new" })).kind, "manual");
  assert.equal(describeSuggestion(out({ ...base, reason: null })).kind, "manual");
});

test("describeSuggestion: exact=false with a value -> manual, no number", () => {
  const v = describeSuggestion(out({ exact: false }));
  assert.deepEqual(v, { kind: "manual", stale: false });
});

test("describeSuggestion: a value with a reason, or out of range, -> manual", () => {
  assert.equal(describeSuggestion(out({ reason: "season_ended" })).kind, "manual");
  assert.equal(describeSuggestion(out({ suggestion: 1.2 })).kind, "manual");
  assert.equal(describeSuggestion(out({ suggestion: -0.1 })).kind, "manual");
  assert.equal(describeSuggestion(out({ suggestion: Number.NaN })).kind, "manual");
});

test("suggestionText", () => {
  const v = describeSuggestion(out());
  assert.ok(v.kind === "value");
  assert.equal(
    suggestionText(v),
    "About 74% full. Based on no irrigation since 2026-10-21 (29 days of weather).",
  );
  const one = describeSuggestion(out({ past_days_returned: 1 }));
  assert.ok(one.kind === "value");
  assert.match(suggestionText(one), /\(1 day of weather\)/);
  const none = describeSuggestion(out({ suggestion: 1, past_days_returned: 0 }));
  assert.ok(none.kind === "value");
  assert.equal(
    suggestionText(none),
    "About 100% full. You irrigated on 2026-10-21, so the bucket is assumed full.",
  );
});

test("formatBucketPercent", () => {
  assert.equal(formatBucketPercent(0), "0%");
  assert.equal(formatBucketPercent(1), "100%");
  assert.equal(formatBucketPercent(0.74), "74%");
  assert.equal(formatBucketPercent(0.7416), "74.2%");
  assert.equal(formatBucketPercent(0.505), "50.5%");
});

test("parsePercentInput", () => {
  assert.equal(parsePercentInput(""), null);
  assert.equal(parsePercentInput("   "), null);
  assert.equal(parsePercentInput("abc"), null);
  assert.equal(parsePercentInput("-1"), null);
  assert.equal(parsePercentInput("101"), null);
  assert.equal(parsePercentInput("100.1"), null);
  assert.equal(parsePercentInput("1e2"), null);
  assert.equal(parsePercentInput("5."), null);
  assert.equal(parsePercentInput("NaN"), null);
  assert.equal(parsePercentInput("0"), 0);
  assert.equal(parsePercentInput("100"), 1);
  assert.equal(parsePercentInput("50.5"), 0.505);
  assert.equal(parsePercentInput(" 74 "), 0.74);
});

test("bucketUrl", () => {
  assert.equal(
    bucketUrl("/plots/abc", { bucketStart: 0.74, irrigated: "2026-10-21" }),
    "/plots/abc?bucket_start=0.74&irrigated=2026-10-21",
  );
  assert.equal(bucketUrl("/plots/abc", { bucketStart: 0.5 }), "/plots/abc?bucket_start=0.5");
  assert.equal(bucketUrl("/plots/abc", { bucketStart: 0 }), "/plots/abc?bucket_start=0");
  // an invalid date is dropped, a full bucket is the default
  assert.equal(
    bucketUrl("/plots/abc", { bucketStart: 0.5, irrigated: "garbage" }),
    "/plots/abc?bucket_start=0.5",
  );
  assert.equal(
    bucketUrl("/plots/abc", { bucketStart: 1, irrigated: "2026-10-21" }),
    "/plots/abc",
  );
});

test("isUuid: accepts a lowercase and an uppercase UUID", () => {
  assert.equal(isUuid("cb543426-0bc2-4ceb-b01c-62c9aec0553f"), true);
  assert.equal(isUuid("CB543426-0BC2-4CEB-B01C-62C9AEC0553F"), true);
});

test("isUuid: rejects empty, short, path-like and padded values", () => {
  assert.equal(isUuid(""), false);
  assert.equal(isUuid("abc"), false);
  assert.equal(isUuid("../health"), false);
  assert.equal(isUuid("cb543426-0bc2-4ceb-b01c-62c9aec0553f/../x"), false);
  assert.equal(isUuid("cb543426-0bc2-4ceb-b01c-62c9aec0553fz"), false);
  assert.equal(isUuid(" cb543426-0bc2-4ceb-b01c-62c9aec0553f"), false);
  assert.equal(isUuid("cb543426-0bc2-4ceb-b01c-62c9aec0553"), false);
  assert.equal(isUuid("cb543426-0bc2-4ceb-b01c-62c9aec0553g"), false);
});

test("isUuid: rejects non-strings", () => {
  assert.equal(isUuid(undefined), false);
  assert.equal(isUuid(null), false);
  assert.equal(isUuid(42), false);
  assert.equal(isUuid(["cb543426-0bc2-4ceb-b01c-62c9aec0553f"]), false);
});
