import "server-only";
import { config } from "./config";
import { serviceFetch } from "./http";
import type { Crop, Emitter, Farm, Plot, Soil } from "./types";

function get<T>(path: string, query?: Record<string, string | number>) {
  return serviceFetch<T>({
    service: "registry",
    baseUrl: config.registryUrl,
    path,
    timeoutMs: config.registryTimeoutMs,
    query,
  });
}

export const listFarms = () => get<Farm[]>("/v1/farms");
export const listPlots = (farmId: string) =>
  get<Plot[]>("/v1/plots", { farm_id: farmId });
export const getPlot = (id: string) =>
  get<Plot>(`/v1/plots/${encodeURIComponent(id)}`);
export const listCrops = () => get<Crop[]>("/v1/crops");
export const listSoils = () => get<Soil[]>("/v1/soils");
export const listEmitters = () => get<Emitter[]>("/v1/emitters");
