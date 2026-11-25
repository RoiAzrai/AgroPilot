"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

// A plot photo through the proxy route. If it fails to load (404, 503, broken file),
// the `fallback` (illustration with "No photo yet") is shown instead.
export function PhotoImage({
  src,
  alt,
  className = "",
  fallback,
}: {
  src: string;
  alt: string;
  className?: string;
  fallback: ReactNode;
}) {
  const ref = useRef<HTMLImageElement>(null);
  // Keyed by src: a new URL (after an upload) gets a fresh try.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  // An error that fired before hydration never reaches onError: check once mounted.
  useEffect(() => {
    const img = ref.current;
    if (img && img.complete && img.naturalWidth === 0) setFailedSrc(src);
  }, [src]);

  if (failedSrc === src) return fallback;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- the proxy route already serves the right bytes; next/image would re-encode them
    <img
      ref={ref}
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailedSrc(src)}
      className={`block w-full object-cover ${className}`}
    />
  );
}
