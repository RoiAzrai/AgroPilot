import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { DeletePlotButton } from "@/components/delete-plot-button";
import { PlotThumbnail } from "@/components/plot-thumbnail";
import { SeasonBadge } from "@/components/season-badge";
import { describeSeason } from "@/lib/recommendation";
import type { Plot } from "@/lib/types";

function cropLabel(cropId: string): string {
  const text = cropId.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const EYEBROW = "text-[12px] font-semibold text-muted-foreground uppercase";

// Desktop (md+) and phone (PhoneA) headers differ in layout, so each is its own block.
// The hidden one is display:none, so it is also out of the accessibility tree.
// `stage` is null when the plan is unavailable: no season pill or word then.
// `hasPhoto` (phone thumbnail): the registry lists a photo for this plot.
export function PlotHeader({
  plot,
  farmName,
  stage,
  hasPhoto,
}: {
  plot: Plot;
  farmName: string | null;
  stage: string | null;
  hasPhoto: boolean;
}) {
  const crop = cropLabel(plot.crop_id);
  const area = `${plot.area_m2.toLocaleString("en-US")} m²`;
  const season = stage === null ? null : describeSeason(stage);

  return (
    <>
      <Link
        href="/"
        className="-ml-1 inline-flex min-h-12 w-fit items-center gap-1 rounded-md pr-2 text-[15px] font-medium text-primary no-underline hover:text-[#1E3322] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:min-h-11 md:gap-1.5"
      >
        <ChevronLeft aria-hidden className="size-[18px] md:size-4" />
        All farms
      </Link>

      <header className="hidden flex-wrap items-start justify-between gap-4 md:flex">
        <div className="flex flex-col gap-2">
          <span className={`${EYEBROW} tracking-[1px]`}>
            {farmName === null ? "Farm" : `Farm · ${farmName}`}
          </span>
          <h1 className="font-heading text-[44px] leading-[1.1] font-bold text-primary">
            {plot.name}
          </h1>
          <div className="flex flex-wrap items-center gap-3 text-[15px] text-muted-foreground">
            <span>{crop}</span>
            {stage !== null && <SeasonBadge stage={stage} />}
            <span>{area}</span>
            <span>Planted {plot.planting_date}</span>
          </div>
        </div>
        <DeletePlotButton
          plotId={plot.id}
          plotName={plot.name}
          className="min-h-11 py-2.5 text-[14px]"
        />
      </header>

      <header className="flex items-center gap-3 md:hidden">
        <div className="size-16 flex-none overflow-hidden rounded-xl">
          <PlotThumbnail plotId={plot.id} hasPhoto={hasPhoto} />
        </div>
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className={`${EYEBROW} tracking-[0.8px]`}>{farmName ?? "Farm"}</span>
          <h1 className="font-heading text-[30px] leading-[1.1] font-bold text-primary">
            {plot.name}
          </h1>
          <span className="text-[14px] text-muted-foreground">
            {[crop, season?.label, area].filter(Boolean).join(" · ")}
          </span>
        </div>
      </header>
    </>
  );
}
