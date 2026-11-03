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
