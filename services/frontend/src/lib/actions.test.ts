import assert from "node:assert/strict";
import { mock, test } from "node:test";

// actions.ts imports server-only modules; replace them so tsx can load it.
const deletePlot = mock.fn(async (id: string) => void id);
const uploadPlotPhoto = mock.fn(async (id: string, file: Blob): Promise<unknown> => ({ id, file }));
const revalidatePath = mock.fn((path: string) => void path);
mock.module("server-only", { namedExports: {} });
mock.module("next/cache", { namedExports: { revalidatePath } });
mock.module("@/lib/registry", {
  namedExports: {
    createFarm: async () => ({}),
    createPlot: async () => ({}),
    deletePlot,
    uploadPlotPhoto,
  },
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

const PLOT = "123e4567-e89b-42d3-a456-426614174000";
const photoForm = (file: unknown) => {
  const fd = new FormData();
  if (file !== undefined) fd.append("file", file as Blob);
  return fd;
};
const jpeg = (size = 3) => new File([new Uint8Array(size)], "photo.jpg", { type: "image/jpeg" });

test("uploadPlotPhotoAction: invalid plot id is rejected and the registry is not called", async () => {
  const { uploadPlotPhotoAction } = await import("../app/actions");
  const before = uploadPlotPhoto.mock.callCount();
  for (const id of ["", "../v1/farms", "not-a-uuid"]) {
    const r = await uploadPlotPhotoAction(id, photoForm(jpeg()));
    assert.ok(!r.ok);
    assert.equal(r.kind, "rejected");
    assert.equal(r.plotGone, true);
  }
  assert.equal(uploadPlotPhoto.mock.callCount(), before);
});

test("uploadPlotPhotoAction: missing file, text field, wrong type, empty and too big are refused", async () => {
  const { uploadPlotPhotoAction } = await import("../app/actions");
  const before = uploadPlotPhoto.mock.callCount();
  const cases = [
    photoForm(undefined),
    photoForm("just text"),
    photoForm(new File(["x"], "a.gif", { type: "image/gif" })),
    photoForm(new File([], "a.jpg", { type: "image/jpeg" })),
    photoForm(jpeg(5 * 1024 * 1024 + 1)),
  ];
  for (const fd of cases) {
    const r = await uploadPlotPhotoAction(PLOT, fd);
    assert.ok(!r.ok);
    assert.equal(r.kind, "validation");
  }
  assert.equal(uploadPlotPhoto.mock.callCount(), before);
});

test("uploadPlotPhotoAction: success uploads the file and revalidates the plot page and home", async () => {
  const { uploadPlotPhotoAction } = await import("../app/actions");
  revalidatePath.mock.resetCalls();
  const file = jpeg();
  assert.deepEqual(await uploadPlotPhotoAction(PLOT, photoForm(file)), { ok: true, data: undefined });
  const args = uploadPlotPhoto.mock.calls.at(-1)!.arguments;
  assert.equal(args[0], PLOT);
  assert.equal((args[1] as File).name, "photo.jpg");
  assert.equal((args[1] as File).size, 3);
  assert.deepEqual(
    revalidatePath.mock.calls.map((c) => c.arguments[0]),
    [`/plots/${PLOT}`, "/"],
  );
});

test("uploadPlotPhotoAction: registry errors map to photo messages, nothing is revalidated", async () => {
  const { uploadPlotPhotoAction } = await import("../app/actions");
  const { ApiError } = await import("./errors");
  revalidatePath.mock.resetCalls();
  uploadPlotPhoto.mock.mockImplementationOnce(async () => {
    throw new ApiError({ service: "registry", kind: "http", status: 503, detail: "Photo storage unavailable" });
  });
  const r = await uploadPlotPhotoAction(PLOT, photoForm(jpeg()));
  assert.deepEqual(r, {
    ok: false,
    kind: "unavailable",
    message: "Photo storage unavailable. Nothing changed. Try again.",
  });
  uploadPlotPhoto.mock.mockImplementationOnce(async () => {
    throw new ApiError({ service: "registry", kind: "http", status: 404, detail: "Plot not found" });
  });
  const gone = await uploadPlotPhotoAction(PLOT, photoForm(jpeg()));
  assert.ok(!gone.ok && gone.plotGone);
  assert.equal(revalidatePath.mock.callCount(), 0);
});

test("uploadPlotPhotoAction: a non-ApiError is rethrown", async () => {
  const { uploadPlotPhotoAction } = await import("../app/actions");
  uploadPlotPhoto.mock.mockImplementationOnce(async () => {
    throw new TypeError("bug");
  });
  await assert.rejects(uploadPlotPhotoAction(PLOT, photoForm(jpeg())), TypeError);
});
