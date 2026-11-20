import "server-only";
import { config } from "./config";
import type { ServiceName } from "./errors";

export type Health = Record<ServiceName, "up" | "down">;

async function ping(baseUrl: string): Promise<"up" | "down"> {
  const res = await fetch(`${baseUrl}/health`, {
    cache: "no-store",
    signal: AbortSignal.timeout(config.healthTimeoutMs),
  });
  return res.status === 200 ? "up" : "down";
}

export async function checkAll(): Promise<Health> {
  const [registry, weather, planner] = await Promise.allSettled([
    ping(config.registryUrl),
    ping(config.weatherUrl),
    ping(config.plannerUrl),
  ]);
  const state = (r: PromiseSettledResult<"up" | "down">) =>
    r.status === "fulfilled" ? r.value : "down";
  return { registry: state(registry), weather: state(weather), planner: state(planner) };
}
