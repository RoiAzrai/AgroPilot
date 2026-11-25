// Pure helpers for plot photos. No server imports (`import type` only), so they run
// in client components and in `npm test` (tsx). The ETag uses Web Crypto, which
// exists in Node and in browsers.
import type { ActionResult, FailureLike } from "./action-result";

export const PHOTO_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;

// The registry's limit (registry-service routers/plots.py, MAX_PHOTO_BYTES).
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

export function isPhotoType(type: string): boolean {
  return (PHOTO_CONTENT_TYPES as readonly string[]).includes(type);
}

export type PhotoCheck = { ok: true } | { ok: false; message: string };

// Same rules as the registry, checked before sending (client) and again in the action.
export function validatePhotoFile(file: { type: string; size: number }): PhotoCheck {
  if (!isPhotoType(file.type)) {
    return { ok: false, message: "Use a JPEG, PNG or WebP photo." };
  }
  if (file.size === 0) return { ok: false, message: "This file is empty. Choose another photo." };
  if (file.size > MAX_PHOTO_BYTES) {
    return { ok: false, message: "This photo is larger than 5 MB. Choose a smaller one." };
  }
  return { ok: true };
}

// Fits the long side into `max` keeping the aspect ratio. Never upscales.
export function scaledSize(
  width: number,
  height: number,
  max = 2048,
): { width: number; height: number } {
  const long = Math.max(width, height);
  if (long <= max) return { width, height };
  const k = max / long;
  return {
    width: Math.max(1, Math.round(width * k)),
    height: Math.max(1, Math.round(height * k)),
  };
}

const MSG_TYPE = "Use a JPEG, PNG or WebP photo up to 5 MB.";
const MSG_UNAVAILABLE = "Photo storage unavailable. Nothing changed. Try again.";
const MSG_TIMEOUT = "No answer in time. The photo may not have been saved. Try again.";
const MSG_GENERIC = "The photo could not be saved. Try again.";

// Upload failures in the shape the other actions return. Only the registry's 422 detail
// is shown (it is written for users, e.g. "Photo is larger than 5 MB"); never other details.
export function photoFailureToResult(f: FailureLike): ActionResult<never> {
  if (f.kind === "timeout") return { ok: false, kind: "timeout", message: MSG_TIMEOUT };
  if (f.kind === "network" || f.status === 503) {
    return { ok: false, kind: "unavailable", message: MSG_UNAVAILABLE };
  }
  if (f.status === 404) {
    return { ok: false, kind: "rejected", message: "This plot no longer exists.", plotGone: true };
  }
  if (f.status === 422) {
    // http.ts falls back to "422 Unprocessable Entity" when there is no problem detail.
    const detail = f.detail.trim();
    const real = detail !== "" && !/^\d{3}\b/.test(detail);
    return { ok: false, kind: "validation", message: real ? `${MSG_TYPE} (${detail})` : MSG_TYPE };
  }
  return { ok: false, kind: "unavailable", message: MSG_GENERIC };
}

// Same-origin proxy URL. `version` changes the URL after an upload so the <img> reloads.
export function photoUrl(plotId: string, version?: number | string): string {
  const path = `/api/plots/${encodeURIComponent(plotId)}/photo`;
  return version === undefined ? path : `${path}?v=${encodeURIComponent(String(version))}`;
}

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Strong ETag: the quoted base64url SHA-256 of the bytes.
export async function computeEtag(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `"${base64url(new Uint8Array(digest))}"`;
}

// If-None-Match uses weak comparison (RFC 9110 13.1.2): W/ is ignored, "*" matches any
// current representation, and the header may list several tags separated by commas.
export function ifNoneMatchMatches(header: string | null, etag: string): boolean {
  if (!header) return false;
  const opaque = (tag: string) => tag.trim().replace(/^W\//, "").replace(/^"(.*)"$/, "$1");
  const target = opaque(etag);
  return header.split(",").some((part) => {
    const tag = part.trim();
    return tag === "*" || (tag !== "" && opaque(tag) === target);
  });
}

export type ProxyResponse = {
  status: number;
  headers: Record<string, string>;
  body: Uint8Array<ArrayBuffer> | string | null;
};

export type PhotoFetchResult =
  | { ok: true; bytes: Uint8Array<ArrayBuffer>; contentType: string }
  | { ok: false; error: FailureLike };

// Short public texts only: never the registry's detail, a URL or an S3 key.
const ERROR_TEXT: Record<number, string> = {
  404: "Photo not found",
  502: "Photo could not be loaded",
  503: "Photo storage unavailable",
  504: "Photo request timed out",
};

export function photoErrorResponse(status: 404 | 502 | 503 | 504): ProxyResponse {
  const headers: Record<string, string> = {
    "Content-Type": "text/plain; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  };
  if (status === 503) headers["Retry-After"] = "5";
  return { status, headers, body: ERROR_TEXT[status] };
}

function allowedType(raw: string): string | null {
  const type = raw.split(";")[0].trim().toLowerCase();
  return isPhotoType(type) ? type : null;
}

// Maps the registry's answer to what the proxy route sends, so it is testable without Next.
export async function photoProxyResponse(
  result: PhotoFetchResult,
  ifNoneMatch: string | null,
): Promise<ProxyResponse> {
  if (!result.ok) {
    const { error } = result;
    if (error.kind === "timeout") return photoErrorResponse(504);
    if (error.kind === "network" || error.status === 503) return photoErrorResponse(503);
    if (error.status === 404) return photoErrorResponse(404);
    return photoErrorResponse(502);
  }
  const type = allowedType(result.contentType);
  if (type === null) return photoErrorResponse(502);

  const etag = await computeEtag(result.bytes);
  const headers: Record<string, string> = {
    "Cache-Control": "private, no-cache",
    ETag: etag,
    "X-Content-Type-Options": "nosniff",
  };
  if (ifNoneMatchMatches(ifNoneMatch, etag)) {
    return { status: 304, headers, body: null };
  }
  return { status: 200, headers: { ...headers, "Content-Type": type }, body: result.bytes };
}
