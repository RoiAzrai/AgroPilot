import { TriangleAlert } from "lucide-react";
import { cells, weekdayLabel, type DayCells } from "@/lib/recommendation";
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
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[12px] font-semibold text-muted-foreground ring-1 ring-border">
      <TriangleAlert aria-hidden className="size-3" />
      Stale forecast
    </span>
  );
}

const orDash = (v: string | null) => v ?? <NotApplicable />;

// Run time and litres in one cell: the run time leads, litres are secondary.
function Irrigation({ c }: { c: DayCells }) {
  if (c.run === null || c.litres === null) return <NotApplicable />;
  return (
    <>
      <span className="font-semibold text-foreground">{c.run}</span>{" "}
      <span className="text-[13px] text-muted-foreground">
        {c.litres.value} {c.litres.unit}
      </span>
    </>
  );
}

const BAND = "border-b border-border bg-card-band font-heading font-semibold text-foreground";

// Desktop (md+) table and phone (PhoneA) list are separate blocks; the hidden one is
// display:none. Labels come from the plan's own dates, never from the browser clock.
export function PlanTable({
  days,
  className = "",
}: {
  days: DayOut[];
  className?: string;
}) {
  return (
    <div className={className}>
      <section
        aria-labelledby="plan-heading-phone"
        className="overflow-hidden rounded-2xl border border-border bg-surface md:hidden"
      >
        <h2 id="plan-heading-phone" className={`${BAND} px-[18px] py-3.5 text-[20px]`}>
          Next 7 days
        </h2>
        <ul>
          {days.map((day, i) => {
            const c = cells(day);
            return (
              <li
                key={day.date}
                className="flex items-center justify-between gap-2.5 border-t border-line px-[18px] py-3 first:border-t-0"
              >
                <div className="flex min-w-0 flex-col items-start gap-1">
                  <span className="text-[15px] font-semibold">
                    {i === 0 ? "Today" : weekdayLabel(day.date)}
                  </span>
                  {day.stale && <StaleBadge />}
                </div>
                <span className="text-right text-[15px]">
                  <Irrigation c={c} />
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section
        aria-labelledby="plan-heading"
        className="hidden overflow-hidden rounded-2xl border border-border bg-surface md:block"
      >
        <h2 id="plan-heading" className={`${BAND} px-5 py-4 text-[22px]`}>
          7-day plan
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[14px] whitespace-nowrap">
            <caption className="sr-only">Irrigation plan for the next 7 days</caption>
            <thead>
              <tr className="bg-card text-muted-foreground">
                <th scope="col" className="px-5 py-3 font-semibold">Day</th>
                <th scope="col" className="px-4 py-3 font-semibold">Stage</th>
                <th scope="col" className="px-4 py-3 font-semibold">Irrigation</th>
                <th scope="col" className="px-4 py-3 font-semibold">ET0 (mm)</th>
                <th scope="col" className="px-4 py-3 font-semibold">Rain (mm)</th>
                <th scope="col" className="px-4 py-3 font-semibold">Kc</th>
                <th scope="col" className="px-5 py-3 font-semibold">Bucket (mm)</th>
              </tr>
            </thead>
            <tbody>
              {days.map((day, i) => {
                const c = cells(day);
                return (
                  <tr key={day.date} className="border-t border-line">
                    <th scope="row" className="px-5 py-3 font-semibold text-foreground">
                      <span className="block">
                        {i === 0 ? `Today, ${day.date}` : day.date}
                      </span>
                      {day.stale && (
                        <span className="mt-1 block font-normal">
                          <StaleBadge />
                        </span>
                      )}
                    </th>
                    <td className="px-4 py-3">{STAGE_LABEL[day.stage]}</td>
                    <td className="px-4 py-3"><Irrigation c={c} /></td>
                    <td className="px-4 py-3">{c.et0.value}</td>
                    <td className="px-4 py-3">{c.rain.value}</td>
                    <td className="px-4 py-3">{orDash(c.kc)}</td>
                    <td className="px-5 py-3">{c.bucket === null ? <NotApplicable /> : c.bucket.value}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
