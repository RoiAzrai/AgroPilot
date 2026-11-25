import { notFound } from "next/navigation";
import { z } from "zod";
import { BucketPanel } from "@/components/bucket-panel";
import { DeletePlotButton } from "@/components/delete-plot-button";
import { ErrorPanel } from "@/components/error-panel";
import { PlanTable } from "@/components/plan-table";
import { PlotHeader } from "@/components/plot-header";
import { PhotoCard } from "@/components/photo-card";
import { PhotoVersionProvider } from "@/components/photo-version";
import { RecommendationHero } from "@/components/recommendation-hero";
import { dateBounds, isRealIsoDate } from "@/lib/bucket";
import { ApiError } from "@/lib/errors";
import { getPlan } from "@/lib/planner";
import { isInSeason } from "@/lib/recommendation";
import { getFarm, getPlot, getPlotPhotoIds } from "@/lib/registry";

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

// The farm name only labels the header. Any registry failure (404 included) means
// "no name", never a broken page; failure() is not used because it 404s the page.
async function loadFarmName(farmId: string): Promise<string | null> {
  try {
    return (await getFarm(farmId)).name;
  } catch (e) {
    if (e instanceof ApiError) return null;
    throw e;
  }
}

// A failed photo list only means "no photo": the card shows the illustration.
async function loadHasPhoto(farmId: string, plotId: string): Promise<boolean> {
  try {
    const ids = await getPlotPhotoIds(farmId);
    return Array.isArray(ids) && ids.includes(plotId);
  } catch {
    return false;
  }
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
    const [farmName, hasPhoto] = await Promise.all([
      loadFarmName(plot.farm_id),
      loadHasPhoto(plot.farm_id, plot.id),
    ]);
    const plan = planResult.status === "fulfilled" ? planResult.value : null;
    const today = plan ? plan.days[0] : null;
    // One computation for both bounds. Null only when the plan failed (no days to read).
    const bounds = today ? dateBounds(today.date, plot.planting_date) : null;
    body = (
      <PhotoVersionProvider>
        <PlotHeader
          plot={plot}
          farmName={farmName}
          stage={today ? today.stage : null}
          hasPhoto={hasPhoto}
        />
        {/* DOM order is the phone order (Today, Plan, Photo). From md the grid areas put
            Photo beside Today and Plan under both. */}
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-6 md:[grid-template-areas:'today_photo'_'plan_plan']">
          {!plan || !today ? (
            <div className="md:[grid-area:today]">
              <ErrorPanel error={planError!} what="plan" detailed />
            </div>
          ) : (
            <>
              <RecommendationHero
                today={today}
                plot={plot}
                fetchedAt={plan.fetched_at}
                planStale={plan.stale}
                className="md:[grid-area:today]"
              >
                {bounds && isInSeason(today) && (
                  <BucketPanel
                    plotId={id}
                    bucketStart={bucketStart}
                    irrigated={irrigated}
                    today={today.date}
                    plantingDate={plot.planting_date}
                    minDate={bounds.min}
                    maxDate={bounds.max}
                  />
                )}
              </RecommendationHero>
              <PlanTable days={plan.days} className="min-w-0 md:[grid-area:plan]" />
            </>
          )}
          <PhotoCard
            plotId={plot.id}
            plotName={plot.name}
            hasPhoto={hasPhoto}
            className="md:[grid-area:photo]"
          />
        </div>
        <div className="md:hidden">
          <DeletePlotButton
            plotId={plot.id}
            plotName={plot.name}
            className="min-h-12 w-full rounded-xl text-[15px]"
          />
        </div>
      </PhotoVersionProvider>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col gap-3.5 px-4 pt-2 pb-6 leading-[normal] md:gap-6 md:px-6 md:pt-6 md:pb-16">
      {body}
    </main>
  );
}
