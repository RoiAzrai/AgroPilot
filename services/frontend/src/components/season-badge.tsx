import { CalendarClock } from "lucide-react";
import { ApiError } from "@/lib/errors";
import { getPlan } from "@/lib/planner";
import { describeSeason, type SeasonKind } from "@/lib/recommendation";

function GrowingIcon() {
  return (
    <svg aria-hidden width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20v-8M12 12c0-4 3-6 7-6 0 4-3 6-7 6zM12 14c0-3-2-5-6-5 0 3 2 5 6 5z" />
    </svg>
  );
}

function EndedIcon() {
  return (
    <svg aria-hidden width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M5 12h14" />
    </svg>
  );
}

function NotPlantedIcon() {
  return <CalendarClock aria-hidden className="size-[13px]" />;
}

const ICON = {
  not_planted: NotPlantedIcon,
  growing: GrowingIcon,
  ended: EndedIcon,
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
    <span
      className={`inline-flex items-center gap-[5px] rounded-full px-2.5 py-[3px] text-[13px] font-semibold ${
        season.kind === "growing"
          ? "bg-badge-growing text-primary"
          : "bg-badge-ended text-muted-foreground"
      }`}
    >
      <Icon />
      {season.label}
    </span>
  );
}

export function SeasonBadgeSkeleton() {
  return (
    <span
      aria-hidden
      className="inline-block h-[22px] w-24 animate-pulse rounded-full bg-muted motion-reduce:animate-none"
    />
  );
}
