import { PlotCard } from "@/components/plot-card";
import type { Farm, Plot } from "@/lib/types";

export function FarmSection({ farm, plots }: { farm: Farm; plots: Plot[] }) {
  const headingId = `farm-${farm.id}`;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-2xl font-bold tracking-tight">
        {farm.name}
      </h2>
      {plots.length === 0 ? (
        <p className="text-muted-foreground">No plots yet.</p>
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
