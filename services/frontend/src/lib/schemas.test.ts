import assert from "node:assert/strict";
import { test } from "node:test";
import { farmSchema } from "./schemas";

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
