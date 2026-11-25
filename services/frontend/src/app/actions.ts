"use server";

import { revalidatePath } from "next/cache";
import {
  deleteFailureToResult,
  failureToResult,
  plotFailureToResult,
  suggestionFailureToResult,
  type ActionResult,
} from "@/lib/action-result";
import {
  describeSuggestion,
  isRealIsoDate,
  isUuid,
  MSG_FORMAT,
  type SuggestionView,
} from "@/lib/bucket";
import { ApiError } from "@/lib/errors";
import { getBucketSuggestion } from "@/lib/planner";
import { photoFailureToResult, validatePhotoFile } from "@/lib/photo";
import { createFarm, createPlot, deletePlot, uploadPlotPhoto } from "@/lib/registry";
import {
  farmSchema,
  firstIssuePerField,
  plotInputFromFormData,
  plotSchema,
} from "@/lib/schemas";
import type { Farm } from "@/lib/types";

export async function createFarmAction(
  _prev: ActionResult<Farm> | null,
  formData: FormData,
): Promise<ActionResult<Farm>> {
  const parsed = farmSchema.safeParse({ name: formData.get("name") });
  if (!parsed.success) {
    return {
      ok: false,
      kind: "validation",
      message: "Please fix the highlighted fields.",
      fieldErrors: { name: parsed.error.issues[0].message },
    };
  }
  try {
    const farm = await createFarm(parsed.data.name);
    revalidatePath("/");
    return { ok: true, data: farm };
  } catch (e) {
    if (e instanceof ApiError) return failureToResult(e);
    throw e;
  }
}

export async function createPlotAction(
  _prev: ActionResult<{ id: string }> | null,
  formData: FormData,
): Promise<ActionResult<{ id: string }>> {
  const parsed = plotSchema.safeParse(plotInputFromFormData(formData));
  if (!parsed.success) {
    return {
      ok: false,
      kind: "validation",
      message: "Please fix the highlighted fields.",
      fieldErrors: firstIssuePerField(parsed.error),
    };
  }
  try {
    const plot = await createPlot(parsed.data);
    revalidatePath("/");
    return { ok: true, data: { id: plot.id } };
  } catch (e) {
    if (e instanceof ApiError) return plotFailureToResult(e);
    throw e;
  }
}

// No revalidatePath here: it would re-render the current route (the plot page being
// deleted) in the same response and flash not-found. "/" is force-dynamic, so the
// client's router.push("/") fetches it fresh anyway.
export async function deletePlotAction(id: string): Promise<ActionResult> {
  // Server actions are public endpoints: a non-UUID id never reaches the registry URL.
  if (!isUuid(id)) {
    return { ok: false, kind: "rejected", message: "This plot no longer exists.", plotGone: true };
  }
  try {
    await deletePlot(id);
    return { ok: true, data: undefined };
  } catch (e) {
    if (e instanceof ApiError) return deleteFailureToResult(e);
    throw e;
  }
}

// Checks only the format and that the date is real. The planner judges the range
// (future, before planting, too old). `plantingDate` only words the "before planting" message.
export async function suggestBucketAction(
  plotId: string,
  date: string,
  plantingDate?: string,
): Promise<ActionResult<SuggestionView>> {
  // Server actions are public endpoints: a non-UUID id never reaches the planner URL.
  if (!isUuid(plotId)) {
    return { ok: false, kind: "rejected", message: "This plot no longer exists.", plotGone: true };
  }
  if (typeof date !== "string" || !isRealIsoDate(date)) {
    return { ok: false, kind: "validation", message: MSG_FORMAT };
  }
  const planting =
    typeof plantingDate === "string" && isRealIsoDate(plantingDate)
      ? plantingDate
      : undefined;
  try {
    return { ok: true, data: describeSuggestion(await getBucketSuggestion(plotId, date)) };
  } catch (e) {
    if (e instanceof ApiError) return suggestionFailureToResult(e, planting);
    throw e;
  }
}

// The client checks and downscales first; everything is checked again here because a
// Server Action is a public endpoint. A body over bodySizeLimit (next.config) throws
// before this runs, which is why the client never sends more than 5 MB.
export async function uploadPlotPhotoAction(
  plotId: string,
  formData: FormData,
): Promise<ActionResult> {
  // A non-UUID id never reaches the registry URL.
  if (!isUuid(plotId)) {
    return { ok: false, kind: "rejected", message: "This plot no longer exists.", plotGone: true };
  }
  const file = formData instanceof FormData ? formData.get("file") : null;
  if (!(file instanceof File)) {
    return { ok: false, kind: "validation", message: "Choose a photo to upload." };
  }
  const check = validatePhotoFile(file);
  if (!check.ok) return { ok: false, kind: "validation", message: check.message };
  try {
    await uploadPlotPhoto(plotId, file);
  } catch (e) {
    if (e instanceof ApiError) return photoFailureToResult(e);
    throw e;
  }
  revalidatePath(`/plots/${plotId}`);
  revalidatePath("/");
  return { ok: true, data: undefined };
}
