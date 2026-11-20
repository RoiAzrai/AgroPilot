import { CircleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ApiError } from "@/lib/errors";

function reason(error: ApiError): string {
  switch (error.kind) {
    case "network":
      return "can't be reached.";
    case "timeout":
      return "did not answer in time.";
    case "http":
      return `answered with status ${error.status ?? "unknown"}: ${error.detail}`;
  }
}

export function ErrorPanel({ error, what }: { error: ApiError; what: string }) {
  return (
    <Alert variant="destructive">
      <CircleAlert aria-hidden />
      <AlertTitle>Can&apos;t load {what}</AlertTitle>
      <AlertDescription>
        {error.service}-service {reason(error)}
      </AlertDescription>
    </Alert>
  );
}
