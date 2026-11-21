> Source: https://github.com/alonitac/OzVeruach26/blob/main/tasks/p2.md (fetched 2026-11-17, upstream commit 9411807)
# P2 - Weather, planner, and the daily plan

In this task AgroPilot answers the grower's real question:

> Should I water this plot today, and for how many minutes?

You will add three new services, `weather-service` and `planner-service`, and show the plan in the `frontend` UI service.

```text
                                      ┌────────────────────┐
                               ┌────► │  registry-service  │ ──► DB (SQLite or PostgreSQL)
                               │      │  :8000             │
 ┌─────────┐   ┌────────────┐  │      └────────────────────┘
 │ Browser │ ─►│ Frontend   │ ─┤      ┌────────────────────┐      ┌────────────────────┐
 └─────────┘   │ :3000      │  └────► │  planner-service   │ ───► │  registry-service  │
               └────────────┘         │  :8002             │      └────────────────────┘
                                      │                    │      ┌────────────────────┐
                                      │                    │ ───► │  weather-service   │ ──► Open-Meteo
                                      └────────────────────┘      │  :8001             │
                                                                  └────────────────────┘
```

Each service is a separate folder under `services/`, with its own `.venv`, its own `.env`, etc... Services never import each other's code. They talk over HTTP only.

## Before you start: Git

1. Commit everything you have now on `main`. Run `git status` and make sure the working tree is clean.
2. Push `main`.
3. Create a branch for this task:

    ```bash
    git switch -c p2
    ```

Do all the work below on `p2`. At the end you open a pull request into `main`.



## The `registry-service`

### Functional requirements

- **FR-2.1** In production, the registry stores its data in PostgreSQL. On a developer's machine, it stores it in a local SQLite file.
- **FR-2.2** A new environment can be set up from nothing: one documented command creates the tables in an empty PostgreSQL database and loads the same 15 seed rows as `seed_registry.sh`.

### Non-functional requirements

- **NFR-2.1** Moving between SQLite and PostgreSQL needs no code change, only configuration.
- **NFR-2.2** NFR-1.1 still holds on PostgreSQL: `GET` list and `GET` by id, p95 `<= 100 ms` at 10 requests per second.

### Notes

- Build this part with Superpowers skill, as instructed in the exercise **Move the registry to PostgreSQL, with Superpowers skills set** in the [coding agents tutorial](../tutorials/intro_to_coding_assistant.md). Commit the design document and the plan that Superpowers wrote.
- All data access goes through SQLAlchemy.
- The service reads the database URL from `DATABASE_URL` in `.env`.
- Install PostgreSQL on your machine (on WSL if you are on Windows), create a database named `registry`, and run the service against it. This is your "production".


## The `weather-service`

Plans depend on the weather. A hot, dry, windy day pulls more water out of the field. `weather-service` fetches the daily forecast from [Open-Meteo](https://open-meteo.com/en/docs) (a.k.a **the provider**) and serves it to the rest of the system.

### Functional requirements

- **FR-2.3** `GET /v1/forecast?lat={lat}&lon={lon}&days={days}` returns the daily forecast for that point: for each of the next `days` days, starting today, the date, **ET0** (how much water a standard patch of grass loses to sun and wind that day, in mm), and **rain** (mm).
- **FR-2.4** `lat` must be from -90 to 90, `lon` from -180 to 180, and `days` from 1 to 7. Otherwise: `422`, `code`: `VALIDATION`.
- **FR-2.5** Two requests for points in the same 0.1° grid cell share one forecast. A forecast is fresh for 3 hours. While it's fresh, the service  doesn't call the provider again.
- **FR-2.6** When the provider fails (timeout, error status, a body that isn't JSON, a missing field), the service retries twice, then answers with the last forecast it has for that cell, and `stale: true`.
- **FR-2.7** When the provider fails and there's no earlier forecast for that cell: `503`, `code`: `UNAVAILABLE`, and a `Retry-After` header.
- **FR-2.8** The service never answers with numbers the provider didn't give. No zeros, no defaults for a missing day. A forecast of zeros looks like "no water needed". That is the worst possible bug in this system.

`GET /v1/forecast?lat=31.25&lon=34.79&days=7`:

```json
{
  "lat": 31.25,
  "lon": 34.79,
  "source": "open-meteo",
  "fetched_at": "2026-11-12T06:00:00Z",
  "stale": false,
  "days": [
    { "date": "2026-11-12", "et0_mm": 3.1, "rain_mm": 0.0 },
    { "date": "2026-11-13", "et0_mm": 2.8, "rain_mm": 4.2 },
    ... (7 days)
  ]
}
```

### Non-functional requirements

- **NFR-2.3** Fresh forecast (no provider call): p95 `<= 100 ms` at 10 requests per second.

### Notes

- The service knows coordinates and dates only. It knows nothing about farms, plots, or crops.
- It caches the forecasts locally, in the memory of the service process. No database. A restart empties the cache: that's fine, the next request fetches again.
- Find in the [Open-Meteo docs](https://open-meteo.com/en/docs) which daily variables give you ET0 and rain, and their units. Write it in the service README. Open-Meteo's field names never leave the code that calls it.
- Call Open-Meteo with [httpx](https://www.python-httpx.org/). The base URL, the timeout, the number of retries, and the freshness time are in `.env`.
- Open-Meteo's free tier needs no API key. Put an API key variable in `.env` anyway (it may be empty), so moving to a paid plan, or to another provider, is a config change.
- Decide how old a forecast can be before you stop serving it even as stale. Write it, and why, in the service README.
- (Optional) Draw the flow as a [Mermaid](https://mermaid.js.org/syntax/sequenceDiagram.html) sequence diagram in the README: request, fresh or not, provider call, retry, stale answer, `503`.


## The `planner-service`

A grower has a plot of tomatoes with drip irrigation. `registry-service` knows the plot. `weather-service` knows the next 7 days. `planner-service` turns those two into a 7-day plan:

> Today: water for 38 minutes. Tomorrow: no need. Day 4: 45 minutes.

Nobody expects you to know agronomy. Part of the task is learning to find, check and document domain knowledge with an AI assistant, the way you would in the first months of a job in an unfamiliar field.

### The ideas you need

- **mm of water.** Water is measured as a depth. 1 mm over 1 m² is 1 litre.
- **ET0** (from `weather-service`). How much water grass loses in one day, in mm.
- **Crop factor (Kc).** Scales ET0 to your crop and its age. A young plant drinks less than a grown one.
- **Drip emitters.** Small outlets on the pipe, each with a fixed flow in litres per hour. Their number and flow decide how long to run the system.
- **The soil bucket.** The soil holds water like a bucket. Its size depends on the soil and the root depth. Rain and irrigation fill it, the crop drains it every day. When the level would fall below half, irrigate.

The bucket is why you don't water every day, and why yesterday's rain still counts today. For example, a 70 mm bucket that loses 7 mm a day: days 1 to 5 bring it down to 35 mm, exactly half. On day 6 it would drop below half, so you irrigate.

### Research the domain first

To find the exact irrigation formulas, use **FAO-56** the standard reference for crop water needs ([FAO Irrigation and Drainage Paper 56](https://www.fao.org/3/x0490E/x0490e00.htm)).

You obviously DON'T need to read the whole book. You'll use a `/research` skills to perform the research and write the findings to a Markdown file.


1. Install the [`research` skill](https://github.com/mattpocock/skills/tree/main/skills/engineering/research) of Matt Pocock. You are highly recommended to read the `SKILL.md` file, it's short.

    ```bash
    npx skills add mattpocock/skills --skill research -a claude-code
    ```

2. New chat with the following prompt:

    > /research I'm building a daily drip-irrigation planner. Use FAO-56 (https://www.fao.org/3/x0490E/x0490e00.htm), chapters 5, 6, 8 and Annex 8. Explain how to get from ET0 and Kc to the crop's water need, the Kc values and growth stages for tomato and bell pepper, how the soil bucket works, and how Annex 8 schedules irrigation day by day. Cite the chapter or table for every claim. Save it to `services/planner-service/docs/research/fao56.md`. Don't write code.

4. Based on the research, let the agent write the irrigation engine. 

Then turn what you learned into a knowledge skill, `irrigation-calc-reference` (see [Writing Skills](../tutorials/writing_skills.md)): the formulas, the units, and three cases you calculated by hand, pointing to `fao56.md`. Without it, the agent re-invents the domain in every session.

### Functional requirements

- **FR-2.9** `GET /v1/plots/{id}/plan?days={days}` returns the irrigation plan of that plot for the next `days` days (1 to 7, default 7), starting today. The first day is today's recommendation.
- **FR-2.10** For each day the plan has: `date`, `et0_mm`, `kc`, `litres`, `run_minutes`, `stale`, and the bucket level at the end of the day. A day with no irrigation has `run_minutes: 0`.
- **FR-2.11** Every number in the plan is calculated as written in your skill, from the plot, its soil and its emitter, and the forecast for the plot's `lat`/`lon`.
- **FR-2.12** Bad `days`: `422`, `code`: `VALIDATION`. Unknown plot: `404`, `code`: `NOT_FOUND`.
- **FR-2.13** A stale forecast still gives a plan, with every affected day `stale: true`.
- **FR-2.14** When `registry-service` or `weather-service` is down, or doesn't answer in time: `503`, `code`: `UPSTREAM_UNAVAILABLE`, and the `detail` says which service.Never a plan of zeros.

Design the exact JSON yourself, and add an example to the service README.


### Notes

- Keep the code ordered
- Every number in the plan comes from your engine. No AI model computes or adjusts irrigation numbers.
- (Optional) Draw the flow as a Mermaid sequence diagram in the README: frontend, planner, registry, weather, and the failure branches.


Let's see an example: a 1000 m² tomato plot at mid-season, ET0 = 6.0 mm, no rain, rows 1.5 m apart, emitters every 0.4 m at 1.0 L/h.

| Field | Meaning | Example |
| --- | --- | --- |
| `date` | The day this row is about. The first row is today. | `2026-11-17` |
| `et0_mm` | From `weather-service`: how much water a standard patch of grass loses that day, in mm. | `6.0` |
| `kc` | Crop factor for this crop at its growth stage that day. The stage comes from days since planting, looked up in FAO-56 chapter 6. | `1.15` |
| `litres` | Water to apply that day: the depth in mm × `area_m2`, since 1 mm over 1 m² is 1 litre. | `6900` |
| `run_minutes` | How long to run the drip system to deliver `litres`. | `248` |
| `stale` | `true` when the forecast behind this row came from an old cached forecast because Open-Meteo was down. | `false` |


## The `frontend`

A grower won't use `curl`. The frontend is a small web app that shows the farms, the plots, and the plan.

> [!NOTE]
> We'll talk about UI apps later in the course. For now, let the coding agent write it. Your job is to check that it meets the requirements below.

1. Install **Node.js** (the LTS version) from [nodejs.org](https://nodejs.org/en/download). Windows users: inside WSL. Check with `node --version`.
2. Install the `frontend-design` skill. Without it, agents design every app the same way:

    ```bash
    npx skills add anthropics/skills --skill frontend-design -a claude-code
    ```

3. Start `registry-service`, `weather-service` and `planner-service`. Then, from the repo root, a new chat:

    > In `services/frontend`, create the AgroPilot frontend: a Next.js app (App Router, TypeScript, Tailwind CSS, shadcn/ui). Use the frontend-design skill. Read the APIs first: registry at http://127.0.0.1:8000/docs, planner at http://127.0.0.1:8002/docs.
    > - Meet the functional and non-functional requirements of the frontend in `tasks/p2.md`.
    > - The browser never calls the services. Pages fetch data on the server. All calls to the services live in `src/lib/`, and use `REGISTRY_URL`, `WEATHER_URL` and `PLANNER_URL` from `.env.local`. Add `.env.example`.
    > - No other pages or features. Run `npm run build` and `npm run lint` when you're done.

4. Run it:

    ```bash
    cd services/frontend
    npm install
    npm run dev
    ```

    Open [http://localhost:3000](http://localhost:3000).

### Functional requirements

- **FR-2.15** The main page, `/`, lists every farm with its plots. Each plot links to its page, `/plots/{id}`.
- **FR-2.16** The plot page shows **today's recommendation** first, big and clear: "Water for 38 minutes" or "No irrigation today". Then the 7-day plan, as a table or a timeline.
- **FR-2.17** When the forecast is stale, the user sees it, next to the numbers it affects.
- **FR-2.18** When the planner answers with an error, the user sees what happened (for example, which service is down), not a blank page and not a stack trace.
- **FR-2.19** A small status line shows whether each of the three services is up (`GET /health`).

### Non-functional requirements

- **NFR-2.8** Usable on a phone: at 375 px width, no horizontal scrolling, and today's recommendation is visible without scrolling. A grower reads this in the field.

### Notes

- Commit `services/frontend`, but not `node_modules/`, `.next/` or `.env.local`. Check `git status`.
- Check NFR-2.8 in the browser: right click > **Inspect**, then the device toolbar icon (a phone and a tablet), and pick a phone.


## Global configurations

Every value that can change between your laptop and production lives in the service's `.env` file, never in the code: database URLs, the URLs of other services, timeouts, retries, freshness times, API keys.

- Each Python service reads its settings with [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), in one `config.py` file.
- Each service has a `.env.example` with every variable and a safe example value. Commit it.
- `.env` is never committed.
- A service starts with a clear error when a required variable is missing, not crash later on the first request.
- Block your coding agent from reading `.env`. In the project root, create `.claude/settings.json`:

    ```json
    { "permissions": { "deny": ["Read(**/.env)"] } }
    ```

    This is not a security boundary, only a guard against accidents. A real production secret never belongs on a machine where an agent runs commands.





## Submit: pull request

1. Push your branch:

    ```bash
    git push -u origin p2
    ```

2. Open a pull request from `p2` into `main` on GitHub. In the description:
    - What you built, in a few lines.
    - The numbers you measured for your NFRs.
    - The skills you used, and what you would change in `irrigation-calc-reference`.
3. Read your own diff on GitHub before you ask for a review. Anything you can't explain, delete or understand first.

**You own the code.** Read every file.

# Good Luck!
