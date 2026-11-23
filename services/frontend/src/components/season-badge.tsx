import { Archive, CalendarClock, Sprout } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/errors";
import { getPlan } from "@/lib/planner";
import { describeSeason, type SeasonKind } from "@/lib/recommendation";

const ICON = {
  not_planted: CalendarClock,
  growing: Sprout,
  ended: Archive,
} satisfies Record<SeasonKind, unknown>;

// No badge when the planner fails or answers something unexpected:
// never a zero, never a guess.
export async function SeasonBadge({ plotId }: { plotId: string }) {
  let stage: string | undefined;
  try {
    const plan = await getPlan(plotId, { days: 1, bucketStart: 1 });
    stage = plan.days[0]?.stage;
  } catch (e) {
    if (e instanceof ApiError) return null;
    throw e;
  }
  const season = stage === undefined ? null : describeSeason(stage);
  if (!season) return null;

  const Icon = ICON[season.kind];
  return (
    <Badge variant={season.kind === "growing" ? "secondary" : "outline"}>
      <Icon aria-hidden />
      {season.label}
    </Badge>
  );
}

export function SeasonBadgeSkeleton() {
  return (
    <span
      aria-hidden
      className="inline-block h-5 w-24 animate-pulse rounded-4xl bg-muted motion-reduce:animate-none"
    />
  );
}
