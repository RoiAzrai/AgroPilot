import { Suspense } from "react";
import { AddFarmDialog } from "@/components/add-farm-dialog";
import { ErrorPanel } from "@/components/error-panel";
import { FarmSection } from "@/components/farm-section";
import { ApiError } from "@/lib/errors";
import {
  getPlotPhotoIds,
  listCrops,
  listEmitters,
  listFarms,
  listPlots,
  listSoils,
} from "@/lib/registry";
import type { Catalogs, Farm, Plot } from "@/lib/types";

export const dynamic = "force-dynamic";

type FarmPlots = { farm: Farm; plots: Plot[]; error?: ApiError; photoIds: ReadonlySet<string> };

type Loaded =
  | { ok: true; farms: FarmPlots[] }
  | { ok: false; error: ApiError; what: string };

async function load(): Promise<Loaded> {
  let farms: Farm[];
  try {
    farms = await listFarms();
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e, what: "farms" };
    throw e;
  }
  // One farm's plots failing must not hide the other farms. Photo lists load in
  // parallel; a failed one only means "no photos" for that farm.
  const [results, photoResults] = await Promise.all([
    Promise.allSettled(farms.map((f) => listPlots(f.id))),
    Promise.allSettled(farms.map((f) => getPlotPhotoIds(f.id))),
  ]);
  return {
    ok: true,
    farms: farms.map((farm, i) => {
      const result = results[i];
      const photos = photoResults[i];
      const photoIds = new Set(
        photos.status === "fulfilled" && Array.isArray(photos.value) ? photos.value : [],
      );
      if (result.status === "fulfilled") return { farm, plots: result.value, photoIds };
      if (result.reason instanceof ApiError) {
        return { farm, plots: [], error: result.reason, photoIds };
      }
      throw result.reason;
    }),
  };
}

// Loaded once per page render and shared by every farm's "+ Plot" dialog.
// null if any catalogue fails: the dialog then shows an error instead of guessing.
async function loadCatalogs(): Promise<Catalogs | null> {
  const [crops, soils, emitters] = await Promise.allSettled([
    listCrops(),
    listSoils(),
    listEmitters(),
  ]);
  for (const r of [crops, soils, emitters]) {
    if (r.status === "rejected" && !(r.reason instanceof ApiError)) throw r.reason;
  }
  if (
    crops.status === "fulfilled" &&
    soils.status === "fulfilled" &&
    emitters.status === "fulfilled"
  ) {
    return { crops: crops.value, soils: soils.value, emitters: emitters.value };
  }
  return null;
}

async function Farms() {
  const [data, catalogs] = await Promise.all([load(), loadCatalogs()]);
  if (!data.ok) return <ErrorPanel error={data.error} what={data.what} detailed />;
  if (data.farms.length === 0) {
    return <p className="text-muted-foreground">No farms yet.</p>;
  }
  return data.farms.map(({ farm, plots, error, photoIds }) => (
    <FarmSection
      key={farm.id}
      farm={farm}
      plots={plots}
      error={error}
      catalogs={catalogs}
      photoIds={photoIds}
    />
  ));
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col gap-7 px-4 pt-10 pb-16 leading-[normal] sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-heading text-[48px] leading-[1.05] font-bold text-primary">
          AgroPilot
        </h1>
        <AddFarmDialog />
      </header>

      <Suspense
        fallback={<p className="text-muted-foreground">Loading farms…</p>}
      >
        <Farms />
      </Suspense>
    </main>
  );
}
