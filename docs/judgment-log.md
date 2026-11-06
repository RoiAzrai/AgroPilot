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
