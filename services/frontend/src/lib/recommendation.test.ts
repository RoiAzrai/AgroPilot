import assert from "node:assert/strict";
import { test } from "node:test";
import { describeToday, formatFetchedAt, formatMinutes } from "./recommendation";
import type { DayOut, Plot } from "./types";

const day = (over: Partial<DayOut>): DayOut => ({
  date: "2026-11-20",
  stage: "dev",
  et0_mm: 2.7,
  rain_mm: 0,
  kc: 0.6,
  litres: 0,
  run_minutes: 0,
  bucket_mm: 70,
  bucket_capacity_mm: 72.5,
  stale: false,
  ...over,
});

const plot = { planting_date: "2026-12-01" } as Plot;

test("formatMinutes", () => {
  assert.equal(formatMinutes(38), "38 minutes");
  assert.equal(formatMinutes(1), "1 minute");
  assert.equal(formatMinutes(65), "1 h 5 min");
  assert.equal(formatMinutes(1366), "22 h 46 min");
  assert.equal(formatMinutes(1440), "24 h");
  assert.equal(formatMinutes(60), "1 h");
});

test("describeToday: water in every growing stage", () => {
  for (const stage of ["ini", "dev", "mid", "late"] as const) {
    const r = describeToday(day({ stage, run_minutes: 38, litres: 1234567 }));
    assert.equal(r.kind, "water");
    assert.equal(r.headline, "Water for 38 minutes");
    assert.equal(r.detail, "About 1,234,567 litres, in total for this plot.");
  }
});

test("describeToday: no irrigation while growing", () => {
  for (const stage of ["ini", "dev", "mid", "late"] as const) {
    const r = describeToday(day({ stage, run_minutes: 0 }));
    assert.equal(r.kind, "skip");
    assert.equal(r.headline, "No irrigation today");
    assert.equal(r.detail, "The soil still holds enough water.");
  }
});

test("describeToday: not planted", () => {
  const r = describeToday(day({ stage: "not_planted" }), plot);
  assert.equal(r.kind, "not_planted");
  assert.equal(r.headline, "Not planted yet");
  assert.equal(r.detail, "Planting date: 2026-12-01.");
});

test("describeToday: ended wins over run_minutes", () => {
  const r = describeToday(day({ stage: "ended", run_minutes: 0 }), plot);
  assert.equal(r.kind, "ended");
  assert.equal(r.headline, "Season ended");
  assert.equal(r.detail, "No more irrigation for this crop.");
});

test("formatFetchedAt", () => {
  assert.equal(formatFetchedAt("2026-11-18T11:35:00Z"), "2026-11-18 11:35 UTC");
  assert.equal(formatFetchedAt("yesterday"), "yesterday");
});
