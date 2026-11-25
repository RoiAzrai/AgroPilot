import "server-only";
import { config } from "./config";
import { serviceFetch } from "./http";
import type { PlotPayload } from "./schemas";
import type { Crop, Emitter, Farm, Plot, Soil } from "./types";

function call<T>(
  path: string,
  extra: { method?: "GET" | "POST" | "DELETE"; body?: unknown } = {},
  query?: Record<string, string | number>,
) {
  return serviceFetch<T>({
    ...extra,
    service: "registry",
    baseUrl: config.registryUrl,
    path,
    timeoutMs: config.registryTimeoutMs,
    query,
  });
}

const get = <T>(path: string, query?: Record<string, string | number>) =>
  call<T>(path, {}, query);

export const listFarms = () => get<Farm[]>("/v1/farms");
export const getFarm = (id: string) =>
  get<Farm>(`/v1/farms/${encodeURIComponent(id)}`);
export const listPlots = (farmId: string) =>
  get<Plot[]>("/v1/plots", { farm_id: farmId });
export const getPlot = (id: string) =>
  get<Plot>(`/v1/plots/${encodeURIComponent(id)}`);
export const listCrops = () => get<Crop[]>("/v1/crops");
export const listSoils = () => get<Soil[]>("/v1/soils");
export const listEmitters = () => get<Emitter[]>("/v1/emitters");
export const createFarm = (name: string) =>
  call<Farm>("/v1/farms", { method: "POST", body: { name } });
export const createPlot = (payload: PlotPayload) =>
  call<Plot>("/v1/plots", { method: "POST", body: payload });
export const deletePlot = (id: string) =>
  call<void>(`/v1/plots/${encodeURIComponent(id)}`, { method: "DELETE" });
