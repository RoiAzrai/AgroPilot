import { Suspense } from "react";
import { notFound } from "next/navigation";
import { z } from "zod";
import { ErrorPanel } from "@/components/error-panel";
import { PlanTable } from "@/components/plan-table";
import { PlotHeader } from "@/components/plot-header";
import { BucketPanel } from "@/components/bucket-panel";
import { RecommendationHero } from "@/components/recommendation-hero";
import { StatusLine } from "@/components/status-line";
import { dateBounds, isRealIsoDate } from "@/lib/bucket";
import { ApiError } from "@/lib/errors";
import { getPlan } from "@/lib/planner";
import { isInSeason } from "@/lib/recommendation";
import { getPlot } from "@/lib/registry";

export const dynamic = "force-dynamic";

const DEFAULT_BUCKET_START = 1;

// The bucket panel sets this parameter (and `irrigated`); a hand-written value works too.
// Invalid means full.
const bucketStartSchema = z
  .string()
  .trim()
  .min(1)
  .transform(Number)
  .pipe(z.number().min(0).max(1));

function parseBucketStart(raw: string | string[] | undefined): number {
  const parsed = bucketStartSchema.safeParse(raw);
  return parsed.success ? parsed.data : DEFAULT_BUCKET_START;
}

// `irrigated` only words the summary line. Anything that is not a real date is dropped.
function parseIrrigated(raw: string | string[] | undefined): string | null {
  return typeof raw === "string" && isRealIsoDate(raw) ? raw : null;
}

// A failed call is a 404 (-> notFound), an ApiError to show, or a bug to rethrow.
function failure(result: PromiseSettledResult<unknown>): ApiError | null {
  if (result.status === "fulfilled") return null;
  if (!(result.reason instanceof ApiError)) throw result.reason;
  if (result.reason.status === 404) notFound();
  return result.reason;
}

export default async function PlotPage({
  params,
  searchParams,
}: PageProps<"/plots/[id]">) {
  const { id } = await params;
  const query = await searchParams;
  const bucketStart = parseBucketStart(query.bucket_start);
  const irrigated = parseIrrigated(query.irrigated);

  const [plotResult, planResult] = await Promise.allSettled([
    getPlot(id),
    getPlan(id, { days: 7, bucketStart }),
  ]);
  const plotError = failure(plotResult);
  const planError = failure(planResult);

  let body;
  if (plotResult.status === "rejected") {
    body = <ErrorPanel error={plotError!} what="plot" detailed />;
  } else {
    const plot = plotResult.value;
    // One computation for both bounds. Null only when the plan failed (no days to read).
    const bounds =
      planResult.status === "fulfilled"
        ? dateBounds(planResult.value.days[0].date, plot.planting_date)
        : null;
    body = (
      <>
        <PlotHeader plot={plot} />
        {planResult.status === "rejected" ? (
          <ErrorPanel error={planError!} what="plan" detailed />
        ) : (
          <>
            <RecommendationHero
              today={planResult.value.days[0]}
              plot={plot}
              fetchedAt={planResult.value.fetched_at}
              planStale={planResult.value.stale}
            />
            {bounds && isInSeason(planResult.value.days[0]) && (
              <BucketPanel
                plotId={id}
                bucketStart={bucketStart}
                irrigated={irrigated}
                today={planResult.value.days[0].date}
                plantingDate={plot.planting_date}
                minDate={bounds.min}
                maxDate={bounds.max}
              />
            )}
            <PlanTable days={planResult.value.days} />
          </>
        )}
      </>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 px-4 py-5 sm:gap-8 sm:py-10">
      {body}
      <footer className="mt-4">
        <Suspense
          fallback={
            <p className="text-sm text-muted-foreground">Checking services…</p>
          }
        >
          <StatusLine />
        </Suspense>
      </footer>
    </main>
  );
}
