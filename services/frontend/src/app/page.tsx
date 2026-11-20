import { Suspense } from "react";
import { ErrorPanel } from "@/components/error-panel";
import { FarmSection } from "@/components/farm-section";
import { StatusLine } from "@/components/status-line";
import { ApiError } from "@/lib/errors";
import { listFarms, listPlots } from "@/lib/registry";
import type { Farm, Plot } from "@/lib/types";

export const dynamic = "force-dynamic";

type Loaded =
  | { ok: true; farms: Farm[]; plotsByFarm: Plot[][] }
  | { ok: false; error: ApiError; what: string };

async function load(): Promise<Loaded> {
  let farms: Farm[];
  try {
    farms = await listFarms();
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e, what: "farms" };
    throw e;
  }
  try {
    const plotsByFarm = await Promise.all(farms.map((f) => listPlots(f.id)));
    return { ok: true, farms, plotsByFarm };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e, what: "plots" };
    throw e;
  }
}

export default async function Home() {
  const data = await load();

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-10 sm:py-14">
      <header className="flex flex-col gap-3">
        <h1 className="text-5xl font-extrabold tracking-tight sm:text-6xl">
          AgroPilot
        </h1>
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

      {!data.ok ? (
        <ErrorPanel error={data.error} what={data.what} />
      ) : data.farms.length === 0 ? (
        <p className="text-muted-foreground">No farms yet.</p>
      ) : (
        data.farms.map((farm, i) => (
          <FarmSection key={farm.id} farm={farm} plots={data.plotsByFarm[i]} />
        ))
      )}
    </main>
  );
}
