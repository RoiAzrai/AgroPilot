# Judgment log

Decisions made while building the registry service with a coding agent
(Claude Code). Each entry records what the agent suggested, what I decided,
and why.

## 1. Foreign-key errors are not always validation errors
- **Agent suggested:** Map every SQLite `FOREIGN KEY constraint failed` error
  globally to `422 VALIDATION`.
- **I decided:** Rejected. Only `UNIQUE` is mapped globally (to `409 CONFLICT`).
  FK failures are handled per endpoint: deleting a farm that still has plots
  returns `409 CONFLICT`.
- **Why:** The same FK error happens in two different situations. Creating a
  plot for a missing farm is a bad request (422), but deleting a farm with plots
  is a valid request that conflicts with existing data, and the spec requires
  409 there. A global mapping would return the wrong status.

## 2. Check referenced ids explicitly, keep foreign keys as a safety net
- **Agent suggested:** Rely on the database foreign keys to reject unknown
  `farm_id` values.
- **I decided:** Check `farm_id`, `crop_id`, `soil_id` and `emitter_id` in one
  reusable helper before writing, returning `422` with "Unknown farm",
  "Unknown crop", "Unknown soil" or "Unknown emitter". The DB foreign keys stay
  as a safety net.
- **Why:** SQLite's FK error does not say which column failed, so it cannot
  produce the clear detail the spec shows ("Unknown emitter").

## 3. Catalogue existence checks moved from FR-1.3 into FR-1.1
- **Agent suggested:** Following my original plan, leave the crop/soil/emitter
  existence checks for the FR-1.3 step.
- **I decided:** Include them already when building plots CRUD.
- **Why:** Without them, an unknown crop would hit an unhandled FK error and
  return 500 until FR-1.3 was done. The spec lists "unknown crop, soil, or
  emitter -> 422" as an API failure, and the helper already existed, so the cost
  was a few lines.

## 4. A 405 response needs a `code`, but the spec defines none for it
- **Agent suggested:** Return `405` as problem+json with `code: "VALIDATION"`,
  the `Allow` header, and a detail naming the method and path.
- **I decided:** Accepted.
- **Why:** FR-1.4 requires every error to carry one of the four codes. A 405 is
  a client error (the client used a method the route does not allow), and
  VALIDATION is the closest fit. Omitting `code` would break FR-1.4.

## 5. Rely on the database UNIQUE constraint for duplicate plot names
- **Agent suggested:** Let the `UNIQUE (farm_id, name)` constraint reject
  duplicates and translate it to `409`, instead of checking for an existing name
  first.
- **I decided:** Accepted.
- **Why:** A check-then-insert has a race: two requests at the same moment can
  both see no duplicate and both insert. The database enforces the rule
  atomically. It also covers PATCH, both renaming and moving a plot to another
  farm.

## 6. Status codes for ids that are invalid or unknown
- **Agent suggested:** A path id that is not a valid UUID returns `404`; a
  `farm_id` in a request body that does not exist returns `422`; a `?farm_id=`
  filter with an unknown UUID returns `200 []`, and a non-UUID filter returns
  `422`.
- **I decided:** Accepted all four.
- **Why:** The path identifies the resource, so "no such resource" is 404
  whatever the reason. A body field pointing at nothing is invalid input, like
  an unknown crop, so 422. A filter that matches nothing is an empty list, and
  the spec says "no rows means 200 and []".

## 7. PATCH with an empty body
- **Agent suggested:** `PATCH {}` returns `200` with the unchanged record;
  `{"name": null}` returns `422`.
- **I decided:** Accepted.
- **Why:** The spec says PATCH "changes only the fields in the body". An empty
  body changes nothing, which is not an error. Sending `null` is an attempt to
  clear a required field, which is invalid.

## 8. Comparing plot names
- **Agent suggested:** Strip leading and trailing whitespace, and compare names
  case-sensitively.
- **I decided:** Accepted.
- **Why:** Stripping gives "non-empty" a real meaning (`"   "` is rejected).
  Case-sensitive comparison matches the existing `UNIQUE` constraint in the seed
  schema, which I am not allowed to change; case-insensitive uniqueness would
  need an app-level rule the database does not enforce.

## 9. Farm names are not unique
- **Agent suggested:** Nothing yet, but agents tend to extend a uniqueness rule
  from plots to farms.
- **I decided:** Told the agent explicitly not to add a farm-name uniqueness
  check, and tested that two farms with the same name are both created.
- **Why:** The spec only requires unique plot names within a farm. Adding rules
  the spec does not list is extra functionality.

## 10. Strict number validation, but integers accepted
- **Agent suggested:** Strict mode for numbers, rejecting `"1000"` as a string
  and `true` as a number.
- **I decided:** Accepted, with a condition: integers must be accepted for float
  fields, proven by a test that posts the exact example body from the spec.
- **Why:** The spec example sends `"area_m2": 1000`. Too strict a rule would
  reject the official example. Strings and booleans are still rejected, and
  NaN/Infinity too, because SQLite would store NaN as NULL and fail with 500.

## 11. Keep `httpx` despite a deprecation warning
- **Agent suggested:** Flagged that Starlette's TestClient warns about `httpx`
  and recommends a replacement; left the choice to me.
- **I decided:** Keep `httpx` for now.
- **Why:** The tests pass, and changing a test dependency mid-task does not serve
  the spec. Noted as a known limitation in the PR.

## 12. Defining "today" for planting_date
- **Agent suggested:** Nothing specific; the spec says only that `planting_date`
  must not be in the future, without saying in which time zone.
- **I decided:** A date counts as "in the future" only if it has not started
  anywhere on Earth. The check compares against the current date in UTC+14, the
  earliest time zone.
- **Why:** The goal is that no farmer who enters a true planting date is ever
  rejected, wherever the farm is. We accept the trade-off that in western time
  zones a date up to one day ahead can pass (up to two days, for about an hour a
  day, only on a few Pacific islands at UTC-11/-12), while a clearly future date
  is still rejected. Alternatives rejected:
  - UTC: wrong in both directions. East of UTC it blocks real entries after local
    midnight (in Israel at 00:30 it is already the next day, while UTC is still
    on the previous day); west of UTC it accepts tomorrow's date in the evening.
  - Server local time: the result would depend on the machine the service runs
    on (laptop vs. cloud).
  - Asia/Jerusalem: correct only for Israel; AgroPilot should not assume all
    farms are there.
  - A time zone per farm: the most precise option, but it needs a new field, and
    the spec does not allow adding fields or changing the schema. Deriving the
    time zone from the plot's lat/lon would need a new dependency for one rule.

  The current date comes from one injectable function, so the tests are
  deterministic and do not depend on when they run.

## 13. Catalogue ids are matched exactly
- **Agent suggested:** Nothing different; the question was whether `Tomato` should
  find `tomato`.
- **I decided:** Catalogue ids are matched exactly and case-sensitively, so
  `GET /v1/crops/Tomato` returns 404.
- **Why:** Catalogue ids are identifiers (slugs), not display names. Accepting
  several spellings would mean the same crop has more than one id, and plots
  could store inconsistent references. SQLite's default `BINARY` comparison
  already enforces this, with no extra code.

## 14. Which database errors return 503
- **Agent suggested:** Map every `sqlite3.OperationalError` to `503`, since a
  missing file and a lock both raise it.
- **I decided:** 503 UNAVAILABLE with Retry-After: 5 only for errors in the
  database's environment: the file cannot be opened, it is locked, the disk fails,
  or the file is damaged. Classified by SQLite error code, not message text.
  Errors that mean our code is wrong ("no such table", "no such column",
  syntax errors) are treated as bugs (500).
- **Why:** 503 tells the client "not your fault, try again later". That is true
  when the database is locked or missing and can be fixed by waiting or by
  restoring the file, without a code change. A broken query will fail on every
  retry, so returning 503 would invite retries that can never succeed and would
  hide a bug as an outage. SQLite reports both kinds as OperationalError, so the
  exception type alone cannot tell them apart. 5 seconds is short enough for a
  lock to clear and avoids clients hammering the service.

## 15. Unexpected errors: 500 with code UNAVAILABLE
- **Agent suggested:** Leave unhandled errors to the framework's default
  plain-text 500, as in the earlier parts.
- **I decided:** Any unhandled exception returns 500 as problem+json with
  code UNAVAILABLE, a generic detail, and no Retry-After. The full exception is
  logged on the server only.
- **Why:** FR-1.4 requires every error to be problem+json with one of four codes,
  and none means "server bug". Alternatives rejected: the framework's plain-text
  500 breaks the format; omitting `code` breaks "a stable code"; a new INTERNAL
  code is outside the spec's closed list, so clients built on four codes would not
  know it; returning 503 for bugs would disguise them as temporary outages.
  Keeping status 500 stays honest about what happened, while UNAVAILABLE tells
  the client "the service could not serve you, and it is not your fault".
  Retry-After is omitted because a retry is not expected to help. The detail is
  generic so internal details (SQL, table names, paths) never leak.

## 16. How NFR-1.1 is measured
- **Agent suggested:** A simple loop that sends requests at roughly 10 per second,
  awaits each response and times it with a monotonic clock, then reports
  percentiles.
- **I decided:** An open-model load test with Poisson arrivals at 10 requests per
  second on average, over all 11 GET endpoints with equal weight, 20 s warm-up and
  300 s measurement, run 3 times. Latency is measured from the scheduled send
  time. The run reports queueing-theory checks (arrival CV, generator lag,
  Little's Law, utilization). k6 is used later as an independent cross-check.
- **Why:** A closed loop that waits for each response stops sending exactly when
  the server is slow, so slow periods disappear from the results (coordinated
  omission). Poisson arrivals model many independent clients and produce natural
  small bursts, so the p95 is not flattered by perfectly spaced requests. At
  10 requests per second the difference from a constant rate is expected to be
  small; the constant-rate comparison run checks this. The checks validate the
  measurement itself, not only the service. Measured on localhost with the seed
  database, so the numbers are a lower bound: a real network adds latency.
  Timing and endpoint selection use separate random streams from the same seed
  (common random numbers), so the Poisson and constant runs send the same
  requests and differ only in timing. The Little's Law line is a bookkeeping
  consistency check, not an independent validation of the measurement.

## 17. First measurement runs were invalid; diagnosing before re-running
- **Agent suggested:** Re-run the same measurement when the machine is quiet, or
  first add a per-request timeline to find the cause. Later it pointed out that a
  5 ms lag bound would likely fail on a WSL2 laptop even when quiet.
- **I decided:** Diagnose first. A timeline and vmstat showed every stall
  coincided with high CPU load on the machine (run queue up to 13 on 8 CPUs) while
  the service used about 1-2% CPU, with 0 errors and p50 about 12 ms. The official
  runs are executed by me from a plain terminal with VS Code closed, via a script
  that also records the top CPU consumers. I raised the generator-lag validity
  bound from 5 ms to 10 ms, after seeing the diagnostic data.
- **Why:** Re-running without understanding the cause would just be hoping for
  luck. The coding agent runs inside VS Code, so it cannot measure with VS Code
  closed. The WSL monitors (vmstat, top) cannot see Windows processes. A game
  running on Windows was competing for CPU and memory; Windows memory pressure can
  pause the whole WSL VM, which matches the multi-second stalls where server and
  client froze together. It was closed before the official runs. On the bound:
  latency is measured from the scheduled send time, so client lag is always
  included in the result and can only make it worse; it can never produce a false
  pass. The bound only needs to keep the client's share small relative to the
  100 ms budget, and 10% is a defensible margin. The change does not rescue the
  earlier runs: their lag (p99 about 30 ms and above) is still INVALID under the
  new bound.

## 18. Re-running as adjacent pairs with confidence intervals
- **Agent suggested:** After the first official session, the agent found that the
  VM slowed down about 14 minutes in and was suspended for about 8 minutes during
  the constant-rate run, undetected because the VM's monotonic clock stopped. It
  suggested detecting suspensions by comparing wall-clock and monotonic time.
- **I decided:** Add suspension detection; re-run as three adjacent pairs (Poisson
  then constant, same seed, seeds 1-3) with Windows sleep and screen-off
  disabled; and report a 95% bootstrap confidence interval for each p95. The
  official NFR-1.1 number comes from the three Poisson runs. The verdict still
  uses the point p95; the interval is informational.
- **Why:** NFR-1.1 was already met (worst p95 47.5 ms), so the re-run is not about
  passing. It gives clean numbers, and it answers the question the first session
  could not: the Poisson vs constant comparison was confounded, because the
  constant run came last and straddled two machine states. Adjacent pairs with
  the same seed send the same requests in the same machine state, so timing is
  the only difference; three pairs show whether a difference is consistent. The
  interval shows whether about 270 samples per endpoint per run are enough; it
  covers sampling noise only, not machine drift, which is why runs are repeated.
  The first session also showed that the laptop's power state changed latency
  more than anything in the code, most likely Windows power saving and sleep.

## 19. A single transport error traced to a keep-alive race
- **Agent suggested:** Investigate before re-running. It found that httpx and
  uvicorn both default to a 5 s keep-alive, with the server's timer starting
  slightly earlier, so a pooled connection can be reused just as the server closes
  it. It reproduced the race (35 of 480 reuses near the edge failed at 5.0 s,
  0 at 4.0 s) and recommended a shorter client keep-alive plus recording error
  details.
- **I decided:** Keep the FAIL of Poisson seed 2 on record as it is. Set the
  client's keepalive_expiry to 4 s, record exception details, and run a new paired
  session (paired2). Report the finding for real clients of the service.
- **Why:** The zero-error rule was set before the run, so it is not reinterpreted
  afterwards. The mechanism is proven from source and by experiment; that this
  specific request failed for this reason is strongly supported but not proven,
  because only "transport_error" was recorded - hence the error details. The
  error appeared only in a Poisson run: bursts occasionally need a second pooled
  connection, which then sits idle close to the 5 s limit, while a constant rate
  almost never opens one. A constant-rate test alone would have hidden this bug.
  It is a client configuration issue, not an application bug, but any real client
  using httpx defaults would hit it, so it belongs in the PR.

## 20. Cross-checking our load tool with k6
- **Agent suggested:** Run k6 with the same 11-endpoint mix at the same constant
  rate, in adjacent pairs with our constant-rate runs, and compare k6's
  http_req_duration with our service time per endpoint (p50, p95, p99), using
  k6's own summary export. On top of the prescribed design it chose to count only
  successful requests in k6's percentiles (status 200, as our tool does), to keep
  k6's connection-wait and TCP-setup times in the report so the time k6 leaves
  out is visible, and to log every failed request with its scenario, k6 error
  code and message.
- **I decided:** Run k6 v2.3.0 as an independent cross-check in three adjacent
  pairs with our tool's constant-rate mode, comparing our service time with k6's
  http_req_duration per endpoint. k6 was installed per-user from the official
  GitHub release, verified by SHA-256 checksum, without sudo.
- **Why:** We wrote our own measurement tool, so its accuracy needs independent
  evidence. k6 is a widely used open-model tool. It only supports a constant
  arrival rate and measures from the actual send, so the fair comparison is with
  our constant-rate runs and our service-time column. Adjacent pairs keep both
  tools in the same machine state. k6 has no seed, so we compare distributions,
  not identical request sequences. Installing without sudo keeps the agent
  without administrator rights.

## 21. Scale experiment with 10,000 plots (predictions written before running)
- **Agent suggested:** Generate the data with a seeded script that writes a
  separate copy of the database (never registry.db), validates every plot with
  the service's own PlotCreate model and inserts it in one transaction, then run
  the existing sessions against it through REGISTRY_DB_PATH. Within the
  prescribed design it chose a lognormal with median 9 and sigma 0.7 before
  scaling (58% of farms end up with 5-15 plots, the largest has 140), made the
  generator refuse an existing file, and records each run's database row counts
  through the API's list endpoints, so the load tool stays black-box.
- **I decided:** One scale level: 10,000 plots across about 750 farms, with a
  lognormal plots-per-farm distribution, values inside FR-1.3 and validated with
  the service's own model, generated reproducibly from a seed. Run the paired
  Poisson/constant session and the k6 cross-check once each on it. This is an
  experiment, not the official NFR-1.1 result, which stays on the spec's seed DB.
- **Why:** The seed has 4 plots, so it cannot show how the service behaves with
  realistic data volumes. Predictions, written before running:
  1. By-id and catalogue endpoints barely change (primary-key lookups; catalogues
     do not grow).
  2. ?farm_id= rises slightly, depending on farm size (index from
     UNIQUE(farm_id, name)).
  3. GET /v1/farms rises moderately.
  4. GET /v1/plots rises sharply and likely exceeds 100 ms p95, because it
     returns every plot (no pagination in the spec) - a finding that pagination
     would be needed at this size, not a failure of the assignment.
  5. Server utilization rises, so the Poisson-vs-constant gap should be larger
     than the ~1 ms seen at ~10% utilization.
  6. The ~2 ms offset between our tool and k6 may grow for the large plots list,
     since our Python client has to read a much bigger body.

## 22. The 10,000-plot dry run collapsed; scale reduced to 2,000
- **Agent suggested:** It found that GET /v1/plots returns about 3 MB and takes
  0.3-0.8 s even on an idle server. Under load the server saturated: p95 rose to
  hundreds of ms or seconds even on light endpoints, abandoned client requests
  kept running on the server, and the backlog outlasted each run (one request took
  125 s after a run), so three of six runs could not start. It proposed waiting for
  the server to drain before each run.
- **I decided:** Record this as a qualitative finding, and run the full sessions at
  2,000 plots (~150 farms) instead. Add a drain wait before each run (restart after
  10 minutes), and give setup a longer timeout than measurement.
- **Why:** The spec defines no data volume; NFR-1.1 is measured on the spec's seed
  database and already passed. 2,000 plots was chosen as a plausible size for this
  stage (one region or cooperative), not because 10,000 failed; the 10,000 result
  stays on record. The collapse is the queueing "hockey stick": near full
  utilization, small bursts build a queue that does not clear. One heavy endpoint
  slows the light ones, because a single Python worker serializes a large response
  while other requests wait behind it, and a client giving up does not stop the
  server's work. Findings for the PR, not to implement here: pagination for list
  endpoints, and more than one worker.

## 23. Predictions for 2,000 plots (written before running)
- **Agent suggested:** The same structure as entry 21, with predictions scaled to
  2,000 plots. Its own estimate differed on prediction 4: scaling the idle timing
  at 10,000 plots (0.3-0.8 s for about 3 MB) linearly gives roughly 60-170 ms per
  GET /v1/plots at 2,000 plots (about 600 KB) even before any queueing, so it
  expected that p95 to be above 100 ms rather than near it.
- **I decided:** Predictions, written before the official runs:
  1. By-id and catalogue endpoints rise a little, mainly from sharing the server
     with the heavier list requests.
  2. ?farm_id= stays close to the seed result (similar plots per farm).
  3. GET /v1/farms rises slightly (~150 farms).
  4. GET /v1/plots (~600 KB) rises sharply; its p95 is near the 100 ms limit and
     may exceed it.
  5. No collapse and no backlog between runs; utilization stays well below 1.
  6. The Poisson-vs-constant gap is somewhat larger than ~1 ms, mostly on
     GET /v1/plots and in the tail.
  7. The ~2 ms offset between our tool and k6 is larger for GET /v1/plots, since
     our Python client reads a much bigger body.
- **Why:** Writing predictions first keeps the analysis honest: results are
  compared with what we expected, and wrong predictions are explained, not hidden.

## 24. Scale experiment results compared with the predictions
- **Agent suggested:** The results are clean enough to read as they are: all 12
  runs valid, no errors, no backlog, so nothing needs re-running. Its own
  estimate for GET /v1/plots in entry 23 (above 100 ms) was wrong; the outcome
  was p95 66-80 ms. It had scaled the 10,000-plot timings linearly, taking the
  0.3-0.8 s range at face value. That range included a cold first request
  (0.85 s); the steady idle requests (0.33-0.43 s) scale to about 66-86 ms, which
  is close to what was measured, and it also expected queueing to add on top,
  which at a utilization of 0.11-0.15 it barely did. On the mixed
  Poisson-vs-constant result it checked the seed 2 pair: the median service time
  of the light endpoints jumped from 5.0 ms (Poisson) to 10.7 ms (constant)
  between the two adjacent runs, against 6.1-7.7 ms in the other four runs, so
  the machine changed state within that pair. On the k6 cross-check it sees the
  missed 5 ms tolerance as a real result, not a near miss to explain away: the
  offset is consistent (our tool higher in 32 of 33 comparisons, about 5 ms on
  light endpoints), so it is a systematic bias of our tool, and its direction
  (overstating latency) is the safe one for an NFR verdict.
- **I decided:** Record the results against the predictions as they are, and keep
  the pre-set 5 ms k6 tolerance unchanged even though it was not met.
- **Why:** Results at 2,000 plots (~150 farms), sessions large2k-paired and
  large2k-k6 on commit fca946e: 12 runs, all valid, 0 errors, 0 restarts, drain
  0.1-0.2 s before every run.
  1. By-id and catalogue endpoints: p95 about 16-19 ms - consistent with
     prediction 1.
  2. ?farm_id=: p95 17-20 ms - consistent with prediction 2.
  3. GET /v1/farms: p95 18-21 ms - consistent with prediction 3.
  4. GET /v1/plots (~603 KB): p95 66-80 ms with Poisson; k6 measured 64-69 ms.
     Close to the limit but below it - consistent with prediction 4 as written;
     the agent's estimate of "above 100 ms" did not hold, because it scaled the
     10,000-plot dry-run timings (0.3-0.8 s on an idle server, including a slow
     first request) and expected queueing on top.
  5. No collapse and no backlog; utilization about 0.11-0.15 - consistent with
     prediction 5.
  6. Poisson vs constant: mixed on overall p95 (+3.5, -9.7, +4.0 ms), because one
     heavy endpoint (about 9% of requests) dominates the overall percentile, and
     the seed 2 pair was disturbed by a machine-state change within the pair. On
     the p99 of GET /v1/plots, Poisson was higher in all three pairs (+8, +21,
     +12 ms) - the tail effect queueing theory predicts. Partly consistent.
  7. Our tool vs k6: our tool reads higher in 32 of 33 endpoint comparisons, so it
     stays on the pessimistic side. The offset was about 5 ms on light endpoints
     and about 2 ms on GET /v1/plots - the opposite of prediction 7, which is
     therefore wrong. The largest difference was 5.9 ms, above the pre-set 5 ms
     tolerance, so the cross-check did not meet its criterion at this scale.
     Hypotheses, not tested: our client's overhead is mostly per request, not per
     byte; its single event loop, busy reading large bodies, records the end of
     concurrent small requests late; and the machine was slower in that session.
  The criterion is not changed after seeing the data. The NFR-1.1 conclusion is
  unaffected, because the bias is toward overstating latency. Overall: the service
  meets NFR-1.1 at 500 times the spec's data volume (worst p95 80.1 ms), confirmed
  independently by k6, and collapses at 10,000 plots. Recommendations for the PR,
  not to implement here: pagination for list endpoints, and more than one worker.

## 25. List order on PostgreSQL: a `rowid` identity column
- **Agent suggested:** Six queries return lists in insertion order with
  `ORDER BY rowid`, and PostgreSQL has no `rowid`. Give each PostgreSQL table a
  `rowid BIGINT GENERATED ALWAYS AS IDENTITY` column, so the same SQL runs on
  both databases. Alternative: `ORDER BY id`.
- **I decided:** Accepted the `rowid` column. The schema-comparison test allows
  `rowid` as the only difference between the PostgreSQL schema and
  `seed_registry.sh`, and fails on anything else.
- **Why:** Keeping list order exactly as today matters more than a perfectly
  identical schema. `ORDER BY id` would reorder every list, because farm and
  plot ids are random UUIDs. The column is never returned, because every
  `SELECT` names its columns.

## 26. Missing PostgreSQL database and authorization errors are 503
- **Agent suggested:** Classify PostgreSQL errors by SQLSTATE: no connection,
  classes 08, 53, 57, 58, and 55P03, 25006, XX001, XX002 are 503. Asked whether
  a missing database (3D000) and authorization errors (class 28) should be 503
  or 500.
- **I decided:** 503 with `Retry-After`, and a warning log that includes the
  SQLSTATE.
- **Why:** Same rule as P1 (entry 14), where a missing SQLite file is 503: the
  fix is in the environment (create the database, fix the password or grants),
  not in the code. The log gives operations the exact cause.

## 27. NUL characters in names are rejected with 422
- **Agent suggested:** Flagged that the `Name` type accepts any non-empty string,
  including the NUL character (`\x00`). SQLite stores it, but PostgreSQL `TEXT`
  cannot, so the same request would be 201 on SQLite and 500 on PostgreSQL.
- **I decided:** Reject NUL in name fields (farm and plot names, create and
  PATCH) with `422 VALIDATION` on both databases, with a test. This is the one
  deliberate behavior change in the PostgreSQL move, and the PR mentions it.
- **Why:** The service must behave the same on both databases, and a name with
  a NUL character is not a real name. A 500 would report a client mistake as a
  server bug. Rejecting it on both databases keeps them identical, at the cost
  of one change from P1, where SQLite accepted it.

## 28. Lock waits, deadlocks and a full connection pool on PostgreSQL are 503
- **Agent suggested:** PostgreSQL waits for a lock forever by default, so a
  request blocked by a lock would never answer, while in P1 a locked SQLite file
  gives 503 after 5 s. Set PostgreSQL's `lock_timeout` from the same
  `DB_BUSY_TIMEOUT_SECONDS`. Also, when every pooled connection is busy,
  SQLAlchemy raises `TimeoutError` after 30 s (a hardcoded default), which would
  become a 500.
- **I decided:** `lock_timeout` = `DB_BUSY_TIMEOUT_SECONDS` (5 s). A full pool
  returns 503 with `Retry-After`, after `DB_POOL_TIMEOUT_SECONDS` (5 s), both
  set in `.env`. No general `statement_timeout`. A deadlock (SQLSTATE `40P01`)
  is also 503: it is a lock conflict, like `SQLITE_LOCKED` in P1, and a retry
  fixes it.
- **Why:** Both are the environment being busy, not a bug, so the P1 rule
  (entry 14) gives 503: waiting helps. A request that hangs without limit gives
  the client no answer at all, and timeouts must come from configuration, not
  from code or library defaults.

## 29. One PostgreSQL role for setup and service; insufficient privilege is 503
- **Agent suggested:** If `seed_db.py` runs as one role and the service as
  another, every request fails with SQLSTATE `42501` (insufficient privilege),
  which the classification table mapped to 500. Use one role that owns the
  tables for both, and treat `42501` like the authorization errors of class 28.
- **I decided:** One role owns the tables and is used by both `seed_db.py` and
  the service; `seed_db.py` runs no `GRANT`, and the setup docs say so. `42501`
  returns 503 with a warning log that includes the SQLSTATE.
- **Why:** One role keeps setup to one command with no permission logic.
  A missing grant is fixed in the environment, not in the code, the same rule as
  entry 26.

## 30. Unknown keys in `.env` stop the service at startup
- **Agent suggested:** The task reviewer flagged that `Settings` rejects any key
  it does not know, so an unrelated key in `.env` (for example `LOG_LEVEL`)
  crashes startup, and suggested `extra="ignore"`.
- **I decided:** Keep `Settings` strict (pydantic-settings' default). `.env.example`
  says that unknown keys stop the service at startup.
- **Why:** A typo such as `DB_BUSY_TIMEOUT_SECOND` must fail loudly. With
  `extra="ignore"` it would be silently dropped and the service would run with
  the default value, which is much harder to notice. A new setting is added as a
  field in `config.py` anyway.

## 31. "No connection" on PostgreSQL means `OperationalError` only
- **Agent suggested:** The task reviewer noted that the approved table mapped a
  psycopg `InterfaceError` with no SQLSTATE to 503, like `OperationalError`. But
  psycopg also raises `InterfaceError` for client-side misuse, such as using a
  closed cursor.
- **I decided:** Only `psycopg.OperationalError` with no SQLSTATE ("no
  connection at all": server down, connection refused, DNS, connect timeout) is
  503. `InterfaceError` with no SQLSTATE is 500, like the other client-side
  errors.
- **Why:** Misusing the driver is a bug in our code, and retrying will never fix
  it. Returning 503 would hide it as an outage, the same rule as entry 14. The
  smoke test showed that a real refused connection is an `OperationalError`
  (`SQLSTATE=None connection failed: ... Connection refused`), so outages are
  still 503.

## 32. weather-service: a forecast older than 24 h is never served
- **Agent suggested:** The spec asks the service to decide how old a forecast
  can be before it stops serving it even as stale.
- **I decided:** 24 hours (`FORECAST_MAX_STALE_SECONDS`). Older than that, the
  service answers 503 `UNAVAILABLE`, never the old forecast. The service asks
  the provider for 8 days, so a forecast up to 24 h old still has 7 full days
  after dropping the day that has passed.
- **Why:** Irrigation decisions are daily. After a day, the forecast may miss a
  change such as new rain, and a plan built on it could water a field that
  rain already watered, or skip one that needs water.

## 33. weather-service: a pause after a failed refresh (deviation from FR-2.6)
- **Agent suggested:** Per the letter of FR-2.6, every request after the 3
  fresh hours retries the provider twice before serving stale. While the
  provider is down, every request then waits for three attempts, and the load
  on the provider grows exactly when it is in trouble. Suggested a pause.
- **I decided:** After a failed refresh of a cell, for `FAILURE_PAUSE_SECONDS`
  (default 60), requests for that cell get the stale forecast at once, or a 503
  if there is no usable stale, without calling the provider. During the pause,
  the 503's `Retry-After` is the seconds left in it. After the pause, one
  request tries again (single-flight).
- **Why:** The planner has its own timeout. If every request waited for three
  attempts before serving stale, the planner would give up first and FR-2.13 (a
  stale forecast still gives a plan) would break. This is a deliberate deviation
  from the letter of FR-2.6, also written in the design and the service README.

## 34. weather-service: one refresh deadline bounds all attempts and waiters
- **Agent suggested:** Even without the pause, the first failure of a cell costs
  three attempts plus backoff, possibly longer than the planner waits. Bound the
  whole refresh by one deadline.
- **I decided:** `REFRESH_DEADLINE_SECONDS` (default 5) bounds all attempts of a
  refresh together, and requests waiting on the same refresh (single-flight)
  wait no longer than the same deadline. When it runs out, the service falls
  back to stale or 503 at once. The per-attempt timeout (default 1.5 s) must be
  smaller than the deadline; otherwise the service refuses to start. The
  planner's timeout will be set above this deadline.
- **Why:** One number gives the worst case the planner can plan around. An
  attempt timeout as long as the deadline would eat the whole budget, and the
  retries would never happen.

## 35. weather-service: cell center to the provider; time-zone name for "today"
- **Agent suggested:** Two fixes to the first decisions: (1) asking the provider
  for the exact point of the first request makes a cell's forecast depend on
  who asked first; (2) keeping only the provider's UTC offset shifts "today" by
  an hour around midnight when a DST change happens while the forecast is kept.
- **I decided:** The provider is always asked for the cell's center (floor to
  0.1°, plus 0.05), clamped to the valid range at the edges (lat 90 stays 90).
  The service keeps the time-zone name the provider returns and computes the
  point's local "today" with `zoneinfo`. The response still echoes the
  client's lat/lon.
- **Why:** A cell's content must not depend on request order, and "today" must
  stay right across DST changes, because serving yesterday as today is one of
  the errors this service exists to prevent.

## 36. weather-service: Retry-After right after a failed refresh is the pause length
- **Agent suggested:** The first implementation gave the request whose own
  refresh had just failed `Retry-After: RETRY_AFTER_SECONDS` (5), and only later
  requests during the pause got the seconds left in it, because two earlier
  tests (written before the pause existed) expected 5.
- **I decided:** That request gets the seconds left in the pause, which right
  after the failure is the full `FAILURE_PAUSE_SECONDS` (60). The two tests
  change from 5 to 60. A waiter that times out at the very start of a refresh,
  in the same moment, before the pause is set, may still get 5: accepted.
- **Why:** Once a refresh has failed, the pause has started and nothing will
  change for 60 seconds. "Retry in 5" would be wrong: a client that retried
  after 5 seconds would only get another 503 without a provider call.

## 37. weather-service: a bug in our code never starts the pause
- **Agent suggested:** The task reviewer found that an unexpected exception (a
  bug, not a provider failure) also started the 60-second pause, so for a minute
  the bug was hidden behind stale answers or 503s.
- **I decided:** The pause starts only when all provider attempts failed or the
  refresh deadline ran out. Any other exception propagates and stays a 500 on
  every request; the next request tries again. A test covers it.
- **Why:** Same rule as the registry (entry 14): a bug must not be hidden as an
  outage. Retrying cannot fix it, and a 503 would invite retries and hide the
  real cause.

## 38. weather-service: `past_days` (deviation from FR-2.3)
- **Agent suggested:** For the planner's "suggest and confirm" bucket start
  (the bucket level from the date of the last irrigation), add an optional
  `past_days` (0-92) to `GET /v1/forecast`, keep one cache entry per cell that
  always holds 92 past + 8 forecast days, and treat a `null` or invalid value
  anywhere in the 100 days as a provider failure, as FR-2.8 does for the 8 days.
- **I decided:** `past_days` 0-92, default 0, with the same response shape;
  `past_days=0` is the old response (except the clock case below). One entry
  per cell, 92 + 8 days. Open-Meteo documents that requests with more than 7
  days of data count as more than one call (example from the docs: 4 weeks =
  3.0 calls); a conservative upper bound is ~14 calls per 100-day fetch, so
  ~112 calls a day per cell at one refresh per 3 h, far below the free limit
  of 10,000 a day.
  But a bad value in a **past** day only marks the past days of that entry
  unavailable: they are never served, `past_days > 0` gets a 503, and it is
  not a provider failure (no retry, no pause, no stale fallback). One warning
  is logged when the entry is parsed, not one per request. W26: that 503's
  `Retry-After` is the seconds until the entry stops being fresh (its next
  refresh), at least 1; during a failure pause, the seconds left in it. (First
  decided: the default `RETRY_AFTER_SECONDS`; changed, because a client told
  to retry in 5 s would get the same 503 for up to 3 h.) Structural problems anywhere, and a bad value in a
  forecast day, stay provider failures. The served window must be complete
  and contiguous; when the provider's clock is ahead around midnight, today is
  now served from its past days with the correct date instead of a 503, also
  with `past_days=0`, but only while the past days are available. A bad past
  value can come back on every fetch until its date leaves the 92-day window,
  so the planner must handle a lasting 503 for `past_days > 0`.
- **Why:** FR-2.3 says the forecast starts today, but the planner cannot
  suggest a bucket level without the ET0 and rain since the last irrigation.
  An add-on must not break what worked before it: one bad value three months
  ago must not cost a grower today's plan.
- **Superseded (17.11, entry 39):** the past-related parts of this entry (a
  bad past value marks all past days unavailable, `past_days > 0` gets a 503,
  and W26's `Retry-After` for it) are replaced by W27. The rest still holds.

## 39. weather-service: serve the past days that exist (W27)
- **Found:** a real Open-Meteo check on 2026-11-17 (lat 31.25, lon 34.75,
  `past_days=92`, `forecast_days=8`) answered 200 in 403 ms with 100 days, but
  the 25 oldest days (2026-08-17 .. 2026-09-10) were `null` in both ET0 and
  rain; from 2026-09-11 on every value was valid. Only 67 past days really
  exist. Under entry 38 (W23=B) the whole past was marked unavailable, so
  `past_days=3` got a 503 although those 3 days existed.
- **I decided (W27):** structural problems anywhere and any invalid value in
  the 8 forecast days stay provider failures. A past day is valid only when
  both ET0 and rain are valid numbers. The available past is the longest run
  of valid past days that ends on the provider's yesterday; the first invalid
  day counting back, and everything older, is dropped and never served. If
  yesterday is invalid, there are no past days. Not a provider failure: no
  retry, no pause, no stale fallback. `past_days=N` (0-92) returns the
  requested past days that are available, contiguous and ending yesterday
  (fewer than N, possibly 0), then the forecast days, with 200. When the query
  has `past_days > 0` the response adds `past_days_returned`; without
  `past_days`, or with 0, the response is unchanged. No 503 for missing past
  days, so W26 no longer applies to the past; 503 stays for forecast failures
  with the existing `Retry-After` rules. A stale entry after midnight counts
  the former today as a past day. One INFO line per stored entry when the past
  is limited; DEBUG per request that gets fewer past days than asked. The
  service had no logging setup, so INFO from its own loggers was dropped under
  uvicorn: `main.py` now sets `provider`, `forecasts` and `main` to INFO with a
  stderr handler (timestamp, level, logger name), leaves uvicorn's loggers
  alone, and adds no `.env` key.
- **Why:** the service reports facts; the planner decides what to do with
  fewer days (for example, ask the grower instead of suggesting a bucket
  level). A 503 hid 67 good days because 25 older ones were missing, and
  told the client nothing it could act on.

## 40. planner-service: "cannot suggest" is a 200, not an error (P4)
- **Decided (2026-11-18):** when the bucket suggestion can't be computed
  exactly (fewer past days than needed and the optimistic run never empties,
  or no past days at all: I22) or the season has ended (I18), the answer is
  `200` with `suggestion: null`, `exact: false` and a `reason`
  (`"insufficient_past_weather"` or `"season_ended"`). Invalid input (I15:
  a future date, before planting, more than 92 days ago, not a date) is `422`.
- **Why:** the request was valid and every upstream answered. A 422 would
  blame the grower's input, a 503 would invite a retry that gives the same
  answer. "We can't know this exactly, enter the level by hand" is a correct,
  final answer, and the frontend shows it as such.

## 41. planner-service: upstream errors (P6)
- **Decided (2026-11-18):** a registry 404 for the plot is `404 NOT_FOUND`.
  A connection error, a timeout or a 5xx from the registry or weather is
  `503 UPSTREAM_UNAVAILABLE`, its `detail` names the service, with
  `Retry-After`. Any other unexpected upstream answer (other status, bad JSON,
  a missing field, a wrong number of days, a non-finite number) is a `500`.
  Same problem+json body as the registry and weather. No partial plan ever.
- **Why:** FR-2.14 asks for 503 and the service name when an upstream is down
  or slow. An answer we don't understand is not an outage: as in weather-service
  (entry 37), a bug must not hide as "service down". And a plan built around a
  missing number would be the "plan of zeros" FR-2.14 forbids.

## 42. planner-service: timeouts, the weather one above weather's deadline (P7)
- **Decided (2026-11-18):** `REGISTRY_TIMEOUT_SECONDS=3` and
  `WEATHER_TIMEOUT_SECONDS=6` in `.env`. The weather timeout must stay above
  weather's 5 s refresh deadline, checked at startup. No retries in the
  planner (P8).
- **Why:** when Open-Meteo is slow, weather-service spends up to its 5 s
  deadline and then answers with a stale forecast. A planner timeout below
  that would turn a valid stale answer into a 503 and break FR-2.13 (a stale
  forecast still gives a plan). The registry answers in milliseconds (NFR-1.1),
  so 3 s only catches a hung registry. Retries are weather's job, behind its
  pause; retrying in the planner as well would multiply the wait.

## 43. planner-service: a daily cap on run minutes (P11, skill I23)
- **Decided (2026-11-18):** `MAX_DAILY_RUN_MINUTES` (default 1440, `.env`).
  When a refill needs more, the plan irrigates the cap today and continues on
  the following days until the bucket is full again. Goes into the skill as
  I23.
- **Why:** the North block (loam, tomato, Zr 0.70 → TAW 122.5 mm, RAW 49 mm;
  emitters 1.5 × 0.4 m at 1.0 L/h = 1.67 mm/h) needs about 1,800 minutes to
  refill once. A plan that says "run 1,800 minutes today" is physically
  impossible, and a grower who can't follow the plan stops trusting it. No
  case in cases.md reaches the cap, so no existing number changes.

## 44. planner-service: today for the suggestion comes from one weather call (Q1)
- **Decided (2026-11-18):** the suggestion calls weather once with
  `days=1&past_days=92`; today is the date after the past days. The planner
  uses only the `today − D − 1` days it needs, and `past_days_requested`
  reports that count, not 92. A future date is checked before any call
  against UTC+14, like the registry.
- **Why:** only weather-service knows the point's local date, and the I15
  rules need it. A planner clock plus a time zone key could disagree with
  weather around midnight; two calls would double the latency. 92 past days is
  one cached entry on weather anyway.

## 45. planner-service: weather's deadline is a planner key (Q2)
- **Decided (2026-11-18):** `WEATHER_REFRESH_DEADLINE_SECONDS=5` in `.env`
  (strict key, in `.env.example`). At startup `WEATHER_TIMEOUT_SECONDS` must
  be above it.
- **Why:** the P7 check needs weather's deadline and the planner can't read
  weather's settings. A key is explicit and can differ per environment; a
  constant in code would hide a value that can change. The cost, two places
  to keep in step, is written in the README.

## 46. planner-service: output precision (Q3)
- **Decided (2026-11-18):** the engine computes unrounded. `kc` is served with
  4 decimals, `bucket_mm` and `bucket_capacity_mm` with 2, rounded half up
  (I19 rule). `et0_mm` and `rain_mm` pass through exactly as weather sent
  them.
- **Why:** cases.md shows kc to 4 decimals and mm to 2-3, so a hand check
  matches. Unrounded floats (115.60000000000001) look like a bug to a grower.
  The planner didn't compute ET0 or rain, so it must not alter them.

## 47. planner-service: a day before planting is "not_planted" (Q4)
- **Decided (2026-11-18):** a plan day before the planting date has
  `stage: "not_planted"`, `litres` and `run_minutes` 0, and `kc`, `bucket_mm`,
  `bucket_capacity_mm` null, like the ended season of P2.
- **Why:** the registry accepts a planting date up to UTC+14, so for a few
  hours the planting date is tomorrow at the point. Calling that season day 1
  would invent a crop that isn't there, and a 422 would blame a valid plot.

## 48. planner-service: the seed stays, the README explains (Q5)
- **Decided (2026-11-18):** the seed data is unchanged. All four seed seasons
  have ended by 2026-11-18, so their plans are `ended`. The README says so and
  the demo creates a new plot with `POST /v1/plots`. Requirement for stage 5:
  the frontend shows "season ended", not "no irrigation today".
- **Why:** FR-2.2 fixes the seed rows and registry tests may depend on them.
  A date override on the plan would be new scope. An ended season returning
  zeros is correct, but shown as "no irrigation" it would read as the plan of
  zeros that FR-2.14 forbids.

## 49. planner-service: order of checks in the bucket suggestion (P4, I15, I18)
- **Decided (2026-11-18):** (1) bad date format or a date clearly in the
  future (beyond UTC+14) → 422, before any upstream call; (2) fetch the plot
  (404 / 503); (3) season ended → 200, `suggestion: null`, `reason:
  "season_ended"`; (4) date before planting or more than 92 days back → 422;
  (5) otherwise the calculation → 200.
- **Why:** a future date is invalid input for any plot; the other checks
  depend on the plot, so they run after it is fetched, and "no suggestion
  because the season ended" is the true answer (I18).

## 50. registry-service: plot photos in S3, decisions and known limits
- **Decided (2026-11-25):** key and content type in a separate `plot_photos`
  table (`plot_id` primary key, foreign key to `plots` with `ON DELETE
  CASCADE`), not in the plot JSON and not as new `plots` columns. The
  registry creates it at startup with `checkfirst` (idempotent). It is not in
  `TABLES` and not in `seed_registry.sh`, so the seed schema and its
  comparison test stay as given. `seed_db.py --reset` drops it before `plots`.
- **Why:** there is no migration tool, and the production database has real
  data. Creating one missing table is additive: older code ignores it, so a
  rollback still works. New `plots` columns would need an `ALTER TABLE`, change
  the given schema and break the schema comparison. If the database is
  unavailable at startup, the service logs it and starts as before (503s); the
  table is created on the next start.
- **Orphans:** deleting a plot deletes its row (CASCADE, so the delete returns
  `204`, not the foreign key `422`). The S3 object stays: the server's IAM
  policy allows only `s3:PutObject` and `s3:GetObject`, no delete.
- **Object missing in S3:** without `s3:ListBucket`, S3 answers `403
  AccessDenied`, not `404`. It returns `503 UNAVAILABLE` and is logged, like any
  other S3 error: the database says a photo exists, so this is an operations
  problem, not "no photo".
- **S3 timeouts:** `S3_CONNECT_TIMEOUT_SECONDS=3`, `S3_READ_TIMEOUT_SECONDS=10`,
  `S3_MAX_ATTEMPTS=3` (standard retry mode), optional keys with defaults.
  botocore's defaults (60 s, legacy retries) would hold a request for minutes.
- **503 from S3 carries `Retry-After: 5`,** like the database's 503.
- **GET sends `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.**
  `no-store` lets a re-upload show at once; `nosniff` stops a browser from
  guessing another type for the bytes.
- **Order of checks:** plot id (404), then the file (422), then S3 (503), then
  the database write. The row is written only after S3 succeeded, so a failed
  upload leaves the stored key unchanged. The read transaction is ended before
  the S3 call, so PostgreSQL is not left idle in a transaction while S3 is slow.
- **Known limits:**
  - Moving a plot to another farm (`PATCH farm_id`) keeps the stored key: GET
    still works. The next upload writes a new key and leaves the old object.
  - The content type is the one the client declared. The bytes are not checked
    (no magic-byte sniffing); `nosniff` limits the harm.
  - Two uploads to the same plot at the same time: the last S3 write and the
    last database write may come from different uploads, so the stored content
    type can disagree with the object. Rare; accepted.
  - The 5 MiB check runs in the handler. Starlette has already received the
    whole request body by then.
  - Deploy: an older registry refuses the new `.env` keys, so a rollback to a
    commit from before this feature needs the `AWS_*` lines removed first
    (deploy/README.md).

## 51. registry-service: `GET /v1/plot-photos?farm_id=` lists plots that have a photo
- **Decided (2026-11-25):** a read-only endpoint returning `{"plot_ids": [...]}`:
  the plots of one farm that have a `plot_photos` row. One query (`plots` joined
  to `plot_photos`, filtered by farm, `ORDER BY p.rowid`, so plot creation
  order). No S3 call. `farm_id` is required; a missing or malformed value is
  `422`. An unknown farm is `200` with `[]`, like `GET /v1/plots?farm_id=`.
- **Why this over per-plot `GET /plots/{id}/photo`:** the home page would send
  one request per plot and get a `404` for each plot without a photo (a 404
  storm), and every request would also hit S3. One call answers for the whole
  farm, and the plot JSON stays unchanged (judgment log 50).
- **Known limits:**
  - It says the database has a row, not that the S3 object exists. If the
    object is missing, `GET /plots/{id}/photo` still returns `503`.
  - It cannot tell the frontend when a photo changed. `plot_ids` has no
    version or timestamp, and the photo GET is `no-store`.
  - No pagination: the list is as long as the farm's photo count.
  - A plot moved to another farm shows up under its current farm.

