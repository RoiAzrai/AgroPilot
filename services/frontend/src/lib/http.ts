import "server-only";
import { ApiError, type ServiceName } from "./errors";
import type { Problem } from "./types";

type Options = {
  service: ServiceName;
  baseUrl: string;
  path: string;
  timeoutMs: number;
  query?: Record<string, string | number>;
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
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

const JSON_ACCEPT = "application/json, application/problem+json";

function timeoutOrNetwork(opts: Options, err: unknown): ApiError {
  const timedOut = err instanceof DOMException && err.name === "TimeoutError";
  return new ApiError({
    service: opts.service,
    kind: timedOut ? "timeout" : "network",
    detail: timedOut
      ? `No answer within ${opts.timeoutMs} ms`
      : "Could not reach the service",
  });
}

// A FormData body is passed as is: fetch writes the multipart Content-Type with its
// boundary. Any other body is sent as JSON.
function encodeBody(body: unknown): { body?: BodyInit; contentType?: string } {
  if (body === undefined) return {};
  if (body instanceof FormData) return { body };
  return { body: JSON.stringify(body), contentType: "application/json" };
}

// Sends the request and returns the response if its status is 2xx.
// Failure is decided by the HTTP status. `code` is only carried along for display:
// the registry answers code UNAVAILABLE even on a 500.
async function send(opts: Options, accept: string): Promise<Response> {
  const url = new URL(opts.baseUrl + opts.path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    url.searchParams.set(k, String(v));
  }
  const encoded = encodeBody(opts.body);

  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      cache: "no-store",
      headers: {
        accept,
        ...(encoded.contentType && { "content-type": encoded.contentType }),
      },
      body: encoded.body,
      signal: AbortSignal.timeout(opts.timeoutMs),
    });
  } catch (err) {
    throw timeoutOrNetwork(opts, err);
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
  return res;
}

export async function serviceFetch<T>(opts: Options): Promise<T> {
  const res = await send(opts, JSON_ACCEPT);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type BinaryBody = { bytes: Uint8Array<ArrayBuffer>; contentType: string };

// For binary answers (plot photos): the raw bytes and the Content-Type as sent.
// The body is read under the same timeout, so a stalled download is a timeout too.
export async function serviceFetchBinary(opts: Options): Promise<BinaryBody> {
  const res = await send(opts, "image/*, application/problem+json");
  let buffer: ArrayBuffer;
  try {
    buffer = await res.arrayBuffer();
  } catch (err) {
    throw timeoutOrNetwork(opts, err);
  }
  return {
    bytes: new Uint8Array(buffer),
    contentType: res.headers.get("content-type") ?? "",
  };
}
