import { AddPlotDialog } from "@/components/add-plot-dialog";
import { ErrorPanel } from "@/components/error-panel";
import { PlotCard } from "@/components/plot-card";
import type { ApiError } from "@/lib/errors";
import { photoUrl } from "@/lib/photo";
import type { Catalogs, Farm, Plot } from "@/lib/types";

export function FarmSection({
  farm,
  plots,
  error,
  catalogs,
  photoIds,
}: {
  farm: Farm;
  plots: Plot[];
  error?: ApiError;
  catalogs: Catalogs | null;
  photoIds: ReadonlySet<string>;
}) {
  const headingId = `farm-${farm.id}`;
  return (
    <section
      aria-labelledby={headingId}
      className="overflow-hidden rounded-2xl border border-border bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-card-band px-6 py-[18px]">
        <div className="flex flex-col gap-0.5">
          <span className="text-[12px] font-semibold tracking-[1px] text-muted-foreground uppercase">
            Farm
          </span>
          <h2
            id={headingId}
            className="font-heading text-[26px] font-semibold text-foreground"
          >
            {farm.name}
          </h2>
        </div>
        <div className="flex items-center gap-3">
          {!error && (
            <span className="text-[14px] text-muted-foreground">
              {plots.length} {plots.length === 1 ? "plot" : "plots"}
            </span>
          )}
          <AddPlotDialog farm={farm} catalogs={catalogs} />
        </div>
      </div>
      <div className="flex flex-wrap gap-4 p-6">
        {error ? (
          <div className="w-full">
            <ErrorPanel error={error} what="plots" detailed />
          </div>
        ) : plots.length === 0 ? (
          <p className="text-muted-foreground">No plots yet.</p>
        ) : (
          plots.map((plot) => (
            <PlotCard
              key={plot.id}
              plot={plot}
              photoUrl={photoIds.has(plot.id) ? photoUrl(plot.id) : undefined}
            />
          ))
        )}
      </div>
    </section>
  );
}
