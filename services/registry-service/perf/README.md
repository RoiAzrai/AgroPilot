# Load test (NFR-1.1)

NFR-1.1: `GET` list and `GET` by id, p95 ≤ 100 ms at 10 requests per second.
`load_test.py` measures it with an open-model load generator: standard library
plus `httpx`, no other dependencies.

## Run it

From `services/registry-service`:

```bash
bash seed_registry.sh                                  # known data
uv run uvicorn main:app --host 127.0.0.1 --port 8000   # one worker, no --reload, no debugger
```

In a second terminal:

```bash
uv run python perf/load_test.py --seed 1 --out perf/results/poisson-seed1.json
```

The default run is Poisson arrivals at 10/s, a 20 s warm-up and 300 s of
measurement, so it takes about 5½ minutes. `perf/results/` is in `.gitignore`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--base-url` | `http://127.0.0.1:8000` | Service to measure. |
| `--rate` | `10` | Mean arrival rate, λ (requests/s). |
| `--arrival` | `poisson` | `poisson` (exponential gaps) or `constant` (gaps of exactly 1/λ). |
| `--seed` | `1` | Seeds the schedule. The same seed gives the same run. |
| `--warmup` | `20` | Seconds of load that are sent but left out of the results. |
| `--duration` | `300` | Seconds of measured load. |
| `--timeout` | `5` | Per-request timeout, in seconds. |
| `--threshold-ms` | `100` | p95 limit for every endpoint. |
| `--max-lag-ms` | `10` | Generator lag p99 limit (10% of the 100 ms budget). Above it, the run is INVALID. |
| `--out` | none | Writes the JSON summary to this file, and the per-request timeline next to it (same name, `.csv`). |

Exit codes: `0` pass, `1` NFR failed (p95 over the limit, or any error), `2`
INVALID run, `3` setup error (service down, or a list is empty).

## Official measurement: `run_official.sh`

**Purpose.** It runs the four official NFR-1.1 runs in one go, against a freshly
seeded service, and records what the machine was doing at the same time, so a
bad run can be explained instead of guessed at.

**Run it** from a plain WSL terminal (not from VS Code):

```bash
cd services/registry-service
bash perf/run_official.sh
```

It takes about 22 minutes. The script:

1. **Pre-flight.** Warns if VS Code server processes are running and prints the
   top 5 CPU consumers. Fails if port 8000 is already in use.
2. **Server.** Runs `bash seed_registry.sh`, then starts
   `uv run uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning` in
   the background and waits up to 30 s for `/health`.
3. **Monitors.** Starts `vmstat -t -w 1` (CPU, run queue, swap, steal, every
   second) and `top -b -d 5 -o %CPU` (all processes by CPU, every 5 s), and saves
   `free -m` before and after.
4. **Runs.** Poisson with seeds 1, 2 and 3, then constant with seed 1. A failed or
   INVALID run is recorded and the script carries on, so one bad run does not lose
   the rest.
5. **Summary.** One line per run (name, exit code, overall p95, lag p99, verdict),
   plus the total time.

The server and the monitors are stopped on exit, including on failure or
Ctrl+C.

**Results** go to `perf/results/` (ignored by git), prefixed with
`RESULTS_PREFIX`:

| File | Content |
| --- | --- |
| `<prefix>-<arrival>-seed<n>.json` / `.csv` / `.txt` | Each run's summary, per-request timeline and printed report. |
| `<prefix>-vmstat.txt`, `<prefix>-top.txt` | System monitors for the whole session. |
| `<prefix>-free-before.txt`, `<prefix>-free-after.txt` | Memory before and after. |
| `<prefix>-server.log` | Server output (warnings and errors only). |

**Dry run.** Environment overrides shorten it: `WARMUP` (default 20),
`DURATION` (default 300) and `RESULTS_PREFIX` (default `official`).

```bash
WARMUP=2 DURATION=10 RESULTS_PREFIX=dry bash perf/run_official.sh
```

**Prepare the machine first.** The service, the load generator and the monitors
share one laptop, so anything else running there ends up in the numbers.

- Close VS Code. The coding agent runs inside VS Code, so the official run is
  started by a person from a plain terminal.
- Plug the laptop into power and set the Windows power mode to best performance.
- Close games and other heavy Windows apps, including their launchers and
  background services. The WSL monitors cannot see Windows processes.
- Check Windows Task Manager before starting: idle CPU under 10% and a few GB of
  free memory.
- Do not use the computer during the ~22 minutes.

## How it works

- **Endpoints.** All 11 `GET` routes (`/v1/farms`, `/v1/farms/{id}`, `/v1/plots`,
  `/v1/plots/{id}`, `/v1/plots?farm_id={id}`, and the list and by-id routes of crops,
  soils and emitters) have equal weight.
- **Ids.** The tool reads ids from the API's own list endpoints at start-up. It
  never reads the database, so it also works against a remote service. Each by-id
  request picks an id uniformly at random.
- **Schedule.** Every send time, endpoint and id is generated up front from the
  seed. Timing and the endpoint/id mix use two separate random streams, so
  `--arrival constant --seed 1` sends exactly the same sequence of requests as
  Poisson seed 1, with different timing only.
- **Open model.** Each request is launched in its own asyncio task at its
  scheduled time. The generator never waits for a response before sending the
  next request, so a slow server cannot slow the arrivals down.
- **Latency.** Latency is measured from the **scheduled** send time. A request
  that leaves late, because the client or the event loop was busy, still counts
  the wait. This corrects *coordinated omission*. The tool also reports *service
  time*, measured from the actual send. The verdict uses latency.
- **Client.** One `httpx.AsyncClient` with keep-alive and a limit of 1000
  connections, so the client never queues requests itself. A timeout, a
  connection error or any status other than 200 counts as an error.
- **Percentiles.** Nearest rank: the p-th percentile of n sorted values is the
  value at rank ⌈p/100 · n⌉. It is always a real measured value. Only successful
  requests count toward percentiles; errors are counted separately.

## Reading the report

1. **Metadata.** Start time, commit (with `+dirty` if the tree had uncommitted
   changes), Python version, OS/kernel, CPU, and every run parameter.
2. **Latency table.** Per endpoint and `OVERALL`: requests, errors, p50, p95, p99,
   max and mean, in ms. The verdict is based on this table.
3. **Service-time table.** The same columns, measured from the actual send. When
   it is close to the latency table, the requests left on time.
4. **Errors by type.** Errors in the measurement window, by type: `timeout`,
   `connect_error`, `transport_error` (any other network failure), or
   `http_<status>` for a response other than 200.
5. **Stalls.** Every period in the whole run, warm-up included, where generator lag
   exceeded 100 ms. A stall is a run of consecutive late requests in schedule
   order. It starts at the first one's scheduled time and ends when the last one
   was finally sent. Each line shows the start (seconds from the start of the
   run), the duration, the number of late requests, the maximum lag, and the
   maximum service time of requests sent during that period. When the service
   time spikes in the same period as the lag, the server and the generator were
   held up together, which points to the machine rather than to either one.
6. **Queueing checks.** These validate the measurement itself. Each one prints a
   one-line interpretation:
   - **Arrivals.** The achieved rate, and the mean and coefficient of variation
     (CV = stdev / mean) of the actual gaps between sends. Poisson arrivals give
     a CV of about 1.0; constant arrivals give about 0. A different value means
     the load was not the intended process.
   - **Generator lag.** Actual send time minus scheduled time. The report always
     prints p50, p99 and max, whatever the verdict. Latency is measured from the
     scheduled send time, so lag is always **included** in the measured latency.
     Lag can only make the results worse, never better: a PASS cannot be caused
     by lag. The validity bound protects FAIL verdicts and tail values from being
     blamed on the server when the client was slow. If p99 is above
     `--max-lag-ms` (default 10 ms, which is 10% of the 100 ms budget), the run
     is **INVALID**: the load generator, not the server, was the bottleneck, and
     the numbers say nothing about the service.
   - **Little's Law consistency check** (L = λ·W over the same requests;
     near-identity by construction). The time-averaged number of requests in
     flight, found by integrating the in-flight count over the window, is
     compared with arrival rate × mean latency. Both sides use the same requests
     and the same definition: a request is in the system from its scheduled time
     to completion, clipped to the measurement window. So the two sides are equal
     by construction, except for requests that cross the window edges. This is a
     bookkeeping check, not a validation: more than a few percent of difference
     points to lost requests, a wrong window or wrong clipping.
   - **Utilization.** ρ = λ × mean service time: the share of time a single
     server would be busy. The service runs one uvicorn worker, but FastAPI runs
     synchronous endpoints in a thread pool, so it is not a single server in the
     M/M/1 sense. ρ is a rough estimate. Well below 0.5, queueing adds little
     latency; as ρ approaches 1, latency rises sharply.
7. **VERDICT.** PASS only if every endpoint has p95 ≤ the limit, there are zero
   errors, and the run is valid. Otherwise the report prints each reason.

## Timeline (CSV)

With `--out perf/results/run.json`, the tool also writes `perf/results/run.csv`:
one raw row per request, warm-up included, in schedule order.

| Column | Meaning |
| --- | --- |
| `scheduled`, `sent`, `done` | Seconds from the start of the run. Lag = `sent − scheduled`; latency = `done − scheduled`; service time = `done − sent`. |
| `endpoint` | One of the 11 endpoint names. |
| `status` | HTTP status, empty when no response arrived. |
| `error` | Empty on success, otherwise the error type (see above). |
| `in_window` | `1` if the request counts toward the results, `0` for warm-up. |

Use it to line stalls up against system data, such as `vmstat 1` recorded during
the run.

## Limits

- A run on localhost with the seed database is a lower bound. A real network adds
  latency, and a larger database makes the list endpoints slower.
- The machine running the measurement also runs the generator. Background load
  on the machine shows up as generator lag; the lag check catches this.
