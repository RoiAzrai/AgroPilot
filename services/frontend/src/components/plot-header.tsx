import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import type { Plot } from "@/lib/types";

function cropLabel(cropId: string): string {
  const text = cropId.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function PlotHeader({ plot }: { plot: Plot }) {
  return (
    <header className="flex flex-col gap-1">
      <Link
        href="/"
        className="-ml-1 inline-flex w-fit items-center gap-0.5 rounded-md py-1 pr-2 text-sm font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronLeft aria-hidden className="size-4" />
        All plots
      </Link>
      <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">
        {plot.name}
      </h1>
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-primary">
          {cropLabel(plot.crop_id)}
        </span>
        , {plot.area_m2.toLocaleString("en-US")} m², planted {plot.planting_date}
      </p>
    </header>
  );
}
