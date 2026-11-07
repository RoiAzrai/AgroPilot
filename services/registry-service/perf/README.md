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
| `--keepalive-expiry` | `4` | Client idle keep-alive, in seconds. Must be shorter than the server's (uvicorn: 5 s); see [Keep-alive race](#keep-alive-race). |
| `--out` | none | Writes the JSON summary to this file, and the per-request timeline next to it (same name, `.csv`). |

Exit codes: `0` pass, `1` NFR failed (p95 over the limit, or any error), `2`
INVALID run (generator lag over the bound, or a VM suspension during the run), `3`
setup error (service down, or a list is empty).

## Official measurement: `run_official.sh`

**Purpose.** It runs the official NFR-1.1 session in one go, against a freshly
seeded service: three adjacent pairs of runs, Poisson then constant, with seeds 1,
2 and 3. It records what the machine was doing at the same time, so a bad run can
be explained instead of guessed at, and it ends with the session comparison.

**Paired design.** In each pair, the two runs use the same seed, so they send
exactly the same requests (same endpoints, same ids, same order). They also run
back to back, so the machine is in as similar a state as possible. That leaves
timing (Poisson or evenly spaced) as the only difference between them. Three pairs
show whether a difference is consistent or just noise. The official NFR-1.1 number
comes from the three Poisson runs.

**Run it** from a plain WSL terminal (not from VS Code). The next session uses the
prefix `paired2`. The earlier `official-*` and `paired-*` results stay as they are,
and the script refuses to overwrite an existing prefix:

```bash
cd services/registry-service
RESULTS_PREFIX=paired2 bash perf/run_official.sh
```

It takes about 35 minutes. The script:

1. **Pre-flight.**
   - Fails if `perf/results/<prefix>-*` already exists, so an earlier session
     (such as `official-*`) is never overwritten.
   - Warns if VS Code server processes are running and prints the top 5 CPU
     consumers.
   - Fails if port 8000 is already in use.
   - Prints the Windows preparation reminder and waits for Enter.
     `ASSUME_YES=1` skips the prompt, for dry runs.
2. **Server.** Runs `bash seed_registry.sh`, then starts
   `uv run uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning` in
   the background and waits up to 30 s for `/health`.
3. **Monitors.** Starts `vmstat -t -w 1` (CPU, run queue, swap, steal, every
   second) and `top -b -d 5 -o %CPU` (all processes by CPU, every 5 s), and saves
   `free -m` before and after.
4. **Runs,** in this order: Poisson seed 1, constant seed 1, Poisson seed 2,
   constant seed 2, Poisson seed 3, constant seed 3. A failed or INVALID run is
   recorded and the script carries on, so one bad run does not lose the rest.
5. **Summary.** One line per run (name, exit code, overall p95, lag p99,
   suspensions, verdict).
6. **Session comparison.** Runs `compare_runs.py` (see below) and saves its output,
   then prints the total time.

The server and the monitors are stopped on exit, including on failure or
Ctrl+C.

**Results** go to `perf/results/` (ignored by git), prefixed with
`RESULTS_PREFIX`:

| File | Content |
| --- | --- |
| `<prefix>-<arrival>-seed<n>.json` / `.csv` / `.txt` | Each run's summary, per-request timeline and printed report. |
| `<prefix>-comparison.txt` | The session comparison. |
| `<prefix>-vmstat.txt`, `<prefix>-top.txt` | System monitors for the whole session. |
| `<prefix>-free-before.txt`, `<prefix>-free-after.txt` | Memory before and after. |
| `<prefix>-server.log` | Server output (warnings and errors only). |

**Dry run.** Environment overrides shorten it: `WARMUP` (default 20),
`DURATION` (default 300), `RESULTS_PREFIX` (default `paired`) and `ASSUME_YES`.

```bash
WARMUP=2 DURATION=10 ASSUME_YES=1 RESULTS_PREFIX=dry2 bash perf/run_official.sh
```

**Prepare the machine first.** The service, the load generator and the monitors
share one laptop, so anything else running there ends up in the numbers. In the
first official session, Windows power saving slowed the VM down and then suspended
it for about 8 minutes.

- Close VS Code. The coding agent runs inside VS Code, so the official run is
  started by a person from a plain terminal.
- Windows Settings > System > Power & battery > Screen and sleep: set all four
  options (screen and sleep, on battery and plugged in) to **Never**.
- Keep the laptop lid open.
- Plug the laptop into power and set the Windows power mode to best performance.
- Close games and other heavy Windows apps, including their launchers and
  background services. The WSL monitors cannot see Windows processes.
- Check Windows Task Manager before starting: idle CPU under 10% and a few GB of
  free memory.
- Do not use the computer until the summary prints (about 35 minutes).

## Comparing a session: `compare_runs.py`

```bash
uv run python perf/compare_runs.py --prefix paired
```

It reads `perf/results/<prefix>-*.json` and prints two sections:

- **Official NFR-1.1 result.** The three Poisson runs: p95 [95% CI] per endpoint
  per run, the worst p95 across endpoints and runs, and an overall PASS only if
  every Poisson run passed. Exit code `0` for PASS, `1` otherwise.
- **Paired comparison.** One row per seed: Poisson overall p95 [CI], constant
  overall p95 [CI], and the difference (Poisson minus constant) in ms. A pair is
  marked *not comparable* if either run is INVALID or had a suspension. A summary
  line says whether the difference has the same sign in all comparable pairs,
  and in how many pairs the two intervals overlap.

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
2. **Latency table.** Per endpoint and `OVERALL`: requests, errors, p50, p95 with
   its 95% confidence interval as `p95 [low, high]`, p99, max and mean, in ms. The
   verdict is based on this table and uses the point p95, as the spec says. One
   informational line follows: whether the upper bound of every endpoint's
   interval is also within the limit.
3. **Service-time table.** The same columns, measured from the actual send. When
   it is close to the latency table, the requests left on time.
4. **Errors by type and by detail.** Errors in the measurement window, by type:
   `timeout`, `connect_error`, `transport_error` (any other network failure), or
   `http_<status>` for a response other than 200. Then the same errors by detail:
   the exception class and message, plus the class and message of its cause,
   for example `ReadError: (no message) (caused by ConnectionResetError: [Errno 104]
   Connection reset by peer)`. httpx often wraps a lower-level error with an empty
   message, so the cause is what explains it. The detail is for diagnosis only;
   errors are counted and judged by type, as before.
5. **Stalls.** Every period in the whole run, warm-up included, where generator lag
   exceeded 100 ms. A stall is a run of consecutive late requests in schedule
   order. It starts at the first one's scheduled time and ends when the last one
   was finally sent. Each line shows the start (seconds from the start of the
   run), the duration, the number of late requests, the maximum lag, and the
   maximum service time of requests sent during that period. When the service
   time spikes in the same period as the lag, the server and the generator were
   held up together, which points to the machine rather than to either one.
6. **Suspensions.** Every period where the whole VM was paused (see below), with
   its start (seconds into the run, and wall-clock time), its duration and its
   kind. A suspension during warm-up or measurement makes the run **INVALID**.
7. **Queueing checks.** These validate the measurement itself. Each one prints a
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
8. **VERDICT.** PASS only if every endpoint has p95 ≤ the limit, there are zero
   errors, and the run is valid. Otherwise the report prints each reason.

## Confidence interval for p95

A single run measures about 270 requests per endpoint. Another run of the same
length would draw a slightly different set of requests and give a slightly
different p95. The 95% interval shows how much the p95 could move from that
sampling alone. A narrow interval means the sample is large enough. A wide one
means the p95 rests on only a few slow requests.

The tool uses the **percentile bootstrap**:

1. Draw a resample of the same size from the measured latencies, with
   replacement.
2. Take the nearest-rank p95 of that resample.
3. Repeat 2000 times. The interval runs from the 2.5th to the 97.5th percentile
   of those 2000 values.

It uses only the standard library. The resampling has its own random stream
derived from the run seed, so the same run data and seed always give the same
interval.

**Limitation.** The interval covers sampling noise only. The bootstrap treats
requests as independent draws from one unchanging distribution. It does not
capture changes in the machine's state over time, such as the slowdown of about 3×
seen in the first official session. That is why runs are repeated, and why the
pairs run back to back. Because a nearest-rank percentile is always a measured
value, the bounds are measured latencies too, and small samples give intervals
that move in steps.

## VM suspension detection

When Windows sleeps or pauses the WSL VM, everything inside the VM stops, and so
does its monotonic clock. Requests in flight look normal, and generator lag stays
at zero, so the lag check cannot see it. In the first official session, an
8-minute suspension in the middle of a run went unnoticed this way.

During each run, a heartbeat task records the monotonic clock and the wall clock
about once per second. Between two heartbeats, the run counts as suspended if:

- the wall clock advanced more than the monotonic clock by over 1 s (kind
  `clock_gap`), or
- no heartbeat came for over 2 s of wall time (kind `no_heartbeat`: the event loop
  did not run at all).

Smaller differences, such as normal clock adjustments and scheduling jitter, are
ignored. A suspension during warm-up or measurement makes the run INVALID. One
outside the run is reported but does not.

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
| `error_detail` | Empty on success, otherwise the exception class and message with its cause, or `HTTP <status>`. |

Use it to line stalls up against system data, such as `vmstat 1` recorded during
the run.

## Limits

- A run on localhost with the seed database is a lower bound. A real network adds
  latency, and a larger database makes the list endpoints slower.
- The machine running the measurement also runs the generator. Background load
  on the machine shows up as generator lag; the lag check catches this.
- A change in the machine's speed that affects the server and the generator
  equally, such as a CPU power state, does not show up as lag. It shows up only as
  a change in service time across the timeline, and by comparing repeated runs.

## Keep-alive race

**Finding.** In the first paired session, Poisson seed 2 had one `transport_error`
(`GET /v1/farms/{id}`). It failed 7 ms after being sent, on a quiet machine, with
no lag and no suspension. The cause was traced to the keep-alive settings of the
client and the server:

- httpx keeps an idle pooled connection for 5 s by default
  (`Limits(keepalive_expiry=5.0)`), and uvicorn closes an idle connection after
  5 s by default (`timeout_keep_alive=5`).
- The server's timer starts when it finishes sending a response. The client's
  timer starts a little later, when it finishes reading it. So the server always
  closes first, and for a short moment the client still treats the connection as
  usable. A request sent in that moment fails with
  `RemoteProtocolError: Server disconnected without sending a response.` or a
  `ReadError`.
- Under Poisson arrivals, a short burst occasionally needs a second pooled
  connection. That connection then sits idle until the next burst, sometimes
  close to the 5 s limit. A reconstruction of the pool from the timeline showed
  that the failed request reused such a connection after 4996.7 ms idle. It was
  the only reuse within 5 ms of the limit in the whole session. A constant rate
  almost never opens a second connection, which is why the error appeared only in
  a Poisson run.

**Evidence.**
- *Proven from source and by experiment:* the defaults above, and the
  mechanism. A scratch test reused pooled connections idle 4.990–5.002 s, with
  the server under load. Result: **35 of 480** reuses failed with
  `keepalive_expiry=5.0`, and **0 of 480** with `keepalive_expiry=4.0`.
- *Strongly supported, not proven:* that the session's single error had this
  cause. The tool recorded only `transport_error` at the time, which is why it now
  records error details.

**In the tool.** The client's keep-alive is now 4 s (`--keepalive-expiry`), shorter
than the server's 5 s, and every error records its exception class, message and
cause. The FAIL of `paired-poisson-seed2` stays on record.

**For real clients of the service.** It is not a bug in the application code,
but any client that keeps idle connections for 5 s or more against this server
will hit it now and then. That includes httpx with its defaults. Recommended:

- Set the client's idle keep-alive below the server's, for example
  `httpx.Limits(keepalive_expiry=4)`.
- Retry a `GET` once on `RemoteProtocolError` or `ReadError`. These requests are
  idempotent, so a single retry is safe.
- Alternatively, raise the server's keep-alive above its clients' idle time with
  uvicorn `--timeout-keep-alive`. That is a deployment setting, not a code change.

## Cross-check with k6

**Why.** `load_test.py` is our own tool, so its numbers need independent evidence.
k6 is a widely used open-model load tool with its own HTTP client and its own
timing code. If both tools measure the same latency distribution on the same
machine, the measurement is not an artefact of our tool. The cross-check is
about the tool, not the service: it does not change the NFR-1.1 result, which
still comes from the Poisson runs.

**Version.** k6 v2.3.0, installed per user at `~/.local/bin/k6` from the official
GitHub release (SHA-256 verified). The script uses this version's APIs:
`constant-arrival-rate` scenarios, `handleSummary`, `k6/execution`.

**What is compared, and why.**

- **Constant rate only.** k6's open-model executor, `constant-arrival-rate`,
  starts iterations at evenly spaced times; it has no Poisson mode. So k6 is
  compared with our `--arrival constant` runs, not with the Poisson runs.
- **Our service time vs k6's `http_req_duration`.** k6 measures
  `http_req_duration` (= sending + waiting + receiving) from the moment the
  request actually goes out. It has no equivalent of our scheduled-time latency.
  The matching number in our report is the table *Service time from actual send
  time*, so that is what is compared, per endpoint: p50, p95 and p99.
- **Remaining definitional differences.**
  - k6 leaves out `http_req_blocked` (waiting for a free connection, DNS) and
    `http_req_connecting` (TCP setup). Our service time starts before httpx takes
    a connection from its pool, so it includes those when they happen, plus a
    little Python and event-loop overhead. Expect ours to be slightly higher. The
    k6 report keeps `http_req_blocked` and `http_req_connecting` so the left-out
    time is visible.
  - Percentiles: k6 interpolates between values, our tool uses nearest rank.
    Both use successful requests only (k6: `expected_response:true`, with only
    status 200 counted as expected, as in our tool).
  - Same per-request timeout (5 s) and the same 11 endpoints, tag names and
    equal weights.

**How to run.** Like `run_official.sh`: from a plain terminal, VS Code closed,
machine prepared as described there. About 35 minutes.

```bash
cd services/registry-service
bash perf/run_k6_crosscheck.sh                      # RESULTS_PREFIX defaults to k6cross
```

Dry run: `WARMUP=2 DURATION=10 ASSUME_YES=1 RESULTS_PREFIX=k6dry bash perf/run_k6_crosscheck.sh`.

The harness has the same pre-flight checks as `run_official.sh` (refuses an
existing prefix, VS Code warning, top CPU consumers, port 8000 free, Enter
confirmation), and also fails if `k6` is not in `PATH` and prints its version.
It seeds the database, starts the server and the `vmstat`/`top`/`free` monitors,
then runs three adjacent pairs, back to back so both tools see the same machine
state:

`ours-constant-seed1, k6-run1, ours-constant-seed2, k6-run2, ours-constant-seed3, k6-run3`

A failed run is recorded and the script carries on. It ends with a summary line
per run and `compare_k6.py`.

**The k6 script, `perf/k6_mix.js`.** In `setup()` it reads the ids once through
the API's list endpoints (black-box, like our tool). Two scenarios, both
`constant-arrival-rate` at 10/s: `warmup` for `WARMUP` seconds (default 20), then
`measure` for `DURATION` seconds (default 300), starting right after. Only
`measure` counts. `preAllocatedVUs` is 10 (one second of arrivals) and `maxVUs`
50; at about 10 ms per request fewer than one VU is busy on average. Thresholds
on the `measure` scenario only:

- `http_req_duration` p95 < 100 ms per endpoint tag and overall,
- `http_req_failed` rate == 0, per endpoint and overall,
- `dropped_iterations` == 0. This is k6's equivalent of our generator-lag check:
  k6 drops an iteration when it cannot start it on time, and then the run is not
  valid.

k6 exits with 99 when a threshold fails. The base URL, `WARMUP`, `DURATION`,
`SUMMARY_OUT` and `K6_VERSION` come from `-e` options. The harness runs it with
`--no-usage-report`, so k6 sends no usage statistics.

**Results** in `perf/results/`, prefixed with `RESULTS_PREFIX`:

| File | Content |
| --- | --- |
| `<prefix>-constant-seed<n>.json` / `.csv` / `.txt` | Our runs, as in the official session. |
| `<prefix>-k6-run<n>.json` | k6 report: per endpoint requests, errors and `http_req_duration` p50/p95/p99/max/mean; `http_req_blocked` and `http_req_connecting`; `dropped_iterations`; failed thresholds; metadata (k6 version, VUs, rate); and the full k6 summary under `k6_summary`. |
| `<prefix>-k6-run<n>.txt` | The per-endpoint table k6 printed. |
| `<prefix>-k6-run<n>.log` | k6's log, including one `request_error` line per failed request with its scenario, endpoint, status, k6 `error_code` and message. |
| `<prefix>-comparison.txt` | The output of `compare_k6.py`. |
| `<prefix>-vmstat.txt`, `-top.txt`, `-free-*.txt`, `-server.log` | As in the official session. |

**Reading the comparison, `compare_k6.py`.**

```bash
uv run python perf/compare_k6.py --prefix k6cross [--tolerance-ms 5]
```

- **One table per pair:** per endpoint and `OVERALL`, our p50/p95/p99 next to
  k6's, the p95 difference (k6 − ours, in ms; negative means k6 measured less)
  and the error count on each side. Above the table: our generator lag p99 and
  suspensions, and k6's `dropped_iterations`.
- A pair is **not comparable** if our run is INVALID (lag or suspension), had any
  suspension, or k6 dropped iterations. Errors do not make a pair not comparable;
  they are shown on both sides.
- **Overall:** per endpoint, the mean over comparable pairs of each side's
  percentiles and of the difference, and the total errors.
- **Summary line:** the largest |k6 − ours| p95 difference and whether every one
  is within the tolerance (default 5 ms); the `OVERALL` p95 difference per pair
  and whether it has the same sign in all pairs; how many endpoint comparisons
  have k6 higher or lower; and the errors on each side. Exit code `0` when every
  comparable p95 difference is within the tolerance, `1` otherwise.

Agreement within a few ms supports our tool. A small, consistent negative
difference (k6 lower) is expected from the definitions above. A large or
inconsistent difference means one of the tools is measuring something else.

**Limitations.**

- **No seed.** k6 picks endpoints and ids with `Math.random`, so it does not send
  the same request sequence as our tool. The comparison is between
  distributions, not individual requests. With about 270 requests per endpoint
  per run, the per-endpoint p95 moves by a few ms from sampling alone (see the
  confidence intervals in our reports), so per-endpoint differences of that size
  are noise; the `OVERALL` row and the sign across pairs say more.
- **Different HTTP client and connection handling.** k6 uses Go's HTTP client
  with connections per VU, so it may hold several connections where our tool
  mostly holds one. k6's settings are left at their defaults (connections are
  reused). k6 keeps idle connections longer than uvicorn's 5 s keep-alive, so the
  [keep-alive race](#keep-alive-race) may appear in k6 runs. Settings are not
  changed to hide such errors: they are recorded with their error codes and
  messages and reported.
- **Same machine.** Both tools share the laptop with the server, as in the
  official session. Adjacent pairs reduce, but do not remove, differences in
  machine state between the two runs of a pair.
