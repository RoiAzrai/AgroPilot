import { AddPlotDialog } from "@/components/add-plot-dialog";
import { ErrorPanel } from "@/components/error-panel";
import { PlotCard } from "@/components/plot-card";
import type { ApiError } from "@/lib/errors";
import type { Catalogs, Farm, Plot } from "@/lib/types";

export function FarmSection({
  farm,
  plots,
  error,
  catalogs,
}: {
  farm: Farm;
  plots: Plot[];
  error?: ApiError;
  catalogs: Catalogs | null;
}) {
  const headingId = `farm-${farm.id}`;
  // One "+ Plot" per farm: the primary action of the empty state, otherwise in the header.
  const empty = !error && plots.length === 0;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 id={headingId} className="text-2xl font-bold tracking-tight">
          {farm.name}
        </h2>
        {!empty && <AddPlotDialog farm={farm} catalogs={catalogs} />}
      </div>
      {error ? (
        <ErrorPanel error={error} what="plots" detailed />
      ) : empty ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-muted-foreground">No plots yet.</p>
          <AddPlotDialog farm={farm} catalogs={catalogs} primary />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {plots.map((plot) => (
            <PlotCard key={plot.id} plot={plot} />
          ))}
        </div>
      )}
    </section>
  );
}
