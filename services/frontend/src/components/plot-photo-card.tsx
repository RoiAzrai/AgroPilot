import { FieldIllustration } from "@/components/field-illustration";
import { PhotoImage } from "@/components/photo-image";

function UploadIcon() {
  return (
    <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
    </svg>
  );
}

function CameraIcon() {
  return (
    <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  );
}

const BUTTON =
  "inline-flex items-center justify-center gap-2 bg-primary font-semibold text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60";

function NoPhoto() {
  return (
    <div className="relative h-full">
      <FieldIllustration height="100%" />
      <span className="absolute top-2.5 left-2.5 rounded-full bg-[rgba(251,246,236,0.94)] px-2.5 py-1 text-[12px] font-semibold text-muted-foreground md:hidden">
        No photo yet
      </span>
      <div className="absolute bottom-3 left-3 hidden flex-col gap-0.5 rounded-[10px] bg-[rgba(251,246,236,0.94)] px-3 py-2 md:flex">
        <span className="text-[14px] font-semibold text-foreground">No photo yet</span>
        <span className="text-[12px] text-muted-foreground">
          Sample picture. Upload a photo of this plot.
        </span>
      </div>
    </div>
  );
}

// Upload is not wired yet, so both buttons are disabled.
// Desktop (Plot design): band with title and button, image inside the padding.
// Phone (PhoneA): full-bleed image with a chip, big button under it.
// `photoUrl` only when the registry lists a photo for this plot.
export function PlotPhotoCard({
  photoUrl,
  plotName,
  className = "",
}: {
  photoUrl?: string;
  plotName: string;
  className?: string;
}) {
  return (
    <section
      aria-labelledby="photo-heading"
      className={`flex flex-col overflow-hidden rounded-2xl border border-border bg-card ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 md:border-b md:border-border md:bg-card-band md:px-[18px] md:py-3.5">
        <h2
          id="photo-heading"
          className="sr-only font-heading text-[20px] font-semibold md:not-sr-only"
        >
          Plot photo
        </h2>
        <button
          type="button"
          disabled
          aria-disabled="true"
          className={`${BUTTON} hidden min-h-11 rounded-[10px] px-4 py-2.5 text-[14px] md:inline-flex`}
        >
          <UploadIcon />
          {photoUrl ? "Replace photo" : "Upload photo"}
        </button>
      </div>

      <div className="md:px-[18px] md:pt-4">
        <div className="relative h-[190px] overflow-hidden md:h-[230px] md:rounded-xl">
          {photoUrl ? (
            <PhotoImage
              src={photoUrl}
              alt={`Photo of plot ${plotName}`}
              className="h-full"
              fallback={<NoPhoto />}
            />
          ) : (
            <NoPhoto />
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5 px-[18px] py-3.5 md:pt-2 md:pb-4">
        <button
          type="button"
          disabled
          aria-disabled="true"
          className={`${BUTTON} min-h-[52px] rounded-xl text-[16px] md:hidden`}
        >
          <CameraIcon />
          Take or upload photo
        </button>
        <span className="text-center text-[12px] text-muted-foreground md:hidden">
          JPEG, PNG or WebP, up to 5 MB
        </span>
        <span className="hidden text-[13px] text-muted-foreground md:inline">
          JPEG, PNG or WebP, up to 5 MB.
        </span>
      </div>
    </section>
  );
}
