import { TriangleAlert } from "lucide-react";
import { cells, type Quantity } from "@/lib/recommendation";
import type { DayOut, Stage } from "@/lib/types";

const STAGE_LABEL: Record<Stage, string> = {
  not_planted: "Not planted yet",
  ini: "Initial growth",
  dev: "Development",
  mid: "Mid-season",
  late: "Late season",
  ended: "Season ended",
};

function NotApplicable() {
  return (
    <span role="img" aria-label="Not applicable">
      —
    </span>
  );
}

function StaleBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-chart-4/15 px-1.5 py-0.5 text-xs font-medium text-foreground ring-1 ring-chart-4/50">
      <TriangleAlert aria-hidden className="size-3 text-chart-4" />
      Stale forecast
    </span>
  );
}

const orDash = (v: string | null) => v ?? <NotApplicable />;

const orDashQuantity = (q: Quantity | null) =>
  q ? `${q.value} ${q.unit}` : <NotApplicable />;

export function PlanTable({ days }: { days: DayOut[] }) {
  return (
    <section aria-labelledby="plan-heading" className="flex flex-col gap-3">
      <h2 id="plan-heading" className="text-2xl font-bold tracking-tight">
        Next 7 days
      </h2>

      <ul className="flex flex-col gap-3 md:hidden">
        {days.map((day) => {
          const c = cells(day);
          return (
            <li
              key={day.date}
              className="flex flex-col gap-3 rounded-xl bg-card p-4 ring-1 ring-foreground/15"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold">{day.date}</p>
                  <p className="text-sm text-muted-foreground">
                    {STAGE_LABEL[day.stage]}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl leading-tight font-extrabold">
                    {orDash(c.run)}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {orDashQuantity(c.litres)}
                  </p>
                </div>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">ET0</dt>
                <dd className="text-right">{orDashQuantity(c.et0)}</dd>
                <dt className="text-muted-foreground">Rain</dt>
                <dd className="text-right">{orDashQuantity(c.rain)}</dd>
                <dt className="text-muted-foreground">Kc</dt>
                <dd className="text-right">{orDash(c.kc)}</dd>
                <dt className="text-muted-foreground">Bucket</dt>
                <dd className="text-right">{orDashQuantity(c.bucket)}</dd>
              </dl>
              {day.stale && (
                <div>
                  <StaleBadge />
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <div className="hidden overflow-x-auto rounded-xl bg-card ring-1 ring-foreground/15 md:block">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Irrigation plan for the next 7 days</caption>
          <thead className="text-muted-foreground">
            <tr className="border-b border-border">
              <th scope="col" className="px-4 py-3 font-medium">Date</th>
              <th scope="col" className="px-4 py-3 font-medium">Stage</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Run time</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Litres (L)</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">ET0 (mm)</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Rain (mm)</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Kc</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Bucket (mm)</th>
            </tr>
          </thead>
          <tbody>
            {days.map((day) => {
              const c = cells(day);
              return (
                <tr
                  key={day.date}
                  className="border-b border-border last:border-b-0"
                >
                  <th scope="row" className="px-4 py-3 font-semibold whitespace-nowrap">
                    <span className="block">{day.date}</span>
                    {day.stale && (
                      <span className="mt-1 block font-normal">
                        <StaleBadge />
                      </span>
                    )}
                  </th>
                  <td className="px-4 py-3">{STAGE_LABEL[day.stage]}</td>
                  <td className="px-4 py-3 text-right text-base font-bold whitespace-nowrap">{orDash(c.run)}</td>
                  <td className="px-4 py-3 text-right">{c.litres === null ? <NotApplicable /> : c.litres.value}</td>
                  <td className="px-4 py-3 text-right">{c.et0.value}</td>
                  <td className="px-4 py-3 text-right">{c.rain.value}</td>
                  <td className="px-4 py-3 text-right">{orDash(c.kc)}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">{c.bucket === null ? <NotApplicable /> : c.bucket.value}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
