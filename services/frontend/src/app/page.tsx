import { Suspense } from "react";
import { AddFarmDialog } from "@/components/add-farm-dialog";
import { ErrorPanel } from "@/components/error-panel";
import { FarmSection } from "@/components/farm-section";
import { StatusLine } from "@/components/status-line";
import { ApiError } from "@/lib/errors";
import { listFarms, listPlots } from "@/lib/registry";
import type { Farm, Plot } from "@/lib/types";

export const dynamic = "force-dynamic";

type FarmPlots = { farm: Farm; plots: Plot[]; error?: ApiError };

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
  // One farm's plots failing must not hide the other farms.
  const results = await Promise.allSettled(farms.map((f) => listPlots(f.id)));
  return {
    ok: true,
    farms: farms.map((farm, i) => {
      const result = results[i];
      if (result.status === "fulfilled") return { farm, plots: result.value };
      if (result.reason instanceof ApiError) {
        return { farm, plots: [], error: result.reason };
      }
      throw result.reason;
    }),
  };
}

async function Farms() {
  const data = await load();
  if (!data.ok) return <ErrorPanel error={data.error} what={data.what} />;
  if (data.farms.length === 0) {
    return <p className="text-muted-foreground">No farms yet.</p>;
  }
  return data.farms.map(({ farm, plots, error }) => (
    <FarmSection key={farm.id} farm={farm} plots={plots} error={error} />
  ));
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-10 sm:py-14">
      <header className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-5xl font-extrabold tracking-tight sm:text-6xl">
            AgroPilot
          </h1>
          <AddFarmDialog />
        </div>
        <p className="max-w-prose text-lg text-muted-foreground">
          When to water each plot, and for how long.
        </p>
        <Suspense
          fallback={
            <p className="text-sm text-muted-foreground">
              Checking services…
            </p>
          }
        >
          <StatusLine />
        </Suspense>
      </header>

      <Suspense
        fallback={<p className="text-muted-foreground">Loading farms…</p>}
      >
        <Farms />
      </Suspense>
    </main>
  );
}
