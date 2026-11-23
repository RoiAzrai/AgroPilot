# frontend

The AgroPilot web UI. It has two pages: `/` (farms and plots) and `/plots/{id}` (today's recommendation, the 7-day plan and the soil bucket panel). Next.js App Router, port 3000.

## Prerequisites

- Node.js and npm (no version is pinned in `package.json`).
- The three backend services running (see Running locally).

## Configuration

Copy the example file and edit the values:

```bash
cp .env.example .env.local
```

| Variable | Meaning |
| --- | --- |
| `REGISTRY_URL` | Base URL of registry-service (farms, plots, catalogues). |
| `WEATHER_URL` | Base URL of weather-service. Used only for the status line health check. |
| `PLANNER_URL` | Base URL of planner-service (plans and bucket suggestions). |
| `REGISTRY_TIMEOUT_MS` | Timeout in milliseconds for each call to registry-service. |
| `PLANNER_TIMEOUT_MS` | Timeout in milliseconds for each call to planner-service. |
| `HEALTH_TIMEOUT_MS` | Timeout in milliseconds for each service health check. |

The app reads these with zod in `src/lib/config.ts`. If a value is missing or invalid, the app stops with an error that names the variable.

## Running locally

Start the backend services first. Run each command group from the repository root, each in its own terminal (adapted from each service's README):

```bash
# registry-service, port 8000
cd services/registry-service
uv run uvicorn main:app --host 127.0.0.1 --port 8000

# weather-service, port 8001
cd services/weather-service
uv sync
cp -n .env.example .env
uv run uvicorn main:app --host 127.0.0.1 --port 8001

# planner-service, port 8002
cd services/planner-service
cp -n .env.example .env
uv sync
uv run uvicorn main:app --host 127.0.0.1 --port 8002
```

The registry needs `DATABASE_URL` in its `.env` (SQLite or PostgreSQL; see `services/registry-service/README.md`). First-time database setup and seeding are described there. `seed_registry.sh` is for first-time setup only. It replaces existing data: it deletes `registry.db` before writing a new one (`rm -f`, line 17).

Then, in `services/frontend`:

```bash
npm install
npm run dev
```

Open http://localhost:3000.

## Scripts

- `npm run dev`: development server on port 3000.
- `npm run build`: production build.
- `npm run start`: runs the production build on port 3000 (run `npm run build` first).
- `npm run lint`: runs ESLint.
- `npm test`: runs the unit tests in `src/lib/*.test.ts` with `tsx --experimental-test-module-mocks --test`. The flag lets the tests mock modules, because the server actions import `server-only`.

## How it works

The browser never calls the services directly. Every call to registry-service, planner-service and the health checks is made on the server, from the modules in `src/lib` (they import `server-only`, so they cannot reach the browser bundle). Pages read data during rendering. Writes (create a farm, create a plot, delete a plot, suggest a bucket level) go through server actions in `src/app/actions.ts`.

## Caching

`cacheComponents` is off. `next.config.ts` does not set it, so Next's default (off) applies. The two pages therefore use `export const dynamic = "force-dynamic"` (`src/app/page.tsx` and `src/app/plots/[id]/page.tsx`), and every request gets fresh data from the services. If `cacheComponents` is ever turned on, this setting must be revisited.
