import { z } from "zod";

export const farmSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Enter a farm name")
    .max(100, "Name must be at most 100 characters")
    .refine((v) => !v.includes("\0"), "The name contains an invalid character"),
});

export type FarmInput = z.infer<typeof farmSchema>;

// ---- Plot -----------------------------------------------------------------

export const PLOT_FIELDS = [
  "farm_id",
  "name",
  "crop_id",
  "planting_date",
  "soil_id",
  "emitter_id",
  "area_m2",
  "row_spacing_m",
  "emitter_spacing_m",
  "lat",
  "lon",
] as const;

export type PlotField = (typeof PLOT_FIELDS)[number];

// Same rule as the registry: the date in UTC+14, the earliest zone on Earth.
export function latestDateOnEarth(now: Date = new Date()): string {
  return new Date(now.getTime() + 14 * 3_600_000).toISOString().slice(0, 10);
}

const DECIMAL = /^[+-]?(\d+\.?\d*|\.\d+)$/;

// "12,5" -> 12.5. Rejects "", "1e3", "Infinity", "1 000". Returns null when invalid.
// A comma followed by exactly 3 digits ("1,000") could be a thousands separator, so it is
// rejected instead of silently read as 1.
export function parseDecimal(raw: string): number | null {
  const trimmed = raw.trim();
  if (/,\d{3}$/.test(trimmed)) return null;
  const text = trimmed.replace(",", ".");
  if (!DECIMAL.test(text)) return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function isRealDate(text: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!m) return false;
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (year < 1 || month < 1 || month > 12) return false;
  const last = new Date(0); // setUTCFullYear avoids Date.UTC's 0-99 -> 1900s rule
  last.setUTCFullYear(year, month, 0);
  return day >= 1 && day <= last.getUTCDate();
}

const decimal = (what: string) =>
  z
    .string(`Enter ${what}`)
    .refine((v) => parseDecimal(v) !== null, `${what} must be a number. Use a dot or comma for decimals, no thousands separators.`)
    .transform((v) => parseDecimal(v) as number);

const positive = (what: string) =>
  decimal(what).pipe(z.number().gt(0, `${what} must be greater than 0`));

const choice = (what: string) => z.string(`Choose ${what}`).min(1, `Choose ${what}`);

// Takes raw form strings, outputs the exact 11-field registry payload (real numbers).
// `now` is injectable for tests; it is read at parse time, not at import time.
export function makePlotSchema(now: () => Date = () => new Date()) {
  return z.object({
    farm_id: z.string("Missing farm").min(1, "Missing farm"),
    name: z
      .string("Enter a plot name")
      .trim()
      .min(1, "Enter a plot name")
      .max(100, "Name must be at most 100 characters")
      .refine((v) => !v.includes("\0"), "The name contains an invalid character"),
    area_m2: positive("Area"),
    crop_id: choice("a crop"),
    planting_date: z
      .string("Enter the planting date")
      .refine((v) => isRealDate(v), "Enter a date as YYYY-MM-DD")
      .refine(
        (v) => v <= latestDateOnEarth(now()),
        "The planting date can't be in the future",
      ),
    soil_id: choice("a soil"),
    row_spacing_m: positive("Row spacing"),
    emitter_spacing_m: positive("Emitter spacing"),
    emitter_id: choice("an emitter"),
    lat: decimal("Latitude").pipe(
      z.number().min(-90, "Latitude must be between -90 and 90").max(90, "Latitude must be between -90 and 90"),
    ),
    lon: decimal("Longitude").pipe(
      z.number().min(-180, "Longitude must be between -180 and 180").max(180, "Longitude must be between -180 and 180"),
    ),
  });
}

export const plotSchema = makePlotSchema();

export type PlotPayload = z.output<typeof plotSchema>;

// Missing or non-string entries become undefined, so the schema reports them by key.
export function plotInputFromFormData(formData: FormData): Record<PlotField, unknown> {
  const out = {} as Record<PlotField, unknown>;
  for (const key of PLOT_FIELDS) {
    const v = formData.get(key);
    out[key] = typeof v === "string" ? v : undefined;
  }
  return out;
}

// First message per field: { name: "Enter a plot name", lat: "..." }
export function firstIssuePerField(error: z.ZodError): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? "");
    if (key && !(key in out)) out[key] = issue.message;
  }
  return out;
}
