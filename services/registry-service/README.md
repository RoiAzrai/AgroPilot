# registry-service

Farms, plots and catalogues for AgroPilot (FastAPI, port 8000). SQLite locally, PostgreSQL in production.

## Configuration

```bash
cp .env.example .env
```

Four keys, read from the environment first and then from `.env`:

- `DATABASE_URL` (required): `sqlite:///file:registry.db?mode=rw&uri=true` or `postgresql+psycopg://agropilot:<password>@localhost:5432/registry`.
- `DB_CONNECT_TIMEOUT_SECONDS`, `DB_BUSY_TIMEOUT_SECONDS`, `DB_POOL_TIMEOUT_SECONDS`.

Percent-encode special characters in the password (for example `@` becomes `%40`, `:` becomes `%3A`).

## Local SQLite

```bash
bash seed_registry.sh
uv run uvicorn main:app --port 8000
```

## PostgreSQL

One role owns the five tables and is used by both `seed_db.py` and the service, through the same `DATABASE_URL`. `seed_db.py` runs no `GRANT`, so a service running as a different role without grants fails with SQLSTATE `42501`.

Databases must be UTF8. As a PostgreSQL superuser:

```sql
CREATE ROLE agropilot LOGIN PASSWORD '...';
CREATE DATABASE registry_perf OWNER agropilot ENCODING 'UTF8' TEMPLATE template0;
-- for an existing database:
ALTER DATABASE registry OWNER TO agropilot;
```

Then create the tables and load the 15 seed rows:

```bash
uv run python seed_db.py            # refuses if any of the five tables already exists
uv run python seed_db.py --reset    # prints the target, asks you to type the database name, then drops all registry data and rebuilds
uv run python seed_db.py --reset --yes   # the same without the question (for scripts)
```

`--reset` deletes every row in the registry tables of the database named by `DATABASE_URL`. It prints the target (the database the driver will really use, including `?dbname=` and `?host=` from the URL) and asks you to type its name: the file name for SQLite, the database name for PostgreSQL. Without a terminal it refuses unless `--yes` is passed.
