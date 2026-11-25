import type { NextRequest } from "next/server";
import { isUuid } from "@/lib/bucket";
import { ApiError } from "@/lib/errors";
import {
  photoErrorResponse,
  photoProxyResponse,
  type PhotoFetchResult,
  type ProxyResponse,
} from "@/lib/photo";
import { getPlotPhoto } from "@/lib/registry";

// Same-origin proxy for plot photos: the browser never talks to the registry or S3.
// Never cached by Next: every request asks the registry (the ETag saves the transfer).
export const dynamic = "force-dynamic";

function send(r: ProxyResponse): Response {
  return new Response(r.body, { status: r.status, headers: r.headers });
}

export async function GET(
  request: NextRequest,
  ctx: RouteContext<"/api/plots/[id]/photo">,
) {
  const { id } = await ctx.params;
  // The id goes into the registry URL: only a real UUID is passed on.
  if (!isUuid(id)) return send(photoErrorResponse(404));

  let result: PhotoFetchResult;
  try {
    result = { ok: true, ...(await getPlotPhoto(id)) };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    result = { ok: false, error: e };
  }
  return send(await photoProxyResponse(result, request.headers.get("if-none-match")));
}
