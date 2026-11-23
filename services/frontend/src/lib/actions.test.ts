import assert from "node:assert/strict";
import { mock, test } from "node:test";

// actions.ts imports server-only modules; replace them so tsx can load it.
const deletePlot = mock.fn(async (id: string) => void id);
mock.module("server-only", { namedExports: {} });
mock.module("next/cache", { namedExports: { revalidatePath: () => {} } });
mock.module("@/lib/registry", {
  namedExports: { createFarm: async () => ({}), createPlot: async () => ({}), deletePlot },
});
mock.module("@/lib/planner", { namedExports: { getBucketSuggestion: async () => ({}) } });

test("deletePlotAction: invalid id is rejected and the registry is not called", async () => {
  const { deletePlotAction } = await import("../app/actions");
  for (const id of ["..", "", "not-a-uuid", "../v1/farms"]) {
    const r = await deletePlotAction(id);
    assert.ok(!r.ok);
    assert.equal(r.kind, "rejected");
    assert.equal(r.message, "This plot no longer exists.");
  }
  assert.equal(deletePlot.mock.callCount(), 0);
});

test("deletePlotAction: a valid UUID still deletes", async () => {
  const { deletePlotAction } = await import("../app/actions");
  const id = "123e4567-e89b-42d3-a456-426614174000";
  assert.deepEqual(await deletePlotAction(id), { ok: true, data: undefined });
  assert.deepEqual(deletePlot.mock.calls[0].arguments, [id]);
});
