import "server-only";
import { config } from "./config";
import { serviceFetch } from "./http";
import type { PlanOut, SuggestionOut } from "./types";

export const getPlan = (
  id: string,
  opts: { days: number; bucketStart: number },
) =>
  serviceFetch<PlanOut>({
    service: "planner",
    baseUrl: config.plannerUrl,
    path: `/v1/plots/${encodeURIComponent(id)}/plan`,
    timeoutMs: config.plannerTimeoutMs,
    query: { days: opts.days, bucket_start: opts.bucketStart },
  });

export const getBucketSuggestion = (id: string, date: string) =>
  serviceFetch<SuggestionOut>({
    service: "planner",
    baseUrl: config.plannerUrl,
    path: `/v1/plots/${encodeURIComponent(id)}/bucket-suggestion`,
    timeoutMs: config.plannerTimeoutMs,
    query: { last_irrigation: date },
  });
