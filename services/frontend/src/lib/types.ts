import "server-only";

// Registry (services/registry-service/models.py)
export type Farm = { id: string; name: string };

export type Plot = {
  id: string;
  farm_id: string;
  name: string;
  area_m2: number;
  crop_id: string;
  planting_date: string; // YYYY-MM-DD
  soil_id: string;
  row_spacing_m: number;
  emitter_spacing_m: number;
  emitter_id: string;
  lat: number;
  lon: number;
};

export type PlotPhoto = { plot_id: string; key: string; content_type: string };

export type Crop = { id: string; name: string };
export type Soil = { id: string; name: string; available_water_mm_per_m: number };
export type Emitter = { id: string; name: string; flow_lph: number };
export type Catalogs = { crops: Crop[]; soils: Soil[]; emitters: Emitter[] };

// Planner (services/planner-service/models.py, engine/season.py)
export type Stage = "not_planted" | "ini" | "dev" | "mid" | "late" | "ended";

export type DayOut = {
  date: string;
  stage: Stage;
  et0_mm: number;
  rain_mm: number;
  kc: number | null;
  litres: number;
  run_minutes: number;
  bucket_mm: number | null;
  bucket_capacity_mm: number | null;
  stale: boolean;
};

export type PlanOut = {
  plot_id: string;
  crop: string;
  bucket_start: number;
  fetched_at: string;
  stale: boolean;
  days: DayOut[];
};

export type SuggestionOut = {
  plot_id: string;
  last_irrigation: string;
  suggestion: number | null;
  exact: boolean;
  reason: string | null;
  past_days_requested: number;
  past_days_returned: number;
  stale: boolean;
};

// RFC 9457 body as returned by every service
export type Problem = {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
};
