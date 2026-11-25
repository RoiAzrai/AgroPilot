"use client";

import { FieldIllustration } from "@/components/field-illustration";
import { PhotoImage } from "@/components/photo-image";
import { usePhotoVersion } from "@/components/photo-version";
import { photoUrl } from "@/lib/photo";

// Phone header thumbnail (64px). Decorative: the photo card shows the same photo with
// its alt text.
export function PlotThumbnail({ plotId, hasPhoto }: { plotId: string; hasPhoto: boolean }) {
  const { version } = usePhotoVersion();
  if (!hasPhoto && version === null) return <FieldIllustration height={64} />;
  return (
    <PhotoImage
      src={photoUrl(plotId, version ?? undefined)}
      alt=""
      className="h-16"
      fallback={<FieldIllustration height={64} />}
    />
  );
}
