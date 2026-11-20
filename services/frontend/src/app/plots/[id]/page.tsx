import { Suspense } from "react";
import { notFound } from "next/navigation";
import { z } from "zod";
import { ErrorPanel } from "@/components/error-panel";
import { PlanTable } from "@/components/plan-table";
import { PlotHeader } from "@/components/plot-header";
import { RecommendationHero } from "@/components/recommendation-hero";
import { StatusLine } from "@/components/status-line";
import { ApiError } from "@/lib/errors";
import { getPlan } from "@/lib/planner";
import { getPlot } from "@/lib/registry";

export const dynamic = "force-dynamic";

const DEFAULT_BUCKET_START = 1;

// Temporary test hook: step 5 replaces it with a button.
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
  const bucketStart = parseBucketStart((await searchParams).bucket_start);

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
    body = (
      <>
        <PlotHeader plot={plot} />
        {planResult.status === "rejected" ? (
          <ErrorPanel error={planError!} what="plan" detailed />
        ) : (
          <>
            {bucketStart !== DEFAULT_BUCKET_START && (
              <p className="text-sm text-muted-foreground">
                {`Assumed bucket level: ${Number((bucketStart * 100).toFixed(1))}%`}
              </p>
            )}
            <RecommendationHero
              today={planResult.value.days[0]}
              plot={plot}
              fetchedAt={planResult.value.fetched_at}
              planStale={planResult.value.stale}
            />
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
