# Changelog

All notable changes to AgroPilot are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [P2] - 2026-11-23

### Added

- registry-service: PostgreSQL support through SQLAlchemy Core, chosen by `DATABASE_URL`. SQLite still works locally.
- registry-service: with PostgreSQL, a lock wait, a deadlock, a lost connection or a full connection pool gives `503` with a `Retry-After` header.
- registry-service: `seed_db.py` creates the tables in an empty database and loads the seed rows. `--reset` rebuilds the data, and asks you to type the database name first. Without a terminal it needs `--yes`.
- registry-service: load-test tooling under `perf/`.
- weather-service: new service (port 8001). It reads ET0 and rain from Open-Meteo and rejects provider data that is missing, in the wrong unit or negative.
- weather-service: in-memory cache per 0.1° cell, with one refresh at a time (single-flight), a failure pause, and stale forecasts (`stale: true`) when the provider fails. Forecasts older than the max-stale time are removed.
- weather-service: provider timeouts, connection errors and 5xx answers are retried. Client errors (4xx, such as 429) are not.
- weather-service: the service refuses to start when the retry attempts do not fit in the refresh deadline.
- weather-service: optional `past_days` parameter, used to suggest the starting soil-bucket level.
- planner-service: new service (port 8002). It builds the 7-day irrigation plan (litres and drip minutes) from the soil-water balance, using registry-service and weather-service.
- planner-service: bucket-suggestion endpoint, computed from the date of the last irrigation.
- planner-service: the connection limit to the other services is a setting (`UPSTREAM_MAX_CONNECTIONS`, default 20).
- frontend: new Next.js app (port 3000) with the farm list, plot page (today's recommendation and 7-day plan), farm and plot creation, plot deletion, bucket-suggestion panel, and a status line with the health of the three services. It calls the services from the server only.
- frontend: farm and plot names are limited to 100 characters. When deleting a plot fails, the message says whether the plot was deleted or may have been.
- CI: GitHub Actions workflow per Python service, running tests and a dependency audit on pull requests.
- Project skills: `irrigation-calc-reference` (irrigation math and decisions) and an updated `registry-api`. Design and plan documents under `docs/superpowers/` and decisions in `docs/judgment-log.md`.

### Changed

- registry-service: a farm or plot name that contains a NUL character is now rejected with `422` (POST and PATCH).
- registry-service: PATCH writes only the fields that were sent, so a PATCH of one field no longer overwrites a concurrent change to another field.
- registry-service: it is now configured with `DATABASE_URL` in `.env`, which replaces `REGISTRY_DB_PATH` (no longer read). There is no default: the service refuses to start without `DATABASE_URL`, and also when `.env` still has an unknown key such as `REGISTRY_DB_PATH`.

Known limitations and future work are listed in the P2 pull request.
