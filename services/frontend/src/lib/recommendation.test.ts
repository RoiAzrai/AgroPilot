import assert from "node:assert/strict";
import { test } from "node:test";
import {
  cells,
  describeSeason,
  describeToday,
  formatFetchedAt,
  formatMinutes,
  weekdayLabel,
} from "./recommendation";
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
    assert.equal(r.detail, "About 1,234,567 litres");
  }
});

test("describeToday: no irrigation while growing", () => {
  for (const stage of ["ini", "dev", "mid", "late"] as const) {
    const r = describeToday(day({ stage, run_minutes: 0 }));
    assert.equal(r.kind, "skip");
    assert.equal(r.headline, "No irrigation today");
    assert.equal(r.detail, "The soil has enough water for today.");
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
  assert.equal(r.detail, "This plot has finished its growing season.");
});

test("formatFetchedAt", () => {
  assert.equal(formatFetchedAt("2026-11-18T11:35:00Z"), "2026-11-18 11:35 UTC");
  assert.equal(formatFetchedAt("yesterday"), "yesterday");
});

test("describeSeason: every stage", () => {
  assert.deepEqual(describeSeason("not_planted"), {
    label: "Not planted yet",
    kind: "not_planted",
  });
  for (const stage of ["ini", "dev", "mid", "late"] as const) {
    assert.deepEqual(describeSeason(stage), { label: "Growing", kind: "growing" });
  }
  assert.deepEqual(describeSeason("ended"), {
    label: "Season ended",
    kind: "ended",
  });
});

test("describeSeason: an unknown stage gives null", () => {
  assert.equal(describeSeason("harvest"), null);
  assert.equal(describeSeason(""), null);
});

test("cells: et0/rain split into value and unit", () => {
  const c = cells(day({ et0_mm: 2.5, rain_mm: 0 }));
  assert.deepEqual(c.et0, { value: "2.5", unit: "mm" });
  assert.deepEqual(c.rain, { value: "0.0", unit: "mm" });
});

test("cells: litres split into value and unit", () => {
  const c = cells(day({ stage: "dev", litres: 1234567 }));
  assert.deepEqual(c.litres, { value: "1,234,567", unit: "L" });
});

test("cells: bucket split into value and unit", () => {
  const c = cells(
    day({ stage: "dev", bucket_mm: 70, bucket_capacity_mm: 72.5 }),
  );
  assert.deepEqual(c.bucket, { value: "70.0 / 72.5", unit: "mm" });
});

test("cells: ended season gives null for run, litres, kc and bucket", () => {
  const c = cells(
    day({
      stage: "ended",
      run_minutes: 38,
      litres: 1234,
      kc: 0.6,
      bucket_mm: 70,
      bucket_capacity_mm: 72.5,
    }),
  );
  assert.equal(c.run, null);
  assert.equal(c.litres, null);
  assert.equal(c.kc, null);
  assert.equal(c.bucket, null);
  assert.deepEqual(c.et0, { value: "2.7", unit: "mm" });
});

test("describeToday: water for 24 h", () => {
  const r = describeToday(day({ stage: "mid", run_minutes: 1440, litres: 76800 }));
  assert.equal(r.headline, "Water for 24 h");
  assert.equal(r.detail, "About 76,800 litres");
});

test("weekdayLabel: weekday and day of month, in UTC", () => {
  assert.equal(weekdayLabel("2026-11-26"), "Thu 26");
  assert.equal(weekdayLabel("2026-12-01"), "Tue 1");
  assert.equal(weekdayLabel("2024-02-29"), "Thu 29");
});

test("weekdayLabel: anything that is not a real date is shown raw", () => {
  assert.equal(weekdayLabel("2026-02-30"), "2026-02-30");
  assert.equal(weekdayLabel("tomorrow"), "tomorrow");
  assert.equal(weekdayLabel("2026-11-26T10:00:00Z"), "2026-11-26T10:00:00Z");
});
