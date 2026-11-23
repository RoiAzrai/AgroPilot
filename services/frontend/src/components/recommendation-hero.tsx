import { Clock } from "lucide-react";
import {
  describeToday,
  formatFetchedAt,
} from "@/lib/recommendation";
import type { DayOut, Plot } from "@/lib/types";

export function RecommendationHero({
  today,
  plot,
  fetchedAt,
  planStale,
}: {
  today: DayOut;
  plot: Plot;
  fetchedAt: string;
  planStale: boolean;
}) {
  const rec = describeToday(today, plot);
  const water = rec.kind === "water";
  const stale = today.stale || planStale;

  return (
    <section
      aria-labelledby="today-heading"
      className={`flex flex-col gap-3 rounded-2xl p-5 sm:p-8 ${
        water
          ? "bg-primary text-primary-foreground"
          : "bg-card ring-1 ring-foreground/15"
      }`}
    >
      <h2
        id="today-heading"
        className={`text-base font-semibold ${
          water ? "text-primary-foreground/85" : "text-muted-foreground"
        }`}
      >
        {`Today, ${today.date}`}
      </h2>
      <p className="text-4xl leading-[1.05] font-extrabold tracking-tight text-balance sm:text-6xl">
        {rec.headline}
      </p>
      <p
        className={`text-lg ${
          water ? "text-primary-foreground/90" : "text-muted-foreground"
        }`}
      >
        {rec.detail}
      </p>
      {stale && (
        <p className="mt-1 flex items-center gap-2 text-sm font-medium">
          <Clock aria-hidden className="size-4 shrink-0" />
          Based on an old forecast (updated {formatFetchedAt(fetchedAt)})
        </p>
      )}
    </section>
  );
}
