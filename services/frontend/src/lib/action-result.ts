import {
  friendlyValidationMessage,
  MSG_GENERIC_DATE,
} from "./bucket";

export type FieldErrors = Record<string, string>;

export type ActionResult<T = undefined> =
  | { ok: true; data: T; alreadyDeleted?: boolean }
  | {
      ok: false;
      kind: "validation" | "unavailable" | "timeout" | "rejected";
      message: string;
      fieldErrors?: FieldErrors;
      plotGone?: boolean;
    };

// Structural subset of ApiError, so this file stays importable from client code and tests.
export type FailureLike = {
  kind: "http" | "network" | "timeout";
  status?: number;
  detail: string;
};

const UNAVAILABLE = "Registry unavailable. Nothing was saved. Try again.";
const TIMEOUT =
  "The registry did not answer. It may have been saved. Check before retrying.";

// "body.name: Field required; body.area_m2: Input should be > 0" -> { name: "...", area_m2: "..." }
export function parseValidationDetail(detail: string): FieldErrors {
  const out: FieldErrors = {};
  for (const part of detail.split(";")) {
    const m = /^\s*body\.([\w.]+):\s*(.+?)\s*$/.exec(part);
    if (m && !(m[1] in out)) out[m[1]] = m[2];
  }
  return out;
}

export function failureToResult(f: FailureLike): ActionResult<never> {
  if (f.kind === "timeout") {
    return { ok: false, kind: "timeout", message: TIMEOUT };
  }
  if (f.kind === "network" || (f.status !== undefined && f.status >= 500)) {
    return { ok: false, kind: "unavailable", message: UNAVAILABLE };
  }
  if (f.status === 422) {
    const fieldErrors = parseValidationDetail(f.detail);
    return Object.keys(fieldErrors).length > 0
      ? {
          ok: false,
          kind: "validation",
          message: "Please fix the highlighted fields.",
          fieldErrors,
        }
      : { ok: false, kind: "validation", message: f.detail };
  }
  return { ok: false, kind: "rejected", message: f.detail };
}

// 404 on delete means the plot is already gone: success from the user's point of view.
export function deleteFailureToResult(f: FailureLike): ActionResult {
  if (f.kind === "http" && f.status === 404) {
    return { ok: true, data: undefined, alreadyDeleted: true };
  }
  return failureToResult(f);
}

const UNKNOWN_REFERENCE: Record<string, string> = {
  "Unknown crop": "crop_id",
  "Unknown soil": "soil_id",
  "Unknown emitter": "emitter_id",
};

// Plot create: the registry's 409 and "Unknown ..." 422s belong to one field each.
export function plotFailureToResult(f: FailureLike): ActionResult<never> {
  if (f.kind === "http" && f.status === 409) {
    return {
      ok: false,
      kind: "validation",
      message: "Please fix the highlighted fields.",
      fieldErrors: { name: "A plot with this name already exists in this farm" },
    };
  }
  if (f.kind === "http" && f.status === 422) {
    const detail = f.detail.trim();
    if (detail === "Unknown farm") {
      return { ok: false, kind: "rejected", message: "This farm no longer exists." };
    }
    const field = UNKNOWN_REFERENCE[detail];
    if (field) {
      return {
        ok: false,
        kind: "validation",
        message: "Please fix the highlighted fields.",
        fieldErrors: { [field]: detail },
      };
    }
  }
  return failureToResult(f);
}

const PLANNER_UNREACHABLE =
  "The planner can't reach its data right now. Try again in a moment.";
const OUR_SIDE = "Something went wrong on our side. Try again.";

// The bucket suggestion is a read: trying again is always safe. Never a zero or a guessed value.
// `plantingDate` is only used to word the "before planting" message.
export function suggestionFailureToResult(
  f: FailureLike,
  plantingDate?: string,
): ActionResult<never> {
  if (f.kind === "timeout") {
    return { ok: false, kind: "timeout", message: "No answer in time. Try again." };
  }
  if (f.kind === "network") {
    return { ok: false, kind: "unavailable", message: PLANNER_UNREACHABLE };
  }
  if (f.status === 404) {
    return {
      ok: false,
      kind: "rejected",
      message: "This plot no longer exists.",
      plotGone: true,
    };
  }
  if (f.status === 422) {
    return {
      ok: false,
      kind: "validation",
      message: friendlyValidationMessage(f.detail, plantingDate),
    };
  }
  if (f.status === 500) {
    return { ok: false, kind: "unavailable", message: OUR_SIDE };
  }
  if (f.status !== undefined && f.status >= 500) {
    return { ok: false, kind: "unavailable", message: PLANNER_UNREACHABLE };
  }
  return { ok: false, kind: "rejected", message: MSG_GENERIC_DATE };
}
