"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { describeGeoError, roundCoord } from "@/lib/geo";

type Status = { kind: "idle" } | { kind: "locating" } | { kind: "error"; message: string };

export function UseMyLocation({
  onLocate,
}: {
  onLocate: (lat: string, lon: string) => void;
}) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  // This renders only inside the open dialog, so it always runs in the browser.
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) return null;

  function locate() {
    setStatus({ kind: "locating" });
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onLocate(
          String(roundCoord(pos.coords.latitude)),
          String(roundCoord(pos.coords.longitude)),
        );
        setStatus({ kind: "idle" });
      },
      (err) => setStatus({ kind: "error", message: describeGeoError(err.code) }),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 },
    );
  }

  const locating = status.kind === "locating";
  return (
    <div className="flex flex-col gap-2">
      <Button
        type="button"
        variant="outline"
        disabled={locating}
        onClick={locate}
        className="h-11 w-full sm:w-auto sm:self-start"
      >
        {locating ? "Locating…" : "Use my location"}
      </Button>
      {!window.isSecureContext && (
        <p className="text-sm text-muted-foreground">
          Location needs localhost or HTTPS.
        </p>
      )}
      {status.kind === "error" && (
        <p role="status" className="text-sm text-muted-foreground">
          {status.message}
        </p>
      )}
    </div>
  );
}
