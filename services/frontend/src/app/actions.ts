"use server";

import { revalidatePath } from "next/cache";
import {
  deleteFailureToResult,
  failureToResult,
  plotFailureToResult,
  type ActionResult,
} from "@/lib/action-result";
import { ApiError } from "@/lib/errors";
import { createFarm, createPlot, deletePlot } from "@/lib/registry";
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
  if (typeof id !== "string" || id.length === 0) {
    return { ok: false, kind: "rejected", message: "Missing plot id." };
  }
  try {
    await deletePlot(id);
    return { ok: true, data: undefined };
  } catch (e) {
    if (e instanceof ApiError) return deleteFailureToResult(e);
    throw e;
  }
}
