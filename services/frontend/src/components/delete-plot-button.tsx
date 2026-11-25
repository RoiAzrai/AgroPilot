"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { deletePlotAction } from "@/app/actions";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

// Outline button in the design's red (#8A3B2E). `className` sets the size per placement.
const TRIGGER =
  "inline-flex items-center justify-center rounded-[10px] border-[1.5px] border-destructive bg-transparent px-4 font-semibold text-destructive transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

export function DeletePlotButton({
  plotId,
  plotName,
  className = "",
}: {
  plotId: string;
  plotName: string;
  className?: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const cancelRef = useRef<HTMLButtonElement>(null);

  function onDelete() {
    setError(null);
    startTransition(async () => {
      const result = await deletePlotAction(plotId);
      if (result.ok) {
        toast.success(
          result.alreadyDeleted ? "This plot was already deleted" : "Plot deleted",
        );
        router.push("/");
      } else {
        setError(result.message);
      }
    });
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (pending) return;
        setError(null);
        setOpen(next);
      }}
    >
      <AlertDialogTrigger
        render={<button type="button" className={`${TRIGGER} ${className}`} />}
      >
        Delete plot
      </AlertDialogTrigger>
      <AlertDialogContent initialFocus={cancelRef}>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete &quot;{plotName}&quot;?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the plot. This can&apos;t be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel
            ref={cancelRef}
            disabled={pending}
            className="h-11 w-full sm:w-auto"
          >
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={pending}
            onClick={onDelete}
            className="h-11 w-full sm:w-auto"
          >
            {pending ? "Deleting…" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
