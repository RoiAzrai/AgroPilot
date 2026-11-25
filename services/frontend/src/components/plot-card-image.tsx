import { FieldIllustration } from "@/components/field-illustration";

export type PlotCardImageProps = {
  // Reserved for stage 3 (real plot photos). Not read yet: the card always
  // shows the illustration for now.
  photoUrl?: string;
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- photoUrl is used in stage 3
export function PlotCardImage(props: PlotCardImageProps) {
  return (
    <div className="relative h-[140px]">
      <FieldIllustration />
      <span className="absolute top-2.5 left-2.5 rounded-full bg-[rgba(251,246,236,0.92)] px-2.5 py-[3px] text-[12px] font-semibold text-muted-foreground">
        No photo yet
      </span>
    </div>
  );
}
