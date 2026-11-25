import "server-only";
import { config } from "./config";
import { serviceFetch, serviceFetchBinary } from "./http";
import type { PlotPayload } from "./schemas";
import type { Crop, Emitter, Farm, Plot, PlotPhoto, Soil } from "./types";

function call<T>(
  path: string,
  extra: { method?: "GET" | "POST" | "DELETE"; body?: unknown; timeoutMs?: number } = {},
  query?: Record<string, string | number>,
) {
  return serviceFetch<T>({
    ...extra,
    service: "registry",
    baseUrl: config.registryUrl,
    path,
    timeoutMs: extra.timeoutMs ?? config.registryTimeoutMs,
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

// Ids of the farm's plots that have a photo. Reads the registry database only, never S3.
export const getPlotPhotoIds = async (farmId: string) =>
  (await get<{ plot_ids: string[] }>("/v1/plot-photos", { farm_id: farmId })).plot_ids;

// The photo bytes come from S3 through the registry, which retries S3: a longer timeout.
export const getPlotPhoto = (plotId: string) =>
  serviceFetchBinary({
    service: "registry",
    baseUrl: config.registryUrl,
    path: `/v1/plots/${encodeURIComponent(plotId)}/photo`,
    timeoutMs: config.photoTimeoutMs,
  });

// Multipart field "file". Photo timeout: the registry retries S3 up to 3 times.
export function uploadPlotPhoto(plotId: string, file: Blob) {
  const form = new FormData();
  form.append("file", file, file instanceof File && file.name ? file.name : "photo.jpg");
  return call<PlotPhoto>(`/v1/plots/${encodeURIComponent(plotId)}/photo`, {
    method: "POST",
    body: form,
    timeoutMs: config.photoTimeoutMs,
  });
}
