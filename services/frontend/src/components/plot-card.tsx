import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { Plot } from "@/lib/types";

function cropLabel(cropId: string): string {
  const text = cropId.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function PlotCard({ plot }: { plot: Plot }) {
  return (
    <Link
      href={`/plots/${plot.id}`}
      className="group flex items-start justify-between gap-3 rounded-xl bg-card p-4 ring-1 ring-foreground/15 transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="min-w-0">
        <h3 className="truncate text-lg font-semibold leading-snug">
          {plot.name}
        </h3>
        <p className="text-sm font-medium text-primary">
          {cropLabel(plot.crop_id)}
        </p>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
          <dt className="text-muted-foreground">Area</dt>
          <dd>{plot.area_m2.toLocaleString("en-US")} m²</dd>
          <dt className="text-muted-foreground">Planted</dt>
          <dd>{plot.planting_date}</dd>
        </dl>
      </div>
      <ChevronRight
        aria-hidden
        className="mt-1 size-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
      />
    </Link>
  );
}
