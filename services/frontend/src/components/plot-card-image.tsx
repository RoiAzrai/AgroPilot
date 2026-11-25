import { FieldIllustration } from "@/components/field-illustration";
import { PhotoImage } from "@/components/photo-image";

function NoPhoto() {
  return (
    <div className="relative h-[140px]">
      <FieldIllustration />
      <span className="absolute top-2.5 left-2.5 rounded-full bg-[rgba(251,246,236,0.92)] px-2.5 py-[3px] text-[12px] font-semibold text-muted-foreground">
        No photo yet
      </span>
    </div>
  );
}

// `photoUrl` only for plots the registry lists as having a photo. If the photo fails
// to load, the card falls back to the illustration.
export function PlotCardImage({
  photoUrl,
  plotName,
}: {
  photoUrl?: string;
  plotName: string;
}) {
  if (!photoUrl) return <NoPhoto />;
  return (
    <PhotoImage
      src={photoUrl}
      alt={`Photo of plot ${plotName}`}
      className="h-[140px]"
      fallback={<NoPhoto />}
    />
  );
}
