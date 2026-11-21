# Design: registry-service on PostgreSQL

Date: 2026-11-14. Branch: `p2`. Spec: `docs/task-p2.md`, section "The
registry-service" (FR-2.1, FR-2.2, NFR-2.1, NFR-2.2).

## 1. Intent

In production, `registry-service` stores its data in PostgreSQL (the existing
database `registry`). On a developer's machine and in tests, it keeps using a
local SQLite file. Moving between the two is configuration only: the
`DATABASE_URL` in `.env`.

Clients must not notice the move. Planner and frontend (P2) depend on every
status code, every `application/problem+json` body and `code`, and the
`Retry-After` on 503 staying exactly as P1 shipped them.

## 2. Goals, non-goals, anti-goals

**Goals**

- G1. Every existing endpoint behaves exactly the same on both databases:
  same status codes, bodies, `code` values, headers, and list order.
- G2. `DATABASE_URL` alone selects the database. No code change, no code path
  chosen by a flag other than the URL's dialect.
- G3. One documented command creates the five tables in an empty database and
  loads the same 15 seed rows as `seed_registry.sh` (FR-2.2).
- G4. NFR-2.2: `GET` list and `GET` by id, p95 <= 100 ms at 10 req/s, on
  PostgreSQL, measured with the existing `perf/` tooling.
- G5. The 503 rule from P1 holds on PostgreSQL: environment problems are 503 +
  `Retry-After: 5`; bugs are 500.

**Non-goals**

- No ORM, no Alembic, no migrations framework.
- No schema change in `seed_registry.sh`; it stays the local seed tool.
- No new endpoints, fields, or validation rules, except one deliberate
  change: NUL in name fields (5.12).
- `perf/make_large_db.py` (the scale experiment) stays SQLite-only.
- No statement timeouts, read replicas, or async database access.

**Anti-goals** (a failure even if everything "works")

- A test that connects to the PostgreSQL `registry` database, or modifies
  `registry.db`.
- Any `OperationalError` mapped to 503 by exception type alone. On SQLite,
  "no such table" is also an `OperationalError`.
- A missing SQLite file silently turned into a new empty database.
- List order that changes after the move.
- `lat`/`lon`/`area_m2` values that come back different from what was sent.
- A `--reset` that runs by accident, or a load test run against `registry`.

## 3. Constraints

- `.claude/rules/repo.md`: `uv` from `services/registry-service`; no schema
  change in `seed_registry.sh`; tests never touch a real database; never
  commit `registry.db`, `.env`, `perf/results/`.
- Settings come from one `config.py` with pydantic-settings. No hardcoded
  URLs, timeouts, or retries.
- All data access goes through SQLAlchemy (task-p2 notes).
- Decisions already logged in `docs/judgment-log.md` (1-24) stay in force,
  especially 1, 2, 5 (UNIQUE and FK handling) and 14, 15 (503 vs 500).
- All 303 existing tests keep passing. Tests that check behavior over HTTP stay
  unchanged. Tests of SQLite internals (`test_db.py`, parts of
  `test_unavailable.py`) are adapted to the new connection layer while keeping
  what they verify.

## 4. Approaches considered

1. **SQLAlchemy Core with `text()` SQL, one SQL string per query, all
   dialect differences in `db.py`.** (Chosen.) The routers change only in
   their connection type, `?` -> `:name` parameters, transaction blocks, and
   row access. Driver differences (connect arguments, FK pragma, error
   classification, constraint detection) live in one module.
2. **A separate data-access layer per database.** Every query written twice;
   behavior can drift between the two. Rejected: works against NFR-2.1 and G1.
3. **SQLAlchemy Core expressions (`select(table)...`) instead of SQL text.**
   Portable, but rewrites every query. Rejected by D1: larger change for no
   behavioral gain.

## 5. Decisions

Decisions D1-D7 are the owner's, as given. Later decisions were agreed in the
design conversation. Items marked *(builder's call, accepted)* were proposed by
the agent and accepted by the owner.

### 5.1 Stack

- **D1.** SQLAlchemy Core, queries as `text()` SQL. Not the ORM.
- **D2.** PostgreSQL driver: `psycopg` v3 (`psycopg[binary]`). URL scheme
  `postgresql+psycopg://`.
- Dependencies added: `sqlalchemy~=2.0`, `psycopg[binary]~=3.2`,
  `pydantic-settings~=2.6`.

### 5.2 Configuration (D6, D7)

`config.py` (new) holds one pydantic-settings `Settings` class, read from
`services/registry-service/.env` (path anchored to the folder of `config.py`,
not the working directory) and from the environment (environment wins):

| Setting | Required | Example / default | Used for |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes, no default | `sqlite:///file:registry.db?mode=rw&uri=true` | Selects the database. |
| `DB_CONNECT_TIMEOUT_SECONDS` | no, default 3 | `3` | psycopg `connect_timeout`. |
| `DB_BUSY_TIMEOUT_SECONDS` | no, default 5 | `5` | SQLite busy timeout (today's `BUSY_TIMEOUT_SECONDS`) and PostgreSQL `lock_timeout`. |
| `DB_POOL_TIMEOUT_SECONDS` | no, default 5 | `5` | PostgreSQL: how long a request waits for a free pooled connection. |

- If `DATABASE_URL` is missing, the service fails at startup with a clear
  message naming the variable. Settings are read when the app starts
  (lifespan), not at import, so tests can set the environment first.
- `.env.example` is added with the four keys and a commented PostgreSQL
  example (`postgresql+psycopg://user:password@localhost:5432/registry`).
- Defaults for the three timeouts are a *(builder's call, accepted)*; D7 puts
  the real values in `.env`.

### 5.3 Engine and connections *(builder's call, accepted)*

- One engine per app run, created in the FastAPI lifespan from `Settings`
  and disposed on shutdown. `get_db` yields one `Connection` per request and
  closes it.
- **PostgreSQL:** default `QueuePool` (5 + 10 overflow is enough for
  10 req/s), `pool_pre_ping=True` so a connection dropped by a server restart
  becomes a fresh connect (or a clean 503), and
  `pool_timeout=DB_POOL_TIMEOUT_SECONDS`, and
  `connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS, "options":
  "-c lock_timeout=<DB_BUSY_TIMEOUT_SECONDS in ms>"}`. Pooling matters for
  NFR-2.2: a new PostgreSQL connection per request costs several ms.
- **Locks on PostgreSQL** (owner's decision): PostgreSQL waits for a lock
  forever by default, so a request stuck behind a lock would never answer and
  `55P03` would never occur. `lock_timeout` is set from the same
  `DB_BUSY_TIMEOUT_SECONDS` (5 s) as SQLite's busy timeout, so a blocked
  request gets `55P03` -> 503, as a locked SQLite file does in P1. This limits
  only lock waits; a general `statement_timeout` stays out of scope.
- **Full pool** (owner's decision): when all pooled connections are busy for
  `DB_POOL_TIMEOUT_SECONDS`, SQLAlchemy raises `sqlalchemy.exc.TimeoutError`
  (not a `DBAPIError`). A handler maps it to 503 + `Retry-After: 5` with a
  warning log ("connection pool exhausted"), because it is load in the
  environment, not a bug. The SQLAlchemy default of 30 s is replaced by the
  `.env` value.
- **SQLite:** `NullPool`, so every request opens the file as today. A file
  deleted or corrupted while the service runs is noticed on the next request,
  exactly as in P1. `connect_args={"timeout": DB_BUSY_TIMEOUT_SECONDS,
  "check_same_thread": False}`. A `connect` event listener runs
  `PRAGMA foreign_keys = ON` on every new connection.
- `/health` still does not touch the database (engine creation does not
  connect).

### 5.4 Missing SQLite file stays a 503

P1 opens SQLite with `mode=rw`, so a missing file fails (503) instead of
silently creating an empty database. A plain `sqlite:///registry.db` URL in
SQLAlchemy would create the file. We keep URI mode through SQLAlchemy:

```
DATABASE_URL=sqlite:///file:registry.db?mode=rw&uri=true
```

SQLAlchemy's pysqlite dialect passes `file:...?mode=rw` to `sqlite3.connect`
with `uri=True`. The existing test `test_missing_database_is_503` stays, and
still asserts that the file was not created. A relative path is relative to
the working directory, which is always `services/registry-service` (repo
rule). `.env.example` documents that `mode=rw&uri=true` is required.

### 5.5 Schema in PostgreSQL

- **D4, amended: same column types as SQLite, except `REAL` -> `DOUBLE
  PRECISION`.** PostgreSQL `REAL` is a 4-byte float with about 6 significant
  digits. It would round `lat`/`lon` (for example `31.2345678`) and values like
  `area_m2: 1000.1`, so responses would differ from what was sent. SQLite
  `REAL` is an 8-byte float; `DOUBLE PRECISION` is the same thing in
  PostgreSQL. `TEXT` and `INTEGER` stay as they are. No UUID or DATE types.
- **List order: a `rowid` identity column in PostgreSQL.** Six queries use
  `ORDER BY rowid` to return lists in insertion order. PostgreSQL has no
  `rowid`, so each of the five PostgreSQL tables gets
  `rowid BIGINT GENERATED ALWAYS AS IDENTITY`. `rowid` is not reserved in
  PostgreSQL, so the same `ORDER BY rowid` SQL runs on both databases and the
  order stays exactly as today. The column is never selected, because every
  `SELECT` names its columns. Reason: keeping list order exactly as today
  matters more than a perfectly identical schema. Rejected alternative:
  `ORDER BY id`, which needs no extra column but reorders every list, since
  farm and plot ids are random UUIDs.
- Constraints match `seed_registry.sh`: the same primary keys, `NOT NULL`,
  foreign keys, and `UNIQUE (farm_id, name)` on `plots`. The unique constraint
  is created with an explicit name, `plots_farm_id_name_key`.
- **Where the schema lives** *(builder's call, accepted)*: the new seed module
  defines the five tables once as SQLAlchemy Core `Table` objects (DDL only;
  queries stay as text, D1). The PostgreSQL-only `rowid` column is added when
  the target dialect is PostgreSQL. `metadata.create_all()` renders the DDL for
  either dialect.

### 5.6 Setup command (FR-2.2, D3)

```bash
# from services/registry-service; uses DATABASE_URL from .env or the environment
uv run python seed_db.py            # create tables + load seed rows
uv run python seed_db.py --reset    # drop and rebuild the five tables
```

- Works for any `DATABASE_URL` (PostgreSQL or SQLite). For SQLite it opens the
  file in create mode (`mode=rwc`), so it can build a new file.
- **Without `--reset`:** if any of the five tables already exists, it fails
  with a clear message and changes nothing. Exit code non-zero.
- **With `--reset`:** first prints which database it will reset: dialect,
  host, port, and database name (or the file path for SQLite), never the user
  password. Then, in one transaction, drops the five tables (children first)
  and rebuilds and seeds them. PostgreSQL DDL is transactional, so a failure
  leaves the old tables in place.
- Seed rows: the same 15 rows as `seed_registry.sh` (2 crops, 3 soils, 4
  emitters, 2 farms, 4 plots), inserted in the same order, so `rowid` order
  equals the SQLite order.
- **One PostgreSQL role** (owner's decision) owns the five tables and is used
  by both `seed_db.py` and the service, through the same `DATABASE_URL`.
  `seed_db.py` runs no `GRANT`. The setup docs state this requirement and show
  how to create the role and the `registry` / `registry_perf` databases owned
  by it. A service running as a role without grants gets `42501` -> 503 with a
  warning naming the SQLSTATE.
- `seed_registry.sh` is unchanged and stays the usual way to make the local
  `registry.db`. It is also the reference for the tests in 5.10.
- Documented in a short `services/registry-service/README.md` section, or the
  existing docs the builder finds most fitting.

### 5.7 Error handling: the 503 rule (G5)

Handlers in `errors.py` are registered for `sqlalchemy.exc.IntegrityError` and
`sqlalchemy.exc.DBAPIError` instead of `sqlite3.IntegrityError` and
`sqlite3.Error`. They decide by the **original driver exception**
(`exc.orig`), never by the SQLAlchemy type. `db.is_unavailable(orig)` takes the
driver exception:

- **`sqlite3.Error`:** unchanged. The primary SQLite error name is in
  `_UNAVAILABLE_ERRORS` (`CANTOPEN`, `BUSY`, `LOCKED`, `IOERR`, `NOTADB`,
  `CORRUPT`, `FULL`, `READONLY`).
- **`psycopg.Error`:** by SQLSTATE:

| Situation | SQLSTATE | Result |
| --- | --- | --- |
| No connection at all (server down, refused, DNS, connect timeout): `psycopg.OperationalError` with no SQLSTATE | `None` | 503 |
| Connection exception | class `08` | 503 |
| Insufficient resources (disk full, out of memory, too many connections) | class `53` | 503 |
| Operator intervention (shutdown, restart, cannot connect now) | class `57` | 503 |
| System error (I/O) | class `58` | 503 |
| Lock not available (the `SQLITE_BUSY` counterpart) | `55P03` | 503 |
| Deadlock detected (a lock conflict, like `SQLITE_LOCKED`; a retry fixes it) | `40P01` | 503 |
| Read-only transaction | `25006` | 503 |
| Data corrupted / index corrupted | `XX001`, `XX002` | 503 |
| Database does not exist | `3D000` | 503 |
| Invalid authorization (bad password, no permission to connect) | class `28` | 503 |
| Insufficient privilege (no `CONNECT` on the database, no grant on a table) | `42501` | 503 |
| Any other error with no SQLSTATE (client-side errors such as `DataError` for a NUL byte, `ProgrammingError`, `InterfaceError`) | `None` | 500 |
| Anything else (e.g. `42P01` undefined table, `42601` syntax, `42703` undefined column) | | 500 |

- `3D000`, class `28` and `42501` are 503 for the same reason as P1's missing
  SQLite file: the fix is in the environment (create the database, fix the
  password or grants), not in the code.
- Every 503 logs a warning with the method, path, and the driver code: the
  SQLite error name as today, or `SQLSTATE=<code>` for PostgreSQL (`None` for
  no connection). The client body stays `"Database unavailable"`, with no
  driver text.
- The `None` row is narrowed to "no connection at all" *(builder's call)*:
  psycopg also raises errors with no SQLSTATE on the client side (for example
  `DataError` for a NUL byte), and those are bugs, not outages.
  Narrowed further to `psycopg.OperationalError` only (owner's decision,
  judgment log 31): psycopg also raises `InterfaceError` for client-side
  misuse such as a closed cursor, which is a bug.
- Any other driver error is re-raised to the 500 handler, unchanged from P1.
- **Connect failures:** `engine.connect()` in `get_db` raises
  `sqlalchemy.exc.OperationalError` wrapping the driver error, so it goes
  through the same handler, as today.

### 5.8 Constraint violations

Detection moves into `db.py` helpers so routers stay dialect-free *(builder's
call, accepted)*:

- `is_foreign_key_violation(orig)`: SQLite message contains `FOREIGN KEY`
  (as today); PostgreSQL SQLSTATE `23503`.
- `unique_violation_key(orig)`: returns a dialect-neutral key, or `None`.
  SQLite: the text after `UNIQUE constraint failed: ` (as today). PostgreSQL:
  SQLSTATE `23505`, mapped from `orig.diag.constraint_name`
  (`plots_farm_id_name_key` -> `"plots.farm_id, plots.name"`), so
  `_UNIQUE_DETAILS` and the 409 body stay the same.
- Judgment log 1, 2, 5 still apply: only UNIQUE is mapped globally; FK
  failures are handled per endpoint (`delete_farm` -> 409, plot writes -> 422
  safety net).

### 5.9 Router changes (mechanical)

- `Db = Annotated[Connection, Depends(get_db)]` (SQLAlchemy `Connection`).
- `?` placeholders -> named parameters (`:id`), executed with `text()`.
- `with conn:` -> `with conn.begin():` for writes.
- Row access via `.mappings()` so `Farm(**row)` and the existing models keep
  working.
- `rowcount` from the `CursorResult`, as today.
- SQLAlchemy 2 "autobegins" a transaction on the first `execute`, so
  `conn.begin()` after a read in the same request fails. Writes that follow a
  read in the same request (PATCH, plot create after `check_references`) use
  `conn.commit()` at the end of the block (and rollback on error), or an
  equivalent the builder picks; the behavior to keep is "all of the
  request's writes in one transaction, rolled back on error".
- `except sqlite3.IntegrityError` in `farms.delete_farm` and `plots._write` ->
  `except sqlalchemy.exc.IntegrityError` plus `is_foreign_key_violation`.
- `check_references` keeps its f-string table name (from a fixed dict, not
  user input).
- No query changes its logic, filter, or order.

### 5.10 Tests (D5)

Tests run on SQLite only. No test connects to PostgreSQL.

- **Autouse fixture (conftest):** before every test, sets `DATABASE_URL` in
  the environment to a SQLite URI for a temporary file, so a developer's
  `.env` that points at PostgreSQL is never used. It also asserts the
  effective URL starts with `sqlite` and fails the test otherwise. `db_file`
  sets `DATABASE_URL` (instead of `REGISTRY_DB_PATH`) to the fresh seeded copy.
- The session fixture that checks `registry.db` is untouched stays (the
  path constant moves to `conftest.py` if `db.py` no longer has it).
- Tests that build their own `FastAPI()` app (`test_errors.py`) do not need an
  engine; tests that use `main.app` get one through the lifespan.
- **Schema comparison test:** build a SQLite file with `seed_registry.sh` and
  read it with SQLAlchemy's inspector. Compare it with the `Table` objects of
  `seed_db.py` for each dialect: table names, column names, order, types,
  nullability, primary keys, foreign keys, and unique constraints. Types match
  when equal, or when SQLite `REAL` corresponds to PostgreSQL `DOUBLE
  PRECISION`. On PostgreSQL, the extra `rowid` identity column is the only
  allowed difference; anything else fails. The PostgreSQL DDL is compiled
  with the PostgreSQL dialect (no connection) to check that the identity and
  `DOUBLE PRECISION` are really emitted.
- **Seed rows test:** run `seed_db.py` against a temporary SQLite file; every
  table's rows, in `rowid` order, equal those of a `seed_registry.sh` copy.
  Also: running it again without `--reset` fails and changes nothing; with
  `--reset` it rebuilds; the reset message shows host and database name and
  never the password (checked on a PostgreSQL URL object, no connection).
- **503 rule on PostgreSQL with fake driver errors:** psycopg exception
  instances (`psycopg.errors.lookup(sqlstate)`, and `psycopg.OperationalError`
  with no SQLSTATE) wrapped in `sqlalchemy.exc.OperationalError`. A
  parametrized `is_unavailable` test covers every row of the table in 5.7,
  (including `40P01`), plus 500 cases (`42P01`, `42601`, `23505`). An HTTP test makes `get_db`
  raise a wrapped error and checks 503 + `Retry-After: 5` (unavailable) and
  500 without `Retry-After` (bug), and the warning log contains the SQLSTATE.
- `get_db` raising `sqlalchemy.exc.TimeoutError` -> 503 + `Retry-After: 5`
  and a warning log.
- The PostgreSQL engine's settings are checked without connecting: the
  `lock_timeout` option equals `DB_BUSY_TIMEOUT_SECONDS` in ms, the connect
  timeout and pool timeout come from the settings.
- Fake `23505` / `23503` errors with `diag.constraint_name` check the 409
  body and the per-endpoint FK mapping.
- **Config tests:** a missing `DATABASE_URL` fails startup with a message
  naming it.
- The existing classification test (`sqlite3` errors by name), the
  missing-file, corrupt-file and locked-file tests stay; the locked test sets
  `DB_BUSY_TIMEOUT_SECONDS` through the environment before the client starts.

### 5.11 Measuring NFR-2.2

- Runs against a separate PostgreSQL database, **`registry_perf`**, never
  `registry`. The owner creates `registry_perf`.
- `run_official.sh` gets a PostgreSQL mode: run with
  `PERF_DATABASE_URL=postgresql+psycopg://.../registry_perf`. The script
  refuses to start unless the URL's database name is exactly `registry_perf`.
  It then exports `DATABASE_URL` for both the seed and the server, resets it
  with `uv run python seed_db.py --reset`, and starts uvicorn as today. Without
  `PERF_DATABASE_URL`, the script behaves exactly as today (SQLite).
- `--db-label postgres` is recorded in the results metadata.
- `load_test.py` is unchanged; it measures over HTTP.
- **Every perf script that starts the server sets `DATABASE_URL`
  explicitly** (`run_official.sh` in both modes, `run_k6_crosscheck.sh`, the
  large-database mode with the file from `make_large_db.py`), replacing
  today's `REGISTRY_DB_PATH`. Otherwise a `.env` pointing at `registry` would
  put load on production. *(builder's call)*
- Pass criterion: as NFR-1.1, p95 <= 100 ms on every list and by-id endpoint,
  from the three Poisson runs of the paired session. Results stay in
  `perf/results/` (not committed) and are summarized in the PR.

### 5.12 NUL characters (`\x00`) in text input

PostgreSQL `TEXT` cannot store NUL; psycopg rejects such a parameter before
sending it, which would surface as a 500. SQLite stores it.

- **Name fields: rejected with 422 `VALIDATION` on both databases.** The
  `Name` type in `models.py` (farm `name`, plot `name`, in create and PATCH)
  rejects any value containing `\x00`. This is **the one deliberate behavior
  change** of this work: on SQLite such a name was accepted (201/200) before.
  The owner's decision; recorded in judgment log 27 and to be mentioned in the
  PR. Tests: farm create, farm PATCH, plot create, plot PATCH with a NUL in
  `name` -> 422 `VALIDATION`.
- **Catalogue ids: no behavior change** *(builder's call)*. `crop_id`, `soil_id`, `emitter_id` (request body) and the
  catalogue path ids (`/v1/crops/{id}`, `/v1/soils/{id}`,
  `/v1/emitters/{id}`) are free strings. Today on SQLite a NUL id matches no
  row: 422 `Unknown crop`/`soil`/`emitter` in a body, 404 on a path. Since no
  stored id can contain NUL, an id containing `\x00` is treated as "no such
  row" without running the query, in `check_references` and the catalogue
  lookups. Responses stay exactly as today on both databases. Tests: one per
  field and per path.
- UUID fields (`farm_id`, plot and farm path ids, `?farm_id=`) are already
  validated as UUIDs, so NUL never reaches the database.

## 6. Files touched

New: `config.py`, `seed_db.py`, `.env.example`, `tests/test_config.py`,
`tests/test_seed_db.py`, PostgreSQL error tests (in `test_unavailable.py` or
a new file).
Changed: `db.py`, `errors.py`, `main.py` (lifespan), `routers/*.py`,
`tests/conftest.py`, `tests/test_db.py`, `tests/test_unavailable.py`,
`pyproject.toml`/`uv.lock`, `perf/run_official.sh`,
`perf/run_k6_crosscheck.sh`, `perf/README.md`,
`docs/judgment-log.md`.
Also changed: `models.py` (NUL in `Name`, 5.12), `routers/catalogue.py` and
`routers/plots.py` (NUL ids, 5.12).
Unchanged: `seed_registry.sh`, `load_test.py`,
`make_large_db.py`.

## 7. Recorded in `docs/judgment-log.md`

- 25. List order on PostgreSQL: a `rowid` identity column.
- 26. Missing database (`3D000`) and authorization errors (class `28`) are 503.
- 27. NUL in name fields is rejected with 422 (the one deliberate behavior
  change).
- 28. Lock waits, deadlocks (`40P01`) and a full pool on PostgreSQL are
  503, with timeouts from `.env`.
- 29. One PostgreSQL role for setup and service; `42501` is 503.

## 8. Left to the builder

- Exact names of the `db.py` helpers and test files.
- Where the setup command is documented (README section or existing doc).
- Whether the PostgreSQL error tests extend `test_unavailable.py` or live in a
  new file.

Required of the plan (owner's instructions):

- The last task updates the `registry-api` skill
  (`.claude/skills/registry-api/SKILL.md`) for PostgreSQL: SQLite-only wording,
  the FK/UNIQUE guidance, and the test fixtures.
- The plan lists every existing test that changes, and why.

## 9. Open questions

None. All questions raised in the design conversation and by the builder
check are answered above.
