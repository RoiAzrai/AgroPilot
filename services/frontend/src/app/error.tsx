"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "cn";

export default function ErrorPage({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  // Only the digest is shown, never the message or stack (may leak internals).
  const digest =
    error instanceof Error &&
    "digest" in error &&
    typeof error.digest === "string" &&
    error.digest
      ? error.digest
      : null;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-10 sm:py-14">
      <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
        Something went wrong
      </h1>
      <p className="max-w-prose text-lg text-muted-foreground">
        This page hit an unexpected error. You can try again or go back to your
        farms.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button type="button" className="h-11" onClick={() => retry()}>
          Try again
        </Button>
        <Link
          href="/"
          className={cn(buttonVariants({ variant: "outline" }), "h-11")}
        >
          Back to farms
        </Link>
      </div>
      {digest && (
        <p className="break-all text-xs text-muted-foreground">
          Error ID: {digest}
        </p>
      )}
    </main>
  );
}
