// Pure helpers for the bucket panel. No server imports: `import type` only, so
// the unit test runs with `npm test` (tsx), without a build step.
// All date math is on YYYY-MM-DD strings and Date.UTC, never `new Date("YYYY-MM-DD")`
// (that parses as UTC midnight but prints in local time) and never `new Date()`.
import type { SuggestionOut } from "./types";

// The most past weather the planner serves (planner-service engine/suggestion.py).
export const MAX_PAST_DAYS = 92;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// The plot id goes into the planner URL, so only a real UUID is passed on.
export function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

export function isRealIsoDate(value: string): boolean {
  const m = ISO_DATE.exec(value);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const t = new Date(Date.UTC(y, mo - 1, d));
  return (
    t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d
  );
}

export function addDays(iso: string, days: number): string {
  if (!isRealIsoDate(iso)) throw new RangeError(`Not a real date: ${iso}`);
  const [y, mo, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, mo - 1, d + days));
  const p = (n: number, width: number) => String(n).padStart(width, "0");
  return `${p(t.getUTCFullYear(), 4)}-${p(t.getUTCMonth() + 1, 2)}-${p(t.getUTCDate(), 2)}`;
}

export type DateBounds = { min: string; max: string };

// Same-format ISO dates sort the same as text and as dates.
export function dateBounds(today: string, plantingDate: string): DateBounds {
  const oldest = addDays(today, -MAX_PAST_DAYS);
  return { min: plantingDate > oldest ? plantingDate : oldest, max: today };
}

export const MSG_FORMAT = "Enter a valid date.";
export const MSG_FUTURE = "That date is in the future.";
export const MSG_TOO_OLD = `That date is too far back. Pick a date within the last ${MAX_PAST_DAYS} days.`;
export const MSG_CROP = "Can't estimate for this plot's crop.";
export const MSG_GENERIC_DATE = "Can't use that date. Try another one.";
export const msgBeforePlanting = (plantingDate?: string) =>
  plantingDate
    ? `That date is before the planting date (${plantingDate}).`
    : "That date is before the planting date.";

// The checks follow the planner's order: format, future, before planting, too old.
// `null` means the date is fine as far as the browser can tell. The planner decides.
export function validateLastIrrigation(
  value: string,
  ctx: { today: string; plantingDate: string },
): string | null {
  if (!isRealIsoDate(value)) return MSG_FORMAT;
  if (value > ctx.today) return MSG_FUTURE;
  if (value < ctx.plantingDate) return msgBeforePlanting(ctx.plantingDate);
  if (value < addDays(ctx.today, -MAX_PAST_DAYS)) return MSG_TOO_OLD;
  return null;
}

// The planner's 422 text has prefixes like "query.last_irrigation:". Map by content,
// never show it. The order matters: "cannot be in the future" must not fall through.
export function friendlyValidationMessage(
  detail: string,
  plantingDate?: string,
): string {
  if (/future/i.test(detail)) return MSG_FUTURE;
  if (/before the planting date/i.test(detail)) return msgBeforePlanting(plantingDate);
  if (/days ago/i.test(detail)) return MSG_TOO_OLD;
  if (/must be a date/i.test(detail)) return MSG_FORMAT;
  if (/coefficients/i.test(detail)) return MSG_CROP;
  return MSG_GENERIC_DATE;
}

export type SuggestionView =
  | {
      kind: "value";
      percent: number; // whole percent, 0..100: what the user sees and what is applied
      apply: number; // percent / 100
      since: string; // the last irrigation date
      days: number; // days of weather behind the estimate
      stale: boolean;
    }
  | { kind: "season_ended" }
  | { kind: "manual"; stale: boolean };

function isFraction(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
}

// A number is shown only for a complete answer: a value, exact, and no reason.
// Everything else that is not a clean season_ended is "manual": no guess.
export function describeSuggestion(out: SuggestionOut): SuggestionView {
  const stale = out.stale === true;
  if (isFraction(out.suggestion) && out.exact === true && out.reason === null) {
    // toFixed first: 0.145 * 100 is 14.499999999999998 and must round to 15
    const percent = Math.round(Number((out.suggestion * 100).toFixed(6)));
    return {
      kind: "value",
      percent,
      apply: percent / 100,
      since: out.last_irrigation,
      days: out.past_days_returned,
      stale,
    };
  }
  if (out.suggestion === null && out.reason === "season_ended") {
    return { kind: "season_ended" };
  }
  return { kind: "manual", stale };
}

export function suggestionText(view: Extract<SuggestionView, { kind: "value" }>): string {
  const basis =
    view.days > 0
      ? `Based on no irrigation since ${view.since} (${view.days} ${view.days === 1 ? "day" : "days"} of weather).`
      : `You irrigated on ${view.since}, so the bucket is assumed full.`;
  return `About ${view.percent}% full. ${basis}`;
}

// 0.74 -> "74%", 1 -> "100%", 0 -> "0%", 0.7416 -> "74.2%"
export function formatBucketPercent(fraction: number): string {
  return `${Number((fraction * 100).toFixed(1))}%`;
}

// "0".."100", integers or decimals. Returns a fraction, or null for anything else.
export function parsePercentInput(raw: string): number | null {
  const text = raw.trim();
  if (!/^\d+(\.\d+)?$/.test(text)) return null;
  const n = Number(text);
  if (!Number.isFinite(n) || n > 100) return null;
  return Number((n / 100).toFixed(6));
}

// A full bucket is the default, so it needs no parameter.
export function bucketUrl(
  pathname: string,
  opts: { bucketStart: number; irrigated?: string },
): string {
  if (opts.bucketStart === 1) return pathname;
  const params = new URLSearchParams({ bucket_start: String(opts.bucketStart) });
  if (opts.irrigated !== undefined && isRealIsoDate(opts.irrigated)) {
    params.set("irrigated", opts.irrigated);
  }
  return `${pathname}?${params.toString()}`;
}
