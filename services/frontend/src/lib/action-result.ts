export type FieldErrors = Record<string, string>;

export type ActionResult<T = undefined> =
  | { ok: true; data: T; alreadyDeleted?: boolean }
  | {
      ok: false;
      kind: "validation" | "unavailable" | "timeout" | "rejected";
      message: string;
      fieldErrors?: FieldErrors;
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
