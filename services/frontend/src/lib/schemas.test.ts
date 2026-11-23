import assert from "node:assert/strict";
import { test } from "node:test";
import {
  farmSchema,
  firstIssuePerField,
  latestDateOnEarth,
  makePlotSchema,
  parseDecimal,
} from "./schemas";

test("farm: valid name is trimmed", () => {
  const r = farmSchema.safeParse({ name: "  Green Acres " });
  assert.ok(r.success);
  assert.equal(r.data.name, "Green Acres");
});

test("farm: empty is rejected", () => {
  assert.equal(farmSchema.safeParse({ name: "" }).success, false);
});

test("farm: spaces only is rejected", () => {
  assert.equal(farmSchema.safeParse({ name: "   " }).success, false);
});

test("farm: NUL character is rejected", () => {
  assert.equal(farmSchema.safeParse({ name: "a\0b" }).success, false);
});

// ---- plot ------------------------------------------------------------------

const NOW = new Date("2026-11-20T12:00:00Z"); // UTC+14 date: 2026-11-21
const schema = makePlotSchema(() => NOW);

const valid = {
  farm_id: "f1",
  name: " North field ",
  crop_id: "tomato",
  planting_date: "2026-05-01",
  soil_id: "loam",
  emitter_id: "e2",
  area_m2: "12.5",
  row_spacing_m: "1,5",
  emitter_spacing_m: " 0.3 ",
  lat: "31.25",
  lon: "34.78",
};

const issuesFor = (over: Record<string, unknown>) => {
  const r = schema.safeParse({ ...valid, ...over });
  return r.success ? {} : firstIssuePerField(r.error);
};

test("plot: valid payload outputs real numbers and a trimmed name", () => {
  const r = schema.safeParse(valid);
  assert.ok(r.success);
  assert.deepEqual(r.data, {
    farm_id: "f1",
    name: "North field",
    area_m2: 12.5,
    crop_id: "tomato",
    planting_date: "2026-05-01",
    soil_id: "loam",
    row_spacing_m: 1.5,
    emitter_spacing_m: 0.3,
    emitter_id: "e2",
    lat: 31.25,
    lon: 34.78,
  });
  assert.equal(Object.keys(r.data).length, 11);
});

test("plot: decimal parsing accepts 12.5, 12,5 and ' 7 '", () => {
  for (const v of ["12.5", "12,5", " 7 "]) {
    assert.equal(schema.safeParse({ ...valid, area_m2: v }).success, true, v);
  }
});

test("plot: decimal parsing rejects junk", () => {
  for (const v of ["", "abc", "1e3", "Infinity", "1 000"]) {
    assert.ok("area_m2" in issuesFor({ area_m2: v }), v);
  }
});

test("plot: area 0 is rejected", () => {
  assert.ok("area_m2" in issuesFor({ area_m2: "0" }));
});

test("plot: lat and lon bounds", () => {
  assert.ok("lat" in issuesFor({ lat: "90.0001" }));
  assert.ok("lon" in issuesFor({ lon: "-180.1" }));
  assert.deepEqual(issuesFor({ lat: "-90", lon: "180" }), {});
});

test("plot: impossible date is rejected", () => {
  assert.ok("planting_date" in issuesFor({ planting_date: "2026-13-45" }));
  assert.ok("planting_date" in issuesFor({ planting_date: "2026-02-30" }));
  assert.ok("planting_date" in issuesFor({ planting_date: "5/1/2026" }));
});

test("plot: date today at UTC+14 is valid, tomorrow is not", () => {
  assert.equal(latestDateOnEarth(NOW), "2026-11-21");
  assert.deepEqual(issuesFor({ planting_date: "2026-11-21" }), {});
  assert.ok("planting_date" in issuesFor({ planting_date: "2026-11-22" }));
});

test("plot: name with only spaces or a NUL is rejected", () => {
  assert.ok("name" in issuesFor({ name: "   " }));
  assert.ok("name" in issuesFor({ name: "a\0b" }));
});

test("plot: every missing field reports its own key", () => {
  for (const key of Object.keys(valid)) {
    const { [key]: _omit, ...rest } = valid as Record<string, string>;
    void _omit;
    const r = schema.safeParse(rest);
    assert.ok(!r.success, key);
    assert.ok(key in firstIssuePerField(r.error), key);
  }
});

test("plot: empty select values are rejected", () => {
  for (const key of ["crop_id", "soil_id", "emitter_id", "farm_id"]) {
    assert.ok(key in issuesFor({ [key]: "" }), key);
  }
});

test("parseDecimal: comma plus exactly 3 digits is ambiguous and rejected", () => {
  for (const v of ["1,000", "12,500", "-34,850"]) {
    assert.equal(parseDecimal(v), null, v);
    assert.ok("area_m2" in issuesFor({ area_m2: v }), v);
  }
});

test("parseDecimal: other comma and dot decimals still work", () => {
  assert.equal(parseDecimal("12,5"), 12.5);
  assert.equal(parseDecimal("31,2518"), 31.2518);
  assert.equal(parseDecimal("0,75"), 0.75);
  assert.equal(parseDecimal("1000"), 1000);
  assert.equal(parseDecimal("1.000"), 1);
});

const TOO_LONG = "Name must be at most 100 characters";

test("farm: 100-character name passes, 101 is rejected with a message", () => {
  assert.equal(farmSchema.safeParse({ name: "a".repeat(100) }).success, true);
  const r = farmSchema.safeParse({ name: "a".repeat(101) });
  assert.ok(!r.success);
  assert.equal(r.error.issues[0].message, TOO_LONG);
});

test("plot: 100-character name passes, 101 is rejected with a message", () => {
  assert.deepEqual(issuesFor({ name: "a".repeat(100) }), {});
  assert.equal(issuesFor({ name: "a".repeat(101) }).name, TOO_LONG);
});
