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

// Used only with `detailed`: a title and a sentence per kind of failure.
// 4xx = the request was refused, 5xx = the service failed,
// timeout and network have no HTTP status.
function explain(error: ApiError, what: string): { title: string; hint: string } {
  if (error.kind === "network") {
    return {
      title: `Can't reach the ${what} service`,
      hint: "Check that the service is running, then reload the page.",
    };
  }
  if (error.kind === "timeout") {
    return {
      title: `The ${what} took too long to load`,
      hint: "The service is slow right now. Reload the page in a moment.",
    };
  }
  if ((error.status ?? 0) >= 500) {
    return {
      title: `The ${what} is unavailable right now`,
      hint: "The service has a problem on its side. Reload the page in a moment.",
    };
  }
  return {
    title: `The ${what} request was refused`,
    hint: "The service did not accept the request. Go back to the plots and try again.",
  };
}

export function ErrorPanel({
  error,
  what,
  detailed = false,
}: {
  error: ApiError;
  what: string;
  detailed?: boolean;
}) {
  const info = detailed ? explain(error, what) : null;
  return (
    <Alert variant="destructive">
      <CircleAlert aria-hidden />
      <AlertTitle>{info ? info.title : <>Can&apos;t load {what}</>}</AlertTitle>
      <AlertDescription>
        {error.service}-service {reason(error)}
        {info && <span className="mt-1 block">{info.hint}</span>}
      </AlertDescription>
    </Alert>
  );
}
