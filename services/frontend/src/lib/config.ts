import "server-only";
import { z } from "zod";

const url = z.url({ protocol: /^https?$/ });
const ms = z.coerce.number().int().positive();

const schema = z.object({
  REGISTRY_URL: url,
  WEATHER_URL: url,
  PLANNER_URL: url,
  REGISTRY_TIMEOUT_MS: ms,
  PLANNER_TIMEOUT_MS: ms,
  HEALTH_TIMEOUT_MS: ms,
  PHOTO_TIMEOUT_MS: ms,
});

const parsed = schema.safeParse(process.env);
if (!parsed.success) {
  const problems = parsed.error.issues
    .map((i) => `${i.path.join(".")}: ${i.message}`)
    .join("; ");
  throw new Error(`Invalid frontend configuration (check .env.local): ${problems}`);
}

const env = parsed.data;
const trim = (u: string) => u.replace(/\/+$/, "");

export const config = {
  registryUrl: trim(env.REGISTRY_URL),
  weatherUrl: trim(env.WEATHER_URL),
  plannerUrl: trim(env.PLANNER_URL),
  registryTimeoutMs: env.REGISTRY_TIMEOUT_MS,
  plannerTimeoutMs: env.PLANNER_TIMEOUT_MS,
  healthTimeoutMs: env.HEALTH_TIMEOUT_MS,
  photoTimeoutMs: env.PHOTO_TIMEOUT_MS,
} as const;
