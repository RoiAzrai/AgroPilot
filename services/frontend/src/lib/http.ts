import "server-only";
import { ApiError, type ServiceName } from "./errors";
import type { Problem } from "./types";

type Options = {
  service: ServiceName;
  baseUrl: string;
  path: string;
  timeoutMs: number;
  query?: Record<string, string | number>;
};

async function readProblem(res: Response): Promise<Problem | undefined> {
  if (!res.headers.get("content-type")?.includes("application/problem+json")) {
    return undefined;
  }
  try {
    return (await res.json()) as Problem;
  } catch {
    return undefined;
  }
}

// Failure is decided by the HTTP status. `code` is only carried along for display:
// the registry answers code UNAVAILABLE even on a 500.
export async function serviceFetch<T>(opts: Options): Promise<T> {
  const url = new URL(opts.baseUrl + opts.path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    url.searchParams.set(k, String(v));
  }

  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      headers: { accept: "application/json, application/problem+json" },
      signal: AbortSignal.timeout(opts.timeoutMs),
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "TimeoutError";
    throw new ApiError({
      service: opts.service,
      kind: timedOut ? "timeout" : "network",
      detail: timedOut
        ? `No answer within ${opts.timeoutMs} ms`
        : "Could not reach the service",
    });
  }

  if (!res.ok) {
    const problem = await readProblem(res);
    throw new ApiError({
      service: opts.service,
      kind: "http",
      status: res.status,
      code: problem?.code,
      detail: problem?.detail ?? `${res.status} ${res.statusText}`.trim(),
    });
  }

  return (await res.json()) as T;
}
