import type { ReactNode } from "react";
import { Clock } from "lucide-react";
import {
  describeToday,
  formatFetchedAt,
} from "@/lib/recommendation";
import type { DayOut, Plot } from "@/lib/types";

// Always a white card (design): the headline carries the decision, not a fill colour.
// `children` is the bucket row, shown at the bottom of the card.
export function RecommendationHero({
  today,
  plot,
  fetchedAt,
  planStale,
  className = "",
  children,
}: {
  today: DayOut;
  plot: Plot;
  fetchedAt: string;
  planStale: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const rec = describeToday(today, plot);
  const stale = today.stale || planStale;

  return (
    <section
      aria-labelledby="today-heading"
      className={`flex flex-col gap-2 rounded-2xl border border-border bg-surface p-[18px] md:gap-3.5 md:p-6 ${className}`}
    >
      <h2
        id="today-heading"
        className="text-[12px] font-semibold tracking-[0.8px] text-muted-foreground uppercase md:tracking-[1px]"
      >
        {`Today, ${today.date}`}
      </h2>
      <div className="flex flex-col gap-2 md:gap-1.5">
        <p
          className={`font-heading text-[36px] leading-[1.1] font-bold text-balance md:text-[40px] ${
            rec.kind === "ended" ? "text-muted-foreground" : "text-primary"
          }`}
        >
          {rec.headline}
        </p>
        <p className="text-[16px] text-foreground md:text-[17px]">{rec.detail}</p>
      </div>
      {stale && (
        <p className="flex items-center gap-2 text-[14px] font-medium text-muted-foreground">
          <Clock aria-hidden className="size-4 shrink-0" />
          Based on an old forecast (updated {formatFetchedAt(fetchedAt)})
        </p>
      )}
      {children}
    </section>
  );
}
