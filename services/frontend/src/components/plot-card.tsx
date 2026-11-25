import { Suspense } from "react";
import Link from "next/link";
import { PlotCardImage } from "@/components/plot-card-image";
import {
  PlotSeasonBadge,
  SeasonBadgeSkeleton,
} from "@/components/season-badge";
import type { Plot } from "@/lib/types";

function cropLabel(cropId: string): string {
  const text = cropId.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function PlotCard({ plot, photoUrl }: { plot: Plot; photoUrl?: string }) {
  return (
    <Link
      href={`/plots/${plot.id}`}
      className="flex max-w-[340px] flex-[1_1_260px] flex-col overflow-hidden rounded-[14px] border border-border bg-surface text-foreground no-underline transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
    >
      <PlotCardImage photoUrl={photoUrl} plotName={plot.name} />
      <div className="flex flex-col gap-2.5 px-[18px] pt-3.5 pb-4">
        <h3 className="text-[18px] font-semibold">{plot.name}</h3>
        <div className="flex min-h-[22px] flex-wrap items-center gap-2">
          <span className="text-[15px] text-muted-foreground">
            {cropLabel(plot.crop_id)}
          </span>
          <Suspense fallback={<SeasonBadgeSkeleton />}>
            <PlotSeasonBadge plotId={plot.id} />
          </Suspense>
        </div>
        <div className="flex gap-4 border-t border-line pt-2.5 text-[14px] text-muted-foreground">
          <span>{plot.area_m2.toLocaleString("en-US")} m²</span>
          <span>Planted {plot.planting_date}</span>
        </div>
      </div>
    </Link>
  );
}
