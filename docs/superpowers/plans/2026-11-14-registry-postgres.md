# registry-service on PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `registry-service` runs on SQLite locally and on PostgreSQL in production, selected only by `DATABASE_URL`, with every endpoint behaving exactly as in P1 (one deliberate change: NUL in names -> 422).

**Architecture:** SQLAlchemy Core with `text()` SQL; one engine per app run, created in the FastAPI lifespan; every dialect difference (connect options, FK pragma, 503/500 classification, constraint detection) lives in `db.py`. `seed_db.py` defines the schema once as Core `Table` objects and creates and seeds any database.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 Core, psycopg 3, pydantic-settings, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-14-registry-postgres-design.md`. Read it before any task; section numbers below (§5.7 etc.) refer to it.

## Global Constraints

- All commands run from `services/registry-service` (`uv sync`, `uv run pytest`, `uv run python ...`).
- After every task: `uv run pytest` passes in full (baseline: `303 passed`), and the count only grows.
- Tests never connect to PostgreSQL and never modify `services/registry-service/registry.db`.
- `seed_registry.sh` is not changed.
- Never commit `registry.db`, `.env`, `perf/results/`.
- Dependencies: `sqlalchemy~=2.0`, `psycopg[binary]~=3.2`, `pydantic-settings~=2.6`.
- Settings only from `config.py`: `DATABASE_URL` (required, no default), `DB_CONNECT_TIMEOUT_SECONDS=3`, `DB_BUSY_TIMEOUT_SECONDS=5`, `DB_POOL_TIMEOUT_SECONDS=5`. No hardcoded URLs or timeouts elsewhere.
- Error bodies, codes, details and `Retry-After: 5` stay byte-for-byte as P1 (`errors.py`, `tests/conftest.py::assert_problem`).
- Queries are `text()` SQL with named parameters; every list keeps `ORDER BY rowid`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Non-UTF8 PostgreSQL database or Hebrew/emoji names**: a name like `"חלקה צפונית 🌱"` must round-trip unchanged. Pinned: Task 4 round-trip test on SQLite; README (Task 3) requires `ENCODING 'UTF8'`; owner smoke test U4.
2. **A reference deleted between `check_references` and the write** (PostgreSQL `23503`): plot write -> 422 `"Unknown farm, crop, soil or emitter"`, farm delete -> 409. Pinned: Task 6 fake-FK tests.
3. **Float precision**: `lat: 31.2345678`, `area_m2: 1000.1` come back identical. Pinned: Task 3 DDL test (`DOUBLE PRECISION`), Task 4 round-trip test, U4.
4. **A password with `@`, `:` or `/` in `DATABASE_URL`**: must be percent-encoded or the URL parses wrong. Pinned: README note (Task 3); `describe_target` test (Task 3) uses an encoded password and checks it is never printed.
5. **A running service whose database restarts** (pooled connections die): next request must reconnect (pre-ping) or get 503, never 500. Pinned: Task 6 tests for classes `08`/`57`; Task 5 `pool_pre_ping` test; U4.

## Existing tests that change, and why (spec §8)

| Test | Task | Change | Why |
| --- | --- | --- | --- |
| `tests/conftest.py::db_file` | 4 | Sets `DATABASE_URL` (via `sqlite_url(path)`) instead of `REGISTRY_DB_PATH`. | `REGISTRY_DB_PATH` no longer exists; the URL selects the database. |
| `tests/conftest.py` (new autouse `force_sqlite`) | 4 | Added, not changed. | §5.10: a developer `.env` pointing at PostgreSQL must never be used by tests. |
| `test_db.py::test_fixture_points_at_fresh_seeded_copy` | 4 | Checks `get_settings().database_url == sqlite_url(db_file)`; counts rows through `make_engine`. | `db.db_path()` and `db.connect()` are removed. |
| `test_db.py::test_connect_enables_foreign_keys` | 4 | Same assertion through an engine connection; expects `sqlalchemy.exc.IntegrityError` with `FOREIGN KEY`. | Connections now come from the engine; the pragma moves to a connect listener. |
| `test_db.py::test_connect_returns_rows_by_column_name` | 4 | Uses `.mappings()`. | SQLAlchemy rows replace `sqlite3.Row`. |
| `test_db.py::test_connect_does_not_create_a_missing_file` | 4 | Engine `connect()` on a missing file raises `sqlalchemy.exc.OperationalError`; file still absent. | Same guarantee (§5.4), new API. |
| `test_db.py::test_get_db_closes_the_connection` | 4 | `get_db(request)` with a fake request holding `app.state.engine`; after exhaustion `conn.closed is True`. | `get_db` now takes the request and yields an SQLAlchemy `Connection`. |
| `test_unavailable.py::missing_db` fixture, `test_corrupt_database_is_503` | 4 | Set `DATABASE_URL` instead of `REGISTRY_DB_PATH`. HTTP assertions unchanged. | Same as `db_file`. |
| `test_unavailable.py::test_locked_database_is_503` | 4 | Sets env `DB_BUSY_TIMEOUT_SECONDS=0.05` and opens its own `TestClient(app)` after that, instead of `monkeypatch.setattr(db, "BUSY_TIMEOUT_SECONDS", ...)`. Assertions unchanged. | The timeout is a setting, read when the app starts (§5.2). |
| `test_errors.py::probe` fixture | 4 | Probe app gets `lifespan=db.lifespan`; its two routes take `Connection`, use `text()`, `:id`, `conn.commit()`. All test assertions unchanged. | Probe routes use the real `get_db`, which now needs an engine. |

Unchanged on purpose: `test_classification_by_error_code` (`is_unavailable` keeps accepting `sqlite3` errors), `test_missing_table_is_a_bug_not_503`, `test_unavailable_is_logged_for_operations` (still `SQLITE_CANTOPEN` in the log), all tests that open `db_file` with `sqlite3` for setup or checks (`test_farms.py`, `test_catalogue.py`, `test_errors.py`), `test_make_large_db.py` (`db.DEFAULT_DB_PATH` is kept).

## Steps only the owner does (not planned for the agent)

- **U1.** Create the PostgreSQL role that owns the tables, make it the owner of `registry`, and create `registry_perf` owned by it, both `ENCODING 'UTF8'` (commands in the README from Task 3). After Task 3.
- **U2.** Write `services/registry-service/.env` with the real `DATABASE_URL` (password percent-encoded). After Task 5.
- **U3.** Run `uv run python seed_db.py` against `registry`. After Task 6.
- **U4.** Smoke test on PostgreSQL: start the service; `GET /v1/farms`, `GET /v1/plots/<id>`; POST a plot with `lat: 31.2345678` and a Hebrew name and read it back; `GET /v1/crops/Tomato` -> 404; stop PostgreSQL -> `GET /v1/farms` is 503 with `Retry-After: 5`; start it again -> 200 without restarting the service. After Task 6.
- **U5.** Official NFR-2.2 measurement: `DB=postgres PERF_DATABASE_URL='postgresql+psycopg://<role>:<pw>@localhost:5432/registry_perf' RESULTS_PREFIX=pg bash perf/run_official.sh`. After Task 7.

---

### Task 1: Dependencies and settings

**Files:**
- Modify: `services/registry-service/pyproject.toml`, `uv.lock`
- Create: `services/registry-service/config.py`, `services/registry-service/.env.example`
- Test: `services/registry-service/tests/test_config.py`

**Interfaces:**
- Produces: `config.ENV_FILE: Path` (= `Path(__file__).parent / ".env"`); `class Settings(BaseSettings)` with fields `database_url: str`, `db_connect_timeout_seconds: int = 3`, `db_busy_timeout_seconds: float = 5`, `db_pool_timeout_seconds: float = 5` (env names are the upper-case field names); `def get_settings() -> Settings` reads environment, then `ENV_FILE`, and raises `RuntimeError` whose message starts with `"DATABASE_URL is required"` and mentions `.env.example` when the URL is missing.

- [ ] **Step 1: Add dependencies.** `uv add 'sqlalchemy~=2.0' 'psycopg[binary]~=3.2' 'pydantic-settings~=2.6'`. Expected: `uv.lock` updated, `uv run pytest -q` -> `303 passed`.
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:
  - `test_reads_database_url_from_environment`: setenv `DATABASE_URL=sqlite:///file:x.db?mode=rw&uri=true`, monkeypatch `config.ENV_FILE` to `tmp_path / "none.env"`; `get_settings().database_url` equals it; timeouts equal `3`, `5`, `5`.
  - `test_environment_wins_over_env_file`: write `DATABASE_URL=sqlite:///from-file` to a tmp `.env`, point `config.ENV_FILE` at it, setenv another URL; the env value wins.
  - `test_env_file_is_read`: same file, `delenv("DATABASE_URL")`; value is `sqlite:///from-file`; `DB_BUSY_TIMEOUT_SECONDS=0.05` in the file gives `0.05`.
  - `test_missing_database_url_is_a_clear_error`: delenv, `ENV_FILE` -> missing file; `pytest.raises(RuntimeError, match="^DATABASE_URL is required")`.
- [ ] **Step 3: Run** `uv run pytest tests/test_config.py -v`. Expected: FAIL, `ModuleNotFoundError: No module named 'config'`.
- [ ] **Step 4: Implement `config.py`** as in Interfaces. `get_settings()` constructs `Settings(_env_file=ENV_FILE)` at call time (so tests can patch `ENV_FILE`) and converts the pydantic `ValidationError` for a missing `database_url` into the `RuntimeError`.
- [ ] **Step 5: Write `.env.example`** with the four keys: `DATABASE_URL=sqlite:///file:registry.db?mode=rw&uri=true` (comment: `mode=rw&uri=true` is required so a missing file is an error, not a new empty database; the path is relative to `services/registry-service`), a commented `# DATABASE_URL=postgresql+psycopg://agropilot:<password>@localhost:5432/registry` (comment: percent-encode special characters in the password), and the three timeouts with their defaults.
- [ ] **Step 6: Run** `uv run pytest -q`. Expected: `307 passed`.
- [ ] **Step 7: Commit** `pyproject.toml uv.lock config.py .env.example tests/test_config.py` — "Add settings (DATABASE_URL, DB timeouts) and SQLAlchemy/psycopg dependencies".

### Task 2: NUL characters in text input (§5.12)

**Files:**
- Modify: `models.py` (`Name`), `routers/plots.py` (`check_references`), `routers/catalogue.py` (`get_crop`, `get_soil`, `get_emitter`)
- Test: `tests/test_farms.py`, `tests/test_plot_validation.py`, `tests/test_catalogue.py`

**Interfaces:**
- Produces: `Name` rejects any value containing `"\x00"` (422 `VALIDATION`, detail starts with `body.name:`). `check_references` raises `validation(<detail>)` for a value containing `"\x00"` without querying. Catalogue `get_*` raise their existing `not_found(...)` for an id containing `"\x00"` without querying.

- [ ] **Step 1: Write failing tests.**
  - `test_farms.py::test_name_with_nul_is_422` parametrized over `POST /v1/farms {"name": "a\x00b"}` and `PATCH /v1/farms/{DEMO_COOPERATIVE} {"name": "a\x00b"}`: `assert_problem(..., 422, "VALIDATION")`, `"body.name" in detail`; farm list unchanged afterwards.
  - `test_plot_validation.py::test_plot_name_with_nul_is_422` for POST (spec body with `name="a\x00b"`) and PATCH `/v1/plots/{NORTH_BLOCK}`: 422 `VALIDATION`, `"body.name"` in detail.
  - `test_plot_validation.py::test_catalogue_id_with_nul_is_unknown` parametrized over `crop_id`/`soil_id`/`emitter_id` with value `"tomato\x00"`: 422 with detail exactly `"Unknown crop"` / `"Unknown soil"` / `"Unknown emitter"` (today's SQLite result).
  - `test_catalogue.py::test_catalogue_path_id_with_nul_is_404` over `/v1/crops/tomato%00`, `/v1/soils/sand%00`, `/v1/emitters/dripnet-pc-1.0%00`: 404 `NOT_FOUND`, same detail as an unknown id.
- [ ] **Step 2: Run** these tests. Expected: the name tests FAIL (201/200 today); the catalogue-id and path tests already PASS on SQLite (they pin today's behavior for the PostgreSQL switch).
- [ ] **Step 3: Implement.** Add an `AfterValidator` to `Name` that raises `ValueError("must not contain NUL characters")`; add the `"\x00" in value` guard in `check_references` and the three catalogue lookups.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass (`307 + new`).
- [ ] **Step 5: Commit** — "Reject NUL in names with 422; treat NUL catalogue ids as unknown".

### Task 3: `seed_db.py`: schema, seed rows, setup command, setup docs (§5.5, §5.6)

**Files:**
- Create: `services/registry-service/seed_db.py`, `services/registry-service/README.md`
- Test: `services/registry-service/tests/test_seed_db.py`; add helper `sqlite_url(path: Path) -> str` to `tests/conftest.py` (returns `f"sqlite:///file:{path}?mode=rw&uri=true"`)

**Interfaces:**
- Consumes: `config.get_settings()`.
- Produces (in `seed_db.py`):
  - `TABLES: tuple[str, ...] = ("crops", "soils", "emitters", "farms", "plots")` (insert order; drop is the reverse).
  - `SEED_ROWS: dict[str, list[dict[str, Any]]]` — the 15 rows of `seed_registry.sh`, same order.
  - `def build_metadata(dialect_name: str) -> MetaData` — five tables, columns in `seed_registry.sh` order; `TEXT`/`INTEGER`; `REAL` on sqlite and `DOUBLE_PRECISION` on postgresql; FKs as in the script; `UniqueConstraint("farm_id", "name", name="plots_farm_id_name_key")`; on postgresql only, each table also gets `Column("rowid", BigInteger, Identity(always=True), nullable=False)` as its last column.
  - `class TablesExistError(Exception)`.
  - `def create_and_seed(engine: Engine, *, reset: bool) -> None` — without `reset`, raises `TablesExistError` naming the existing tables if any of `TABLES` exists, before changing anything; with `reset`, in one `engine.begin()` block: drop existing tables (children first), `create_all`, insert `SEED_ROWS`.
  - `def describe_target(url: URL) -> str` — `"postgresql database 'registry_perf' on db.example:5433 as alice"` style (dialect, database, host, port, user); `"sqlite file /abs/path"` for SQLite. Never contains the password.
  - `def seed_url(database_url: str) -> str` — for SQLite, `mode=rw` -> `mode=rwc`; other URLs unchanged.
  - `def main(argv: list[str] | None = None) -> int` — `argparse` with `--reset`; URL from `get_settings()`; with `--reset` prints `Resetting <describe_target>` before touching anything; prints `Created and seeded <describe_target>` on success; on `TablesExistError` prints the message plus "use --reset to rebuild" to stderr and returns `1`. `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 1: Write failing tests** in `tests/test_seed_db.py`:
  - `test_schema_matches_seed_script_on_sqlite`: build a file with `seed_registry.sh`; with `sqlalchemy.inspect` read tables, columns (name, type string, nullable, order), PKs, FKs (`constrained_columns`, `referred_table`, `referred_columns`), unique constraints (column lists). Compare with `build_metadata("sqlite")` (types compiled with the sqlite dialect). Must be equal.
  - `test_postgres_schema_differs_only_by_rowid`: the same reference compared with `build_metadata("postgresql")`, types compiled with the postgresql dialect, with the mapping `REAL -> DOUBLE PRECISION`; after removing the column named `rowid` from each PostgreSQL table, everything is equal; and every PostgreSQL table has exactly one extra column, `rowid`. Any other difference fails.
  - `test_postgres_ddl_emits_identity_and_double_precision`: `str(CreateTable(t).compile(dialect=postgresql.dialect()))` for `plots` contains `GENERATED ALWAYS AS IDENTITY`, `DOUBLE PRECISION`, `CONSTRAINT plots_farm_id_name_key UNIQUE (farm_id, name)`, and no `REAL`.
  - `test_seed_rows_match_seed_script`: env `DATABASE_URL=sqlite_url(tmp/"new.db")` (file absent); `main([]) == 0`; for every table, `SELECT * FROM t ORDER BY rowid` via `sqlite3` equals the `seed_registry.sh` copy; total row count `15`.
  - `test_existing_tables_are_refused`: second `main([])` returns `1`, stderr mentions `--reset`, rows unchanged (rename a farm first and check it is still renamed).
  - `test_reset_rebuilds`: after renaming a farm, `main(["--reset"]) == 0`, stdout starts with `Resetting sqlite file`, rows equal the seed again.
  - `test_describe_target_never_shows_password`: `make_url("postgresql+psycopg://alice:p%40ss%3Aw0rd@db.example:5433/registry_perf")` -> contains `registry_perf`, `db.example`, `5433`, `alice`; does not contain `p@ss`, `p%40ss`, `w0rd`.
- [ ] **Step 2: Run** `uv run pytest tests/test_seed_db.py -v`. Expected: FAIL, `No module named 'seed_db'`.
- [ ] **Step 3: Implement `seed_db.py`** per Interfaces. SQLite connect listener for `PRAGMA foreign_keys = ON` is not needed here.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Write `services/registry-service/README.md`**: configuration (`cp .env.example .env`, the four keys); local SQLite (`bash seed_registry.sh`, then uvicorn); PostgreSQL setup: one role owns the tables and is used by both `seed_db.py` and the service, no GRANTs (§5.6), example `CREATE ROLE agropilot LOGIN PASSWORD '...'; CREATE DATABASE registry_perf OWNER agropilot ENCODING 'UTF8' TEMPLATE template0;` and `ALTER DATABASE registry OWNER TO agropilot;`; databases must be UTF8; percent-encode special characters in the password; `uv run python seed_db.py` and `--reset` (refuses existing tables; `--reset` prints the target first and drops all registry data).
- [ ] **Step 6: Commit** `seed_db.py README.md tests/test_seed_db.py tests/conftest.py` — "Add seed_db.py: one command creates and seeds the registry schema".

### Task 4: Switch the service to SQLAlchemy (SQLite only) (§5.3, §5.4, §5.7 SQLite part, §5.8 SQLite part, §5.9, §5.10)

The largest task; it is one change because routers, `get_db`, the handlers and the fixtures must switch together for the suite to stay green.

**Files:**
- Modify: `db.py`, `main.py`, `errors.py`, `routers/farms.py`, `routers/plots.py`, `routers/catalogue.py`, `tests/conftest.py`, `tests/test_db.py`, `tests/test_unavailable.py`, `tests/test_errors.py`, `perf/run_official.sh`, `perf/run_k6_crosscheck.sh`, `/README.md` (repo root, "Where to start")
- Test: the changed tests above, plus `tests/test_plots.py` round-trip test

**Interfaces:**
- Consumes: `config.Settings`, `config.get_settings()`, `tests/conftest.py::sqlite_url`.
- Produces (in `db.py`; `DEFAULT_DB_PATH` and `_UNAVAILABLE_ERRORS` stay; `db_path`, `connect`, `BUSY_TIMEOUT_SECONDS` are removed):
  - `def engine_kwargs(settings: Settings) -> dict[str, Any]` — SQLite: `{"poolclass": NullPool, "connect_args": {"timeout": settings.db_busy_timeout_seconds, "check_same_thread": False}}`. Other dialects: `ValueError` for now (Task 5).
  - `def make_engine(settings: Settings) -> Engine` — `create_engine(settings.database_url, **engine_kwargs(settings))`; for SQLite, a `"connect"` event listener runs `PRAGMA foreign_keys = ON`.
  - `@asynccontextmanager async def lifespan(app: FastAPI)` — `app.state.engine = make_engine(get_settings())`, yield, `dispose()`.
  - `def get_db(request: Request) -> Iterator[Connection]` — `with request.app.state.engine.connect() as conn: yield conn`.
  - `def is_unavailable(exc: BaseException) -> bool` — the driver exception; SQLite branch unchanged; anything else `False` for now (Task 6).
  - `def driver_code(exc: BaseException) -> str` — SQLite: `exc.sqlite_errorname`; else `"unknown"` for now (Task 6).
  - `def is_foreign_key_violation(exc: BaseException) -> bool` — SQLite: `"FOREIGN KEY" in str(exc)`.
  - `def unique_violation_key(exc: BaseException) -> str | None` — SQLite: text after `"UNIQUE constraint failed: "`, else `None`.
- `main.py`: `FastAPI(..., lifespan=lifespan)`.
- `errors.py`: handlers registered on `sqlalchemy.exc.IntegrityError` (`unique_violation_key(exc.orig)`; `None` -> re-raise) and `sqlalchemy.exc.DBAPIError` (`is_unavailable(exc.orig)`; warning log uses `driver_code(exc.orig)`; bodies unchanged).
- Routers: `Db = Annotated[Connection, Depends(get_db)]`; `text()` with `:name` params; `.mappings()` for rows; writes end with `conn.commit()` (no `conn.begin()` after a read, §5.9); `except sqlalchemy.exc.IntegrityError as exc: if not is_foreign_key_violation(exc.orig): raise` in `delete_farm` and `plots._write` (which takes `params: dict[str, Any]`).
- `tests/conftest.py`: autouse `force_sqlite(tmp_path, monkeypatch)` sets `DATABASE_URL=sqlite_url(tmp_path / "no-database.db")`, then asserts `get_settings().database_url.startswith("sqlite")`; `db_file` sets `DATABASE_URL=sqlite_url(path)`.

- [ ] **Step 1: Write the new tests first.**
  - `tests/test_db.py::test_force_sqlite_is_active`: `get_settings().database_url.startswith("sqlite")` even when a tmp `.env` with `DATABASE_URL=postgresql+psycopg://x@localhost/registry` is patched in as `config.ENV_FILE`.
  - `tests/test_plots.py::test_values_round_trip_exactly`: POST the spec body with `name="חלקה צפונית 🌱"`, `lat=31.2345678`, `lon=34.7818064`, `area_m2=1000.1`; `GET` it back; those four fields equal what was sent.
  - `tests/test_db.py::test_startup_fails_without_database_url`: delenv `DATABASE_URL`, patch `config.ENV_FILE` to a missing file; `with pytest.raises(RuntimeError, match="DATABASE_URL"): with TestClient(app): pass`.
- [ ] **Step 2: Run** them. Expected: `test_force_sqlite_is_active` and `test_startup_fails_without_database_url` FAIL (no fixture, no lifespan); round-trip PASSES (pins SQLite behavior).
- [ ] **Step 3: Implement `db.py`, `main.py`, `errors.py`** per Interfaces.
- [ ] **Step 4: Convert the three routers** per Interfaces. No query changes logic, filter or `ORDER BY rowid`.
- [ ] **Step 5: Update the existing tests** exactly as listed in "Existing tests that change" (conftest, `test_db.py`, `test_unavailable.py`, `test_errors.py::probe`).
- [ ] **Step 6: Run** `uv run pytest -q`. Expected: all pass, none skipped; `git diff --stat tests/` touches only the files in the table plus the new tests.
- [ ] **Step 7: Keep the perf scripts and README runnable.** In both perf scripts, replace `export REGISTRY_DB_PATH="$PWD/$DB_FILE"` with `export DATABASE_URL="sqlite:///file:$PWD/$DB_FILE?mode=rw&uri=true"` and export the same for `DB=seed` (`$PWD/registry.db`) before `start_server`; update the `start_server` comment. Root `README.md` "Where to start": add `cp .env.example .env` and `bash seed_registry.sh` before uvicorn, link `services/registry-service/README.md`.
- [ ] **Step 8: Verify the real service.** Run `DATABASE_URL="sqlite:///file:$PWD/registry.db?mode=rw&uri=true" uv run uvicorn main:app --port 8000` against the existing local `registry.db` (read-only requests), then `curl -s localhost:8000/v1/farms` -> JSON array of 2 farms; `curl -si localhost:8000/health` -> 200. Stop the server. `git status` shows no `registry.db` change.
- [ ] **Step 9: Commit** — "Move data access to SQLAlchemy Core (SQLite behavior unchanged)".

### Task 5: PostgreSQL engine settings (§5.3)

**Files:**
- Modify: `db.py` (`engine_kwargs`)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: for a `postgresql` URL, `engine_kwargs(settings) == {"pool_pre_ping": True, "pool_timeout": settings.db_pool_timeout_seconds, "connect_args": {"connect_timeout": settings.db_connect_timeout_seconds, "options": f"-c lock_timeout={round(settings.db_busy_timeout_seconds * 1000)}"}}` (default `QueuePool`). Unknown dialects still raise `ValueError`.

- [ ] **Step 1: Write failing tests** in `tests/test_db.py`:
  - `test_postgres_engine_options`: `Settings(database_url="postgresql+psycopg://u:p@localhost:5432/registry_perf", db_busy_timeout_seconds=5, db_pool_timeout_seconds=5, db_connect_timeout_seconds=3, _env_file=None)`; `engine_kwargs(...)` equals the dict above with `"-c lock_timeout=5000"`, `connect_timeout` `3`, `pool_timeout` `5`.
  - `test_postgres_engine_is_created_without_connecting`: `make_engine(...)` on that URL succeeds with no server contact; `isinstance(engine.pool, QueuePool)`; `engine.pool.timeout() == 5`.
  - `test_lock_timeout_follows_busy_timeout`: `db_busy_timeout_seconds=0.25` -> `"-c lock_timeout=250"`.
- [ ] **Step 2: Run.** Expected: FAIL with `ValueError`.
- [ ] **Step 3: Implement** the PostgreSQL branch of `engine_kwargs`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** — "PostgreSQL engine: pool, pre-ping, connect and lock timeouts from settings".

### Task 6: PostgreSQL error classification, constraints, full pool (§5.7, §5.8)

**Files:**
- Modify: `db.py` (`is_unavailable`, `driver_code`, `is_foreign_key_violation`, `unique_violation_key`), `errors.py` (new handler)
- Test: create `tests/test_postgres_errors.py`

**Interfaces:**
- Produces:
  - `is_unavailable(exc)` for `psycopg.Error`: `exc.sqlstate is None` -> `isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))`; else `True` iff `sqlstate[:2] in {"08", "53", "57", "58", "28"}` or `sqlstate in {"55P03", "40P01", "25006", "XX001", "XX002", "3D000", "42501"}`.
  - `driver_code(exc)` for `psycopg.Error`: `f"SQLSTATE={exc.sqlstate}"` (`"SQLSTATE=None"` when absent).
  - `is_foreign_key_violation(exc)`: psycopg `sqlstate == "23503"`.
  - `unique_violation_key(exc)`: psycopg `sqlstate == "23505"` and `exc.diag.constraint_name == "plots_farm_id_name_key"` -> `"plots.farm_id, plots.name"`; other `23505` -> `""` (renders `"Record already exists"`); otherwise `None`.
  - `errors.py`: handler for `sqlalchemy.exc.TimeoutError` -> same 503 body and `Retry-After: 5` as the database-unavailable response; warning log `"Database connection pool exhausted on %s %s"`.
- Test helper (in the test file): `fake_pg_error(sqlstate: str | None, constraint_name: str | None = None, base: type | None = None) -> psycopg.Error` — a subclass of `psycopg.errors.lookup(sqlstate)` (or `base`, default `psycopg.OperationalError`, when `sqlstate` is `None`) with `sqlstate` and `diag` (an object with `constraint_name`) overridden as class attributes, then instantiated. Wrap for HTTP tests in `sqlalchemy.exc.OperationalError("SELECT 1", {}, orig)` / `sqlalchemy.exc.IntegrityError(...)`.

- [ ] **Step 1: Write failing tests** in `tests/test_postgres_errors.py`:
  - `test_postgres_classification` parametrized — 503: `None` (OperationalError), `None` (InterfaceError), `08006`, `08001`, `53100`, `53300`, `57P01`, `57P03`, `58030`, `55P03`, `40P01`, `25006`, `XX001`, `XX002`, `3D000`, `28P01`, `28000`, `42501`; 500: `None` with `base=psycopg.DataError`, `None` with `base=psycopg.ProgrammingError`, `42P01`, `42601`, `42703`, `23505`, `23503`, `22021`.
  - `test_postgres_unavailable_is_503_over_http` (override `get_db` on `main.app` with a dependency raising the wrapped `57P01` error, `raise_server_exceptions=False`): `assert_unavailable` (from `test_unavailable.py`), log contains `SQLSTATE=57P01`, body has no driver text.
  - `test_postgres_no_connection_is_503_and_logged`: `None`/OperationalError -> 503, log contains `SQLSTATE=None`.
  - `test_postgres_bug_is_500`: `42P01` -> `assert_internal_error`.
  - `test_pool_exhausted_is_503`: dependency raises `sqlalchemy.exc.TimeoutError("QueuePool limit reached")` -> `assert_unavailable`, log contains `pool exhausted`.
  - Constraint tests use one stub: `get_db` overridden to yield a `StubConnection` whose `execute` raises a given wrapped `sqlalchemy.exc.IntegrityError` and whose `commit`/`rollback` do nothing; `plots.check_references` monkeypatched to a no-op.
  - `test_postgres_unique_violation_is_409`: `POST /v1/plots` (spec body), `execute` raises wrapped `23505` with `constraint_name="plots_farm_id_name_key"` -> 409 `CONFLICT`, detail `"A plot with this name already exists in this farm"`.
  - `test_postgres_fk_on_plot_write_is_422`: same POST, wrapped `23503` -> 422 `VALIDATION`, detail `"Unknown farm, crop, soil or emitter"`.
  - `test_postgres_fk_on_farm_delete_is_409`: `DELETE /v1/farms/{DEMO_COOPERATIVE}`, wrapped `23503` -> 409 `CONFLICT`, detail `"Farm has plots; delete or move them first"`.
- [ ] **Step 2: Run** `uv run pytest tests/test_postgres_errors.py -v`. Expected: classification rows for psycopg FAIL (all `False`), HTTP tests FAIL (500).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** — "Classify PostgreSQL errors by SQLSTATE; full pool is 503".

### Task 7: NFR-2.2 measurement on PostgreSQL (§5.11)

**Files:**
- Modify: `perf/run_official.sh`, `perf/run_k6_crosscheck.sh`, `perf/README.md`

**Interfaces:**
- Produces: `DB=postgres` mode in both scripts. Pre-flight (in the existing `case "$DB"` block, before the Enter prompt): `PERF_DATABASE_URL` must be set, and its database name (read with `uv run python -c 'import sys; from sqlalchemy.engine import make_url; print(make_url(sys.argv[1]).database)'`) must be exactly `registry_perf`; otherwise `FAIL: DB=postgres needs PERF_DATABASE_URL pointing at the registry_perf database` and exit 1. `DB_LABEL="postgres (registry_perf)"`. Build step: `export DATABASE_URL="$PERF_DATABASE_URL"`, then `uv run python seed_db.py --reset | tee "$RESULTS/$RESULTS_PREFIX-seed-db.txt"`. `DB=seed` and `DB=large` behave as after Task 4.

- [ ] **Step 1: Implement** in `run_official.sh`, then the same in `run_k6_crosscheck.sh`.
- [ ] **Step 2: Verify the refusals.** `DB=postgres ASSUME_YES=1 RESULTS_PREFIX=chk1 bash perf/run_official.sh` -> exit 1, the FAIL line, no server started. `DB=postgres PERF_DATABASE_URL='postgresql+psycopg://u:p@localhost/registry' ASSUME_YES=1 RESULTS_PREFIX=chk2 bash perf/run_official.sh` -> exit 1, same FAIL line. Same two checks for `run_k6_crosscheck.sh`. Remove any `perf/results/chk*` left behind.
- [ ] **Step 3: Verify SQLite mode still runs.** `WARMUP=2 DURATION=10 ASSUME_YES=1 RESULTS_PREFIX=dry-p2 bash perf/run_official.sh` -> all six runs complete and the summary prints (pass/fail of a 10 s run is not judged).
- [ ] **Step 4: Document** in `perf/README.md`: the `DB=postgres` mode, `PERF_DATABASE_URL`, the `registry_perf`-only rule, that the owner creates `registry_perf` (README from Task 3), and the U5 command.
- [ ] **Step 5: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** — "perf: PostgreSQL mode against registry_perf for NFR-2.2".

### Task 8: Update the `registry-api` skill for PostgreSQL

**Files:**
- Modify: `.claude/skills/registry-api/SKILL.md`

- [ ] **Step 1: Edit** the skill: description says SQLite locally / PostgreSQL in production via `DATABASE_URL`; data access is SQLAlchemy Core `text()` with named params, `Connection` from `get_db`, `.mappings()`, writes end with `conn.commit()`; FK/UNIQUE: use `is_foreign_key_violation(exc.orig)` and the global UNIQUE handler (both dialects), and keep `check_references` (neither driver's FK error names the column); 503 rule: decided by the driver error in `db.is_unavailable` — add new SQLSTATEs there, never map by exception type; NUL in names is 422; tests: `client`/`db_file` fixtures, the autouse SQLite guard, PostgreSQL errors tested with `fake_pg_error`, never a real PostgreSQL database; schema changes go in `seed_db.build_metadata` and must keep the schema-comparison test green.
- [ ] **Step 2: Verify** `grep -n "sqlite3.Connection\|REGISTRY_DB_PATH" .claude/skills/registry-api/SKILL.md` -> no output; `uv run pytest -q` -> all pass.
- [ ] **Step 3: Commit** — "registry-api skill: PostgreSQL, SQLAlchemy and the 503 rule".
