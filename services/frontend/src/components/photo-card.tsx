"use client";

import { useRef, useState, useTransition, type ChangeEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { uploadPlotPhotoAction } from "@/app/actions";
import { FieldIllustration } from "@/components/field-illustration";
import { PhotoImage } from "@/components/photo-image";
import { usePhotoVersion } from "@/components/photo-version";
import { downscaleToJpeg } from "@/lib/downscale";
import { isPhotoType, photoUrl, validatePhotoFile } from "@/lib/photo";

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

const ACCEPT = "image/jpeg,image/png,image/webp";

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

type Problem = { message: string; plotGone?: boolean };

// Picks a file, re-encodes it in the browser when it can (JPEG, max 2048 px, no EXIF),
// and sends it through the Server Action. Nothing over 5 MB is ever sent: a body over
// the action's limit would throw instead of returning a result.
async function prepare(file: File): Promise<File | Problem> {
  if (!isPhotoType(file.type)) return { message: "Use a JPEG, PNG or WebP photo." };
  const jpeg = await downscaleToJpeg(file);
  // Could not decode: the original is sent as is, if the registry would accept it.
  const out = jpeg ? new File([jpeg], "photo.jpg", { type: "image/jpeg" }) : file;
  const check = validatePhotoFile(out);
  return check.ok ? out : { message: check.message };
}

// Desktop (Plot design): band with title and button, image inside the padding.
// Phone (PhoneA): full-bleed image with a chip, big button under it. Both buttons open
// the same file input. No `capture` attribute, so phones offer camera or gallery.
export function PhotoCard({
  plotId,
  plotName,
  hasPhoto,
  className = "",
}: {
  plotId: string;
  plotName: string;
  hasPhoto: boolean;
  className?: string;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const { version, setVersion } = usePhotoVersion();
  const [preparing, setPreparing] = useState(false);
  const [sending, startSend] = useTransition();
  const [problem, setProblem] = useState<Problem | null>(null);
  const busy = preparing || sending;

  const src = hasPhoto || version !== null ? photoUrl(plotId, version ?? undefined) : null;

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // picking the same file again still fires change
    if (!file || busy) return;
    setProblem(null);
    setPreparing(true);
    let prepared: File | Problem;
    try {
      prepared = await prepare(file);
    } finally {
      setPreparing(false);
    }
    if (!(prepared instanceof File)) {
      setProblem(prepared);
      return;
    }
    const form = new FormData();
    form.append("file", prepared);
    startSend(async () => {
      const result = await uploadPlotPhotoAction(plotId, form);
      if (result.ok) {
        setVersion(Date.now());
        toast.success("Photo saved");
        router.refresh();
      } else {
        setProblem({ message: result.message, plotGone: result.plotGone });
      }
    });
  }

  const open = () => input.current?.click();

  return (
    <section
      aria-labelledby="photo-heading"
      className={`flex flex-col overflow-hidden rounded-2xl border border-border bg-card ${className}`}
    >
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        tabIndex={-1}
        aria-hidden
        onChange={onPick}
      />
      <div className="hidden flex-wrap items-center justify-between gap-3 border-b border-border bg-card-band px-[18px] py-3.5 md:flex">
        <h2
          id="photo-heading"
          className="font-heading text-[20px] font-semibold"
        >
          Plot photo
        </h2>
        <button
          type="button"
          onClick={open}
          disabled={busy}
          aria-busy={busy}
          className={`${BUTTON} min-h-11 rounded-[10px] px-4 py-2.5 text-[14px]`}
        >
          <UploadIcon />
          {src ? "Replace photo" : "Upload photo"}
        </button>
      </div>

      <div className="md:px-[18px] md:pt-4">
        <div className="relative h-[190px] overflow-hidden md:h-[230px] md:rounded-xl">
          {src ? (
            <PhotoImage
              src={src}
              alt={`Photo of plot ${plotName}`}
              className="h-full"
              fallback={<NoPhoto />}
            />
          ) : (
            <NoPhoto />
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5 px-[18px] py-3.5 md:gap-2 md:pt-2 md:pb-4">
        <button
          type="button"
          onClick={open}
          disabled={busy}
          aria-busy={busy}
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
        <p aria-live="polite" className="text-[14px] font-medium text-primary">
          {busy ? "Uploading…" : ""}
        </p>
        {problem && (
          <div
            role="alert"
            className="rounded-[10px] border border-destructive/40 bg-destructive/10 px-3 py-2 text-[14px] text-destructive"
          >
            {problem.message}
            {problem.plotGone && (
              <>
                {" "}
                <Link href="/" className="font-semibold underline underline-offset-4">
                  All farms
                </Link>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
