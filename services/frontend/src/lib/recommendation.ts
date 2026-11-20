// Pure helpers for the plot page. No server imports: `import type` only, so
// the unit test runs with `npm test` (tsx), without a build step.
import type { DayOut, Plot } from "./types";

export type Recommendation = {
  kind: "water" | "skip" | "not_planted" | "ended";
  headline: string;
  detail: string;
};

export function formatMinutes(n: number): string {
  const total = Math.round(n);
  if (total < 60) return `${total} ${total === 1 ? "minute" : "minutes"}`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

// The decision follows `stage`, not run_minutes alone: zero minutes means
// "no irrigation" in a season and "nothing to do" after it has ended.
export function describeToday(day: DayOut, plot?: Plot): Recommendation {
  switch (day.stage) {
    case "not_planted":
      return {
        kind: "not_planted",
        headline: "Not planted yet",
        detail: plot
          ? `Planting date: ${plot.planting_date}.`
          : "The planting date has not come yet.",
      };
    case "ended":
      return {
        kind: "ended",
        headline: "Season ended",
        detail: "No more irrigation for this crop.",
      };
    default:
      if (day.run_minutes > 0) {
        return {
          kind: "water",
          headline: `Water for ${formatMinutes(day.run_minutes)}`,
          detail: `About ${day.litres.toLocaleString("en-US")} litres, in total for this plot.`,
        };
      }
      return {
        kind: "skip",
        headline: "No irrigation today",
        detail: "The soil still holds enough water.",
      };
  }
}

// "2026-11-18T11:35:00Z" -> "2026-11-18 11:35 UTC"; anything else is shown raw.
export function formatFetchedAt(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z$/.test(value)) {
    return `${value.slice(0, 10)} ${value.slice(11, 16)} UTC`;
  }
  return value;
}

// Days outside the season have no Kc, bucket or irrigation to show.
export function isInSeason(day: DayOut): boolean {
  return day.stage !== "ended" && day.stage !== "not_planted";
}
