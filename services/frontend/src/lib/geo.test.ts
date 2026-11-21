import assert from "node:assert/strict";
import { test } from "node:test";
import { describeGeoError, roundCoord } from "./geo";

test("roundCoord: 4 decimals", () => {
  assert.equal(roundCoord(31.251849), 31.2518);
  assert.equal(roundCoord(34.78129), 34.7813);
});

test("roundCoord: negatives", () => {
  assert.equal(roundCoord(-33.868819), -33.8688);
});

test("roundCoord: -0 becomes 0", () => {
  assert.ok(Object.is(roundCoord(-0.00001), 0));
  assert.ok(Object.is(roundCoord(-0), 0));
});

test("describeGeoError: known codes", () => {
  assert.match(describeGeoError(1), /permission was denied/);
  assert.match(describeGeoError(2), /Couldn't work out your location/);
  assert.match(describeGeoError(3), /took too long/);
});

test("describeGeoError: unknown code falls back to the generic message", () => {
  assert.equal(describeGeoError(99), describeGeoError(2));
});
